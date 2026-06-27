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
from datetime import datetime, timedelta

from intradayx.domain.bars import BarSet
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.domain.internals import InternalsSeries, InternalSymbol
from intradayx.domain.signals import Signal
from intradayx.signals.engine import SignalEngine


class LiveMonitor:
    def __init__(
        self,
        caps: ProviderCapabilities,
        engine: SignalEngine | None = None,
        *,
        on_signal: Callable[[Signal], None] | None = None,
        retention: timedelta = timedelta(days=7),
    ) -> None:
        self.caps = caps
        self.engine = engine or SignalEngine()
        self._on_signal = on_signal
        self._retention = retention
        # signal_id -> bar ts. Bounded: a 24/7 poller must not leak forever, and
        # a signal older than the poll lookback can never re-appear anyway.
        self._seen: dict[str, datetime] = {}

    def process(
        self,
        bars: BarSet,
        *,
        internals: dict[InternalSymbol, InternalsSeries] | None = None,
    ) -> list[Signal]:
        """Evaluate the latest bars and return only signals not seen before."""
        signals = self.engine.scan(bars, self.caps, internals=internals)
        if signals:  # prune ids older than `retention` before the newest signal
            cutoff = max(s.ts for s in signals) - self._retention
            self._seen = {sid: ts for sid, ts in self._seen.items() if ts >= cutoff}
        fresh: list[Signal] = []
        for sig in signals:
            if sig.signal_id in self._seen:
                continue
            self._seen[sig.signal_id] = sig.ts
            fresh.append(sig)
            if self._on_signal is not None:
                self._on_signal(sig)
        return fresh
