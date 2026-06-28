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
from typing import Any

import polars as pl

from intradayx.api import settings_store
from intradayx.api.schemas import (
    BacktestLearningDTO,
    BacktestResponse,
    BarsResponse,
    CandleDTO,
    CatalystEventDTO,
    EquityPointDTO,
    LearnResponse,
    LevelsDTO,
    LinePointDTO,
    MarkerDTO,
    MetricsDTO,
    MoveDriverDTO,
    MoveExplanationDTO,
    PeadEquityPointDTO,
    PeadOpenTradeDTO,
    PeadResponse,
    ScanResponse,
    StudyDTO,
    TodStatDTO,
    TradeDTO,
    VolumePointDTO,
    to_attribution_dto,
    to_signal_dto,
)
from intradayx.attribution.catalysts import (
    catalyst_events_from_earnings_dates,
    enrich_with_catalysts,
    nearest_catalysts,
)
from intradayx.attribution.move_explainer import MoveExplanation, explain_latest_move
from intradayx.backtest.runner import Trade, simulate_trades
from intradayx.data.factory import default_provider
from intradayx.data.provider import DataError, DataProvider
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability, CapabilityError, ProviderCapabilities
from intradayx.domain.catalysts import CatalystEvent
from intradayx.features.pipeline import build_features
from intradayx.features.volatility import fetch_volatility_internals
from intradayx.signals.engine import SignalEngine
from intradayx.signals.meta_filter import FitResult, MetaFilter

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_provider() -> DataProvider:
    return default_provider()


@lru_cache(maxsize=1)
def get_engine() -> SignalEngine:
    return SignalEngine()


def _meta_filter_for(symbol: str, scanner: str) -> MetaFilter | None:
    """Load a persisted MetaFilter for the symbol/scanner if one exists."""
    loaded, _ = _meta_filter_with_path(symbol, scanner)
    return loaded


def _meta_model_candidates(symbol: str, scanner: str) -> list[Path]:
    names = (
        f"{symbol.upper()}_{scanner}_forward.joblib",
        f"{symbol.upper()}_{scanner}.joblib",
    )
    models_dir = Path(settings_store.app_data_dir()) / "models"
    local_dir = Path("data/meta_filters")
    return [base / name for base in (models_dir, local_dir) for name in names]


def _meta_filter_with_path(symbol: str, scanner: str) -> tuple[MetaFilter | None, Path | None]:
    """Load a persisted MetaFilter and return the path used."""
    for path in _meta_model_candidates(symbol, scanner):
        if path.exists():
            try:
                mf = MetaFilter.load(path)
                if mf is not None and mf.is_fitted:
                    logger.info("loaded meta-filter: %s", path)
                    return mf, path
            except Exception:
                logger.warning("failed to load meta-filter %s", path, exc_info=True)
    return None, None


def _model_save_path(symbol: str, scanner: str) -> Path:
    models_dir = Path(settings_store.app_data_dir()) / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir / f"{symbol.upper()}_{scanner}.joblib"


def _meta_filter_save_rejection_reason(result: FitResult) -> str:
    """Return why a trained meta-filter is not production-worthy enough to save."""
    if result.insufficient:
        return result.reason
    if result.n_samples < 30:
        return (
            "model not saved: need at least 30 labeled signals for a durable filter "
            f"(got {result.n_samples})"
        )
    if result.cv_roc_auc < 0.52:
        return (
            "model not saved: validation ROC-AUC "
            f"{result.cv_roc_auc:.3f} is below the 0.520 floor"
        )
    if result.cv_precision <= 0.0 and result.cv_recall <= 0.0:
        return "model not saved: validation precision and recall are both zero"
    if not any(score > 1e-9 for _, score in result.feature_importance):
        return "model not saved: no positive feature importance was detected"
    return ""


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
    except (CapabilityError, AttributeError):
        pass
    except DataError:
        logger.info("failed to fetch catalysts for %s", symbol.upper(), exc_info=True)
        return []

    if provider.capabilities().supports(Capability.EARNINGS_CALENDAR):
        try:
            return catalyst_events_from_earnings_dates(provider.earnings_dates(symbol.upper()))
        except (CapabilityError, DataError, AttributeError):
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


