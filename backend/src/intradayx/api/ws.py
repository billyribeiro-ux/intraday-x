"""WebSocket fan-out + live poller.

A single-instance APScheduler job polls watched symbols, runs the shared
SignalEngine via LiveMonitor, and broadcasts NEW signals to all connected
clients. The protocol envelope carries provenance (`source`, `mode`) so the UI
honestly shows "Polling yfinance · 30s" and auto-relabels to a stream when a
push-capable vendor is added. MUST run under a single uvicorn worker.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import WebSocket

from intradayx.api.schemas import to_signal_dto
from intradayx.api.service import get_engine, get_provider
from intradayx.domain.bars import Timeframe
from intradayx.domain.signals import Signal
from intradayx.live.monitor import LiveMonitor

PROTOCOL_VERSION = 1
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

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def broadcast(self, message: dict[str, object]) -> None:
        for ws in list(self._active):
            try:
                await ws.send_json(message)
            except Exception:  # client gone mid-send
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
    ) -> None:
        self.manager = manager
        self.symbols = [s.upper() for s in symbols]
        self.timeframe = timeframe
        self.interval_s = interval_s
        self.recent_days = recent_days
        caps = get_provider().capabilities()
        self._monitors = {s: LiveMonitor(caps, get_engine()) for s in self.symbols}

    def status_data(self) -> dict[str, object]:
        return {
            "source": get_provider().capabilities().provider_name,
            "mode": "poll",
            "poll_interval_s": self.interval_s,
            "market_session": market_session(),
            "watched": self.symbols,
            "engine_version": get_engine().params.version,
        }

    def _fetch_and_process(self, symbol: str) -> list[Signal]:
        provider = get_provider()
        end = datetime.now(tz=UTC)
        start = end - timedelta(days=self.recent_days)
        bars = provider.bars(symbol, start, end, self.timeframe)
        return self._monitors[symbol].process(bars)

    async def poll(self) -> None:
        if self.manager.count == 0:
            return  # nobody listening; skip the vendor call
        for symbol in self.symbols:
            try:
                fresh = await asyncio.to_thread(self._fetch_and_process, symbol)
            except Exception as exc:  # vendor hiccup; report, keep polling
                await self.manager.broadcast(
                    _envelope("error", {"code": "poll_failed", "detail": str(exc)[:200]})
                )
                continue
            for sig in fresh:
                await self.manager.broadcast(_envelope("signal", to_signal_dto(sig).model_dump()))
        await self.manager.broadcast(
            _envelope("heartbeat", {"next_poll_in_s": self.interval_s})
        )


def status_message(poller: SignalPoller) -> dict[str, object]:
    """The `status` envelope sent to a client on connect."""
    return _envelope("status", poller.status_data())
