"""Local Parquet lake — Hive-partitioned bars & internals.

Layout (under ``root``)::

    bars/timeframe=1m/symbol=SPY/year=2024/month=03/data.parquet
    internals/symbol=TICK/year=2024/month=03/data.parquet

Partitioning by ``(timeframe, symbol, year, month)`` means a typical query
("one symbol, one timeframe, a date range") only reads the months it needs.
Writes are idempotent: re-ingesting an overlapping window merges on ``ts`` and
keeps the latest row, so a re-run never duplicates bars.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl

from intradayx.domain.bars import BAR_SCHEMA, BarSet, Timeframe
from intradayx.domain.internals import INTERNALS_SCHEMA, InternalsSeries, InternalSymbol


class Lake:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # ----- bars -----

    def _bars_symbol_dir(self, symbol: str, timeframe: Timeframe) -> Path:
        return self.root / "bars" / f"timeframe={timeframe.value}" / f"symbol={symbol}"

    def write_bars(self, bars: BarSet) -> int:
        """Write a BarSet into month partitions (idempotent upsert). Returns rows written."""
        if bars.is_empty():
            return 0
        df = bars.df.with_columns(
            _year=pl.col("ts").dt.year(),
            _month=pl.col("ts").dt.month(),
        )
        base = self._bars_symbol_dir(bars.symbol, bars.timeframe)
        written = 0
        for (year, month), grp in df.group_by(["_year", "_month"]):
            part = base / f"year={year}" / f"month={int(month):02d}"
            part.mkdir(parents=True, exist_ok=True)
            file = part / "data.parquet"
            out = grp.drop("_year", "_month")
            if file.exists():
                out = (
                    pl.concat([pl.read_parquet(file), out])
                    .unique(subset=["ts"], keep="last")
                    .sort("ts")
                )
            out.write_parquet(file)
            written += out.height
        return written

    def read_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> BarSet:
        base = self._bars_symbol_dir(symbol, timeframe)
        if not base.exists():
            return BarSet(symbol, timeframe, pl.DataFrame(schema=BAR_SCHEMA))
        df = (
            pl.scan_parquet(base / "**" / "*.parquet")
            .filter((pl.col("ts") >= start) & (pl.col("ts") <= end))
            .collect()
        )
        return BarSet(symbol, timeframe, df)

    # ----- internals -----

    def _internals_symbol_dir(self, symbol: InternalSymbol, timeframe: Timeframe) -> Path:
        return (
            self.root
            / "internals"
            / f"timeframe={timeframe.value}"
            / f"symbol={symbol.name}"  # enum name avoids the '$' in the path
        )

    def write_internals(self, series: InternalsSeries) -> int:
        if series.is_empty():
            return 0
        df = series.df.with_columns(
            _year=pl.col("ts").dt.year(),
            _month=pl.col("ts").dt.month(),
        )
        base = self._internals_symbol_dir(series.symbol, series.timeframe)
        written = 0
        for (year, month), grp in df.group_by(["_year", "_month"]):
            part = base / f"year={year}" / f"month={int(month):02d}"
            part.mkdir(parents=True, exist_ok=True)
            file = part / "data.parquet"
            out = grp.drop("_year", "_month")
            if file.exists():
                out = (
                    pl.concat([pl.read_parquet(file), out])
                    .unique(subset=["ts"], keep="last")
                    .sort("ts")
                )
            out.write_parquet(file)
            written += out.height
        return written

    def read_internals(
        self, symbol: InternalSymbol, timeframe: Timeframe, start: datetime, end: datetime
    ) -> InternalsSeries:
        base = self._internals_symbol_dir(symbol, timeframe)
        if not base.exists():
            return InternalsSeries(symbol, timeframe, pl.DataFrame(schema=INTERNALS_SCHEMA))
        df = (
            pl.scan_parquet(base / "**" / "*.parquet")
            .filter((pl.col("ts") >= start) & (pl.col("ts") <= end))
            .collect()
        )
        return InternalsSeries(symbol, timeframe, df)
