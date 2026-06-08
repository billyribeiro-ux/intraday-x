"""Twelve Data provider — FREE, non-broker, multi-year intraday (the yfinance upgrade).

Twelve Data (a pure data vendor, NOT a broker) has a free tier — API key, no credit
card — with **1-minute bars back to 2020-02-10** and multi-year 5-minute, which is
the deep intraday history yfinance lacks. Free-tier limits: ~800 credits/day,
8/min, 5000 bars/request (we paginate by date). Set ``TWELVEDATA_API_KEY``.

Implemented against the documented ``/time_series`` endpoint and verified live
against the free tier (pulls real 1m/5m bars with volume). The read-through cache
(INTRADAYX_CACHE_ENABLED=true) helps stay under the daily quota.
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

_BASE = "https://api.twelvedata.com/time_series"
_NY = ZoneInfo("America/New_York")  # US-equity exchange tz; meta overrides if present
_DEEP = timedelta(days=2000)  # 1m since 2020; the API caps what's actually returned
_PAGE = 5000  # max bars/request on the free tier

_INTERVAL: dict[Timeframe, str] = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.M30: "30min",
    Timeframe.H1: "1h",
    Timeframe.D1: "1day",
}


class TwelveDataProvider(DataProvider):
    name = "twelvedata"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("TWELVEDATA_API_KEY")

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
                    Capability.PREPOST_MARKET,
                }
            ),
            max_intraday_lookback={tf: _DEEP for tf in (Timeframe.M1, Timeframe.M5, Timeframe.H1)},
            rate_limit_hint="free tier: ~800 credits/day, 8/min, 5000 bars/request",
        )

    @staticmethod
    def _parse_dt(value: str, tz: ZoneInfo) -> datetime:
        fmt = "%Y-%m-%d" if len(value) == 10 else "%Y-%m-%d %H:%M:%S"
        return datetime.strptime(value, fmt).replace(tzinfo=tz).astimezone(UTC)

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
                "Twelve Data needs TWELVEDATA_API_KEY (free, no card, at twelvedata.com)."
            )
        key = self._api_key
        interval = _INTERVAL[timeframe]
        retryable = (TransientError, httpx.TransportError, httpx.TimeoutException)
        collected: list[dict[str, Any]] = []
        timeout = httpx.Timeout(30.0, connect=5.0)
        # /time_series returns the NEWEST `outputsize` bars in a window, so we
        # page by walking end_date BACKWARD (start fixed). We always request +
        # parse in NY wall-clock — the `timezone` param sets the output zone, so
        # mixing in meta.exchange_timezone would corrupt non-US timestamps.
        start_str = start.astimezone(_NY).strftime("%Y-%m-%d %H:%M:%S")
        end_cursor = end
        reached_start = False

        with httpx.Client(timeout=timeout) as client:

            def _req(upper: datetime) -> dict[str, Any]:
                params = {
                    "symbol": ticker.upper(),
                    "interval": interval,
                    "start_date": start_str,
                    "end_date": upper.astimezone(_NY).strftime("%Y-%m-%d %H:%M:%S"),
                    "outputsize": str(_PAGE),
                    "order": "ASC",
                    "timezone": "America/New_York",
                    "apikey": key,
                }
                r = client.get(_BASE, params=params)
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError(f"twelvedata {r.status_code} (transient)")
                if r.status_code != 200:
                    raise DataError(f"twelvedata {r.status_code} for {ticker}: {r.text[:200]}")
                try:
                    body: dict[str, Any] = r.json()
                except ValueError as exc:  # non-JSON body (CDN/gateway HTML, etc.)
                    raise DataError(
                        f"twelvedata non-JSON for {ticker} ({r.status_code}): {r.text[:200]}"
                    ) from exc
                if body.get("status") == "error":
                    if str(body.get("code")) == "429":
                        raise TransientError("twelvedata rate limit")
                    raise DataError(f"twelvedata error for {ticker}: {body.get('message')}")
                return body

            for _ in range(120):  # bounded backward pagination
                body = with_retries(partial(_req, end_cursor), retryable=retryable)
                values = body.get("values") or []  # ASC: values[0] oldest
                if not values:
                    reached_start = True
                    break
                collected.extend(values)
                if len(values) < _PAGE:  # partial page => reached start
                    reached_start = True
                    break
                end_cursor = self._parse_dt(values[0]["datetime"], _NY) - timeframe.timedelta
                if end_cursor <= start:
                    reached_start = True
                    break

        if not collected:
            return BarSet(ticker, timeframe, pl.DataFrame(schema=BAR_SCHEMA))
        if not reached_start:
            # Hit the page cap before covering [start, end] — fail loud rather than
            # silently return a short window (the LookbackExceededError principle).
            raise DataError(
                f"twelvedata: {ticker} {interval} window from {start:%Y-%m-%d} exceeds the "
                "pagination cap; request a narrower range or a coarser timeframe."
            )

        # BarSet._coerce dedupes on `ts` (keep='last') and sorts — no hand dedupe needed.
        frame = pl.DataFrame(
            {
                "ts": [self._parse_dt(v["datetime"], _NY) for v in collected],
                "open": [float(v["open"]) for v in collected],
                "high": [float(v["high"]) for v in collected],
                "low": [float(v["low"]) for v in collected],
                "close": [float(v["close"]) for v in collected],
                "volume": [int(float(v.get("volume", 0) or 0)) for v in collected],
                "vwap": [None] * len(collected),
                "trades": [None] * len(collected),
                "source": [self.name] * len(collected),
            }
        )
        return BarSet(ticker, timeframe, frame)
