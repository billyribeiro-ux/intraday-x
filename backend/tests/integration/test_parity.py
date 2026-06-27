"""Backtest <-> live parity: incremental evaluation == batch, and dedup works.

The whole architecture rests on one shared SignalEngine. These tests lock that
processing bars incrementally (as the live monitor does) yields exactly the same
signal set as a single batch scan (as the backtester does), and that the monitor
never re-emits a signal it has already seen.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from intradayx.data.providers.yfinance_provider import YFinanceProvider
from intradayx.domain.bars import BarSet, Timeframe
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.domain.signals import Side, Signal, SignalKind, uncertain_attribution
from intradayx.features.pipeline import FeatureSet
from intradayx.live.monitor import LiveMonitor
from intradayx.signals.engine import SignalEngine
from tests.fixtures.synthetic import make_bars

_TS = [
    datetime(2024, 1, 2, 16, 0, tzinfo=UTC),
    datetime(2024, 1, 2, 16, 5, tzinfo=UTC),
    datetime(2024, 1, 2, 16, 10, tzinfo=UTC),
]


def _fs() -> FeatureSet:
    df = pl.DataFrame(
        {
            "ts": _TS,
            "close": [100.0, 100.0, 95.0],
            "atr": [1.0, 1.0, 1.0],
            "rvol": [4.0, 0.5, 4.0],
            "climax_up_score": [0.9, 0.0, 0.0],
            "climax_down_score": [0.0, 0.0, 0.9],
            "prior_vah": [99.0, 99.0, 98.0],
            "prior_val": [97.0, 97.0, 96.0],
            "prior_poc": [98.0, 98.0, 97.0],
            "vwap_session": [98.0, 98.0, 97.0],
            "confirmed_swing_high": [True, False, False],
            "confirmed_swing_low": [False, False, True],
            "swing_high_price": [101.0, None, None],
            "swing_low_price": [None, None, 94.0],
            "tod_bucket": ["lunch", "lunch", "lunch"],
        }
    )
    return FeatureSet("TEST", Timeframe.M5, df, frozenset(), 0.5)


def test_incremental_equals_batch() -> None:
    engine = SignalEngine()
    fs = _fs()
    batch_ids = {s.signal_id for s in engine.evaluate(fs)}
    assert len(batch_ids) == 2  # a top and a bottom

    # Replay incrementally (as the live monitor sees growing windows), dedup.
    seen: set[str] = set()
    for length in range(1, fs.df.height + 1):
        prefix = FeatureSet("TEST", Timeframe.M5, fs.df.head(length), frozenset(), 0.5)
        for s in engine.evaluate(prefix):
            seen.add(s.signal_id)
    assert seen == batch_ids


class _StubEngine(SignalEngine):
    def __init__(self, signals: list[Signal]) -> None:
        super().__init__()
        self._signals = signals

    def scan(self, bars: BarSet, caps: ProviderCapabilities, **_kwargs: object) -> list[Signal]:
        return list(self._signals)


def test_monitor_dedups_signals() -> None:
    bars = make_bars(closes=[100.0, 100.0], timeframe=Timeframe.M5)
    caps = YFinanceProvider().capabilities()
    sigs = [
        Signal.create(
            symbol="TEST",
            ts=_TS[0],
            kind=SignalKind.REVERSAL_TOP,
            side=Side.SELL,
            confidence=0.4,
            entry=100.0,
            stop=101.0,
            targets=(98.0,),
            time_of_day_bucket="lunch",
            attribution=uncertain_attribution(0.5),
        )
    ]
    monitor = LiveMonitor(caps, engine=_StubEngine(sigs))
    first = monitor.process(bars)
    second = monitor.process(bars)  # same window re-polled
    assert len(first) == 1
    assert second == []  # already seen => not re-emitted
