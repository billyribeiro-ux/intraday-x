"""Polygon.io provider — full-market intraday bars (the upgrade from yfinance/IEX).

Implemented against Polygon's documented v2 aggregates REST API. Needs
``POLYGON_API_KEY`` (a free tier exists: ~2yr history, 5 req/min; paid tiers go
deeper). The composite router auto-prefers it once the key is set — you write no
code, just paste the key.

Scope: ``bars()`` (the well-documented, stable endpoint). Internals (indices/VIX)
and options live behind further Polygon endpoints — declared as next steps in the
roadmap, not yet wired, so capabilities() does NOT advertise them (the system
stays honest about what it can actually fetch).

NOTE: this integration is written from Polygon's published API shape but has not
been run here (no key in this environment) — verify once you add your key.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

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

_BASE = "https://api.polygon.io"
_DEEP = timedelta(days=1825)  # ~5y; the tier caps what's actually returned

# Timeframe -> (multiplier, timespan) for the aggregates endpoint.
# Polygon supports arbitrary minute multipliers and hour/day/week/month/quarter/year.
_AGG: dict[Timeframe, tuple[int, str]] = {
    Timeframe.M1: (1, "minute"),
    Timeframe.M2: (2, "minute"),
    Timeframe.M3: (3, "minute"),
    Timeframe.M4: (4, "minute"),
    Timeframe.M5: (5, "minute"),
    Timeframe.M10: (10, "minute"),
    Timeframe.M15: (15, "minute"),
    Timeframe.M30: (30, "minute"),
    Timeframe.H1: (1, "hour"),
    Timeframe.H2: (2, "hour"),
    Timeframe.H4: (4, "hour"),
    Timeframe.D1: (1, "day"),
    Timeframe.W1: (1, "week"),
    Timeframe.MO1: (1, "month"),
    Timeframe.MO3: (3, "month"),
    Timeframe.Y1: (1, "year"),
}


class PolygonProvider(DataProvider):
    name = "polygon"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("POLYGON_API_KEY")

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
            max_intraday_lookback={
                tf: _DEEP
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
            rate_limit_hint="free tier: 5 req/min, ~2yr; paid tiers unlimited + deeper",
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
        now: datetime | None = None,  # lookback routing is the composite's job
    ) -> BarSet:
        if not self._api_key:
            raise MissingCredentialsError(
                "Polygon needs POLYGON_API_KEY in the environment (free at polygon.io)."
            )
        mult, span = _AGG[timeframe]
        frm = int(start.timestamp() * 1000)
        to = int(end.timestamp() * 1000)
        url: str | None = (
            f"{_BASE}/v2/aggs/ticker/{ticker.upper()}/range/{mult}/{span}/{frm}/{to}"
            f"?adjusted={'true' if adjust else 'false'}&sort=asc&limit=50000"
        )
        rows: list[dict[str, Any]] = []
        timeout = httpx.Timeout(30.0, connect=5.0)  # never hang on a dead handshake
        retryable = (TransientError, httpx.TransportError, httpx.TimeoutException)
        with httpx.Client(timeout=timeout) as client:

            def _fetch(u: str) -> dict[str, Any]:
                r = client.get(u)
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError(f"polygon {r.status_code} (transient)")
                if r.status_code != 200:
                    raise DataError(f"polygon {r.status_code} for {ticker}: {r.text[:200]}")
                parsed: dict[str, Any] = r.json()
                return parsed

            for _ in range(50):  # bounded pagination
                if url is None:
                    break
                sep = "&" if "?" in url else "?"
                full = f"{url}{sep}apiKey={self._api_key}"
                body = with_retries(partial(_fetch, full), retryable=retryable)
                rows.extend(body.get("results") or [])
                url = body.get("next_url")

        if not rows:
            return BarSet(ticker, timeframe, pl.DataFrame(schema=BAR_SCHEMA))

        frame = pl.DataFrame(
            {
                "ts": [datetime.fromtimestamp(r["t"] / 1000, tz=UTC) for r in rows],
                "open": [float(r["o"]) for r in rows],
                "high": [float(r["h"]) for r in rows],
                "low": [float(r["l"]) for r in rows],
                "close": [float(r["c"]) for r in rows],
                "volume": [int(r.get("v") or 0) for r in rows],  # explicit null => 0
                "vwap": [r.get("vw") for r in rows],
                "trades": [r.get("n") for r in rows],
                "source": [self.name] * len(rows),
            }
        )
        return BarSet(ticker, timeframe, frame)
