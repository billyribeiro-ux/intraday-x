"""Deterministic SignalEngine anchor — hand-crafted features → known signal.

Builds a FeatureSet directly (bypassing feature computation) so the strategy +
attribution + engine maths is asserted exactly, and confirms determinism (same
inputs → same signal_id), which is what guarantees backtest↔live agreement.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import polars as pl

from intradayx.domain.bars import Timeframe
from intradayx.domain.signals import CauseKind, Side, SignalKind, make_signal_id
from intradayx.features.pipeline import FeatureSet
from intradayx.signals.engine import SignalEngine

_T0 = datetime(2024, 1, 2, 16, 0, tzinfo=UTC)
_T1 = datetime(2024, 1, 2, 16, 5, tzinfo=UTC)


def _feature_frame() -> pl.DataFrame:
    # Row 0: a clean reversal-top setup. Row 1: nothing.
    return pl.DataFrame(
        {
            "ts": [_T0, _T1],
            "close": [100.0, 100.0],
            "atr": [1.0, 1.0],
            "rvol": [4.0, 0.5],
            "climax_up_score": [0.9, 0.0],
            "climax_down_score": [0.0, 0.0],
            "prior_vah": [99.0, 99.0],
            "prior_val": [97.0, 97.0],
            "prior_poc": [98.0, 98.0],
            "vwap_session": [98.0, 98.0],
            "confirmed_swing_high": [True, False],
            "confirmed_swing_low": [False, False],
            "swing_high_price": [101.0, None],
            "swing_low_price": [None, None],
            "tod_bucket": ["lunch", "lunch"],
        }
    )


def _feature_set() -> FeatureSet:
    return FeatureSet(
        symbol="TEST",
        timeframe=Timeframe.M5,
        df=_feature_frame(),
        feature_manifest=frozenset(),
        data_completeness=0.5,
    )


def test_reversal_top_signal_is_produced_with_expected_fields() -> None:
    signals = SignalEngine().evaluate(_feature_set())
    assert len(signals) == 1
    s = signals[0]

    assert s.kind is SignalKind.REVERSAL_TOP
    assert s.side is Side.SELL
    assert s.entry == 100.0
    # stop = swing_high_price (101) + atr (1) * atr_stop_mult (0.25) = 101.25
    assert math.isclose(s.stop, 101.25, rel_tol=1e-9)
    # confluence = .45*.9 + .2*1 + .25*1 + .1*0 = .855 ; confidence = .855 * 0.5
    assert math.isclose(s.confidence, 0.855 * 0.5, rel_tol=1e-9)
    assert len(s.targets) == 2

    # Attribution is rule-based, not uncertain, and led by the climax.
    assert s.attribution.uncertain is False
    assert s.attribution.data_completeness == 0.5
    assert s.attribution.primary_cause is not None
    assert s.attribution.primary_cause.kind is CauseKind.CLIMAX_REVERSAL


def test_signal_id_is_deterministic() -> None:
    a = SignalEngine().evaluate(_feature_set())[0]
    b = SignalEngine().evaluate(_feature_set())[0]
    assert a.signal_id == b.signal_id
    assert a.signal_id == make_signal_id("TEST", _T0, SignalKind.REVERSAL_TOP, a.params_version)


def test_no_signal_when_no_pivot() -> None:
    df = _feature_frame().with_columns(confirmed_swing_high=pl.lit(False))
    fs = FeatureSet("TEST", Timeframe.M5, df, frozenset(), 0.5)
    assert SignalEngine().evaluate(fs) == []
