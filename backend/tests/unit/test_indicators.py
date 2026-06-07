"""Indicator maths vs hand-computed values."""

from __future__ import annotations

import math

from intradayx.features.indicators import add_atr, add_vwap_session
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
