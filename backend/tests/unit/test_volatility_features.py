"""Volatility-regime features: causal as-of join, term-structure slope, honest gaps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from intradayx.domain.bars import Timeframe
from intradayx.domain.internals import INTERNALS_SCHEMA, InternalsSeries, InternalSymbol
from intradayx.features.volatility import VOLATILITY_REGIME_FEATURES, add_volatility_regime


def _bars(n: int) -> pl.DataFrame:
    t0 = datetime(2026, 6, 26, 13, 30, tzinfo=UTC)
    ts = [t0 + timedelta(minutes=5 * i) for i in range(n)]
    return pl.DataFrame({"ts": ts, "close": [100.0] * n})


def _series(sym: InternalSymbol, ts_vals: list[tuple[datetime, float]]) -> InternalsSeries:
    df = pl.DataFrame(
        {
            "ts": [t for t, _ in ts_vals],
            "value": [v for _, v in ts_vals],
            "source": ["x"] * len(ts_vals),
        },
        schema=INTERNALS_SCHEMA,
    )
    return InternalsSeries(sym, Timeframe.M5, df)


def test_vix_level_is_asof_backward() -> None:
    bars = _bars(3)  # 13:30, 13:35, 13:40
    t0 = datetime(2026, 6, 26, 13, 30, tzinfo=UTC)
    vix = _series(
        InternalSymbol.VIX,
        [(t0, 18.0), (t0 + timedelta(minutes=5), 18.5)],  # no print for the 3rd bar
    )
    out = add_volatility_regime(bars, vix=vix)
    levels = out["vix_level"].to_list()
    assert levels[0] == 18.0
    assert levels[1] == 18.5
    assert levels[2] == 18.5  # carried backward (most recent prior print), not fabricated


def test_term_slope_sign_flags_backwardation() -> None:
    bars = _bars(1)
    t0 = datetime(2026, 6, 26, 13, 30, tzinfo=UTC)
    # VIX9D above VIX3M => inverted term structure => positive slope => stress.
    out = add_volatility_regime(
        bars,
        vix=_series(InternalSymbol.VIX, [(t0, 30.0)]),
        vix9d=_series(InternalSymbol.VIX9D, [(t0, 33.0)]),
        vix3m=_series(InternalSymbol.VIX3M, [(t0, 30.0)]),
    )
    assert out["vix_term_slope"][0] > 0  # 33/30 - 1 = +0.10


def test_missing_series_omits_columns_no_fabrication() -> None:
    bars = _bars(2)
    out = add_volatility_regime(bars, vix=None)  # nothing supplied
    for col in VOLATILITY_REGIME_FEATURES:
        assert col not in out.columns  # honest: absent, not zero-filled
