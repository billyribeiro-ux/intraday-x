"""Financial Modeling Prep (FMP) provider — FREE-tier, non-broker OHLCV bars.

FMP (https://financialmodelingprep.com/) is a pure data vendor, NOT a broker. Its
free tier (API key, no card) gives daily history to IPO plus intraday 1m/5m/…
bars, which fits the project's "free, non-broker vendors only" rule. Free-tier
limit: ~250 requests/day. Set ``FMP_API_KEY``; the composite router uses it once
configured.

Implemented against FMP's documented v3 REST endpoints:
  - intraday: ``/api/v3/historical-chart/{interval}/{symbol}?from&to``
  - daily:    ``/api/v3/historical-price-full/{symbol}?from&to``

Scope: ``bars()`` only (the stable, well-documented surface). Internals, options,
earnings, etc. live behind further FMP endpoints — NOT wired here, so
``capabilities()`` does not advertise them (the system stays honest about what it
can actually fetch).

NOTE: written from FMP's published API shape but not run here (no key in this
environment) — verify once you add your key, exactly as for the Polygon provider.
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

_BASE = "https://financialmodelingprep.com/api/v3"
_NY = ZoneInfo("America/New_York")  # FMP stamps US-equity bars in exchange-local time
_DEEP = timedelta(days=1825)  # ~5y; the tier caps what's actually returned

# Timeframe -> FMP intraday interval token (daily uses a separate endpoint).
_INTERVAL: dict[Timeframe, str] = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.M30: "30min",
    Timeframe.H1: "1hour",
}


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
                }
            ),
            max_intraday_lookback={tf: _DEEP for tf in (Timeframe.M1, Timeframe.M5, Timeframe.H1)},
            rate_limit_hint="free tier: ~250 requests/day (no card)",
        )

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        """Parse an FMP date (``YYYY-MM-DD`` daily or ``... HH:MM:SS`` intraday).

        FMP stamps bars in US-Eastern wall-clock; we localize to NY then convert
        to UTC so timestamps line up with every other provider's UTC bars.
        """
        fmt = "%Y-%m-%d" if len(value) == 10 else "%Y-%m-%d %H:%M:%S"
        return datetime.strptime(value, fmt).replace(tzinfo=_NY).astimezone(UTC)

    def bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
        *,
        session: Session = Session.RTH,
        adjust: bool = True,
        now: datetime | None = None,  # lookback routing is the composite's job
    ) -> BarSet:
        if not self._api_key:
            raise MissingCredentialsError(
                "FMP needs FMP_API_KEY in the environment "
                "(free, no card, at financialmodelingprep.com)."
            )
        symbol = ticker.upper()
        frm = start.astimezone(_NY).strftime("%Y-%m-%d")
        to = end.astimezone(_NY).strftime("%Y-%m-%d")
        params = {"from": frm, "to": to, "apikey": self._api_key}

        if timeframe == Timeframe.D1:
            url = f"{_BASE}/historical-price-full/{symbol}"
        else:
            url = f"{_BASE}/historical-chart/{_INTERVAL[timeframe]}/{symbol}"

        timeout = httpx.Timeout(30.0, connect=5.0)  # never hang on a dead handshake
        retryable = (TransientError, httpx.TransportError, httpx.TimeoutException)

        def _fetch() -> Any:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(url, params=params)
            if r.status_code == 429 or r.status_code >= 500:
                raise TransientError(f"fmp {r.status_code} (transient)")
            if r.status_code != 200:
                raise DataError(f"fmp {r.status_code} for {ticker}: {r.text[:200]}")
            try:
                return r.json()
            except ValueError as exc:  # non-JSON body (CDN/gateway HTML, etc.)
                raise DataError(
                    f"fmp non-JSON for {ticker} ({r.status_code}): {r.text[:200]}"
                ) from exc

        body = with_retries(partial(_fetch), retryable=retryable)

        # FMP error payloads are objects with an "Error Message" key; bar payloads
        # are a list (intraday) or {"historical": [...]} (daily). Fail loud on the
        # former so a bad symbol/key never looks like an empty window.
        if isinstance(body, dict) and "Error Message" in body:
            raise DataError(f"fmp error for {ticker}: {body['Error Message']}")
        if timeframe == Timeframe.D1:
            rows = body.get("historical", []) if isinstance(body, dict) else []
        else:
            rows = body if isinstance(body, list) else []

        if not rows:
            return BarSet(ticker, timeframe, pl.DataFrame(schema=BAR_SCHEMA))

        # BarSet._coerce dedupes on `ts` (keep='last') and sorts — FMP returns
        # newest-first, so no hand ordering is needed here.
        frame = pl.DataFrame(
            {
                "ts": [self._parse_dt(r["date"]) for r in rows],
                "open": [float(r["open"]) for r in rows],
                "high": [float(r["high"]) for r in rows],
                "low": [float(r["low"]) for r in rows],
                "close": [float(r["close"]) for r in rows],
                "volume": [int(float(r.get("volume", 0) or 0)) for r in rows],
                "vwap": [r.get("vwap") for r in rows],  # FMP supplies vwap on daily
                "trades": [None] * len(rows),
                "source": [self.name] * len(rows),
            }
        )
        return BarSet(ticker, timeframe, frame)
