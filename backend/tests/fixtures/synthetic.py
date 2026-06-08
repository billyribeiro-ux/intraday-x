"""Deterministic synthetic data builders for tests (no network)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from intradayx.domain.bars import BarSet, Timeframe

# 2024-01-02 09:30 America/New_York (EST = UTC-5) == 14:30 UTC.
DEFAULT_START = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


def make_bars(
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    opens: Sequence[float] | None = None,
    volumes: Sequence[int] | None = None,
    symbol: str = "TEST",
    timeframe: Timeframe = Timeframe.M1,
    start: datetime = DEFAULT_START,
) -> BarSet:
    n = len(closes)
    highs = list(highs) if highs is not None else [c + 0.5 for c in closes]
    lows = list(lows) if lows is not None else [c - 0.5 for c in closes]
    opens = list(opens) if opens is not None else list(closes)
    volumes = list(volumes) if volumes is not None else [1000] * n
    ts = [start + i * timeframe.timedelta for i in range(n)]
    df = pl.DataFrame(
        {
            "ts": ts,
            "open": [float(x) for x in opens],
            "high": [float(x) for x in highs],
            "low": [float(x) for x in lows],
            "close": [float(x) for x in closes],
            "volume": [int(x) for x in volumes],
            "vwap": [None] * n,
            "trades": [None] * n,
            "source": ["test"] * n,
        }
    )
    return BarSet(symbol, timeframe, df)
