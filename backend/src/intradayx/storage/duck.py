"""DuckDB SQL surface over the Parquet lake.

A thin convenience for ad-hoc analytics and the future API — it registers
``bars`` / ``internals`` views with Hive partition columns exposed, so you can
``SELECT * FROM bars WHERE symbol = 'SPY' AND timeframe = '1m'`` and let DuckDB
prune partitions. The hot path (feature engineering) reads via Polars directly;
this is for exploration and SQL-shaped queries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


def connect(lake_root: Path | str) -> Any:
    """Open an in-memory DuckDB connection with lake views registered."""
    root = Path(lake_root)
    con = duckdb.connect()
    if (root / "bars").exists():
        bars_glob = str(root / "bars" / "**" / "*.parquet")
        con.execute(
            "CREATE VIEW IF NOT EXISTS bars AS "
            f"SELECT * FROM read_parquet('{bars_glob}', hive_partitioning=true)"
        )
    if (root / "internals").exists():
        internals_glob = str(root / "internals" / "**" / "*.parquet")
        con.execute(
            "CREATE VIEW IF NOT EXISTS internals AS "
            f"SELECT * FROM read_parquet('{internals_glob}', hive_partitioning=true)"
        )
    return con
