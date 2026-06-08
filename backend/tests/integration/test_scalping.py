"""Deterministic scalping anchor — a VWAP-reclaim long fires with expected fields."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import polars as pl

from intradayx.domain.bars import Timeframe
from intradayx.domain.signals import CauseKind, Side, SignalKind
from intradayx.features.pipeline import FeatureSet
from intradayx.signals.engine import SignalEngine
from intradayx.signals.scalping import ScalpingStrategy

_T0 = datetime(2024, 1, 2, 16, 0, tzinfo=UTC)
_T1 = datetime(2024, 1, 2, 16, 5, tzinfo=UTC)


def _fs() -> FeatureSet:
    # Row 1 reclaims VWAP (prev close below, this close above) on high volume +
    # a strong up bar → a scalp_long trigger.
    df = pl.DataFrame(
        {
            "ts": [_T0, _T1],
            "open": [99.0, 99.5],
            "high": [99.5, 101.0],
            "low": [98.5, 99.0],
            "close": [99.0, 101.0],
            "vwap_session": [100.0, 100.0],
            "rvol": [1.0, 4.0],
            "atr": [1.0, 1.0],
            "close_position": [0.5, 1.0],
            "ib_high": [None, None],
            "ib_low": [None, None],
            "tod_bucket": ["lunch", "lunch"],
        }
    )
    return FeatureSet("TEST", Timeframe.M5, df, frozenset(), 0.5)


def test_scalp_long_fires_on_vwap_reclaim() -> None:
    signals = SignalEngine(ScalpingStrategy()).evaluate(_fs())
    assert len(signals) == 1
    s = signals[0]
    assert s.kind is SignalKind.SCALP_LONG
    assert s.side is Side.BUY
    assert s.entry == 101.0
    # stop = close - atr*0.5 = 100.5 ; target1 = close + atr*1 = 102
    assert math.isclose(s.stop, 100.5, rel_tol=1e-9)
    assert s.targets[0] == 102.0
    # confluence = .30*1 + .30*1 + .25*1 + .15*0 = .85 ; confidence = .85 * 0.5
    assert math.isclose(s.confidence, 0.85 * 0.5, rel_tol=1e-9)
    kinds = {c.kind for c in s.attribution.ranked_causes}
    assert CauseKind.VWAP_RECLAIM in kinds
    assert s.attribution.uncertain is False


def test_no_scalp_without_trigger() -> None:
    df = _fs().df.with_columns(close=pl.lit(99.0))  # never crosses above VWAP
    fs = FeatureSet("TEST", Timeframe.M5, df, frozenset(), 0.5)
    assert SignalEngine(ScalpingStrategy()).evaluate(fs) == []
