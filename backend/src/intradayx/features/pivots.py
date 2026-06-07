"""Causal swing-pivot detection (tops/bottoms).

A swing high at bar ``j`` means ``high[j]`` is the max over ``[j-k, j+k]``. That
fact is only *known* k bars later, so we expose it CAUSALLY: a pivot is
"confirmed" at bar ``i = j+k``, where every input bar (``[j-k, i]``) is already
available. The reversal scanner acts on the confirmation bar, never on the
extreme bar itself — using a centered/ZigZag pivot as a live feature would leak
the future (see docs/AI_LANDMINES.md).

Columns added (all valued AT the confirmation bar ``i``):
* ``confirmed_swing_high`` / ``confirmed_swing_low`` — bool
* ``swing_high_price`` / ``swing_low_price`` — the pivot extreme (k bars back)
* ``pivot_lookback`` — k (bars back to the extreme)
"""

from __future__ import annotations

import polars as pl

DEFAULT_K = 3


def add_pivots(df: pl.DataFrame, k: int = DEFAULT_K) -> pl.DataFrame:
    """Add causal confirmed-pivot columns. ``k`` = bars on each side."""
    window = 2 * k + 1
    # Centered rolling extreme at the pivot bar j; then shift(k) so the value
    # lands on the confirmation bar i=j+k, using only data up to i.
    centered_max = pl.col("high").rolling_max(window_size=window, center=True, min_samples=window)
    centered_min = pl.col("low").rolling_min(window_size=window, center=True, min_samples=window)
    is_ph = pl.col("high") == centered_max
    is_pl = pl.col("low") == centered_min
    return df.with_columns(
        confirmed_swing_high=is_ph.shift(k).fill_null(False),
        confirmed_swing_low=is_pl.shift(k).fill_null(False),
        swing_high_price=pl.col("high").shift(k),
        swing_low_price=pl.col("low").shift(k),
        pivot_lookback=pl.lit(k, dtype=pl.Int32),
    )
