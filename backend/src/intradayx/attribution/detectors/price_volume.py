"""Deterministic price/volume reversal detectors (vectorized).

Each returns a Polars expression scoring a candidate cause in [0, 1] from causal
feature columns. They're reused by the reversal strategy (and later scalping).
Mapping to :class:`~intradayx.domain.signals.CauseKind`:

* volume_surge      -> VOLUME_SURGE
* climax_top/bottom -> CLIMAX_REVERSAL
* value_area_edge   -> VALUE_AREA_EDGE
* poc_proximity     -> POC_REJECTION
"""

from __future__ import annotations

import polars as pl

from intradayx.signals.params import ReversalParams


def volume_surge(p: ReversalParams) -> pl.Expr:
    """Relative-volume conviction (symmetric for top/bottom)."""
    return (pl.col("rvol") / p.rvol_full).clip(0.0, 1.0).fill_null(0.0)


def climax_top() -> pl.Expr:
    return pl.col("climax_up_score").fill_null(0.0)


def climax_bottom() -> pl.Expr:
    return pl.col("climax_down_score").fill_null(0.0)


def value_area_edge_top(p: ReversalParams) -> pl.Expr:
    """Rejection at/above the prior session's Value Area High."""
    beyond = ((pl.col("close") - pl.col("prior_vah")) / (pl.col("atr") * p.vae_atr)).clip(0.0, 1.0)
    return (
        pl.when(pl.col("prior_vah").is_not_null() & (pl.col("close") >= pl.col("prior_vah")))
        .then(0.5 + 0.5 * beyond)
        .otherwise(0.0)
    )


def value_area_edge_bottom(p: ReversalParams) -> pl.Expr:
    """Rejection at/below the prior session's Value Area Low."""
    beyond = ((pl.col("prior_val") - pl.col("close")) / (pl.col("atr") * p.vae_atr)).clip(0.0, 1.0)
    return (
        pl.when(pl.col("prior_val").is_not_null() & (pl.col("close") <= pl.col("prior_val")))
        .then(0.5 + 0.5 * beyond)
        .otherwise(0.0)
    )


def poc_proximity(p: ReversalParams) -> pl.Expr:
    """Closeness of price to the prior session's POC (a mean-reversion magnet)."""
    dist = (pl.col("close") - pl.col("prior_poc")).abs() / (pl.col("atr") * p.poc_atr)
    return (
        pl.when(pl.col("prior_poc").is_not_null())
        .then((1.0 - dist).clip(0.0, 1.0))
        .otherwise(0.0)
    )
