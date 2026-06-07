"""Causal pivot detection — confirmation is lagged, never peeks ahead."""

from __future__ import annotations

from intradayx.features.pivots import add_pivots
from tests.fixtures.synthetic import make_bars


def test_swing_high_confirmed_k_bars_after_peak() -> None:
    # Clear single peak at index 3 (high=13). With k=1 it confirms at index 4.
    highs = [10.0, 11.0, 12.0, 13.0, 12.0, 11.0, 10.0]
    bars = make_bars(closes=highs, highs=highs, lows=[h - 1 for h in highs])
    df = add_pivots(bars.df, k=1)

    # Causality: the peak bar itself does NOT yet know it's a pivot.
    assert df["confirmed_swing_high"].item(3) is False
    # Confirmed one bar later, pointing back at the peak price.
    assert df["confirmed_swing_high"].item(4) is True
    assert df["swing_high_price"].item(4) == 13.0


def test_swing_low_confirmed_k_bars_after_trough() -> None:
    lows = [13.0, 12.0, 11.0, 10.0, 11.0, 12.0, 13.0]
    bars = make_bars(closes=lows, highs=[x + 1 for x in lows], lows=lows)
    df = add_pivots(bars.df, k=1)
    assert df["confirmed_swing_low"].item(3) is False
    assert df["confirmed_swing_low"].item(4) is True
    assert df["swing_low_price"].item(4) == 10.0
