"""Walk-forward validation — the honest test most backtests skip.

Split history into sequential windows; in each, pick the best threshold on the
*in-sample* portion, then trade it on the *out-of-sample* portion. Aggregate only
the OOS trades. The Deflated Sharpe is computed with ``n_trials = len(grid)`` so
it actually discounts the multiple-testing overfit (a single backtest's Sharpe
is meaningless; this one survived selection on unseen data). On free data the
result is usually sobering — which is the point.
"""

from __future__ import annotations

from dataclasses import dataclass

from intradayx.attribution.validation import deflated_sharpe_ratio
from intradayx.backtest.metrics import BacktestMetrics, compute_metrics
from intradayx.backtest.runner import (
    DEFAULT_MAX_HOLD_BARS,
    DEFAULT_NOTIONAL_CENTS,
    Trade,
    run_backtest,
)
from intradayx.domain.bars import BarSet
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.signals.engine import SignalEngine
from intradayx.signals.params import ReversalParams, ScalpingParams
from intradayx.signals.reversal import ReversalStrategy
from intradayx.signals.scalping import ScalpingStrategy

DEFAULT_THRESHOLDS = (0.30, 0.35, 0.40, 0.45, 0.50)


def _strategy(scanner: str, threshold: float) -> ReversalStrategy | ScalpingStrategy:
    if scanner == "scalping":
        return ScalpingStrategy(ScalpingParams(threshold=threshold))
    return ReversalStrategy(ReversalParams(threshold=threshold))


@dataclass(frozen=True, slots=True)
class WindowResult:
    index: int
    chosen_threshold: float
    in_sample_expectancy_cents: float
    oos_trades: int
    oos_pnl_cents: int


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    symbol: str
    scanner: str
    n_windows: int
    n_trials_per_window: int
    windows: list[WindowResult]
    oos_metrics: BacktestMetrics  # aggregated out-of-sample
    deflated_sharpe: float  # P(true SR > 0), deflated by n_trials
    total_oos_pnl_cents: int


def walk_forward(
    bars: BarSet,
    caps: ProviderCapabilities,
    *,
    scanner: str = "reversal",
    n_windows: int = 4,
    train_frac: float = 0.6,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    max_hold_bars: int = DEFAULT_MAX_HOLD_BARS,
    notional_cents: int = DEFAULT_NOTIONAL_CENTS,
) -> WalkForwardResult:
    df = bars.df
    n = df.height
    window_size = max(n // n_windows, 1)

    windows: list[WindowResult] = []
    oos_trades: list[Trade] = []

    for i in range(n_windows):
        lo = i * window_size
        hi = n if i == n_windows - 1 else (i + 1) * window_size
        block = df.slice(lo, hi - lo)
        # Need room for train + an embargo gap + test.
        if block.height < 2 * max_hold_bars + 10:
            continue
        # EMBARGO the `max_hold_bars` bars between IS and OOS so no in-sample
        # trade's holding window is adjacent to (or correlated with) the OOS
        # region — otherwise the Deflated-Sharpe headline leaks (AI_LANDMINES #8).
        train_end = int(block.height * train_frac)
        test_start = train_end + max_hold_bars
        if test_start >= block.height or train_end < 1:
            continue
        train = BarSet(bars.symbol, bars.timeframe, block.slice(0, train_end))
        test_len = block.height - test_start
        test = BarSet(bars.symbol, bars.timeframe, block.slice(test_start, test_len))

        # Pick the threshold that maximizes in-sample expectancy.
        best_t = thresholds[0]
        best_score = float("-inf")
        for t in thresholds:
            r = run_backtest(
                train,
                caps,
                engine=SignalEngine(_strategy(scanner, t)),
                max_hold_bars=max_hold_bars,
                notional_cents=notional_cents,
            )
            score = r.metrics.expectancy_cents if r.metrics.n_trades else float("-inf")
            if score > best_score:
                best_score, best_t = score, t

        # Trade that choice out-of-sample.
        oos = run_backtest(
            test,
            caps,
            engine=SignalEngine(_strategy(scanner, best_t)),
            max_hold_bars=max_hold_bars,
            notional_cents=notional_cents,
        )
        oos_trades.extend(oos.trades)
        windows.append(
            WindowResult(
                index=i,
                chosen_threshold=best_t,
                in_sample_expectancy_cents=0.0 if best_score == float("-inf") else best_score,
                oos_trades=oos.metrics.n_trades,
                oos_pnl_cents=oos.metrics.total_pnl_cents,
            )
        )

    oos_metrics = compute_metrics(oos_trades, notional_cents)
    returns = [t.pnl_cents / notional_cents for t in oos_trades]
    dsr = deflated_sharpe_ratio(returns, len(thresholds)) if len(returns) >= 3 else 0.0

    return WalkForwardResult(
        symbol=bars.symbol,
        scanner=scanner,
        n_windows=len(windows),
        n_trials_per_window=len(thresholds),
        windows=windows,
        oos_metrics=oos_metrics,
        deflated_sharpe=dsr,
        total_oos_pnl_cents=oos_metrics.total_pnl_cents,
    )
