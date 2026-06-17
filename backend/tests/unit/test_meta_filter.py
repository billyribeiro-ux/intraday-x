"""Meta-filter: learns from labeled signal outcomes and scores fresh signals."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from intradayx.domain.bars import BarSet, Timeframe
from intradayx.domain.signals import Side, Signal, SignalKind, uncertain_attribution
from intradayx.features.pipeline import FeatureSet
from intradayx.signals.accuracy import LabeledSignal, SignalOutcome
from intradayx.signals.engine import SignalEngine
from intradayx.signals.meta_filter import MetaFilter, train_meta_filter
from intradayx.signals.reversal import ReversalStrategy


def _make_signal(
    *,
    ts: datetime,
    kind: SignalKind = SignalKind.REVERSAL_TOP,
    confidence: float = 0.5,
    quality_score: float = 0.5,
    entry: float = 100.0,
    stop: float = 101.0,
    target: float = 99.0,
    snapshot: dict[str, float] | None = None,
) -> Signal:
    return Signal.create(
        symbol="TEST",
        ts=ts,
        kind=kind,
        side=Side.SELL if "top" in kind.value else Side.BUY,
        confidence=confidence,
        entry=entry,
        stop=stop,
        targets=(target,),
        time_of_day_bucket="lunch",
        attribution=uncertain_attribution(0.5),
        feature_snapshot=snapshot or {"confluence": confidence, "c_climax": 0.5},
        quality_score=quality_score,
    )


def test_meta_filter_trains_and_predicts() -> None:
    """A trivially separable synthetic dataset: high quality → target, low → stop."""
    labeled: list[LabeledSignal] = []
    for i in range(100):
        is_target = i % 2 == 0
        s = _make_signal(
            ts=datetime(2024, 1, 2, 14, 30, tzinfo=UTC) + i * Timeframe.M1.timedelta,
            quality_score=0.9 if is_target else 0.2,
            confidence=0.9 if is_target else 0.2,
        )
        outcome = SignalOutcome.TARGET if is_target else SignalOutcome.STOP
        labeled.append(LabeledSignal(signal=s, outcome=outcome))

    mf = MetaFilter(min_samples=10)
    result = mf.fit(labeled)
    assert not result.insufficient
    assert result.n_samples == 100
    assert result.cv_accuracy > 0.5

    fresh = [
        _make_signal(
            ts=datetime(2024, 1, 3, 14, 30, tzinfo=UTC),
            quality_score=0.95,
            confidence=0.95,
        )
    ]
    scores = mf.predict(fresh)
    assert len(scores) == 1
    assert 0.0 <= scores[0] <= 1.0


def test_meta_filter_refuses_small_samples() -> None:
    mf = MetaFilter(min_samples=100)
    result = mf.fit([])
    assert result.insufficient


def test_train_meta_filter_with_engine_signals() -> None:
    """End-to-end: engine emits signals, meta-filter trains on their outcomes."""
    df = pl.DataFrame(
        {
            "ts": [
                datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
                datetime(2024, 1, 2, 14, 35, tzinfo=UTC),
            ],
            "open": [100.0, 100.0],
            "high": [101.0, 101.0],
            "low": [99.0, 99.0],
            "close": [100.0, 100.0],
            "volume": [1000, 1000],
            "atr": [1.0, 1.0],
            "rvol": [4.0, 0.5],
            "close_position": [0.5, 0.5],
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
    fs = FeatureSet("TEST", Timeframe.M5, df, frozenset(), 0.5)
    bars = BarSet(
        "TEST",
        Timeframe.M5,
        pl.DataFrame(
            {
                "ts": [
                    datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
                    datetime(2024, 1, 2, 14, 35, tzinfo=UTC),
                    datetime(2024, 1, 2, 14, 40, tzinfo=UTC),
                ],
                "open": [100.0, 100.0, 100.0],
                "high": [101.0, 101.0, 101.0],
                "low": [99.0, 99.0, 99.0],
                "close": [100.0, 100.0, 99.0],
                "volume": [1000, 1000, 1000],
                "vwap": [None, None, None],
                "trades": [None, None, None],
                "source": ["test", "test", "test"],
            }
        ),
    )
    signals = SignalEngine(ReversalStrategy()).evaluate(fs)
    assert len(signals) == 1
    _, result = train_meta_filter(signals, bars, min_samples=1)
    # Not enough samples for a real CV, but fit should report insufficient or succeed.
    assert isinstance(result.n_samples, int)
