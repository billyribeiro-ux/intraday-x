"""Market data routes: provider capabilities + chart-ready bars."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from intradayx.api.schemas import (
    BarsResponse,
    CapabilitiesResponse,
    to_capabilities_response,
)
from intradayx.api.service import build_chart, get_provider
from intradayx.data.provider import DataError

router = APIRouter(prefix="/api", tags=["market"])


@router.get("/providers/capabilities", response_model=CapabilitiesResponse)
def capabilities() -> CapabilitiesResponse:
    try:
        return to_capabilities_response(get_provider().capabilities())
    except DataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/bars", response_model=BarsResponse)
def bars(
    symbol: str, timeframe: str = "5m", days: int = 7, scanner: str = "reversal"
) -> BarsResponse:
    if scanner not in ("reversal", "scalping"):
        raise HTTPException(
            status_code=400, detail="scanner must be 'reversal' or 'scalping'"
        )
    try:
        return build_chart(symbol, timeframe, days, scanner=scanner)
    except DataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
