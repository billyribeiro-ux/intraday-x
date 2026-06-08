"""Short-squeeze price/volume signature — fires on the footprint, not on quiet bars."""

from __future__ import annotations

import polars as pl

from intradayx.features.squeeze import add_squeeze_signature


def _frame(rvol: float, range_atr: float, close_position: float, *, up: bool, new_high: bool):
    # `add_squeeze_signature` needs rvol, range_atr, close_position, open/high/close.
    close_now = 105.0 if new_high else 99.0
    closes = [*([100.0] * 20), close_now]  # 20-bar prior high of 100, then the test bar
    highs = [*([101.0] * 20), close_now + 0.5]
    opens = [*([100.0] * 20), 99.0 if up else 106.0]
    return pl.DataFrame(
        {
            "open": opens,
            "high": highs,
            "close": closes,
            "rvol": [1.0] * 20 + [rvol],
            "range_atr": [0.5] * 20 + [range_atr],
            "close_position": [0.5] * 20 + [close_position],
        }
    )


def test_squeeze_signature_fires_on_footprint() -> None:
    df = add_squeeze_signature(_frame(6.0, 3.0, 1.0, up=True, new_high=True))
    score = df["squeeze_signature_score"].item(-1)
    assert score > 0.8  # extreme vol + wide range + close at high + new high
    assert df["new_high_break"].item(-1) is True


def test_no_signature_on_down_bar() -> None:
    df = add_squeeze_signature(_frame(6.0, 3.0, 0.2, up=False, new_high=False))
    assert df["squeeze_signature_score"].item(-1) == 0.0  # down bar => not a squeeze


def test_no_signature_on_quiet_volume() -> None:
    df = add_squeeze_signature(_frame(1.0, 0.5, 1.0, up=True, new_high=True))
    assert df["squeeze_signature_score"].item(-1) < 0.3  # no volume => no squeeze
