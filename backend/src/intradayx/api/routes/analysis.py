"""Analysis routes: scan + backtest."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from intradayx.api.schemas import (
    BacktestRequest,
    BacktestResponse,
    LearnRequest,
    LearnResponse,
    PeadRequest,
    PeadResponse,
    ScanRequest,
    ScanResponse,
)
from intradayx.api.service import run_backtest_dto, run_pead, run_scan, train_meta_filter_dto
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
            req.symbol,
            req.timeframe,
            req.days,
            req.max_hold,
            scanner=req.scanner,
            use_learning=req.use_learning,
            meta_threshold=req.meta_threshold,
        )
    except DataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/learn", response_model=LearnResponse)
def learn(req: LearnRequest) -> LearnResponse:
    if req.scanner not in ("reversal", "scalping"):
        raise HTTPException(status_code=400, detail="scanner must be 'reversal' or 'scalping'")
    try:
        return train_meta_filter_dto(
            req.symbol,
            req.timeframe,
            req.days,
            req.max_hold,
            scanner=req.scanner,
            min_samples=req.min_samples,
        )
    except DataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/pead", response_model=PeadResponse)
def pead(req: PeadRequest) -> PeadResponse:
    if not req.symbols:
        raise HTTPException(status_code=400, detail="symbols must not be empty")
    try:
        return run_pead(
            req.symbols,
            hold_days=req.hold_days,
            years=req.years,
            min_sue=req.min_sue,
            cost_bps=req.cost_bps,
            borrow_bps=req.borrow_bps,
        )
    except DataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
