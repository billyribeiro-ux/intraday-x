"""Twelve Data provider — FREE, non-broker, multi-year intraday (the yfinance upgrade).

Twelve Data (a pure data vendor, NOT a broker) has a free tier — API key, no credit
card — with **1-minute bars back to 2020-02-10** and multi-year 5-minute, which is
the deep intraday history yfinance lacks. Free-tier limits: ~800 credits/day,
8/min, 5000 bars/request (we paginate by date). Set ``TWELVEDATA_API_KEY``.

Implemented against the documented ``/time_series`` endpoint; not run here (no key
in this environment) — verify once your key is in. The read-through cache
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
    ) -> BarSet:
        if not self._api_key:
            raise MissingCredentialsError(
                "Twelve Data needs TWELVEDATA_API_KEY (free, no card, at twelvedata.com)."
            )
        key = self._api_key
        interval = _INTERVAL[timeframe]
        retryable = (TransientError, httpx.TransportError, httpx.TimeoutException)
        collected: list[dict[str, Any]] = []
        tz = _NY
        cursor = start
        timeout = httpx.Timeout(30.0, connect=5.0)

        with httpx.Client(timeout=timeout) as client:

            def _req(c: datetime) -> dict[str, Any]:
                params = {
                    "symbol": ticker.upper(),
                    "interval": interval,
                    "start_date": c.astimezone(_NY).strftime("%Y-%m-%d %H:%M:%S"),
                    "end_date": end.astimezone(_NY).strftime("%Y-%m-%d %H:%M:%S"),
                    "outputsize": str(_PAGE),
                    "order": "ASC",
                    "timezone": "America/New_York",
                    "apikey": key,
                }
                r = client.get(_BASE, params=params)
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError(f"twelvedata {r.status_code} (transient)")
                body: dict[str, Any] = r.json()
                if body.get("status") == "error":
                    if str(body.get("code")) == "429":
                        raise TransientError("twelvedata rate limit")
                    raise DataError(f"twelvedata error for {ticker}: {body.get('message')}")
                return body

            for _ in range(60):  # bounded date-chunked pagination
                body = with_retries(partial(_req, cursor), retryable=retryable)
                if "exchange_timezone" in body.get("meta", {}):
                    tz = ZoneInfo(body["meta"]["exchange_timezone"])
                values = body.get("values") or []
                if not values:
                    break
                collected.extend(values)
                if len(values) < _PAGE:
                    break
                cursor = self._parse_dt(values[-1]["datetime"], tz) + timeframe.timedelta

        if not collected:
            return BarSet(ticker, timeframe, pl.DataFrame(schema=BAR_SCHEMA))

        # Dedupe boundary overlaps by datetime string, then build the frame.
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for v in collected:
            if v["datetime"] not in seen:
                seen.add(v["datetime"])
                uniq.append(v)
        frame = pl.DataFrame(
            {
                "ts": [self._parse_dt(v["datetime"], tz) for v in uniq],
                "open": [float(v["open"]) for v in uniq],
                "high": [float(v["high"]) for v in uniq],
                "low": [float(v["low"]) for v in uniq],
                "close": [float(v["close"]) for v in uniq],
                "volume": [int(float(v.get("volume", 0) or 0)) for v in uniq],
                "vwap": [None] * len(uniq),
                "trades": [None] * len(uniq),
                "source": [self.name] * len(uniq),
            }
        )
        return BarSet(ticker, timeframe, frame)
