"""Volume-climax / exhaustion features.

A climax bar = extreme relative volume + a wide range + a wick rejecting the
extreme (close pushed back off the high/low). It signals exhaustion at a turning
point, not direction on its own (see docs/AI_LANDMINES.md). We emit two bounded
[0,1] scores gated by volume, so a wide bar on quiet volume is not a climax:

* ``climax_up_score``   — potential TOP (selling into the highs).
* ``climax_down_score`` — potential BOTTOM (buying off the lows).
"""

from __future__ import annotations

import polars as pl

RVOL_FULL = 3.0  # rvol at/above this counts as full volume conviction
RANGE_ATR_FULL = 2.0  # range/ATR at/above this counts as full range conviction


def add_climax(df: pl.DataFrame) -> pl.DataFrame:
    rng = (pl.col("high") - pl.col("low")).clip(lower_bound=1e-9)
    body_top = pl.max_horizontal("open", "close")
    body_bot = pl.min_horizontal("open", "close")

    upper_wick_frac = ((pl.col("high") - body_top) / rng).clip(0.0, 1.0)
    lower_wick_frac = ((body_bot - pl.col("low")) / rng).clip(0.0, 1.0)
    close_pos = ((pl.col("close") - pl.col("low")) / rng).clip(0.0, 1.0)

    vol_factor = (pl.col("rvol") / RVOL_FULL).clip(0.0, 1.0).fill_null(0.0)
    range_factor = ((pl.col("high") - pl.col("low")) / pl.col("atr") / RANGE_ATR_FULL).clip(
        0.0, 1.0
    ).fill_null(0.0)

    climax_up = vol_factor * (
        0.4 * range_factor + 0.3 * upper_wick_frac + 0.3 * (1.0 - close_pos)
    )
    climax_down = vol_factor * (0.4 * range_factor + 0.3 * lower_wick_frac + 0.3 * close_pos)

    return df.with_columns(
        range_atr=((pl.col("high") - pl.col("low")) / pl.col("atr")),
        upper_wick_frac=upper_wick_frac,
        lower_wick_frac=lower_wick_frac,
        close_position=close_pos,
        climax_up_score=climax_up.clip(0.0, 1.0),
        climax_down_score=climax_down.clip(0.0, 1.0),
    )
