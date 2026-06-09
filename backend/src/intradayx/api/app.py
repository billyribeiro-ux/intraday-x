"""FastAPI app — REST + websocket. MUST run with a single uvicorn worker.

Multiple workers would each start the APScheduler poller (double-polling the
vendor) and split the websocket connection manager (so a signal reaches only the
clients on one worker). See docs/AI_LANDMINES.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from intradayx.api import metrics
from intradayx.api.routes import analysis, market, settings
from intradayx.api.ws import ConnectionManager, SignalPoller, signal_message, status_message
from intradayx.config import Settings, get_settings

logger = logging.getLogger(__name__)

manager = ConnectionManager()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail loud if launched multi-worker: the poller + WS manager are
    # single-instance (N>1 double-polls the vendor and splits the socket fan-out).
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    if workers > 1:
        raise RuntimeError(
            f"intraday-x must run with a single worker (WEB_CONCURRENCY={workers}). "
            "The poller + websocket ConnectionManager are single-instance."
        )
    settings = get_settings()
    poller = SignalPoller(
        manager,
        settings.watched_symbols,
        interval_s=settings.poll_interval_s,
        mode=settings.live_mode,
    )
    app.state.poller = poller

    if settings.live_mode == "stream" and settings.stream_ws_url:
        async with _stream_lifespan(settings):
            yield
    else:
        async with _poll_lifespan(poller):
            yield


@contextlib.asynccontextmanager
async def _poll_lifespan(poller: SignalPoller) -> AsyncIterator[None]:
    """REST-polling mode: APScheduler runs the poller every interval (workers=1)."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poller.poll,
        "interval",
        seconds=poller.interval_s,
        id="signal_poll",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


@contextlib.asynccontextmanager
async def _stream_lifespan(settings: Settings) -> AsyncIterator[None]:
    """WebSocket-streaming mode: consume the feed, run the shared engine, broadcast."""
    from intradayx.api.service import get_engine, get_provider
    from intradayx.domain.bars import Timeframe
    from intradayx.domain.signals import Signal
    from intradayx.live.monitor import LiveMonitor
    from intradayx.live.stream import StreamMonitor, WebSocketBarStream, default_bar_parser

    tasks: set[asyncio.Task[None]] = set()

    def _emit(sig: Signal) -> None:
        task = asyncio.create_task(manager.broadcast(signal_message(sig)))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    sm = StreamMonitor(
        LiveMonitor(get_provider().capabilities(), get_engine()),
        Timeframe(settings.stream_timeframe),
        on_signal=_emit,
    )
    stream = WebSocketBarStream(settings.stream_ws_url, default_bar_parser)
    runner = asyncio.create_task(sm.run(stream))
    logger.info("live mode: stream (%s)", settings.stream_ws_url)
    try:
        yield
    finally:
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner


app = FastAPI(title="intraday-x", version="0.0.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Dev (browser / `tauri dev`) uses the Vite origin; the BUNDLED Tauri app's
    # webview uses tauri://localhost (macOS/Linux) or http://tauri.localhost
    # (Windows). Without the latter, the packaged app's REST fetch() is CORS-blocked
    # (the WebSocket isn't, which is why live signals connect but /api calls fail).
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
        "http://tauri.localhost",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(market.router)
app.include_router(analysis.router)
app.include_router(settings.router)


@app.get("/healthz", tags=["health"])
def healthz() -> dict[str, object]:
    return {"status": "ok", "ws_clients": manager.count}


@app.get("/metrics", tags=["observability"])
def metrics_endpoint() -> Response:
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


@app.websocket("/ws/signals")
async def ws_signals(ws: WebSocket) -> None:
    await manager.connect(ws)
    poller: SignalPoller = ws.app.state.poller
    await ws.send_json(status_message(poller))
    try:
        while True:
            await ws.receive_text()  # keep the socket open; detect disconnect
    except WebSocketDisconnect:
        manager.disconnect(ws)
