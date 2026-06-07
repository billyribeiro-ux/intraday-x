"""API service layer — shared logic for routes and the websocket poller.

Holds the (single-instance) provider + SignalEngine and builds the DTOs. Uses
the same SignalEngine.scan / run_backtest as the CLI, so the API can't drift
from the command line.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache

from intradayx.api.schemas import (
    BacktestResponse,
    BarsResponse,
    CandleDTO,
    EquityPointDTO,
    LevelsDTO,
    LinePointDTO,
    MarkerDTO,
    MetricsDTO,
    ScanResponse,
    TodStatDTO,
    TradeDTO,
    VolumePointDTO,
    to_signal_dto,
)
from intradayx.backtest.runner import run_backtest
from intradayx.data.factory import default_provider
from intradayx.data.provider import DataProvider
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability
from intradayx.features.pipeline import build_features
from intradayx.signals.engine import SignalEngine


@lru_cache(maxsize=1)
def get_provider() -> DataProvider:
    return default_provider()


@lru_cache(maxsize=1)
def get_engine() -> SignalEngine:
    return SignalEngine()


def _epoch(ts: datetime) -> int:
    return int(ts.timestamp())


def run_scan(symbol: str, timeframe: str, days: int, scanner: str = "reversal") -> ScanResponse:
    from intradayx.features.pipeline import data_completeness_for
    from intradayx.signals.engine import SignalEngine
    from intradayx.signals.strategy import make_strategy

    tf = Timeframe(timeframe)
    provider = get_provider()
    end = datetime.now(tz=UTC)
    bars = provider.bars(symbol.upper(), end - timedelta(days=days), end, tf)
    caps = provider.capabilities()

    signals = SignalEngine(make_strategy(scanner)).scan(bars, caps)
    if caps.supports(Capability.EARNINGS_CALENDAR):
        from intradayx.attribution.catalysts import enrich_with_earnings

        signals = enrich_with_earnings(signals, provider.earnings_dates(symbol.upper()))
    return ScanResponse(
        symbol=symbol.upper(),
        timeframe=tf.value,
        n_bars=len(bars),
        data_completeness=data_completeness_for(caps),
        signals=[to_signal_dto(s) for s in signals],
    )


def build_chart(symbol: str, timeframe: str, days: int) -> BarsResponse:
    tf = Timeframe(timeframe)
    provider = get_provider()
    end = datetime.now(tz=UTC)
    bars = provider.bars(symbol.upper(), end - timedelta(days=days), end, tf)
    caps = provider.capabilities()

    if bars.is_empty():
        return BarsResponse(
            symbol=symbol.upper(),
            timeframe=tf.value,
            candles=[],
            volume=[],
            vwap=[],
            markers=[],
            levels=None,
            data_completeness=0.0,
        )

    fs = build_features(bars, caps)
    df = fs.df
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

    last = df.tail(1).to_dicts()[0]
    levels = None
    if last.get("prior_poc") is not None:
        levels = LevelsDTO(poc=last["prior_poc"], vah=last["prior_vah"], val=last["prior_val"])

    signals = get_engine().evaluate(fs)
    markers: list[MarkerDTO] = []
    for s in sorted(signals, key=lambda x: x.ts):
        buy = s.side.is_bullish
        markers.append(
            MarkerDTO(
                time=_epoch(s.ts),
                position="belowBar" if buy else "aboveBar",
                shape="arrowUp" if buy else "arrowDown",
                color="#3fb950" if buy else "#f85149",
                text=s.kind.value.replace("reversal_", ""),
            )
        )

    return BarsResponse(
        symbol=symbol.upper(),
        timeframe=tf.value,
        candles=candles,
        volume=volume,
        vwap=vwap,
        markers=markers,
        levels=levels,
        data_completeness=fs.data_completeness,
    )


def run_backtest_dto(symbol: str, timeframe: str, days: int, max_hold: int) -> BacktestResponse:
    tf = Timeframe(timeframe)
    provider = get_provider()
    end = datetime.now(tz=UTC)
    bars = provider.bars(symbol.upper(), end - timedelta(days=days), end, tf)
    res = run_backtest(bars, provider.capabilities(), engine=get_engine(), max_hold_bars=max_hold)
    m = res.metrics
    metrics = MetricsDTO(
        n_trades=m.n_trades,
        win_rate=m.win_rate,
        expectancy_cents=m.expectancy_cents,
        profit_factor=None if m.profit_factor == float("inf") else m.profit_factor,
        total_pnl_cents=m.total_pnl_cents,
        max_drawdown_cents=m.max_drawdown_cents,
        sharpe_per_trade=m.sharpe_per_trade,
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
