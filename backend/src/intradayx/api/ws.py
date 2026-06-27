"""WebSocket fan-out + live poller.

A single-instance APScheduler job polls watched symbols, runs the shared
SignalEngine via LiveMonitor, and broadcasts NEW signals to all connected
clients. The protocol envelope carries provenance (`source`, `mode`) so the UI
honestly shows FMP status and can surface missing-key/data errors. MUST run
under a single uvicorn worker.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import WebSocket

from intradayx.api import metrics
from intradayx.api.schemas import to_signal_dto
from intradayx.api.service import get_engine, get_provider
from intradayx.data.provider import DataError
from intradayx.domain.bars import Timeframe
from intradayx.domain.signals import Signal
from intradayx.live.monitor import LiveMonitor

PROTOCOL_VERSION = 1
_SEND_TIMEOUT_S = 5.0  # cap one slow client's drag on a broadcast (vs the 30s poll)
_NY = ZoneInfo("America/New_York")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _envelope(msg_type: str, data: dict[str, object]) -> dict[str, object]:
    return {"v": PROTOCOL_VERSION, "type": msg_type, "ts": _now_ms(), "data": data}


def market_session() -> str:
    now = datetime.now(tz=_NY)
    if now.weekday() >= 5:
        return "closed"
    minutes = now.hour * 60 + now.minute
    if minutes < 9 * 60 + 30:
        return "pre"
    if minutes < 16 * 60:
        return "rth"
    return "post"


class ConnectionManager:
    def __init__(self) -> None:
        self._active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)
        metrics.WS_CLIENTS.set(len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)
        metrics.WS_CLIENTS.set(len(self._active))

    async def _safe_send(self, ws: WebSocket, message: dict[str, object]) -> WebSocket | None:
        """Send with a timeout; return the socket if it should be dropped."""
        try:
            await asyncio.wait_for(ws.send_json(message), timeout=_SEND_TIMEOUT_S)
        except Exception:  # slow/half-open client OR client gone
            return ws
        return None

    async def broadcast(self, message: dict[str, object]) -> None:
        # Fan out CONCURRENTLY with a per-send timeout — one slow/half-open client
        # must not block (or even delay) delivery to the others.
        snapshot = list(self._active)
        if not snapshot:
            return
        dead = await asyncio.gather(*(self._safe_send(ws, message) for ws in snapshot))
        for ws in dead:
            if ws is not None:
                self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._active)


class SignalPoller:
    def __init__(
        self,
        manager: ConnectionManager,
        symbols: list[str],
        *,
        timeframe: Timeframe = Timeframe.M5,
        interval_s: int = 30,
        recent_days: int = 5,
        mode: str = "poll",
    ) -> None:
        self.manager = manager
        self.symbols = [s.upper() for s in symbols]
        self.timeframe = timeframe
        self.interval_s = interval_s
        self.recent_days = recent_days
        self.mode = mode
        self._monitors: dict[str, LiveMonitor] = {}
        self._provider_error: str | None = None
        self._sync_provider_state()

    def _sync_provider_state(self) -> bool:
        """Refresh provider-backed monitors; return false when FMP is not usable yet."""
        try:
            caps = get_provider().capabilities()
        except DataError as exc:
            self._provider_error = str(exc)
            self._monitors = {}
            return False
        self._provider_error = None
        self._monitors = {s: LiveMonitor(caps, get_engine()) for s in self.symbols}
        return True

    def status_data(self) -> dict[str, object]:
        # Self-heal: if we have no usable provider yet, re-check now. The cached
        # error is set once at construction, so a key added live (in-app Settings,
        # which rebuilds the provider) must be re-evaluated here — otherwise the
        # "FMP key needed" badge would stay stuck even though data already loads.
        if self._provider_error is not None:
            self._sync_provider_state()
        source = "fmp"
        configured = self._provider_error is None
        if configured:
            try:
                source = get_provider().capabilities().provider_name
            except DataError as exc:
                self._provider_error = str(exc)
                configured = False
        return {
            "source": source,
            "configured": configured,
            "detail": self._provider_error,
            "mode": self.mode,
            "poll_interval_s": self.interval_s,
            "market_session": market_session(),
            "watched": self.symbols,
            "engine_version": get_engine().params_version,
        }

    def _fetch_and_process(self, symbol: str) -> list[Signal]:
        if symbol not in self._monitors and not self._sync_provider_state():
            raise DataError(self._provider_error or "FMP provider is not configured")
        provider = get_provider()
        end = datetime.now(tz=UTC)
        start = end - timedelta(days=self.recent_days)
        bars = provider.bars(symbol, start, end, self.timeframe)
        return self._monitors[symbol].process(bars)

    async def poll(self) -> None:
        if self.manager.count == 0:
            return  # nobody listening; skip the vendor call
        started = time.perf_counter()
        try:
            for symbol in self.symbols:
                try:
                    fresh = await asyncio.to_thread(self._fetch_and_process, symbol)
                except Exception as exc:  # vendor hiccup; report, keep polling
                    metrics.VENDOR_ERRORS.labels(code="poll_failed").inc()
                    await self.manager.broadcast(
                        _envelope("error", {"code": "poll_failed", "detail": str(exc)[:200]})
                    )
                    continue
                for sig in fresh:
                    scanner = "scalping" if sig.kind.value.startswith("scalp") else "reversal"
                    metrics.SIGNALS_EMITTED.labels(
                        scanner=scanner, side=sig.side.ui_direction
                    ).inc()
                    await self.manager.broadcast(
                        _envelope("signal", to_signal_dto(sig).model_dump())
                    )
            await self.manager.broadcast(
                _envelope("heartbeat", {"next_poll_in_s": self.interval_s})
            )
            # Re-broadcast status each cycle so a provider-state change (e.g. a
            # key added live in Settings) reaches already-connected clients — the
            # status envelope is otherwise only sent once, on connect.
            await self.manager.broadcast(_envelope("status", self.status_data()))
        finally:
            metrics.POLL_SECONDS.observe(time.perf_counter() - started)


def status_message(poller: SignalPoller) -> dict[str, object]:
    """The `status` envelope sent to a client on connect."""
    return _envelope("status", poller.status_data())


def signal_message(sig: Signal) -> dict[str, object]:
    """The `signal` envelope (used by both poll and stream paths)."""
    return _envelope("signal", to_signal_dto(sig).model_dump())
