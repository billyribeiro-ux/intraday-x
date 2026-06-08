"""Core price-bar value types.

A :class:`BarSet` is single-symbol, single-timeframe, and wraps a Polars
DataFrame (the efficient representation used across feature engineering and the
lake). :class:`Bar` is a single-row value object for tests and rare row-wise
iteration. The canonical column schema lives here so the domain and the storage
layer agree on one definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import polars as pl


class Timeframe(StrEnum):
    """Bar aggregation interval. Values are the canonical wire/string form."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"

    @property
    def timedelta(self) -> timedelta:
        return {
            Timeframe.M1: timedelta(minutes=1),
            Timeframe.M5: timedelta(minutes=5),
            Timeframe.M15: timedelta(minutes=15),
            Timeframe.M30: timedelta(minutes=30),
            Timeframe.H1: timedelta(hours=1),
            Timeframe.D1: timedelta(days=1),
        }[self]

    @property
    def is_intraday(self) -> bool:
        return self != Timeframe.D1

    @property
    def pandas_freq(self) -> str:
        """The pandas/yfinance interval string (`1m`, `5m`, `1h`, `1d`)."""
        return self.value


# Canonical Polars schema for a bar table. ``ts`` is the bar's START time,
# timezone-aware UTC. ``vwap`` and ``trades`` are nullable (not every vendor
# supplies them). ``source`` records which provider produced the row so a
# CompositeProvider merge stays auditable.
BAR_SCHEMA: dict[str, pl.DataType] = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "volume": pl.Int64(),
    "vwap": pl.Float64(),
    "trades": pl.Int64(),
    "source": pl.String(),
}


@dataclass(frozen=True, slots=True)
class Bar:
    """A single OHLCV bar. ``ts`` is the bar start, UTC tz-aware."""

    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None = None
    trades: int | None = None
    source: str = "unknown"


class BarSet:
    """Single-symbol, single-timeframe collection of bars backed by Polars.

    The DataFrame is coerced to :data:`BAR_SCHEMA` on construction and sorted by
    ``ts`` ascending, so downstream code can rely on causal ordering.
    """

    __slots__ = ("_df", "symbol", "timeframe")

    def __init__(self, symbol: str, timeframe: Timeframe, df: pl.DataFrame) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self._df = self._coerce(df)

    @staticmethod
    def _coerce(df: pl.DataFrame) -> pl.DataFrame:
        missing = set(BAR_SCHEMA) - set(df.columns)
        if missing:
            raise ValueError(f"BarSet DataFrame missing columns: {sorted(missing)}")
        # Reorder + cast to the canonical schema, then sort causally by time.
        return (
            df.select([pl.col(c).cast(dt) for c, dt in BAR_SCHEMA.items()])
            .unique(subset=["ts"], keep="last")
            .sort("ts")
        )

    @property
    def df(self) -> pl.DataFrame:
        return self._df

    def is_empty(self) -> bool:
        return self._df.height == 0

    def __len__(self) -> int:
        return self._df.height

    @property
    def start(self) -> datetime | None:
        return None if self.is_empty() else self._df["ts"].item(0)

    @property
    def end(self) -> datetime | None:
        return None if self.is_empty() else self._df["ts"].item(-1)

    def __repr__(self) -> str:
        return (
            f"BarSet(symbol={self.symbol!r}, timeframe={self.timeframe.value!r}, "
            f"n={len(self)}, start={self.start}, end={self.end})"
        )
