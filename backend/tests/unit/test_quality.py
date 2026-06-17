"""Signal-quality filters: R:R, cooldown, extension, trend."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from intradayx.domain.bars import Timeframe
from intradayx.features.pipeline import FeatureSet
from intradayx.signals.engine import SignalEngine
from intradayx.signals.params import ReversalParams, ScalpingParams
from intradayx.signals.reversal import ReversalStrategy
from intradayx.signals.scalping import ScalpingStrategy

_T0 = datetime(2024, 1, 2, 16, 0, tzinfo=UTC)


def _reversal_fs() -> FeatureSet:
    """Two rows: row 0 is a clean top, row 1 is a weak top with bad R:R."""
    return FeatureSet(
        symbol="TEST",
        timeframe=Timeframe.M5,
        df=pl.DataFrame(
            {
                "ts": [_T0, _T0.replace(minute=5)],
                "open": [100.0, 100.0],
                "high": [101.0, 101.0],
                "low": [99.0, 99.0],
                "close": [100.0, 100.0],
                "volume": [1000, 1000],
                "atr": [1.0, 1.0],
                "rvol": [4.0, 4.0],
                "close_position": [0.5, 0.5],
                "ib_high": [None, None],
                "ib_low": [None, None],
                "climax_up_score": [0.9, 0.9],
                "climax_down_score": [0.0, 0.0],
                "prior_vah": [99.0, 99.0],
                "prior_val": [97.0, 97.0],
                "prior_poc": [98.0, 100.0],  # row 1 POC far away -> bad R:R
                "vwap_session": [98.0, 100.0],
                "confirmed_swing_high": [True, True],
                "confirmed_swing_low": [False, False],
                "swing_high_price": [101.0, 101.0],
                "swing_low_price": [None, None],
                "tod_bucket": ["lunch", "lunch"],
            }
        ),
        feature_manifest=frozenset(),
        data_completeness=0.5,
    )


def test_min_rr_filter_removes_poor_reward_risk() -> None:
    params = ReversalParams(min_rr=1.0)
    signals = SignalEngine(ReversalStrategy(params)).evaluate(_reversal_fs())
    # Row 0: target 98, entry 100, stop 101.25 → RR = 2/1.25 = 1.6 (kept)
    # Row 1: target 100, entry 100, stop 101.25 → RR = 0 (skipped)
    assert len(signals) == 1
    assert signals[0].ts == _T0


def test_cooldown_silences_same_side_signals_within_window() -> None:
    df = pl.DataFrame(
        {
            "ts": [_T0, _T0.replace(minute=5), _T0.replace(minute=10)],
            "close": [100.0, 100.5, 101.0],
            "atr": [1.0, 1.0, 1.0],
            "rvol": [4.0, 4.0, 4.0],
            "climax_up_score": [0.9, 0.9, 0.9],
            "climax_down_score": [0.0, 0.0, 0.0],
            "prior_vah": [99.0, 99.0, 99.0],
            "prior_val": [97.0, 97.0, 97.0],
            "prior_poc": [98.0, 98.0, 98.0],
            "vwap_session": [98.0, 98.0, 98.0],
            "confirmed_swing_high": [True, True, True],
            "confirmed_swing_low": [False, False, False],
            "swing_high_price": [101.0, 101.5, 102.0],
            "swing_low_price": [None, None, None],
            "tod_bucket": ["lunch", "lunch", "lunch"],
        }
    )
    fs = FeatureSet("TEST", Timeframe.M5, df, frozenset(), 0.5)
    params = ReversalParams(cooldown_bars=2)
    signals = SignalEngine(ReversalStrategy(params)).evaluate(fs)
    # First signal kept; next two are within 2 bars -> skipped.
    assert len(signals) == 1


def test_quality_score_is_attached_to_signals() -> None:
    signals = SignalEngine(ReversalStrategy()).evaluate(_reversal_fs())
    assert len(signals) >= 1
    for s in signals:
        assert 0.0 <= s.quality_score <= 1.0


def test_scalp_trend_alignment_skips_countertrend() -> None:
    """A long scalp is rejected when ADX shows a strong bear trend."""
    df = pl.DataFrame(
        {
            "ts": [_T0, _T0.replace(minute=5)],
            "open": [100.0, 99.0],
            "high": [100.5, 101.0],
            "low": [99.5, 98.5],
            "close": [99.0, 101.0],
            "vwap_session": [100.0, 100.0],
            "rvol": [1.0, 4.0],
            "atr": [1.0, 1.0],
            "close_position": [0.0, 1.0],
            "ib_high": [None, None],
            "ib_low": [None, None],
            "adx": [45.0, 45.0],
            "trend_regime": ["bear", "bear"],
            "bar_strength": [0.0, 1.0],
            "momentum_3bar": [0, 1],
            "volume_delta_proxy": [0, 1000],
            "tod_bucket": ["lunch", "lunch"],
        }
    )
    fs = FeatureSet("TEST", Timeframe.M5, df, frozenset(), 0.5)
    params = ScalpingParams(trend_align_adx_threshold=25.0)
    signals = SignalEngine(ScalpingStrategy(params)).evaluate(fs)
    # Long scalp against strong bear trend is filtered out.
    assert len(signals) == 0


@pytest.mark.parametrize("kind", ["reversal", "scalping"])
def test_default_params_emit_quality_score_between_zero_and_one(kind: str) -> None:
    from intradayx.signals.strategy import make_strategy

    fs = _reversal_fs()
    signals = SignalEngine(make_strategy(kind)).evaluate(fs)
    for s in signals:
        assert 0.0 <= s.quality_score <= 1.0
