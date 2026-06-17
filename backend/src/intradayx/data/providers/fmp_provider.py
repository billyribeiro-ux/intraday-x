"""Financial Modeling Prep (FMP) provider — paid non-broker data vendor.

FMP offers OHLCV bars via two endpoints:

* Intraday: ``/api/v3/historical-chart/{interval}/{symbol}``
  (1min, 5min, 15min, 30min, 1hour, 4hour).
* Daily: ``/api/v3/historical-price-full/{symbol}``
  (full daily history).

Set ``FMP_API_KEY`` (paid subscription at https://financialmodelingprep.com/developer/).

Implementation notes:
* FMP caps each call to roughly 1 000 rows, so we paginate by date windows and
  stop when we reach the requested start or an empty page.
* Results are newest-first; each page is reversed before aggregation.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import polars as pl

from intradayx.data.provider import (
    DataError,
    DataProvider,
    MissingCredentialsError,
    Session,
)
from intradayx.domain.bars import BAR_SCHEMA, BarSet, Timeframe
from intradayx.domain.capabilities import Capability, ProviderCapabilities

_BASE = "https://financialmodelingprep.com/api/v3"

# Generous ceilings — the provider will attempt to fetch this far back for a
# "MAX" request, paginating until the API stops returning data.
_INTRADAY_DEEP = timedelta(days=1825)  # ~5 years
_DAILY_DEEP = timedelta(days=365 * 30)  # ~30 years

# FMP's per-call row cap is ~1 000. We target 800 bars per chunk so the call
# safely fits, then walk backward until we cover the requested window.
_CHUNK_BARS_TARGET = 800
_TRADING_MINUTES_PER_DAY = 390

_INTERVAL: dict[Timeframe, str] = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.M30: "30min",
    Timeframe.H1: "1hour",
    Timeframe.H4: "4hour",
}


def _parse_dt(value: str) -> datetime:
    """Parse FMP's ``YYYY-MM-DD HH:MM:SS`` timestamps as UTC."""
    fmt = "%Y-%m-%d %H:%M:%S"
    if len(value) == 10:
        fmt = "%Y-%m-%d"
    return datetime.strptime(value, fmt).replace(tzinfo=UTC)


def _intraday_chunk_delta(timeframe: Timeframe) -> timedelta:
    """Date-window width for one intraday call so we stay under ~1 000 rows."""
    minutes_per_bar = int(timeframe.timedelta.total_seconds() // 60)
    bars_per_day = max(1, _TRADING_MINUTES_PER_DAY // minutes_per_bar)
    days = max(1, _CHUNK_BARS_TARGET // bars_per_day)
    return timedelta(days=days)


class FmpProvider(DataProvider):
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
                }
            ),
            max_intraday_lookback={
                Timeframe.M1: _INTRADAY_DEEP,
                Timeframe.M5: _INTRADAY_DEEP,
                Timeframe.M15: _INTRADAY_DEEP,
                Timeframe.M30: _INTRADAY_DEEP,
                Timeframe.H1: _INTRADAY_DEEP,
                Timeframe.H4: _INTRADAY_DEEP,
            },
            rate_limit_hint="paid subscription; per-call cap ~1,000 rows — paginated internally",
        )

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
                "FMP needs FMP_API_KEY in the environment "
                "(paid subscription at financialmodelingprep.com)."
            )

        symbol = ticker.upper()
        rows: list[dict[str, Any]]

        if timeframe == Timeframe.D1:
            rows = self._daily(symbol, start, end, self._api_key)
        else:
            rows = self._intraday(symbol, timeframe, start, end, self._api_key)

        if not rows:
            return BarSet(ticker, timeframe, pl.DataFrame(schema=BAR_SCHEMA))

        frame = pl.DataFrame(
            {
                "ts": [_parse_dt(r["date"]) for r in rows],
                "open": [float(r["open"]) for r in rows],
                "high": [float(r["high"]) for r in rows],
                "low": [float(r["low"]) for r in rows],
                "close": [float(r["close"]) for r in rows],
                "volume": [int(float(r.get("volume", 0) or 0)) for r in rows],
                "vwap": [None] * len(rows),
                "trades": [None] * len(rows),
                "source": [self.name] * len(rows),
            }
        )
        return BarSet(ticker, timeframe, frame)

    def _fetch(self, url: str, params: dict[str, str]) -> dict[str, Any] | list[dict[str, Any]]:
        timeout = httpx.Timeout(30.0, connect=5.0)
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url, params=params)
            if r.status_code != 200:
                raise DataError(f"fmp {r.status_code}: {r.text[:200]}")
            body = r.json()
            # FMP sometimes returns an error object with a message key.
            if isinstance(body, dict) and "Error Message" in body:
                raise DataError(f"fmp error: {body['Error Message']}")
            return body

    def _intraday(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        api_key: str,
    ) -> list[dict[str, Any]]:
        interval = _INTERVAL[timeframe]
        chunk_delta = _intraday_chunk_delta(timeframe)
        collected: list[dict[str, Any]] = []
        cursor_end = end
        max_chunks = 500  # safety guard for "MAX" requests

        for _ in range(max_chunks):
            if cursor_end <= start:
                break
            chunk_start = max(start, cursor_end - chunk_delta)
            rows = self._intraday_page(symbol, interval, chunk_start, cursor_end, api_key)
            if not rows:
                # Older data may simply not exist for this plan/symbol.
                break
            # API returns newest-first; reverse to oldest-first for this chunk.
            collected.extend(reversed(rows))
            # Walk backward; BarSet dedupes any overlapping bar.
            cursor_end = chunk_start

        return collected

    def _intraday_page(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        api_key: str,
    ) -> list[dict[str, Any]]:
        url = f"{_BASE}/historical-chart/{interval}/{symbol}"
        params: dict[str, str] = {
            "apikey": api_key,
            "from": start.strftime("%Y-%m-%d"),
            "to": end.strftime("%Y-%m-%d"),
        }
        body = self._fetch(url, params)
        if not isinstance(body, list):
            raise DataError(f"fmp unexpected intraday response shape for {symbol}")
        return body

    def _daily(
        self, symbol: str, start: datetime, end: datetime, api_key: str
    ) -> list[dict[str, Any]]:
        chunk_delta = timedelta(days=365 * 3)  # ~3 years / chunk
        collected: list[dict[str, Any]] = []
        cursor_end = end
        max_chunks = 200

        for _ in range(max_chunks):
            if cursor_end <= start:
                break
            chunk_start = max(start, cursor_end - chunk_delta)
            rows = self._daily_page(symbol, chunk_start, cursor_end, api_key)
            if not rows:
                break
            collected.extend(reversed(rows))
            cursor_end = chunk_start

        return collected

    def _daily_page(
        self, symbol: str, start: datetime, end: datetime, api_key: str
    ) -> list[dict[str, Any]]:
        url = f"{_BASE}/historical-price-full/{symbol}"
        params: dict[str, str] = {
            "apikey": api_key,
            "from": start.strftime("%Y-%m-%d"),
            "to": end.strftime("%Y-%m-%d"),
        }
        body = self._fetch(url, params)
        if not isinstance(body, dict):
            raise DataError(f"fmp unexpected daily response shape for {symbol}")
        return body.get("historical") or []
