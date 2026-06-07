"""Live monitor — polls bars and emits NEW signals via the shared SignalEngine.

This is the live half of "backtest + live in parallel": it runs the exact same
:class:`~intradayx.signals.engine.SignalEngine` the backtester uses, only the
source of bars differs (a periodic poll vs a historical replay). Signals are
deduped by their deterministic ``signal_id`` so re-polling the same window never
re-emits one — which is also what lets backtest and live agree (see the parity
test). The APScheduler loop + websocket fan-out is wired in Phase 5; this class
owns the poll→evaluate→dedup core.
"""

from __future__ import annotations

from collections.abc import Callable

from intradayx.domain.bars import BarSet
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.domain.signals import Signal
from intradayx.signals.engine import SignalEngine


class LiveMonitor:
    def __init__(
        self,
        caps: ProviderCapabilities,
        engine: SignalEngine | None = None,
        *,
        on_signal: Callable[[Signal], None] | None = None,
    ) -> None:
        self.caps = caps
        self.engine = engine or SignalEngine()
        self._on_signal = on_signal
        self._seen: set[str] = set()

    def process(self, bars: BarSet) -> list[Signal]:
        """Evaluate the latest bars and return only signals not seen before."""
        fresh: list[Signal] = []
        for sig in self.engine.scan(bars, self.caps):
            if sig.signal_id in self._seen:
                continue
            self._seen.add(sig.signal_id)
            fresh.append(sig)
            if self._on_signal is not None:
                self._on_signal(sig)
        return fresh
