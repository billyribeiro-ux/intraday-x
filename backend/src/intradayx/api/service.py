"""API service layer — shared logic for routes and the websocket poller.

Holds the (single-instance) provider + SignalEngine and builds the DTOs. Uses
the same SignalEngine.scan / run_backtest as the CLI, so the API can't drift
from the command line.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import polars as pl

from intradayx.api import settings_store
from intradayx.api.schemas import (
    BacktestResponse,
    BarsResponse,
    CandleDTO,
    CatalystEventDTO,
    EquityPointDTO,
    LevelsDTO,
    LinePointDTO,
    MarkerDTO,
    MetricsDTO,
    MoveDriverDTO,
    MoveExplanationDTO,
    ScanResponse,
    StudyDTO,
    TodStatDTO,
    TradeDTO,
    VolumePointDTO,
    to_signal_dto,
)
from intradayx.attribution.catalysts import (
    catalyst_events_from_earnings_dates,
    enrich_with_catalysts,
)
from intradayx.attribution.move_explainer import MoveExplanation, explain_latest_move
from intradayx.backtest.runner import run_backtest
from intradayx.data.factory import default_provider
from intradayx.data.provider import DataError, DataProvider
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability, CapabilityError, ProviderCapabilities
from intradayx.domain.catalysts import CatalystEvent
from intradayx.features.pipeline import build_features
from intradayx.signals.engine import SignalEngine
from intradayx.signals.meta_filter import MetaFilter

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_provider() -> DataProvider:
    return default_provider()


@lru_cache(maxsize=1)
def get_engine() -> SignalEngine:
    return SignalEngine()


def _meta_filter_for(symbol: str, scanner: str) -> MetaFilter | None:
    """Load a persisted MetaFilter for the symbol/scanner if one exists."""
    models_dir = Path(settings_store.app_data_dir()) / "models"
    candidates = (
        f"{symbol.upper()}_{scanner}_forward.joblib",
        f"{symbol.upper()}_{scanner}.joblib",
    )
    for name in candidates:
        path = models_dir / name
        if path.exists():
            try:
                mf = MetaFilter.load(path)
                if mf is not None and mf.is_fitted:
                    logger.info("loaded meta-filter: %s", path)
                    return mf
            except Exception:
                logger.warning("failed to load meta-filter %s", path, exc_info=True)
    return None


def _epoch(ts: datetime) -> int:
    return int(ts.timestamp())


def _line_points(df, column: str) -> list[LinePointDTO]:
    points: list[LinePointDTO] = []
    for row in df.select("ts", column).drop_nulls(column).iter_rows(named=True):
        points.append(LinePointDTO(time=_epoch(row["ts"]), value=row[column]))
    return points


def _move_explanation_dto(move: MoveExplanation | None) -> MoveExplanationDTO | None:
    if move is None:
        return None
    return MoveExplanationDTO(
        direction=move.direction,
        regime=move.regime,
        confidence=move.confidence,
        summary=move.summary,
        drivers=[
            MoveDriverDTO(
                kind=d.kind,
                score=d.score,
                label=d.label,
                evidence=d.evidence,
            )
            for d in move.drivers
        ],
    )


def _catalyst_event_dto(event: CatalystEvent) -> CatalystEventDTO:
    return CatalystEventDTO(
        kind=event.kind.value,
        ts=event.ts.isoformat(),
        title=event.title,
        source=event.source,
        score=event.score,
        url=event.url,
        evidence=event.evidence,
    )


def _fetch_catalysts(
    provider: DataProvider, symbol: str, start: datetime, end: datetime
) -> list[CatalystEvent]:
    """Best-effort FMP catalyst fetch; never lets optional evidence break bars."""
    try:
        return provider.catalyst_events(symbol.upper(), start, end)
    except CapabilityError:
        pass
    except DataError:
        logger.info("failed to fetch catalysts for %s", symbol.upper(), exc_info=True)
        return []

    if provider.capabilities().supports(Capability.EARNINGS_CALENDAR):
        try:
            return catalyst_events_from_earnings_dates(provider.earnings_dates(symbol.upper()))
        except (CapabilityError, DataError):
            logger.info("failed to fetch earnings catalysts for %s", symbol.upper(), exc_info=True)
    return []


def _rank_chart_catalysts(
    events: list[CatalystEvent], anchor: datetime, limit: int = 8
) -> list[CatalystEvent]:
    anchor_utc = anchor.astimezone(UTC) if anchor.tzinfo else anchor.replace(tzinfo=UTC)

    def relevance(event: CatalystEvent) -> tuple[float, datetime]:
        hours = abs((anchor_utc - event.ts.astimezone(UTC)).total_seconds()) / 3600
        proximity = max(0.15, 1.0 - min(hours / 72.0, 1.0))
        return event.score * proximity, event.ts

    return sorted(events, key=relevance, reverse=True)[:limit]


def _clamped_start(end: datetime, days: int, caps: ProviderCapabilities, tf: Timeframe) -> datetime:
    """Return the start time, clamped to what the active provider can serve.

    For very large ``days`` (e.g. "max" = 36500) we fetch as far back as the
    provider's declared lookback instead of raising a lookback error.
    """
    requested = end - timedelta(days=days)
    window = caps.lookback_for(tf)
    if window is None:
        return requested
    earliest = end - window - timedelta(days=1)
    return max(requested, earliest)


def run_scan(symbol: str, timeframe: str, days: int, scanner: str = "reversal") -> ScanResponse:
    from intradayx.features.pipeline import data_completeness_for
    from intradayx.signals.engine import SignalEngine
    from intradayx.signals.strategy import make_strategy

    tf = Timeframe(timeframe)
    provider = get_provider()
    end = datetime.now(tz=UTC)
    caps = provider.capabilities()
    start = _clamped_start(end, days, caps, tf)
    bars = provider.bars(symbol.upper(), start, end, tf)

    meta_filter = _meta_filter_for(symbol, scanner)
    signals = SignalEngine(make_strategy(scanner), meta_filter=meta_filter).scan(bars, caps)
    signals = enrich_with_catalysts(signals, _fetch_catalysts(provider, symbol, start, end))
    return ScanResponse(
        symbol=symbol.upper(),
        timeframe=tf.value,
        n_bars=len(bars),
        data_completeness=data_completeness_for(caps),
        signals=[to_signal_dto(s) for s in signals],
    )


def build_chart(symbol: str, timeframe: str, days: int, scanner: str = "reversal") -> BarsResponse:
    from intradayx.signals.strategy import make_strategy

    tf = Timeframe(timeframe)
    provider = get_provider()
    end = datetime.now(tz=UTC)
    caps = provider.capabilities()
    start = _clamped_start(end, days, caps, tf)
    bars = provider.bars(symbol.upper(), start, end, tf)

    if bars.is_empty():
        return BarsResponse(
            symbol=symbol.upper(),
            timeframe=tf.value,
            candles=[],
            volume=[],
            vwap=[],
            studies=[],
            markers=[],
            levels=None,
            data_completeness=0.0,
            move_explanation=None,
            catalysts=[],
        )

    catalysts = _fetch_catalysts(provider, symbol, start, end)
    fs = build_features(bars, caps)
    df = fs.df.with_columns(
        ema20=pl.col("close").ewm_mean(span=20, adjust=False, min_samples=20),
        ema50=pl.col("close").ewm_mean(span=50, adjust=False, min_samples=50),
    )
    candles: list[CandleDTO] = []
    volume: list[VolumePointDTO] = []
    vwap: list[LinePointDTO] = []
    for row in df.iter_rows(named=True):
        t = _epoch(row["ts"])
        candles.append(
            CandleDTO(
                time=t,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
            )
        )
        up = row["close"] >= row["open"]
        volume.append(
            VolumePointDTO(
                time=t,
                value=int(row["volume"]),
                color="rgba(38,166,154,0.5)" if up else "rgba(239,83,80,0.5)",
            )
        )
        if row.get("vwap_session") is not None:
            vwap.append(LinePointDTO(time=t, value=row["vwap_session"]))

    studies = [
        StudyDTO(key="ema20", label="EMA 20", pane="price", points=_line_points(df, "ema20")),
        StudyDTO(key="ema50", label="EMA 50", pane="price", points=_line_points(df, "ema50")),
    ]

    last = df.tail(1).to_dicts()[0]
    levels = None
    if last.get("prior_poc") is not None:
        levels = LevelsDTO(poc=last["prior_poc"], vah=last["prior_vah"], val=last["prior_val"])

    meta_filter = _meta_filter_for(symbol, scanner)
    signals = SignalEngine(make_strategy(scanner), meta_filter=meta_filter).evaluate(fs)
    markers: list[MarkerDTO] = []
    for s in sorted(signals, key=lambda x: x.ts):
        buy = s.side.is_bullish
        markers.append(
            MarkerDTO(
                time=_epoch(s.ts),
                position="belowBar" if buy else "aboveBar",
                shape="arrowUp" if buy else "arrowDown",
                color="#3fb950" if buy else "#f85149",
                text=s.kind.value.replace("reversal_", "").replace("scalp_", ""),
            )
        )

    return BarsResponse(
        symbol=symbol.upper(),
        timeframe=tf.value,
        candles=candles,
        volume=volume,
        vwap=vwap,
        studies=studies,
        markers=markers,
        levels=levels,
        data_completeness=fs.data_completeness,
        move_explanation=_move_explanation_dto(explain_latest_move(df, fs.data_completeness)),
        catalysts=[
            _catalyst_event_dto(event)
            for event in _rank_chart_catalysts(catalysts, df.tail(1).to_dicts()[0]["ts"])
        ],
    )


def run_backtest_dto(
    symbol: str, timeframe: str, days: int, max_hold: int, scanner: str = "reversal"
) -> BacktestResponse:
    from intradayx.attribution.validation import deflated_sharpe_ratio
    from intradayx.backtest.runner import DEFAULT_NOTIONAL_CENTS
    from intradayx.signals.strategy import make_strategy

    tf = Timeframe(timeframe)
    provider = get_provider()
    end = datetime.now(tz=UTC)
    caps = provider.capabilities()
    start = _clamped_start(end, days, caps, tf)
    bars = provider.bars(symbol.upper(), start, end, tf)
    # Build the engine for the CHOSEN scanner (mirrors run_scan), not the cached
    # default-reversal engine — so the backtest actually runs the selected scanner.
    meta_filter = _meta_filter_for(symbol, scanner)
    engine = SignalEngine(make_strategy(scanner), meta_filter=meta_filter)
    res = run_backtest(bars, provider.capabilities(), engine=engine, max_hold_bars=max_hold)
    m = res.metrics

    # Deflated Sharpe — IN-SAMPLE, n_trials=1, computed over this backtest's
    # realized per-trade returns (pnl / notional). Identical method to the CLI
    # `backtest` command (which uses /$10k notional, trials=1). Needs >= 3
    # trades for skew/kurtosis moments; below that it is honestly None, never
    # fabricated. OOS deflation by a threshold grid lives in walk-forward.
    returns = [t.pnl_cents / DEFAULT_NOTIONAL_CENTS for t in res.trades]
    n_trials = 1
    deflated_sharpe = deflated_sharpe_ratio(returns, n_trials) if len(returns) >= 3 else None

    metrics = MetricsDTO(
        n_trades=m.n_trades,
        win_rate=m.win_rate,
        expectancy_cents=m.expectancy_cents,
        profit_factor=None if m.profit_factor == float("inf") else m.profit_factor,
        total_pnl_cents=m.total_pnl_cents,
        max_drawdown_cents=m.max_drawdown_cents,
        sharpe_per_trade=m.sharpe_per_trade,
        deflated_sharpe=deflated_sharpe,
        n_trials=n_trials,
        per_tod=[
            TodStatDTO(
                bucket=s.bucket,
                n=s.n,
                win_rate=s.win_rate,
                expectancy_cents=s.expectancy_cents,
            )
            for s in m.per_tod.values()
        ],
    )
    return BacktestResponse(
        symbol=res.symbol,
        timeframe=res.timeframe.value,
        n_signals=res.n_signals,
        metrics=metrics,
        trades=[
            TradeDTO(
                signal_id=t.signal_id,
                kind=t.kind,
                is_long=t.is_long,
                entry_ts=t.entry_ts.isoformat(),
                exit_ts=t.exit_ts.isoformat(),
                entry=t.entry,
                exit=t.exit,
                shares=t.shares,
                pnl_cents=t.pnl_cents,
                exit_reason=t.exit_reason.value,
                tod_bucket=t.tod_bucket,
            )
            for t in res.trades
        ],
        equity_curve=[
            EquityPointDTO(ts=ts.isoformat(), equity_cents=e) for ts, e in res.equity_curve
        ],
    )
