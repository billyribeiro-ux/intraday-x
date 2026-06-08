"""Market data routes: provider capabilities + chart-ready bars."""

from __future__ import annotations

from fastapi import APIRouter

from intradayx.api.schemas import (
    BarsResponse,
    CapabilitiesResponse,
    to_capabilities_response,
)
from intradayx.api.service import build_chart, get_provider

router = APIRouter(prefix="/api", tags=["market"])


@router.get("/providers/capabilities", response_model=CapabilitiesResponse)
def capabilities() -> CapabilitiesResponse:
    return to_capabilities_response(get_provider().capabilities())


@router.get("/bars", response_model=BarsResponse)
def bars(symbol: str, timeframe: str = "5m", days: int = 7) -> BarsResponse:
    return build_chart(symbol, timeframe, days)
