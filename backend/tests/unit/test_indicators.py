"""Indicator maths vs hand-computed values."""

from __future__ import annotations

import math

from intradayx.features.indicators import (
    add_adx,
    add_atr,
    add_bar_strength,
    add_trend_regime,
    add_vwap_extension,
    add_vwap_session,
)
from intradayx.features.session import add_session_columns
from tests.fixtures.synthetic import make_bars


def test_vwap_session_matches_hand_computation() -> None:
    # Two bars, one session. tp = (H+L+C)/3.
    bars = make_bars(
        closes=[10.0, 11.0],
        highs=[11.0, 12.0],
        lows=[9.0, 10.0],
        volumes=[100, 100],
    )
    df = add_vwap_session(add_session_columns(bars.df))
    # tp0=10, tp1=11; vwap at bar1 = (10*100 + 11*100)/200 = 10.5
    assert math.isclose(df["vwap_session"].item(0), 10.0, rel_tol=1e-9)
    assert math.isclose(df["vwap_session"].item(1), 10.5, rel_tol=1e-9)


def test_atr_matches_true_range_mean() -> None:
    # Three bars each with true range 2.0 → ATR(window=2) == 2.0.
    bars = make_bars(
        closes=[10.0, 11.0, 12.0],
        highs=[11.0, 12.0, 13.0],
        lows=[9.0, 10.0, 11.0],
    )
    df = add_atr(bars.df, window=2)
    assert math.isclose(df["true_range"].item(0), 2.0, rel_tol=1e-9)
    assert math.isclose(df["atr"].item(2), 2.0, rel_tol=1e-9)


def test_atr_first_bar_is_null_until_window_filled() -> None:
    bars = make_bars(closes=[10.0, 11.0, 12.0])
    df = add_atr(bars.df, window=2)
    # window=2 → first bar has no full window
    assert df["atr"].item(0) is None


def test_bar_strength_is_signed_body_over_range() -> None:
    bars = make_bars(
        closes=[11.0],
        opens=[10.0],
        highs=[12.0],
        lows=[9.0],
    )
    df = add_bar_strength(bars.df)
    # body = 1, range = 3 → strength ≈ 0.333
    assert math.isclose(df["bar_strength"].item(0), 1.0 / 3.0, rel_tol=1e-9)


def test_vwap_extension_in_atr_units() -> None:
    bars = make_bars(
        closes=[100.0],
        opens=[100.0],
        highs=[101.0],
        lows=[99.0],
        volumes=[1000],
    )
    df = add_session_columns(bars.df)
    df = add_vwap_session(df)
    df = add_atr(df, window=1)
    df = add_vwap_extension(df)
    # tp = (101+99+100)/3 = 100 = close, so extension = 0
    assert math.isclose(df["vwap_extension"].item(0), 0.0, abs_tol=1e-9)


def test_adx_and_trend_regime_on_strong_uptrend() -> None:
    # 30 straight up bars: high > prev high, close rising.
    closes = [float(i) for i in range(1, 31)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    bars = make_bars(closes=closes, highs=highs, lows=lows)
    df = add_adx(add_atr(bars.df))
    df = add_trend_regime(df)
    # By the end ADX should be high and regime bullish.
    assert df["adx"].drop_nulls()[-1] > 20.0
    assert df["trend_regime"].drop_nulls()[-1] == "bull"
