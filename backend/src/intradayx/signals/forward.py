"""Forward-learning loop for the meta-filter.

Trains a MetaFilter only on past completed signals, then applies it to the next
out-of-sample window.  Aggregating those OOS decisions gives an honest estimate
of how the self-learning scanner improves over time, with no lookahead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from intradayx.backtest.runner import simulate_trades
from intradayx.domain.bars import BarSet
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.signals.accuracy import SignalOutcome, accuracy_report, label_outcomes
from intradayx.signals.engine import SignalEngine
from intradayx.signals.meta_filter import MetaFilter, train_meta_filter
from intradayx.signals.strategy import make_strategy


@dataclass(frozen=True, slots=True)
class ForwardWindowResult:
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    n_train_signals: int
    n_test_signals: int
    n_test_trades: int
    test_win_rate: float
    test_pnl_cents: int
    model_insufficient: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ForwardLearningResult:
    symbol: str
    scanner: str
    windows: list[ForwardWindowResult]
    oos_accuracy: float
    oos_pnl_cents: int
    n_oos_signals: int
    n_oos_trades: int
    final_model: MetaFilter | None = None


def _slice_bars(bars: BarSet, start: datetime, end: datetime) -> BarSet:
    """Return a new BarSet containing bars in [start, end)."""
    df = bars.df.filter((pl.col("ts") >= start) & (pl.col("ts") < end))
    return BarSet(bars.symbol, bars.timeframe, df)


def forward_learn(
    bars: BarSet,
    caps: ProviderCapabilities,
    *,
    scanner: str = "reversal",
    total_days: int = 120,
    train_days: int = 40,
    test_days: int = 10,
    step_days: int = 10,
    max_hold_bars: int = 24,
    quality_threshold: float = 0.0,
    meta_threshold: float = 0.5,
    min_samples: int = 50,
) -> ForwardLearningResult:
    """Walk-forward meta-filter training and OOS application.

    For each window the model is fit ONLY on signals from the preceding
    ``train_days`` and scored ONLY on signals from the following ``test_days``.
    """
    if scanner not in ("reversal", "scalping"):
        raise ValueError("scanner must be 'reversal' or 'scalping'")

    engine = SignalEngine(make_strategy(scanner))
    end = bars.end or datetime.now(tz=bars.df["ts"].dt.time_zone() or "UTC")
    total_start = end - timedelta(days=total_days)

    windows: list[ForwardWindowResult] = []
    all_oos_labeled: list[Any] = []
    final_model: MetaFilter | None = None

    current = total_start
    idx = 0
    while current + timedelta(days=train_days + test_days) <= end + timedelta(seconds=1):
        train_start = current
        train_end = train_start + timedelta(days=train_days)
        test_start = train_end
        test_end = min(test_start + timedelta(days=test_days), end + timedelta(seconds=1))

        train_bars = _slice_bars(bars, train_start, train_end)
        test_bars = _slice_bars(bars, test_start, test_end)

        if train_bars.is_empty() or test_bars.is_empty():
            current += timedelta(days=step_days)
            idx += 1
            continue

        train_signals = [
            s for s in engine.scan(train_bars, caps) if s.quality_score >= quality_threshold
        ]
        mf, fit_result = train_meta_filter(
            train_signals, train_bars, max_hold_bars=max_hold_bars, min_samples=min_samples
        )

        if fit_result.insufficient:
            windows.append(
                ForwardWindowResult(
                    index=idx,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    n_train_signals=len(train_signals),
                    n_test_signals=0,
                    n_test_trades=0,
                    test_win_rate=0.0,
                    test_pnl_cents=0,
                    model_insufficient=True,
                    reason=fit_result.reason,
                )
            )
            current += timedelta(days=step_days)
            idx += 1
            continue

        test_signals = [
            s for s in engine.scan(test_bars, caps) if s.quality_score >= quality_threshold
        ]
        scores = mf.predict(test_signals)
        filtered = [
            s
            for s, score in zip(test_signals, scores, strict=True)
            if score is not None and score >= meta_threshold
        ]

        labeled = label_outcomes(filtered, test_bars, max_hold_bars=max_hold_bars)
        all_oos_labeled.extend(labeled)

        bt = simulate_trades(filtered, test_bars, max_hold_bars=max_hold_bars)
        wins = sum(1 for x in labeled if x.outcome is SignalOutcome.TARGET)
        win_rate = wins / len(labeled) if labeled else 0.0

        windows.append(
            ForwardWindowResult(
                index=idx,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                n_train_signals=len(train_signals),
                n_test_signals=len(test_signals),
                n_test_trades=len(bt.trades),
                test_win_rate=win_rate,
                test_pnl_cents=bt.metrics.total_pnl_cents,
            )
        )
        final_model = mf
        current += timedelta(days=step_days)
        idx += 1

    report = accuracy_report(all_oos_labeled)
    total_pnl = sum(w.test_pnl_cents for w in windows)
    total_signals = sum(w.n_test_signals for w in windows)
    total_trades = sum(w.n_test_trades for w in windows)

    return ForwardLearningResult(
        symbol=bars.symbol,
        scanner=scanner,
        windows=windows,
        oos_accuracy=report.win_rate,
        oos_pnl_cents=total_pnl,
        n_oos_signals=total_signals,
        n_oos_trades=total_trades,
        final_model=final_model,
    )