def _metrics_dto(metrics, trades: list[Trade]) -> MetricsDTO:
    from intradayx.attribution.validation import deflated_sharpe_ratio
    from intradayx.backtest.runner import DEFAULT_NOTIONAL_CENTS

    returns = [t.pnl_cents / DEFAULT_NOTIONAL_CENTS for t in trades]
    n_trials = 1
    deflated_sharpe = deflated_sharpe_ratio(returns, n_trials) if len(returns) >= 3 else None
    return MetricsDTO(
        n_trades=metrics.n_trades,
        win_rate=metrics.win_rate,
        expectancy_cents=metrics.expectancy_cents,
        profit_factor=None if metrics.profit_factor == float("inf") else metrics.profit_factor,
        total_pnl_cents=metrics.total_pnl_cents,
        max_drawdown_cents=metrics.max_drawdown_cents,
        sharpe_per_trade=metrics.sharpe_per_trade,
        deflated_sharpe=deflated_sharpe,
        n_trials=n_trials,
        per_tod=[
            TodStatDTO(
                bucket=s.bucket,
                n=s.n,
                win_rate=s.win_rate,
                expectancy_cents=s.expectancy_cents,
            )
            for s in metrics.per_tod.values()
        ],
    )


def _explain_at(df: pl.DataFrame, ts: datetime, data_completeness: float) -> MoveExplanation | None:
    frame = df.filter(pl.col("ts") <= ts).tail(1)
    return explain_latest_move(frame, data_completeness)


def _nearby_catalyst_dtos(
    catalysts: list[CatalystEvent], ts: datetime, *, limit: int = 3
) -> list[CatalystEventDTO]:
    return [
        _catalyst_event_dto(event)
        for event, _offset, _score in nearest_catalysts(ts, catalysts)[:limit]
    ]


def _trade_diagnosis(
    trade: Trade,
    signal,
    entry_move: MoveExplanation | None,
    exit_move: MoveExplanation | None,
    catalysts: list[CatalystEventDTO],
) -> str:
    top = (
        signal.attribution.primary_cause.label
        if signal.attribution.primary_cause
        else "No primary cause"
    )
    model = (
        f" Meta-filter score {signal.meta_score:.0%}."
        if signal.meta_score is not None
        else " No learned model score was available."
    )
    catalyst = f" Nearest FMP catalyst: {catalysts[0].title}." if catalysts else ""
    exit_state = f" Exit state: {exit_move.summary}" if exit_move is not None else ""
    if trade.exit_reason.value == "target":
        return f"Target-first winner. Signal thesis: {top}.{model}{catalyst}{exit_state}"
    if trade.exit_reason.value == "stop":
        entry_state = f" Entry state: {entry_move.summary}" if entry_move is not None else ""
        return (
            "Stop-first loser. Thesis failed or timing was late: "
            f"{top}.{model}{catalyst}{entry_state}"
        )
    return (
        "Timed exit. Setup did not resolve before max hold. Signal thesis: "
        f"{top}.{model}{catalyst}{exit_state}"
    )


