"""Reversal (tops/bottoms) strategy — the FIRST scanner.

Vectorized confluence of deterministic detectors gated on a CONFIRMED causal
swing pivot. A top fires near a confirmed swing high when climax/volume/value-
area-edge/POC confluence clears the threshold; a bottom is the mirror. Output is
a Polars frame of triggered bars (with each component score retained for honest
attribution). :class:`~intradayx.signals.engine.SignalEngine` turns rows into
``Signal`` objects — and the SAME frame logic runs in backtest and live.

v0.2 adds a signal-quality layer: minimum R:R, price-extension limits, cooldown,
and a hard block on fading a strong trending regime.
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
from intradayx.signals.quality import ensure_quality_columns, quality_score_expr

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
    "quality_score",
)


def _extension_expr() -> pl.Expr:
    """Fallback extension when the pre-computed column is absent (e.g. tests)."""
    return pl.col("vwap_extension").fill_null(
        (pl.col("close") - pl.col("vwap_session")) / pl.col("atr").clip(lower_bound=1e-9)
    )


def _adx_expr() -> pl.Expr:
    return pl.col("adx").fill_null(0.0)


def _trend_expr() -> pl.Expr:
    return pl.col("trend_regime").fill_null("range")


def _quality_filter(df: pl.DataFrame, p: ReversalParams) -> pl.DataFrame:
    """Enforce R:R, extension bounds, and strong-trend avoidance."""
    stop_dist = (pl.col("stop") - pl.col("entry")).abs().clip(lower_bound=1e-9)
    target_dist = (pl.col("target1") - pl.col("entry")).abs()
    rr = target_dist / stop_dist
    extension = _extension_expr().abs()
    adx = _adx_expr()
    trend = _trend_expr()

    return df.filter(
        (rr >= p.min_rr)
        & (extension >= p.extension_min_atr)
        & (extension <= p.extension_max_atr)
        & ~(
            (pl.col("kind") == SignalKind.REVERSAL_TOP.value)
            & (trend == pl.lit("bull"))
            & (adx >= p.counter_trend_adx_threshold)
        )
        & ~(
            (pl.col("kind") == SignalKind.REVERSAL_BOTTOM.value)
            & (trend == pl.lit("bear"))
            & (adx >= p.counter_trend_adx_threshold)
        )
    )


def _apply_cooldown(df: pl.DataFrame, cooldown_bars: int) -> pl.DataFrame:
    """Keep the first signal per side, then silence any within ``cooldown_bars``."""
    if cooldown_bars <= 0 or df.is_empty():
        return df
    df = df.with_columns(_idx=pl.int_range(0, pl.len(), dtype=pl.Int64))
    rows = list(df.iter_rows(named=True))
    kept: list[dict[str, Any]] = []
    last_idx: dict[str, int] = {}
    for row in rows:
        side = row["side"]
        idx = row["_idx"]
        if idx - last_idx.get(side, -cooldown_bars - 1) > cooldown_bars:
            kept.append(row)
            last_idx[side] = idx
    if not kept:
        return df.head(0).select(SIGNAL_COLUMNS)
    return pl.DataFrame(kept).select(SIGNAL_COLUMNS)


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

    df = ensure_quality_columns(df)

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
        .with_columns(quality_score=quality_score_expr())
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
        .with_columns(quality_score=quality_score_expr())
    )

    triggered = pl.concat([tops, bottoms]).sort("ts")
    quality = _quality_filter(triggered, p)
    return _apply_cooldown(quality, p.cooldown_bars)


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
