"""Reversal (tops/bottoms) strategy — the FIRST scanner.

Vectorized confluence of deterministic detectors gated on a CONFIRMED causal
swing pivot. A top fires near a confirmed swing high when climax/volume/value-
area-edge/POC confluence clears the threshold; a bottom is the mirror. Output is
a Polars frame of triggered bars (with each component score retained for honest
attribution). :class:`~intradayx.signals.engine.SignalEngine` turns rows into
``Signal`` objects — and the SAME frame logic runs in backtest and live.
"""

from __future__ import annotations

import polars as pl

from intradayx.attribution.detectors.price_volume import (
    climax_bottom,
    climax_top,
    poc_proximity,
    value_area_edge_bottom,
    value_area_edge_top,
    volume_surge,
)
from intradayx.features.pipeline import FeatureSet
from intradayx.signals.params import ReversalParams

# Unified column order for a triggered-signal row (top or bottom).
SIGNAL_COLUMNS = (
    "ts",
    "kind",
    "side",
    "tod_bucket",
    "entry",
    "stop",
    "target1",
    "target2",
    "confluence",
    "c_climax",
    "c_volume",
    "c_value_area",
    "c_poc",
)


def reversal_signal_frame(fs: FeatureSet, params: ReversalParams) -> pl.DataFrame:
    """Return triggered reversal signals (top & bottom) as one frame, ts-sorted."""
    p = params
    df = fs.df.with_columns(
        c_volume=volume_surge(p),
        c_climax_top=climax_top(),
        c_climax_bottom=climax_bottom(),
        c_vae_top=value_area_edge_top(p),
        c_vae_bottom=value_area_edge_bottom(p),
        c_poc=poc_proximity(p),
    ).with_columns(
        confluence_top=(
            p.w_climax * pl.col("c_climax_top")
            + p.w_volume * pl.col("c_volume")
            + p.w_value_area * pl.col("c_vae_top")
            + p.w_poc * pl.col("c_poc")
        ),
        confluence_bottom=(
            p.w_climax * pl.col("c_climax_bottom")
            + p.w_volume * pl.col("c_volume")
            + p.w_value_area * pl.col("c_vae_bottom")
            + p.w_poc * pl.col("c_poc")
        ),
    )

    tops = (
        df.filter(pl.col("confirmed_swing_high") & (pl.col("confluence_top") >= p.threshold))
        .with_columns(
            kind=pl.lit("reversal_top"),
            side=pl.lit("sell"),
            entry=pl.col("close"),
            stop=pl.col("swing_high_price") + pl.col("atr") * p.atr_stop_mult,
            target1=pl.col("vwap_session"),
            target2=pl.col("prior_poc"),
            confluence=pl.col("confluence_top"),
            c_climax=pl.col("c_climax_top"),
            c_value_area=pl.col("c_vae_top"),
        )
        .select(SIGNAL_COLUMNS)
    )

    bottoms = (
        df.filter(pl.col("confirmed_swing_low") & (pl.col("confluence_bottom") >= p.threshold))
        .with_columns(
            kind=pl.lit("reversal_bottom"),
            side=pl.lit("buy"),
            entry=pl.col("close"),
            stop=pl.col("swing_low_price") - pl.col("atr") * p.atr_stop_mult,
            target1=pl.col("vwap_session"),
            target2=pl.col("prior_poc"),
            confluence=pl.col("confluence_bottom"),
            c_climax=pl.col("c_climax_bottom"),
            c_value_area=pl.col("c_vae_bottom"),
        )
        .select(SIGNAL_COLUMNS)
    )

    return pl.concat([tops, bottoms]).sort("ts")
