"""Financial Modeling Prep (FMP) provider — canonical market-data source.

Implemented against FMP's current ``/stable`` API surface:

* EOD full chart: ``/stable/historical-price-eod/full``
* Intraday charts: ``/stable/historical-chart/{1min|5min|15min|30min|1hour|4hour}``

FMP is the only runtime market-data provider for intraday-x. Unsupported app
intervals (2m/3m/4m/10m/2h/weekly/monthly) are resampled from finer FMP bars, so
the data provenance remains FMP end-to-end.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import polars as pl

from intradayx.data.provider import (
    DataError,
    DataProvider,
    MissingCredentialsError,
    Session,
)
from intradayx.data.resilience import TransientError, with_retries
from intradayx.domain.bars import BAR_SCHEMA, BarSet, Timeframe
from intradayx.domain.capabilities import Capability, CapabilityError, ProviderCapabilities
from intradayx.domain.catalysts import CatalystEvent, CatalystKind, parse_fmp_datetime
from intradayx.domain.earnings import EarningsSurprise
from intradayx.domain.internals import INTERNALS_SCHEMA, InternalsSeries, InternalSymbol

_BASE = "https://financialmodelingprep.com/stable"
_NY = ZoneInfo("America/New_York")
_FMP_MAX_LOOKBACK = timedelta(days=365 * 30)
# Intraday endpoint returns ~6 trading days/call; cap backward pagination so a
# deep request can't run away (400 pages ≈ 6+ years of 5m history).
_INTRADAY_MAX_PAGES = 400

# Market internals FMP actually serves on the stable API (verified live): the
# CBOE volatility family as index symbols. Breadth ($TICK/$TRIN/$ADD/$VOLD),
# SKEW and put/call are NOT available, so we do not declare them — a missing
# internal must lower data_completeness, never be fabricated.
_INTERNAL_FMP_SYMBOL: dict[InternalSymbol, str] = {
    InternalSymbol.VIX: "^VIX",
    InternalSymbol.VIX9D: "^VIX9D",
    InternalSymbol.VIX3M: "^VIX3M",
    InternalSymbol.VVIX: "^VVIX",
}

_NATIVE_INTRADAY: dict[Timeframe, str] = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.M30: "30min",
    Timeframe.H1: "1hour",
    Timeframe.H4: "4hour",
}

_RESAMPLE_SOURCE: dict[Timeframe, Timeframe] = {
    Timeframe.M2: Timeframe.M1,
    Timeframe.M3: Timeframe.M1,
    Timeframe.M4: Timeframe.M1,
    Timeframe.M10: Timeframe.M5,
    Timeframe.H2: Timeframe.H1,
    Timeframe.W1: Timeframe.D1,
    Timeframe.MO1: Timeframe.D1,
    Timeframe.MO3: Timeframe.D1,
    Timeframe.Y1: Timeframe.D1,
}

TECHNICAL_INDICATORS: tuple[str, ...] = (
    "sma",
    "ema",
    "wma",
    "dema",
    "tema",
    "rsi",
    "standarddeviation",
    "williams",
    "adx",
)

_EVENT_LOOKAROUND = timedelta(days=2)
_CATALYST_KEYWORDS: tuple[str, ...] = (
    "earnings",
    "guidance",
    "forecast",
    "outlook",
    "raises",
    "cuts",
    "cut",
    "upgrade",
    "downgrade",
    "fda",
    "approval",
    "trial",
    "merger",
    "acquisition",
    "lawsuit",
    "sec",
    "investigation",
    "offering",
    "buyback",
    "dividend",
    "contract",
    "partnership",
    "layoff",
)


def _empty_barset(ticker: str, timeframe: Timeframe) -> BarSet:
    return BarSet(ticker, timeframe, pl.DataFrame(schema=BAR_SCHEMA))


class FMPProvider(DataProvider):
    name = "fmp"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("FMP_API_KEY")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name=self.name,
            supported=frozenset(
                {
                    Capability.DAILY_BARS,
                    Capability.INTRADAY_BARS_1M,
                    Capability.INTRADAY_BARS_5M,
                    Capability.EXTENDED_HISTORY_INTRADAY,
                    Capability.LIVE_STREAM,
                    Capability.EARNINGS_CALENDAR,
                    Capability.STOCK_NEWS,
                    Capability.PRESS_RELEASES,
                    Capability.ANALYST_GRADES,
                    # CBOE volatility family (verified live on the stable API).
                    Capability.INTERNALS_VIX,
                    Capability.INTERNALS_VIX_TERM,
                }
            ),
            max_intraday_lookback={
                tf: _FMP_MAX_LOOKBACK
                for tf in (
                    Timeframe.M1,
                    Timeframe.M2,
                    Timeframe.M3,
                    Timeframe.M4,
                    Timeframe.M5,
                    Timeframe.M10,
                    Timeframe.M15,
                    Timeframe.M30,
                    Timeframe.H1,
                    Timeframe.H2,
                    Timeframe.H4,
                )
            },
            rate_limit_hint=(
                "FMP plan-dependent rate limits; stable API, websocket stocks/crypto/forex"
            ),
        )

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        fmt = "%Y-%m-%d" if len(value) == 10 else "%Y-%m-%d %H:%M:%S"
        return datetime.strptime(value, fmt).replace(tzinfo=_NY).astimezone(UTC)

    def _request(self, path: str, params: dict[str, str]) -> Any:
        if not self._api_key:
            raise MissingCredentialsError(
                "FMP_API_KEY is required. Market data is FMP-only."
            )

        timeout = httpx.Timeout(30.0, connect=5.0)
        retryable = (TransientError, httpx.TransportError, httpx.TimeoutException)
        url = f"{_BASE}/{path.lstrip('/')}"
        query = {**params, "apikey": self._api_key}

        def _fetch() -> Any:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(url, params=query)
            if r.status_code == 429 or r.status_code >= 500:
                raise TransientError(f"fmp {r.status_code} (transient)")
            if r.status_code != 200:
                raise DataError(f"fmp {r.status_code}: {r.text[:240]}")
            try:
                body = r.json()
            except ValueError as exc:
                raise DataError(f"fmp non-JSON ({r.status_code}): {r.text[:240]}") from exc
            if isinstance(body, dict):
                message = body.get("Error Message") or body.get("error") or body.get("message")
                if message:
                    raise DataError(f"fmp error: {message}")
            return body

        return with_retries(partial(_fetch), retryable=retryable)

    @staticmethod
    def _rows(body: Any) -> list[dict[str, Any]]:
        if isinstance(body, list):
            return [r for r in body if isinstance(r, dict)]
        if isinstance(body, dict):
            for key in ("data", "historical", "news", "grades", "items"):
                rows = body.get(key)
                if isinstance(rows, list):
                    return [r for r in rows if isinstance(r, dict)]
        return []

    def _optional_rows(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        try:
            return self._rows(self._request(path, params))
        except (DataError, TransientError):
            return []

    @staticmethod
    def _to_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _date_param(value: datetime) -> str:
        return value.astimezone(_NY).strftime("%Y-%m-%d")

    @staticmethod
    def _text(row: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _score_headline(row: dict[str, Any], *, base: float) -> float:
        title = FMPProvider._text(row, "title", "headline")
        body = FMPProvider._text(row, "text", "summary", "description", "content")
        haystack = f"{title} {body}".lower()
        hits = sum(1 for keyword in _CATALYST_KEYWORDS if keyword in haystack)
        return min(base + hits * 0.07, 0.94)

    @staticmethod
    def _earnings_timestamp(row: dict[str, Any]) -> datetime | None:
        raw_date = row.get("date") or row.get("fiscalDateEnding")
        ts = parse_fmp_datetime(raw_date)
        if ts is None:
            return None
        when = str(row.get("time") or row.get("epsTime") or "").lower()
        if isinstance(raw_date, date) and not isinstance(raw_date, datetime):
            report_date = raw_date
        elif isinstance(raw_date, str) and len(raw_date.strip()) == 10:
            report_date = date.fromisoformat(raw_date.strip())
        else:
            report_date = ts.astimezone(_NY).date()
        if "bmo" in when or "before" in when or "morning" in when:
            return datetime.combine(report_date, time(9, 30), tzinfo=_NY).astimezone(UTC)
        if "amc" in when or "after" in when or "evening" in when:
            return datetime.combine(report_date, time(16, 5), tzinfo=_NY).astimezone(UTC)
        return datetime.combine(report_date, time(12, 0), tzinfo=_NY).astimezone(UTC)

    @staticmethod
    def _within_event_window(ts: datetime, start: datetime, end: datetime) -> bool:
        return start - _EVENT_LOOKAROUND <= ts <= end + _EVENT_LOOKAROUND

    @staticmethod
    def _earnings_event(row: dict[str, Any]) -> CatalystEvent | None:
        ts = FMPProvider._earnings_timestamp(row)
        if ts is None:
            return None
        eps = FMPProvider._number(row.get("eps") or row.get("actualEarningResult"))
        est = FMPProvider._number(row.get("epsEstimated") or row.get("estimatedEarning"))
        evidence: dict[str, float | str] = {}
        score = 0.72
        title = "Earnings report"
        if eps is not None:
            evidence["eps"] = eps
        if est is not None:
            evidence["eps_estimated"] = est
        if eps is not None and est not in (None, 0):
            surprise_pct = (eps - est) / abs(est)
            evidence["eps_surprise_pct"] = surprise_pct
            score = min(0.92, 0.74 + min(abs(surprise_pct), 0.5) * 0.32)
            title = f"Earnings report: EPS {eps:g} vs est. {est:g}"
        revenue = FMPProvider._number(row.get("revenue"))
        revenue_est = FMPProvider._number(row.get("revenueEstimated"))
        if revenue is not None:
            evidence["revenue"] = revenue
        if revenue_est is not None:
            evidence["revenue_estimated"] = revenue_est
        return CatalystEvent.create(
            kind=CatalystKind.EARNINGS,
            ts=ts,
            title=title,
            score=score,
            evidence=evidence,
        )

    @staticmethod
    def _news_event(row: dict[str, Any], kind: CatalystKind) -> CatalystEvent | None:
        ts = parse_fmp_datetime(
            row.get("publishedDate")
            or row.get("publishedAt")
            or row.get("date")
            or row.get("createdAt")
        )
        title = FMPProvider._text(row, "title", "headline")
        if ts is None or not title:
            return None
        return CatalystEvent.create(
            kind=kind,
            ts=ts,
            title=title,
            score=FMPProvider._score_headline(
                row, base=0.66 if kind is CatalystKind.PRESS_RELEASE else 0.56
            ),
            url=FMPProvider._text(row, "url", "link") or None,
            evidence={
                "publisher": FMPProvider._text(row, "site", "publisher", "source") or "fmp",
            },
        )

    @staticmethod
    def _grade_event(row: dict[str, Any]) -> CatalystEvent | None:
        ts = parse_fmp_datetime(row.get("date") or row.get("publishedDate"))
        if ts is None:
            return None
        firm = FMPProvider._text(row, "gradingCompany", "analystCompany", "company")
        action = FMPProvider._text(row, "action", "actionCompany").lower()
        previous = FMPProvider._text(row, "previousGrade", "previousRating")
        current = FMPProvider._text(row, "newGrade", "newRating", "grade")
        label_action = action.replace("_", " ").strip() or "rating action"
        title = f"{firm}: {label_action}".strip(": ")
        if previous or current:
            title = f"{title} {previous or '-'} -> {current or '-'}"
        if "downgrade" in action or "upgrade" in action:
            score = 0.82
        elif "initiated" in action or "reiterated" in action:
            score = 0.66
        else:
            score = 0.58
        return CatalystEvent.create(
            kind=CatalystKind.ANALYST_GRADE,
            ts=ts,
            title=title,
            score=score,
            evidence={
                "action": label_action,
                "previous_grade": previous,
                "new_grade": current,
                "firm": firm,
            },
        )

    def earnings_dates(self, ticker: str) -> list[date]:
        symbol = ticker.upper()
        now = datetime.now(tz=UTC)
        rows = self._optional_rows(
            "earnings-calendar",
            {
                "symbol": symbol,
                "from": self._date_param(now - timedelta(days=730)),
                "to": self._date_param(now + timedelta(days=365)),
            },
        )
        dates = {
            ts.date()
            for ts in (self._earnings_timestamp(row) for row in rows)
            if ts is not None
        }
        return sorted(dates)

    def earnings_surprises(self, ticker: str, *, limit: int = 80) -> list[EarningsSurprise]:
        """Historical reported earnings (actual vs estimated EPS), ascending by date.

        Uses FMP's ``/stable/earnings`` (epsActual/epsEstimated), the only feed
        that carries the *fundamental* surprise PEAD trades on. Rows without a
        reported actual (future/unreported) are dropped — no fabrication.
        """
        rows = self._optional_rows("earnings", {"symbol": ticker.upper(), "limit": str(limit)})
        out: list[EarningsSurprise] = []
        for row in rows:
            ea = self._number(row.get("epsActual"))
            ee = self._number(row.get("epsEstimated"))
            raw = self._text(row, "date")
            if ea is None or ee is None or len(raw) < 10:
                continue
            try:
                d = datetime.strptime(raw[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            out.append(EarningsSurprise(date=d, eps_actual=ea, eps_estimated=ee))
        return sorted(out, key=lambda e: e.date)

    def catalyst_events(
        self, ticker: str, start: datetime, end: datetime
    ) -> list[CatalystEvent]:
        symbol = ticker.upper()
        start_utc = self._to_utc(start)
        end_utc = self._to_utc(end)
        query_start = start_utc - _EVENT_LOOKAROUND
        query_end = end_utc + _EVENT_LOOKAROUND
        params = {
            "symbol": symbol,
            "from": self._date_param(query_start),
            "to": self._date_param(query_end),
        }

        events: list[CatalystEvent] = []
        for row in self._optional_rows("earnings-calendar", params):
            event = self._earnings_event(row)
            if event is not None and self._within_event_window(event.ts, start_utc, end_utc):
                events.append(event)

        for row in self._optional_rows(
            "news/stock", {"symbols": symbol, "page": "0", "limit": "100"}
        ):
            event = self._news_event(row, CatalystKind.NEWS)
            if event is not None and self._within_event_window(event.ts, start_utc, end_utc):
                events.append(event)

        for row in self._optional_rows(
            "news/press-releases", {"symbols": symbol, "page": "0", "limit": "50"}
        ):
            event = self._news_event(row, CatalystKind.PRESS_RELEASE)
            if event is not None and self._within_event_window(event.ts, start_utc, end_utc):
                events.append(event)

        for path in ("grades", "grades-historical"):
            for row in self._optional_rows(path, {"symbol": symbol}):
                event = self._grade_event(row)
                if event is not None and self._within_event_window(event.ts, start_utc, end_utc):
                    events.append(event)

        seen: set[tuple[str, datetime, str]] = set()
        unique: list[CatalystEvent] = []
        for event in sorted(events, key=lambda e: (e.ts, e.kind.value, e.title)):
            key = (event.kind.value, event.ts, event.title)
            if key in seen:
                continue
            seen.add(key)
            unique.append(event)
        return unique

    def _fetch_intraday(
        self, ticker: str, start: datetime, end: datetime, timeframe: Timeframe
    ) -> list[dict[str, Any]]:
        # FMP's intraday endpoint returns only ~6 trading days (newest-first)
        # ending at `to`, regardless of how far back `from` reaches. To cover a
        # deep [start, end] we page BACKWARD: walk `to` to just before the oldest
        # row of each page until we pass `start` (or a page comes back empty).
        # BarSet/_rows_to_barset dedupes on ts, so overlap between pages is safe.
        interval = _NATIVE_INTRADAY[timeframe]
        symbol = ticker.upper()
        start_str = start.astimezone(_NY).strftime("%Y-%m-%d")
        collected: list[dict[str, Any]] = []
        cursor = end
        for _ in range(_INTRADAY_MAX_PAGES):
            body = self._request(
                f"historical-chart/{interval}",
                {
                    "symbol": symbol,
                    "from": start_str,
                    "to": cursor.astimezone(_NY).strftime("%Y-%m-%d"),
                },
            )
            rows = body if isinstance(body, list) else []
            if not rows:
                break
            collected.extend(rows)
            oldest = self._parse_dt(str(rows[-1]["date"]))  # FMP returns newest-first
            if oldest <= start:
                break
            next_cursor = oldest - timedelta(days=1)
            if next_cursor >= cursor:  # no progress — avoid an infinite loop
                break
            cursor = next_cursor
        return collected

    def _fetch_eod(self, ticker: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        body = self._request(
            "historical-price-eod/full",
            {
                "symbol": ticker.upper(),
                "from": start.astimezone(_NY).strftime("%Y-%m-%d"),
                "to": end.astimezone(_NY).strftime("%Y-%m-%d"),
            },
        )
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            rows = body.get("historical") or body.get("data") or []
            return rows if isinstance(rows, list) else []
        return []

    def bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
        *,
        session: Session = Session.RTH,
        adjust: bool = True,
        now: datetime | None = None,
    ) -> BarSet:
        if not self._api_key:
            raise MissingCredentialsError(
                "FMP_API_KEY is required. Market data is FMP-only."
            )

        symbol = ticker.upper()
        if timeframe in _NATIVE_INTRADAY:
            return self._rows_to_barset(
                symbol, timeframe, self._fetch_intraday(symbol, start, end, timeframe)
            )
        if timeframe == Timeframe.D1:
            return self._rows_to_barset(symbol, timeframe, self._fetch_eod(symbol, start, end))

        source_tf = _RESAMPLE_SOURCE.get(timeframe)
        if source_tf is None:
            raise DataError(f"fmp cannot serve or derive timeframe {timeframe.value}")
        source = self.bars(symbol, start, end, source_tf, session=session, adjust=adjust, now=now)
        return self._resample(source, timeframe)

    def _rows_to_barset(
        self, ticker: str, timeframe: Timeframe, rows: list[dict[str, Any]]
    ) -> BarSet:
        if not rows:
            return _empty_barset(ticker, timeframe)

        frame = pl.DataFrame(
            {
                "ts": [self._parse_dt(str(r["date"])) for r in rows],
                "open": [float(r["open"]) for r in rows],
                "high": [float(r["high"]) for r in rows],
                "low": [float(r["low"]) for r in rows],
                "close": [float(r["close"]) for r in rows],
                "volume": [int(float(r.get("volume", 0) or 0)) for r in rows],
                "vwap": [self._optional_float(r.get("vwap")) for r in rows],
                "trades": [None] * len(rows),
                "source": [self.name] * len(rows),
            }
        )
        return BarSet(ticker, timeframe, frame)

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    def internals(
        self,
        symbol: InternalSymbol,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
    ) -> InternalsSeries:
        """Fetch a market-internals series. FMP serves the CBOE volatility family
        (VIX / VIX9D / VIX3M / VVIX) as index symbols on the same bar endpoints;
        breadth / SKEW / put-call are not available and raise CapabilityError so
        the caller degrades honestly rather than receiving fabricated data."""
        if not self._api_key:
            raise MissingCredentialsError("FMP_API_KEY is required. Market data is FMP-only.")
        fmp_symbol = _INTERNAL_FMP_SYMBOL.get(symbol)
        if fmp_symbol is None:
            cap = (
                Capability.INTERNALS_VIX
                if symbol is InternalSymbol.VIX
                else Capability.INTERNALS_TICK
            )
            raise CapabilityError(self.name, cap)

        if timeframe in _NATIVE_INTRADAY:
            rows = self._fetch_intraday(fmp_symbol, start, end, timeframe)
        elif timeframe == Timeframe.D1:
            rows = self._fetch_eod(fmp_symbol, start, end)
        else:
            raise DataError(f"fmp internals: unsupported timeframe {timeframe.value}")
        return self._rows_to_internals(symbol, timeframe, rows)

    def _rows_to_internals(
        self, symbol: InternalSymbol, timeframe: Timeframe, rows: list[dict[str, Any]]
    ) -> InternalsSeries:
        if not rows:
            return InternalsSeries(symbol, timeframe, pl.DataFrame(schema=INTERNALS_SCHEMA))
        frame = pl.DataFrame(
            {
                "ts": [self._parse_dt(str(r["date"])) for r in rows],
                "value": [float(r["close"]) for r in rows],  # the index level
                "source": [self.name] * len(rows),
            }
        )
        return InternalsSeries(symbol, timeframe, frame)

    def _resample(self, source: BarSet, target_tf: Timeframe) -> BarSet:
        if source.is_empty():
            return _empty_barset(source.symbol, target_tf)

        grouped = (
            source.df.sort("ts")
            .group_by_dynamic("ts", every=target_tf.value, closed="left", label="left")
            .agg(
                open=pl.col("open").first(),
                high=pl.col("high").max(),
                low=pl.col("low").min(),
                close=pl.col("close").last(),
                volume=pl.col("volume").sum(),
                vwap=pl.when(pl.col("vwap").is_not_null().any())
                .then(
                    (pl.col("vwap").fill_null(pl.col("close")) * pl.col("volume")).sum()
                    / pl.col("volume").sum().clip(lower_bound=1)
                )
                .otherwise(None),
                trades=pl.when(pl.col("trades").is_not_null().any())
                .then(pl.col("trades").sum())
                .otherwise(None),
            )
            .drop_nulls(subset=["open", "high", "low", "close"])
            .with_columns(source=pl.lit(self.name))
        )
        if grouped.is_empty():
            return _empty_barset(source.symbol, target_tf)
        return BarSet(source.symbol, target_tf, grouped)
