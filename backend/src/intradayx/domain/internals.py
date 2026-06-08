"""Market-internals value types ($TICK, $TRIN, $ADD, $VOLD, VIX family, SKEW).

Deep historical *intraday* breadth internals are not commercially purchasable
cheaply, so most of these are populated either by a paid vendor (Phase 7) or by
our own :mod:`intradayx.live.internals_recorder` banking them from a realtime
feed. The types exist from day one so the recorder and the capability-gated
features share one schema.
"""

from __future__ import annotations

from enum import StrEnum

import polars as pl

from intradayx.domain.bars import Timeframe


class InternalSymbol(StrEnum):
    """Canonical ticker for each internal (thinkorSwim-style ``$`` names)."""

    TICK = "$TICK"  # NYSE tick index
    TRIN = "$TRIN"  # Arms index
    ADD = "$ADD"  # advance-decline
    VOLD = "$VOLD"  # up-volume minus down-volume
    UVOL = "$UVOL"  # up volume
    DVOL = "$DVOL"  # down volume
    VIX = "$VIX"
    VIX9D = "$VIX9D"
    VIX3M = "$VIX3M"
    VVIX = "$VVIX"
    SKEW = "$SKEW"
    PCALL = "$PCALL"  # put/call ratio


# Canonical Polars schema for an internals series (long/tidy form: one value per
# timestamp, so a new internal symbol is just a new partition, no schema change).
INTERNALS_SCHEMA: dict[str, pl.DataType] = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "value": pl.Float64(),
    "source": pl.String(),
}


class InternalsSeries:
    """Single-symbol, single-timeframe internals series backed by Polars."""

    __slots__ = ("_df", "symbol", "timeframe")

    def __init__(self, symbol: InternalSymbol, timeframe: Timeframe, df: pl.DataFrame) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        missing = set(INTERNALS_SCHEMA) - set(df.columns)
        if missing:
            raise ValueError(f"InternalsSeries missing columns: {sorted(missing)}")
        self._df = (
            df.select([pl.col(c).cast(dt) for c, dt in INTERNALS_SCHEMA.items()])
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

    def __repr__(self) -> str:
        return f"InternalsSeries({self.symbol.value!r}, {self.timeframe.value!r}, n={len(self)})"
