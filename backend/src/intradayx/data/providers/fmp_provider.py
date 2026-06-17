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
from datetime import UTC, datetime, timedelta
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
from intradayx.domain.capabilities import Capability, ProviderCapabilities

_BASE = "https://financialmodelingprep.com/stable"
_NY = ZoneInfo("America/New_York")
_FMP_MAX_LOOKBACK = timedelta(days=365 * 30)

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
            rate_limit_hint="FMP plan-dependent rate limits; stable API, websocket stocks/crypto/forex",
        )

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        fmt = "%Y-%m-%d" if len(value) == 10 else "%Y-%m-%d %H:%M:%S"
        return datetime.strptime(value, fmt).replace(tzinfo=_NY).astimezone(UTC)

    def _request(self, path: str, params: dict[str, str]) -> Any:
        if not self._api_key:
            raise MissingCredentialsError(
                "FMP_API_KEY is required. Market data is locked to Financial Modeling Prep."
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

    def _fetch_intraday(
        self, ticker: str, start: datetime, end: datetime, timeframe: Timeframe
    ) -> list[dict[str, Any]]:
        interval = _NATIVE_INTRADAY[timeframe]
        body = self._request(
            f"historical-chart/{interval}",
            {
                "symbol": ticker.upper(),
                "from": start.astimezone(_NY).strftime("%Y-%m-%d"),
                "to": end.astimezone(_NY).strftime("%Y-%m-%d"),
            },
        )
        return body if isinstance(body, list) else []

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
                "FMP_API_KEY is required. Market data is locked to Financial Modeling Prep."
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
