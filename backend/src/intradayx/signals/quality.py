"""Signal-quality scoring — a deterministic lens on top of the strategy frame.

The score is intentionally separate from the strategy's confluence so the core
rule set stays stable while the quality layer can be tightened/loosened or
replaced by a learned meta-model later.  All inputs are causal and optional;
missing columns get neutral default scores rather than blocking.
"""

from __future__ import annotations

import polars as pl

from intradayx.domain.signals import SignalKind


def ensure_quality_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Add neutral default quality inputs when the upstream pipeline omitted them."""
    cols = set(df.columns)
    if "vwap_extension" not in cols:
        df = df.with_columns(
            vwap_extension=(pl.col("close") - pl.col("vwap_session"))
            / pl.col("atr").clip(lower_bound=1e-9)
        )
    if "adx" not in cols:
        df = df.with_columns(adx=pl.lit(0.0))
    if "trend_regime" not in cols:
        df = df.with_columns(trend_regime=pl.lit("range"))
    if "bar_strength" not in cols:
        df = df.with_columns(bar_strength=pl.lit(0.0))
    if "momentum_3bar" not in cols:
        df = df.with_columns(momentum_3bar=pl.lit(0.0))
    if "volume_delta_proxy" not in cols:
        df = df.with_columns(volume_delta_proxy=pl.lit(0.0))
    return df


def _side_sign_expr(kind: pl.Expr) -> pl.Expr:
    """+1 for buy/long, -1 for sell/short."""
    return (
        pl.when(
            kind.is_in(
                [SignalKind.REVERSAL_BOTTOM.value, SignalKind.SCALP_LONG.value]
            )
        )
        .then(1)
        .otherwise(-1)
    )


def quality_score_expr(
    kind: pl.Expr | str = "kind",
    entry: pl.Expr | str = "entry",
    stop: pl.Expr | str = "stop",
    target1: pl.Expr | str = "target1",
    atr: pl.Expr | str = "atr",
    vwap: pl.Expr | str = "vwap_session",
    extension: pl.Expr | str = "vwap_extension",
    adx: pl.Expr | str = "adx",
    trend: pl.Expr | str = "trend_regime",
    bar_strength: pl.Expr | str = "bar_strength",
    momentum: pl.Expr | str = "momentum_3bar",
    volume_delta: pl.Expr | str = "volume_delta_proxy",
) -> pl.Expr:
    """Vectorized 0–1 quality score for a triggered signal row.

    Components:
    * R:R (reward vs risk)
    * extension (mean-reversion / pullback sizing)
    * trend (don't fade strong trends; scalp with them)
    * confirmation (bar strength, momentum, volume delta aligned with side)
    """
    kind_e = pl.col(kind) if isinstance(kind, str) else kind
    entry_e = pl.col(entry) if isinstance(entry, str) else entry
    stop_e = pl.col(stop) if isinstance(stop, str) else stop
    target1_e = pl.col(target1) if isinstance(target1, str) else target1
    atr_e = pl.col(atr) if isinstance(atr, str) else atr
    vwap_e = pl.col(vwap) if isinstance(vwap, str) else vwap
    ext_e = pl.col(extension) if isinstance(extension, str) else extension
    adx_e = pl.col(adx) if isinstance(adx, str) else adx
    trend_e = pl.col(trend) if isinstance(trend, str) else trend
    bar_e = pl.col(bar_strength) if isinstance(bar_strength, str) else bar_strength
    mom_e = pl.col(momentum) if isinstance(momentum, str) else momentum
    vol_e = pl.col(volume_delta) if isinstance(volume_delta, str) else volume_delta

    # Fallbacks for tests / partial data.
    ext_fallback = (entry_e - vwap_e) / atr_e.clip(lower_bound=1e-9)
    ext = ext_e.fill_null(ext_fallback)
    adx_f = adx_e.fill_null(0.0)
    trend_f = trend_e.fill_null("range")
    bar_f = bar_e.fill_null(0.0)
    mom_f = mom_e.fill_null(0.0)
    vol_f = vol_e.fill_null(0.0)

    side_sign = _side_sign_expr(kind_e)

    stop_dist = (entry_e - stop_e).abs().clip(lower_bound=1e-9)
    target_dist = (target1_e - entry_e).abs()
    rr = target_dist / stop_dist
    rr_score = rr.clip(0.0, 2.0) / 2.0

    is_reversal = kind_e.is_in(
        [SignalKind.REVERSAL_TOP.value, SignalKind.REVERSAL_BOTTOM.value]
    )
    extension_score = pl.when(is_reversal).then(
        (1.0 - (ext - 1.5).abs() / 2.0).clip(0.0, 1.0)
    ).otherwise((1.0 - ext.abs() / 2.0).clip(0.0, 1.0))

    is_top = kind_e == SignalKind.REVERSAL_TOP.value
    is_bottom = kind_e == SignalKind.REVERSAL_BOTTOM.value
    is_long = kind_e == SignalKind.SCALP_LONG.value
    reversal_counter = (
        (is_top & (trend_f == pl.lit("bull")))
        | (is_bottom & (trend_f == pl.lit("bear")))
    )
    reversal_trend_score = pl.when(reversal_counter & (adx_f >= 40.0)).then(0.0).otherwise(1.0)
    scalp_aligned = (
        (is_long & trend_f.is_in(["bull", "range"]))
        | ((~is_long) & trend_f.is_in(["bear", "range"]))
    )
    scalp_trend_score = pl.when(scalp_aligned).then(1.0).otherwise(0.3)
    trend_score = pl.when(is_reversal).then(reversal_trend_score).otherwise(scalp_trend_score)

    conf_strength = pl.when((bar_f * side_sign) > -0.3).then(1.0).otherwise(0.0)
    conf_momentum = pl.when((mom_f * side_sign) > -0.5).then(1.0).otherwise(0.3)
    conf_volume = pl.when((vol_f * side_sign) >= 0.0).then(1.0).otherwise(0.3)
    confirmation_score = (conf_strength + conf_momentum + conf_volume) / 3.0

    return (rr_score + extension_score + trend_score + confirmation_score) / 4.0
