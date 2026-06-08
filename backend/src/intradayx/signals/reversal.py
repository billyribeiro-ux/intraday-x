"""Reversal (tops/bottoms) strategy — the FIRST scanner.

Vectorized confluence of deterministic detectors gated on a CONFIRMED causal
swing pivot. A top fires near a confirmed swing high when climax/volume/value-
area-edge/POC confluence clears the threshold; a bottom is the mirror. Output is
a Polars frame of triggered bars (with each component score retained for honest
attribution). :class:`~intradayx.signals.engine.SignalEngine` turns rows into
``Signal`` objects — and the SAME frame logic runs in backtest and live.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from intradayx.attribution.detectors.price_volume import (
    climax_bottom,
    climax_top,
    poc_proximity,
    value_area_edge_bottom,
    value_area_edge_top,
    volume_surge,
)
from intradayx.attribution.engine import reversal_attribution
from intradayx.domain.signals import Attribution, SignalKind
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


class ReversalStrategy:
    """Strategy adapter for the reversal scanner."""

    name = "reversal"

    def __init__(self, params: ReversalParams | None = None) -> None:
        self.params = params or ReversalParams()

    @property
    def params_version(self) -> str:
        return self.params.version

    def signal_frame(self, fs: FeatureSet) -> pl.DataFrame:
        return reversal_signal_frame(fs, self.params)

    def attribution(self, row: dict[str, Any], data_completeness: float) -> Attribution:
        return reversal_attribution(
            is_top=row["kind"] == SignalKind.REVERSAL_TOP.value,
            c_climax=float(row.get("c_climax") or 0.0),
            c_volume=float(row.get("c_volume") or 0.0),
            c_value_area=float(row.get("c_value_area") or 0.0),
            c_poc=float(row.get("c_poc") or 0.0),
            params=self.params,
            data_completeness=data_completeness,
        )
