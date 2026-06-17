"""Analysis routes: scan + backtest."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from intradayx.api.schemas import (
    BacktestRequest,
    BacktestResponse,
    ScanRequest,
    ScanResponse,
)
from intradayx.api.service import run_backtest_dto, run_scan
from intradayx.data.provider import DataError

router = APIRouter(prefix="/api", tags=["analysis"])


@router.post("/scan", response_model=ScanResponse)
def scan(req: ScanRequest) -> ScanResponse:
    if req.scanner not in ("reversal", "scalping"):
        raise HTTPException(status_code=400, detail="scanner must be 'reversal' or 'scalping'")
    try:
        return run_scan(req.symbol, req.timeframe, req.days, req.scanner)
    except DataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/backtest", response_model=BacktestResponse)
def backtest(req: BacktestRequest) -> BacktestResponse:
    if req.scanner not in ("reversal", "scalping"):
        raise HTTPException(status_code=400, detail="scanner must be 'reversal' or 'scalping'")
    try:
        return run_backtest_dto(
            req.symbol, req.timeframe, req.days, req.max_hold, scanner=req.scanner
        )
    except DataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
