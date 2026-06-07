"""Short-squeeze PRICE/VOLUME signature (works on free OHLCV).

A real short-squeeze diagnosis needs short interest % + days-to-cover +
cost-to-borrow (a paid feed — Phase 8 proper). But the *footprint* is visible in
price/volume alone: a sharp vertical up-move, extreme relative volume, closing
near the high, breaking recent highs. We score that footprint and label it
honestly as a SIGNATURE — never a confirmed squeeze (see docs/AI_LANDMINES.md).
"""

from __future__ import annotations

import polars as pl

DEFAULT_RVOL_FULL = 4.0  # squeezes run on extreme volume
DEFAULT_RANGE_FULL = 2.0  # range / ATR for a full "vertical" reading
DEFAULT_NEW_HIGH_LOOKBACK = 20


def add_squeeze_signature(
    df: pl.DataFrame,
    *,
    rvol_full: float = DEFAULT_RVOL_FULL,
    range_full: float = DEFAULT_RANGE_FULL,
    lookback: int = DEFAULT_NEW_HIGH_LOOKBACK,
) -> pl.DataFrame:
    """Add ``squeeze_signature_score`` (0–1) and ``new_high_break``. Causal."""
    prior_high = (
        pl.col("high").rolling_max(window_size=lookback, min_samples=lookback).shift(1)
    )
    new_high = (pl.col("close") > prior_high).fill_null(False)
    up_bar = pl.col("close") >= pl.col("open")
    vol_factor = (pl.col("rvol") / rvol_full).clip(0.0, 1.0).fill_null(0.0)
    range_factor = (pl.col("range_atr") / range_full).clip(0.0, 1.0).fill_null(0.0)

    confirm = (
        0.4 * range_factor + 0.3 * pl.col("close_position") + 0.3 * new_high.cast(pl.Float64)
    )
    signature = pl.when(up_bar).then(vol_factor * confirm).otherwise(0.0)
    return df.with_columns(
        new_high_break=new_high,
        squeeze_signature_score=signature.clip(0.0, 1.0),
    )
