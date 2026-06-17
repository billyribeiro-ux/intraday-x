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
    M2 = "2m"
    M3 = "3m"
    M4 = "4m"
    M5 = "5m"
    M10 = "10m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
    MO1 = "1mo"
    MO3 = "3mo"
    Y1 = "1y"

    @property
    def timedelta(self) -> timedelta:
        return {
            Timeframe.M1: timedelta(minutes=1),
            Timeframe.M2: timedelta(minutes=2),
            Timeframe.M3: timedelta(minutes=3),
            Timeframe.M4: timedelta(minutes=4),
            Timeframe.M5: timedelta(minutes=5),
            Timeframe.M10: timedelta(minutes=10),
            Timeframe.M15: timedelta(minutes=15),
            Timeframe.M30: timedelta(minutes=30),
            Timeframe.H1: timedelta(hours=1),
            Timeframe.H2: timedelta(hours=2),
            Timeframe.H4: timedelta(hours=4),
            Timeframe.D1: timedelta(days=1),
            Timeframe.W1: timedelta(weeks=1),
            Timeframe.MO1: timedelta(days=30),
            Timeframe.MO3: timedelta(days=90),
            Timeframe.Y1: timedelta(days=365),
        }[self]

    @property
    def is_intraday(self) -> bool:
        return self.value.endswith("m") or self.value.endswith("h")

    @property
    def is_monthly_or_higher(self) -> bool:
        return self in (Timeframe.MO1, Timeframe.MO3, Timeframe.Y1)

    @property
    def pandas_freq(self) -> str:
        """The pandas/yfinance interval string."""
        return {
            Timeframe.M1: "1m",
            Timeframe.M2: "2m",
            Timeframe.M3: "3m",
            Timeframe.M4: "4m",
            Timeframe.M5: "5m",
            Timeframe.M10: "10m",
            Timeframe.M15: "15m",
            Timeframe.M30: "30m",
            Timeframe.H1: "1h",
            Timeframe.H2: "2h",
            Timeframe.H4: "4h",
            Timeframe.D1: "1d",
            Timeframe.W1: "1wk",
            Timeframe.MO1: "1mo",
            Timeframe.MO3: "3mo",
            Timeframe.Y1: "1y",
        }[self]


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