def _trade_dtos(
    trades: list[Trade],
    signals,
    df: pl.DataFrame,
    data_completeness: float,
    catalysts: list[CatalystEvent],
) -> list[TradeDTO]:
    by_id = {s.signal_id: s for s in signals}
    out: list[TradeDTO] = []
    for trade in trades:
        signal = by_id.get(trade.signal_id)
        if signal is None:
            continue
        entry_move = _explain_at(df, trade.entry_ts, data_completeness)
        exit_move = _explain_at(df, trade.exit_ts, data_completeness)
        catalyst_dtos = _nearby_catalyst_dtos(catalysts, signal.ts)
        out.append(
            TradeDTO(
                signal_id=trade.signal_id,
                signal_ts=signal.ts.isoformat(),
                kind=trade.kind,
                side=signal.side.value,
                is_long=trade.is_long,
                entry_ts=trade.entry_ts.isoformat(),
                exit_ts=trade.exit_ts.isoformat(),
                entry=trade.entry,
                exit=trade.exit,
                shares=trade.shares,
                pnl_cents=trade.pnl_cents,
                exit_reason=trade.exit_reason.value,
                tod_bucket=trade.tod_bucket,
                confidence=signal.confidence,
                quality_score=signal.quality_score,
                meta_score=signal.meta_score,
                attribution=to_attribution_dto(signal.attribution),
                catalysts=catalyst_dtos,
                entry_explanation=_move_explanation_dto(entry_move),
                exit_explanation=_move_explanation_dto(exit_move),
                diagnosis=_trade_diagnosis(
                    trade, signal, entry_move, exit_move, catalyst_dtos
                ),
            )
        )
    return out


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
    vol = fetch_volatility_internals(provider, start, end, tf)

    meta_filter = _meta_filter_for(symbol, scanner)
    signals = SignalEngine(make_strategy(scanner), meta_filter=meta_filter).scan(
        bars, caps, internals=vol
    )
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
    fs = build_features(bars, caps, internals=fetch_volatility_internals(provider, start, end, tf))
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
    symbol: str,
    timeframe: str,
    days: int,
    max_hold: int,
    scanner: str = "reversal",
    *,
    use_learning: bool = True,
    meta_threshold: float = 0.5,
) -> BacktestResponse:
    from intradayx.signals.strategy import make_strategy

    tf = Timeframe(timeframe)
    provider = get_provider()
    end = datetime.now(tz=UTC)
    caps = provider.capabilities()
    start = _clamped_start(end, days, caps, tf)
    bars = provider.bars(symbol.upper(), start, end, tf)

    if bars.is_empty():
        empty_metrics = _metrics_dto(simulate_trades([], bars).metrics, [])
        return BacktestResponse(
            symbol=symbol.upper(),
            timeframe=tf.value,
            n_signals=0,
            n_raw_signals=0,
            data_completeness=0.0,
            learning=BacktestLearningDTO(
                enabled=use_learning,
                model_loaded=False,
                meta_threshold=meta_threshold,
                scored_signals=0,
                selected_signals=0,
                rejected_signals=0,
                summary="No bars returned, so there were no signals to learn from.",
            ),
            metrics=empty_metrics,
            baseline_metrics=empty_metrics,
            trades=[],
            equity_curve=[],
            catalysts=[],
        )

    fs = build_features(bars, caps, internals=fetch_volatility_internals(provider, start, end, tf))
    catalysts = _fetch_catalysts(provider, symbol, start, end)
    raw_signals = SignalEngine(make_strategy(scanner)).evaluate(fs)
    raw_signals = enrich_with_catalysts(raw_signals, catalysts)
    baseline = simulate_trades(raw_signals, bars, max_hold_bars=max_hold)

    meta_filter, model_path = _meta_filter_with_path(symbol, scanner)
    scored_signals = raw_signals
    selected_signals = raw_signals
    if use_learning and meta_filter is not None and meta_filter.is_fitted:
        scored_signals = SignalEngine(make_strategy(scanner), meta_filter=meta_filter).evaluate(fs)
        scored_signals = enrich_with_catalysts(scored_signals, catalysts)
        selected_signals = [
            s
            for s in scored_signals
            if s.meta_score is not None and s.meta_score >= meta_threshold
        ]

    active = simulate_trades(selected_signals, bars, max_hold_bars=max_hold)
    meta_scores = [s.meta_score for s in scored_signals if s.meta_score is not None]
    pnl_delta = active.metrics.total_pnl_cents - baseline.metrics.total_pnl_cents
    if meta_filter is None:
        summary = "No trained meta-filter is available yet; this run used raw scanner signals."
    elif not use_learning:
        summary = "Learning is disabled for this run; model scores were not applied."
    else:
        summary = (
            f"Meta-filter selected {len(selected_signals)} of {len(scored_signals)} "
            f"signals at threshold {meta_threshold:.0%}; P&L delta vs raw was "
            f"{pnl_delta / 100:+.2f}."
        )

    return BacktestResponse(
        symbol=bars.symbol,
        timeframe=bars.timeframe.value,
        n_signals=len(selected_signals),
        n_raw_signals=len(raw_signals),
        data_completeness=fs.data_completeness,
        learning=BacktestLearningDTO(
            enabled=use_learning,
            model_loaded=meta_filter is not None,
            model_path=str(model_path) if model_path is not None else None,
            meta_threshold=meta_threshold,
            scored_signals=len(meta_scores),
            selected_signals=len(selected_signals),
            rejected_signals=max(len(scored_signals) - len(selected_signals), 0),
            avg_meta_score=(sum(meta_scores) / len(meta_scores)) if meta_scores else None,
            pnl_delta_cents=pnl_delta,
            summary=summary,
        ),
        metrics=_metrics_dto(active.metrics, active.trades),
        baseline_metrics=_metrics_dto(baseline.metrics, baseline.trades),
        trades=_trade_dtos(active.trades, selected_signals, fs.df, fs.data_completeness, catalysts),
        equity_curve=[
            EquityPointDTO(ts=ts.isoformat(), equity_cents=e) for ts, e in active.equity_curve
        ],
        catalysts=[
            _catalyst_event_dto(event)
            for event in _rank_chart_catalysts(catalysts, bars.end or end)
        ],
    )


