"""Backtest metrics — win rate, expectancy, profit factor, drawdown, per-ToD.

Per-trade Sharpe is reported *unannualized* and labelled as such (annualizing
intraday strategies is fraught). The Deflated Sharpe Ratio — which discounts the
multiple-testing overfit that kills most intraday edges — needs the number of
trials and lands with the walk-forward optimizer in Phase 6.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from intradayx.backtest.runner import Trade


@dataclass(frozen=True, slots=True)
class TodStat:
    bucket: str
    n: int
    win_rate: float
    expectancy_cents: float


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    n_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_win_cents: float
    avg_loss_cents: float
    expectancy_cents: float
    profit_factor: float  # inf if there are wins but no losses
    total_pnl_cents: int
    max_drawdown_cents: int  # magnitude (>= 0)
    sharpe_per_trade: float  # unannualized
    per_tod: dict[str, TodStat]


_EMPTY = BacktestMetrics(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0.0, {})


def compute_metrics(trades: list[Trade], notional_cents: int) -> BacktestMetrics:
    if not trades:
        return _EMPTY

    pnls = [t.pnl_cents for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)

    gross_win = sum(wins)
    gross_loss = -sum(losses)
    if gross_loss > 0:
        profit_factor = gross_win / gross_loss
    else:
        profit_factor = float("inf") if gross_win > 0 else 0.0

    # Max drawdown on the cumulative-pnl curve.
    cum = peak = 0
    max_dd = 0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)

    returns = [p / notional_cents for p in pnls]
    std_r = statistics.stdev(returns) if n > 1 else 0.0
    sharpe = (statistics.fmean(returns) / std_r) if std_r > 0 else 0.0

    # Per time-of-day bucket.
    per_tod: dict[str, TodStat] = {}
    buckets = sorted({t.tod_bucket for t in trades})
    for b in buckets:
        bt = [t.pnl_cents for t in trades if t.tod_bucket == b]
        bw = sum(1 for p in bt if p > 0)
        per_tod[b] = TodStat(
            bucket=b,
            n=len(bt),
            win_rate=bw / len(bt),
            expectancy_cents=statistics.fmean(bt),
        )

    return BacktestMetrics(
        n_trades=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / n,
        avg_win_cents=statistics.fmean(wins) if wins else 0.0,
        avg_loss_cents=statistics.fmean(losses) if losses else 0.0,
        expectancy_cents=statistics.fmean(pnls),
        profit_factor=profit_factor,
        total_pnl_cents=sum(pnls),
        max_drawdown_cents=-max_dd,
        sharpe_per_trade=sharpe,
        per_tod=per_tod,
    )
