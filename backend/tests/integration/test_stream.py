"""StreamMonitor: consumes a bar stream, runs the shared engine, dedups signals."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from intradayx.data.providers.yfinance_provider import YFinanceProvider
from intradayx.domain.bars import Bar, BarSet, Timeframe
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.domain.signals import Side, Signal, SignalKind, uncertain_attribution
from intradayx.live.monitor import LiveMonitor
from intradayx.live.stream import StreamMonitor
from intradayx.signals.engine import SignalEngine

_T0 = datetime(2024, 1, 2, 16, 0, tzinfo=UTC)


class _FakeStream:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def bars(self) -> AsyncIterator[Bar]:
        for b in self._bars:
            yield b


class _StubEngine(SignalEngine):
    def __init__(self, signals: list[Signal]) -> None:
        super().__init__()
        self._signals = signals

    def scan(self, bars: BarSet, caps: ProviderCapabilities) -> list[Signal]:
        return list(self._signals)


def _bar(i: int) -> Bar:
    return Bar(
        symbol="TEST",
        ts=_T0 + timedelta(minutes=5 * i),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000,
        source="fake",
    )


def test_stream_monitor_emits_then_dedups() -> None:
    sig = Signal.create(
        symbol="TEST",
        ts=_T0,
        kind=SignalKind.REVERSAL_TOP,
        side=Side.SELL,
        confidence=0.4,
        entry=100.0,
        stop=101.0,
        targets=(98.0,),
        time_of_day_bucket="afternoon",
        attribution=uncertain_attribution(0.5),
    )
    emitted: list[Signal] = []
    monitor = LiveMonitor(YFinanceProvider().capabilities(), engine=_StubEngine([sig]))
    sm = StreamMonitor(monitor, Timeframe.M5, on_signal=emitted.append)

    asyncio.run(sm.run(_FakeStream([_bar(0), _bar(1), _bar(2)])))

    # The stub returns the same signal on every bar; dedup => emitted exactly once.
    assert len(emitted) == 1
    assert emitted[0].signal_id == sig.signal_id