def train_meta_filter_dto(
    symbol: str,
    timeframe: str,
    days: int,
    max_hold: int,
    scanner: str = "reversal",
    *,
    min_samples: int = 30,
) -> LearnResponse:
    from intradayx.signals.meta_filter import train_meta_filter
    from intradayx.signals.strategy import make_strategy

    tf = Timeframe(timeframe)
    provider = get_provider()
    end = datetime.now(tz=UTC)
    caps = provider.capabilities()
    start = _clamped_start(end, days, caps, tf)
    bars = provider.bars(symbol.upper(), start, end, tf)
    if bars.is_empty():
        return LearnResponse(
            symbol=symbol.upper(),
            timeframe=tf.value,
            scanner=scanner,
            saved=False,
            n_samples=0,
            pos_rate=0.0,
            cv_accuracy=0.0,
            cv_precision=0.0,
            cv_recall=0.0,
            cv_roc_auc=0.0,
            insufficient=True,
            reason="no bars returned",
        )

    vol = fetch_volatility_internals(provider, start, end, tf)
    signals = SignalEngine(make_strategy(scanner)).scan(bars, caps, internals=vol)
    mf, result = train_meta_filter(
        signals,
        bars,
        max_hold_bars=max_hold,
        min_samples=min_samples,
    )
    rejection_reason = _meta_filter_save_rejection_reason(result)
    save_path: Path | None = None
    if not rejection_reason and mf.is_fitted:
        save_path = _model_save_path(symbol, scanner)
        mf.save(save_path)
    return LearnResponse(
        symbol=symbol.upper(),
        timeframe=tf.value,
        scanner=scanner,
        saved=save_path is not None,
        model_path=str(save_path) if save_path is not None else None,
        n_samples=result.n_samples,
        pos_rate=result.pos_rate,
        cv_accuracy=result.cv_accuracy,
        cv_precision=result.cv_precision,
        cv_recall=result.cv_recall,
        cv_roc_auc=result.cv_roc_auc,
        insufficient=result.insufficient,
        reason=rejection_reason,
        feature_importance=result.feature_importance[:12],
    )


def run_pead(
    symbols: list[str],
    *,
    hold_days: int = 20,
    years: int = 4,
    min_sue: float = 0.0,
    cost_bps: float = 5.0,
    borrow_bps: float = 50.0,
) -> PeadResponse:
    """Post-Earnings-Announcement Drift: edge stats + cost-aware long/short
    portfolio + currently-open trades, for the desktop Earnings-Drift view."""
    from datetime import timedelta

    from intradayx.signals.pead import build_pead_signals, open_signals, pead_stats
    from intradayx.signals.pead_portfolio import pead_portfolio_backtest

    syms = [s.strip().upper() for s in symbols if s.strip()]
    provider = get_provider()
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=365 * years)

    bars_by: dict[str, Any] = {}
    sigs_by: dict[str, Any] = {}
    all_sigs = []
    for sym in syms:
        bars = provider.bars(sym, start, end, Timeframe.D1)
        if bars.is_empty():
            continue
        sigs = build_pead_signals(
            sym, bars, provider.earnings_surprises(sym), hold_days=hold_days, min_abs_sue=min_sue
        )
        bars_by[sym] = bars
        sigs_by[sym] = sigs
        all_sigs.extend(sigs)

    st = pead_stats(all_sigs)
    pf = pead_portfolio_backtest(bars_by, sigs_by, cost_bps=cost_bps, borrow_bps_annual=borrow_bps)
    open_trades = [
        PeadOpenTradeDTO(
            symbol=s.symbol,
            announce_date=s.announce_date.isoformat(),
            entry_date=s.entry_date.isoformat(),
            side=s.side,
            surprise=s.surprise,
            sue=s.sue,
            entry=s.entry,
        )
        for s in sorted(open_signals(all_sigs), key=lambda x: x.announce_date, reverse=True)
    ]
    equity = [
        PeadEquityPointDTO(
            time=int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()), value=v
        )
        for d, v in pf.equity
    ]
    return PeadResponse(
        symbols=syms,
        hold_days=hold_days,
        years=years,
        n_events=st.n,
        mean_return=st.mean_return,
        t_stat=st.t_stat,
        hit_rate=st.hit_rate,
        sharpe=pf.sharpe,
        ann_return=pf.ann_return,
        ann_vol=pf.ann_vol,
        max_drawdown=pf.max_drawdown,
        total_return=pf.total_return,
        n_days=pf.n_days,
        cost_bps=cost_bps,
        borrow_bps=borrow_bps,
        open_trades=open_trades,
        equity=equity,
    )
