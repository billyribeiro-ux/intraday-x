"""Pydantic DTOs for the API + websocket, with converters from domain types.

The SignalDTO mirrors the frontend's `Signal` TS interface (and the websocket
`signal` message). Chart payloads carry Lightweight-Charts-ready shapes (epoch
seconds time).
"""

from __future__ import annotations

from pydantic import BaseModel

from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.domain.signals import Attribution, Signal


class CauseDTO(BaseModel):
    kind: str
    score: float
    source: str
    label: str


class AttributionDTO(BaseModel):
    ranked_causes: list[CauseDTO]
    data_completeness: float
    uncertain: bool
    caveat: str
    summary: str


class SignalDTO(BaseModel):
    signal_id: str
    symbol: str
    ts: str  # ISO-8601 UTC
    kind: str
    side: str
    confidence: float
    entry: float
    stop: float
    targets: list[float]
    time_of_day_bucket: str
    attribution: AttributionDTO
    quality_score: float | None = None
    meta_score: float | None = None


def to_attribution_dto(a: Attribution) -> AttributionDTO:
    return AttributionDTO(
        ranked_causes=[
            CauseDTO(kind=c.kind.value, score=c.score, source=c.source.value, label=c.label)
            for c in a.ranked_causes
        ],
        data_completeness=a.data_completeness,
        uncertain=a.uncertain,
        caveat=a.caveat,
        summary=a.summary,
    )


def to_signal_dto(s: Signal) -> SignalDTO:
    return SignalDTO(
        signal_id=s.signal_id,
        symbol=s.symbol,
        ts=s.ts.isoformat(),
        kind=s.kind.value,
        side=s.side.value,
        confidence=s.confidence,
        entry=s.entry,
        stop=s.stop,
        targets=list(s.targets),
        time_of_day_bucket=s.time_of_day_bucket,
        attribution=to_attribution_dto(s.attribution),
        quality_score=s.quality_score,
        meta_score=s.meta_score,
    )


# --- capabilities ---


class CapabilitiesResponse(BaseModel):
    provider: str
    supported: list[str]
    intraday_lookback_days: dict[str, int]


def to_capabilities_response(caps: ProviderCapabilities) -> CapabilitiesResponse:
    return CapabilitiesResponse(
        provider=caps.provider_name,
        supported=sorted(c.value for c in caps.supported),
        intraday_lookback_days={tf.value: w.days for tf, w in caps.max_intraday_lookback.items()},
    )


# --- scan ---


class ScanRequest(BaseModel):
    symbol: str
    timeframe: str = "5m"
    days: int = 7
    scanner: str = "reversal"


class ScanResponse(BaseModel):
    symbol: str
    timeframe: str
    n_bars: int
    data_completeness: float
    signals: list[SignalDTO]


# --- chart data ---


class CandleDTO(BaseModel):
    time: int  # epoch seconds, UTC
    open: float
    high: float
    low: float
    close: float


class VolumePointDTO(BaseModel):
    time: int
    value: int
    color: str


class LinePointDTO(BaseModel):
    time: int
    value: float


class MarkerDTO(BaseModel):
    time: int
    position: str
    shape: str
    color: str
    text: str


class LevelsDTO(BaseModel):
    poc: float
    vah: float
    val: float


class BarsResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: list[CandleDTO]
    volume: list[VolumePointDTO]
    vwap: list[LinePointDTO]
    markers: list[MarkerDTO]
    levels: LevelsDTO | None
    data_completeness: float


# --- backtest ---


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = "5m"
    days: int = 60
    max_hold: int = 24
    scanner: str = "reversal"  # "reversal" | "scalping" — which scanner to backtest


class TodStatDTO(BaseModel):
    bucket: str
    n: int
    win_rate: float
    expectancy_cents: float


class MetricsDTO(BaseModel):
    n_trades: int
    win_rate: float
    expectancy_cents: float
    profit_factor: float | None  # None encodes "infinite" (wins, no losses)
    total_pnl_cents: int
    max_drawdown_cents: int
    sharpe_per_trade: float
    deflated_sharpe: float | None
    """Deflated Sharpe Ratio P(true SR > 0) in [0, 1], or None for < 3 trades.

    Computed IN-SAMPLE over this backtest's realized per-trade returns with
    ``n_trials = 1`` (the same honest method the CLI ``backtest`` command uses) —
    i.e. it deflates only the per-observation Sharpe for skew/kurtosis and
    sample size, NOT for multiple-testing / threshold selection. This is the
    single-run "is this Sharpe distinguishable from zero?" probability, NOT an
    out-of-sample figure. Honest out-of-sample deflation (deflated by the
    threshold grid) requires the walk-forward optimizer (``/api/walkforward``,
    CLI ``walkforward``); a caption on this field must say "in-sample" only.
    ``None`` when fewer than 3 trades make the moments undefined — never
    fabricated as 0.0 for a degenerate sample.
    """
    n_trials: int  # multiple-testing trials used to deflate (1 = in-sample single run)
    per_tod: list[TodStatDTO]


class TradeDTO(BaseModel):
    signal_id: str
    kind: str
    is_long: bool
    entry_ts: str
    exit_ts: str
    entry: float
    exit: float
    shares: int
    pnl_cents: int
    exit_reason: str
    tod_bucket: str


class EquityPointDTO(BaseModel):
    ts: str
    equity_cents: int


class BacktestResponse(BaseModel):
    symbol: str
    timeframe: str
    n_signals: int
    metrics: MetricsDTO
    trades: list[TradeDTO]
    equity_curve: list[EquityPointDTO]
