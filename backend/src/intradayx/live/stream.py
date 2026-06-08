"""WebSocket streaming ingestion — the push-stream alternative to polling.

A configurable live-data CHOICE (``INTRADAYX_LIVE_MODE=stream``): instead of the
APScheduler poller hitting a REST vendor every N seconds, connect to a vendor's
websocket, feed each closed bar through the SAME ``SignalEngine`` (via
``LiveMonitor``, so dedup + parity still hold), and broadcast new signals. The
browser-facing protocol is unchanged — ``status.mode`` just flips poll→stream.

Vendor-agnostic: ``WebSocketBarStream`` takes a ``wss://`` URL, an optional
subscribe message, and a parser that maps incoming messages to :class:`Bar`
objects (yfinance has no WS; free non-broker WS feeds include Finnhub). The
``StreamMonitor`` keeps a bounded rolling window per symbol and re-evaluates on
each new bar.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Protocol

import polars as pl

from intradayx.domain.bars import BAR_SCHEMA, Bar, BarSet, Timeframe
from intradayx.domain.signals import Signal
from intradayx.live.monitor import LiveMonitor

logger = logging.getLogger(__name__)


class BarStream(Protocol):
    """An async source of closed bars."""

    def bars(self) -> AsyncIterator[Bar]: ...


def _to_df(bars: list[Bar]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [b.ts for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
            "vwap": [b.vwap for b in bars],
            "trades": [b.trades for b in bars],
            "source": [b.source for b in bars],
        },
        schema=BAR_SCHEMA,
    )


class StreamMonitor:
    """Consume a BarStream; run the shared engine per new bar; emit fresh signals."""

    def __init__(
        self,
        monitor: LiveMonitor,
        timeframe: Timeframe,
        *,
        max_bars: int = 500,
        on_signal: Callable[[Signal], None] | None = None,
    ) -> None:
        self._monitor = monitor
        self._timeframe = timeframe
        self._max_bars = max_bars
        self._on_signal = on_signal
        self._windows: dict[str, list[Bar]] = {}

    async def run(self, stream: BarStream) -> None:
        async for bar in stream.bars():
            buf = self._windows.setdefault(bar.symbol, [])
            buf.append(bar)
            if len(buf) > self._max_bars:
                del buf[: len(buf) - self._max_bars]
            fresh = self._monitor.process(BarSet(bar.symbol, self._timeframe, _to_df(buf)))
            for sig in fresh:
                if self._on_signal is not None:
                    self._on_signal(sig)


def default_bar_parser(raw: str | bytes) -> Bar | None:
    """Parse a simple JSON bar message into a :class:`Bar`.

    Expected shape (adapt per vendor by passing your own parser):
    ``{"symbol","ts","open","high","low","close","volume",["vwap"],["trades"]}``
    where ``ts`` is an ISO-8601 UTC string. Tick feeds (Finnhub trades, etc.)
    need a tick→bar aggregator, plugged in as a custom parser. Returns None for
    non-bar control frames.
    """
    from datetime import datetime

    msg = json.loads(raw)
    if not isinstance(msg, dict) or "close" not in msg or "ts" not in msg:
        return None
    return Bar(
        symbol=str(msg["symbol"]),
        ts=datetime.fromisoformat(str(msg["ts"])),
        open=float(msg["open"]),
        high=float(msg["high"]),
        low=float(msg["low"]),
        close=float(msg["close"]),
        volume=int(msg.get("volume", 0) or 0),
        vwap=float(msg["vwap"]) if msg.get("vwap") is not None else None,
        trades=int(msg["trades"]) if msg.get("trades") is not None else None,
        source="websocket",
    )


class WebSocketBarStream:
    """Generic websocket bar source. Point it at a vendor's wss:// feed + a parser."""

    def __init__(
        self,
        url: str,
        parse: Callable[[str | bytes], Bar | None],
        *,
        subscribe: dict[str, object] | None = None,
    ) -> None:
        self._url = url
        self._parse = parse
        self._subscribe = subscribe

    async def bars(self) -> AsyncIterator[Bar]:
        import websockets  # api extra

        async with websockets.connect(self._url) as ws:
            if self._subscribe is not None:
                await ws.send(json.dumps(self._subscribe))
            async for raw in ws:
                try:
                    bar = self._parse(raw)
                except Exception as exc:  # bad frame — log, keep streaming
                    logger.warning("stream parse error: %s", exc)
                    continue
                if bar is not None:
                    yield bar
