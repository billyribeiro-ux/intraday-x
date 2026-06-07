"""FastAPI app — REST + websocket. MUST run with a single uvicorn worker.

Multiple workers would each start the APScheduler poller (double-polling the
vendor) and split the websocket connection manager (so a signal reaches only the
clients on one worker). See docs/AI_LANDMINES.md.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from intradayx.api.routes import analysis, market
from intradayx.api.ws import ConnectionManager, SignalPoller, status_message
from intradayx.config import get_settings

manager = ConnectionManager()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    poller = SignalPoller(
        manager, settings.watched_symbols, interval_s=settings.poll_interval_s
    )
    app.state.poller = poller
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poller.poll,
        "interval",
        seconds=settings.poll_interval_s,
        id="signal_poll",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="intraday-x", version="0.0.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(market.router)
app.include_router(analysis.router)


@app.get("/healthz", tags=["health"])
def healthz() -> dict[str, object]:
    return {"status": "ok", "ws_clients": manager.count}


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
