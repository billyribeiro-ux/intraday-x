"""Scalping scanner — the SECOND strategy, on the same SignalEngine interface.

Discrete momentum entries (not every bar): a VWAP reclaim/rejection OR an
Initial-Balance breakout, confirmed by relative volume + a directional bar.
Tight ATR-based stop and targets. Same universal SIGNAL columns as the reversal
strategy, so the backtester/export/API/dashboard all reuse it unchanged.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from intradayx.attribution.engine import scalping_attribution
from intradayx.domain.signals import Attribution, SignalKind
from intradayx.features.pipeline import FeatureSet
from intradayx.signals.params import ScalpingParams

SCALP_COLUMNS = (
    "ts",
    "kind",
    "side",
    "tod_bucket",
    "entry",
    "stop",
    "target1",
    "target2",
    "confluence",
    "c_vwap",
    "c_volume",
    "c_momentum",
    "c_breakout",
)


def scalping_signal_frame(fs: FeatureSet, params: ScalpingParams) -> pl.DataFrame:
    p = params
    close = pl.col("close")
    open_ = pl.col("open")
    vwap = pl.col("vwap_session")
    atr = pl.col("atr")
    ib_high = pl.col("ib_high")
    ib_low = pl.col("ib_low")
    prev_close = close.shift(1)
    prev_vwap = vwap.shift(1)

    df = fs.df.with_columns(
        c_vwap_long=pl.when(close > vwap)
        .then(0.5 + 0.5 * ((close - vwap) / (atr * p.vwap_atr)).clip(0.0, 1.0))
        .otherwise(0.0),
        c_vwap_short=pl.when(close < vwap)
        .then(0.5 + 0.5 * ((vwap - close) / (atr * p.vwap_atr)).clip(0.0, 1.0))
        .otherwise(0.0),
        c_volume=(pl.col("rvol") / p.rvol_full).clip(0.0, 1.0).fill_null(0.0),
        c_mom_long=pl.when(close >= open_).then(pl.col("close_position")).otherwise(0.0),
        c_mom_short=pl.when(close < open_).then(1.0 - pl.col("close_position")).otherwise(0.0),
        c_brk_long=pl.when(ib_high.is_not_null() & (close > ib_high)).then(1.0).otherwise(0.0),
        c_brk_short=pl.when(ib_low.is_not_null() & (close < ib_low)).then(1.0).otherwise(0.0),
    ).with_columns(
        conf_long=(
            p.w_vwap * pl.col("c_vwap_long")
            + p.w_volume * pl.col("c_volume")
            + p.w_momentum * pl.col("c_mom_long")
            + p.w_breakout * pl.col("c_brk_long")
        ),
        conf_short=(
            p.w_vwap * pl.col("c_vwap_short")
            + p.w_volume * pl.col("c_volume")
            + p.w_momentum * pl.col("c_mom_short")
            + p.w_breakout * pl.col("c_brk_short")
        ),
        long_trig=((close > vwap) & (prev_close <= prev_vwap))
        | (ib_high.is_not_null() & (close > ib_high) & (prev_close <= ib_high)),
        short_trig=((close < vwap) & (prev_close >= prev_vwap))
        | (ib_low.is_not_null() & (close < ib_low) & (prev_close >= ib_low)),
    )

    longs = (
        df.filter(pl.col("long_trig") & (pl.col("conf_long") >= p.threshold))
        .with_columns(
            kind=pl.lit("scalp_long"),
            side=pl.lit("buy"),
            entry=close,
            stop=close - atr * p.atr_stop_mult,
            target1=close + atr * p.atr_target_mult,
            target2=close + atr * p.atr_target_mult * 2,
            confluence=pl.col("conf_long"),
            c_vwap=pl.col("c_vwap_long"),
            c_momentum=pl.col("c_mom_long"),
            c_breakout=pl.col("c_brk_long"),
        )
        .select(SCALP_COLUMNS)
    )
    shorts = (
        df.filter(pl.col("short_trig") & (pl.col("conf_short") >= p.threshold))
        .with_columns(
            kind=pl.lit("scalp_short"),
            side=pl.lit("sell"),
            entry=close,
            stop=close + atr * p.atr_stop_mult,
            target1=close - atr * p.atr_target_mult,
            target2=close - atr * p.atr_target_mult * 2,
            confluence=pl.col("conf_short"),
            c_vwap=pl.col("c_vwap_short"),
            c_momentum=pl.col("c_mom_short"),
            c_breakout=pl.col("c_brk_short"),
        )
        .select(SCALP_COLUMNS)
    )
    return pl.concat([longs, shorts]).sort("ts")


class ScalpingStrategy:
    """Strategy adapter for the scalping scanner."""

    name = "scalping"

    def __init__(self, params: ScalpingParams | None = None) -> None:
        self.params = params or ScalpingParams()

    @property
    def params_version(self) -> str:
        return self.params.version

    def signal_frame(self, fs: FeatureSet) -> pl.DataFrame:
        return scalping_signal_frame(fs, self.params)

    def attribution(self, row: dict[str, Any], data_completeness: float) -> Attribution:
        return scalping_attribution(
            is_long=row["kind"] == SignalKind.SCALP_LONG.value,
            c_vwap=float(row.get("c_vwap") or 0.0),
            c_volume=float(row.get("c_volume") or 0.0),
            c_momentum=float(row.get("c_momentum") or 0.0),
            c_breakout=float(row.get("c_breakout") or 0.0),
            params=self.params,
            data_completeness=data_completeness,
        )
