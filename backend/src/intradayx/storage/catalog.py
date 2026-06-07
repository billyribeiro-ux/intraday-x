"""Lake catalog — what's stored and how fresh it is.

Coverage answers "what do we already have?" so an ingest can fetch only the
missing tail, and so a backtest fails loud if the requested range isn't fully
present rather than silently running on a short window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl

from intradayx.domain.bars import Timeframe
from intradayx.storage.lake import Lake


@dataclass(frozen=True, slots=True)
class Coverage:
    symbol: str
    timeframe: Timeframe
    first_ts: datetime
    last_ts: datetime
    row_count: int


class Catalog:
    def __init__(self, lake: Lake) -> None:
        self.lake = lake

    def coverage(self, symbol: str, timeframe: Timeframe) -> Coverage | None:
        base = self.lake._bars_symbol_dir(symbol, timeframe)
        if not base.exists():
            return None
        stats = (
            pl.scan_parquet(base / "**" / "*.parquet")
            .select(
                first=pl.col("ts").min(),
                last=pl.col("ts").max(),
                n=pl.len(),
            )
            .collect()
        )
        if stats.is_empty() or stats["n"].item(0) == 0:
            return None
        return Coverage(
            symbol=symbol,
            timeframe=timeframe,
            first_ts=stats["first"].item(0),
            last_ts=stats["last"].item(0),
            row_count=int(stats["n"].item(0)),
        )
