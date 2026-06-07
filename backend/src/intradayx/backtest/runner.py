"""Event-driven backtester (reuses the shared SignalEngine).

Signal logic lives in :class:`~intradayx.signals.engine.SignalEngine`, so this
runtime never forks it — the same signals drive backtest and live. Trades fill
on the NEXT bar (no same-bar lookahead), manage a stop + first target with a
bar-count time-stop, and P&L is tracked in integer cents.

A `nautilus_trader` adapter for real broker execution is deferred to the go-live
phase; this custom engine is the research backtester (the plan-sanctioned
fallback). The boundary it shares with live is `SignalEngine.evaluate`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from intradayx.backtest.fills import FillModel
from intradayx.backtest.metrics import BacktestMetrics, compute_metrics
from intradayx.domain.bars import BarSet, Timeframe
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.domain.signals import Signal
from intradayx.signals.engine import SignalEngine

DEFAULT_NOTIONAL_CENTS = 10_000_00  # $10,000 per trade
DEFAULT_MAX_HOLD_BARS = 24


class ExitReason(StrEnum):
    STOP = "stop"
    TARGET = "target"
    TIME = "time"


@dataclass(frozen=True, slots=True)
class Trade:
    signal_id: str
    kind: str
    is_long: bool
    entry_ts: datetime
    exit_ts: datetime
    entry: float
    exit: float
    shares: int
    pnl_cents: int  # net of commission, integer cents
    exit_reason: ExitReason
    tod_bucket: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    symbol: str
    timeframe: Timeframe
    trades: list[Trade]
    equity_curve: list[tuple[datetime, int]]  # (ts, cumulative pnl cents)
    metrics: BacktestMetrics
    n_signals: int
    params_version: str = "0"
    signals: list[Signal] = field(default_factory=list)


def simulate_trades(
    signals: list[Signal],
    bars: BarSet,
    *,
    fill_model: FillModel | None = None,
    notional_cents: int = DEFAULT_NOTIONAL_CENTS,
    max_hold_bars: int = DEFAULT_MAX_HOLD_BARS,
) -> BacktestResult:
    """Simulate `signals` against `bars`. Pure & deterministic (testable anchor)."""
    fm = fill_model or FillModel()
    df = bars.df
    ts = df["ts"].to_list()
    o = df["open"].to_list()
    h = df["high"].to_list()
    low = df["low"].to_list()
    c = df["close"].to_list()
    idx_of = {t: i for i, t in enumerate(ts)}
    n = len(ts)

    trades: list[Trade] = []
    equity = 0
    equity_curve: list[tuple[datetime, int]] = []
    last_exit_idx = -1

    for sig in sorted(signals, key=lambda s: s.ts):
        sig_idx = idx_of.get(sig.ts)
        if sig_idx is None:
            continue
        entry_idx = sig_idx + 1
        if entry_idx >= n or entry_idx <= last_exit_idx:
            continue  # no next bar, or still in a prior position (no overlap)

        is_long = sig.side.is_bullish
        entry = fm.entry_price(o[entry_idx], is_long=is_long)
        shares = int((notional_cents / 100.0) // entry)
        if shares <= 0:
            continue
        stop = sig.stop
        target = sig.targets[0] if sig.targets else None

        exit_idx = min(entry_idx + max_hold_bars, n - 1)
        exit_price = c[exit_idx]
        reason = ExitReason.TIME
        for j in range(entry_idx, min(entry_idx + max_hold_bars, n - 1) + 1):
            if is_long:
                if low[j] <= stop:
                    exit_idx, exit_price, reason = j, stop, ExitReason.STOP
                    break
                if target is not None and h[j] >= target:
                    exit_idx, exit_price, reason = j, target, ExitReason.TARGET
                    break
            else:
                if h[j] >= stop:
                    exit_idx, exit_price, reason = j, stop, ExitReason.STOP
                    break
                if target is not None and low[j] <= target:
                    exit_idx, exit_price, reason = j, target, ExitReason.TARGET
                    break

        per_share = (exit_price - entry) if is_long else (entry - exit_price)
        gross_cents = round(per_share * shares * 100)
        commission = fm.commission_cents(shares) * 2  # entry + exit
        pnl_cents = gross_cents - commission
        equity += pnl_cents
        trades.append(
            Trade(
                signal_id=sig.signal_id,
                kind=sig.kind.value,
                is_long=is_long,
                entry_ts=ts[entry_idx],
                exit_ts=ts[exit_idx],
                entry=round(entry, 4),
                exit=round(exit_price, 4),
                shares=shares,
                pnl_cents=pnl_cents,
                exit_reason=reason,
                tod_bucket=sig.time_of_day_bucket,
            )
        )
        equity_curve.append((ts[exit_idx], equity))
        last_exit_idx = exit_idx

    return BacktestResult(
        symbol=bars.symbol,
        timeframe=bars.timeframe,
        trades=trades,
        equity_curve=equity_curve,
        metrics=compute_metrics(trades, notional_cents),
        n_signals=len(signals),
        signals=sorted(signals, key=lambda s: s.ts),
    )


def run_backtest(
    bars: BarSet,
    caps: ProviderCapabilities,
    *,
    engine: SignalEngine | None = None,
    fill_model: FillModel | None = None,
    notional_cents: int = DEFAULT_NOTIONAL_CENTS,
    max_hold_bars: int = DEFAULT_MAX_HOLD_BARS,
) -> BacktestResult:
    """Scan with the shared SignalEngine, then simulate the trades."""
    eng = engine or SignalEngine()
    signals = eng.scan(bars, caps)
    result = simulate_trades(
        signals,
        bars,
        fill_model=fill_model,
        notional_cents=notional_cents,
        max_hold_bars=max_hold_bars,
    )
    return replace(result, params_version=eng.params.version)
