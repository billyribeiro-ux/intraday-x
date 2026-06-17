"""Signal-level accuracy audit — the scanner's own batting average.

Labels every emitted signal by what actually happened next (target hit first,
stop hit first, or time-stop), independent of position sizing or overlapping
positions.  This is the purest measure of directional call accuracy and is the
metric the quality layer tries to push toward 1.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from intradayx.domain.bars import BarSet
from intradayx.domain.signals import Signal


class SignalOutcome(StrEnum):
    TARGET = "target"
    STOP = "stop"
    TIME = "time"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class LabeledSignal:
    signal: Signal
    outcome: SignalOutcome
    pnl_cents: int = 0
    bars_held: int = 0


@dataclass(frozen=True, slots=True)
class AccuracyReport:
    total: int
    wins: int
    losses: int
    times: int
    win_rate: float
    loss_rate: float
    time_rate: float
    expectancy_cents: float
    per_kind: dict[str, AccuracyReport] = field(default_factory=dict)
    per_tod: dict[str, AccuracyReport] = field(default_factory=dict)


def _empty() -> AccuracyReport:
    return AccuracyReport(0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0)


def label_outcomes(
    signals: list[Signal],
    bars: BarSet,
    *,
    max_hold_bars: int = 24,
) -> list[LabeledSignal]:
    """Label each signal's outcome by simulating it independently on ``bars``."""
    df = bars.df
    ts = df["ts"].to_list()
    o = df["open"].to_list()
    h = df["high"].to_list()
    low = df["low"].to_list()
    c = df["close"].to_list()
    idx_of = {t: i for i, t in enumerate(ts)}
    n = len(ts)

    results: list[LabeledSignal] = []
    for sig in sorted(signals, key=lambda s: s.ts):
        sig_idx = idx_of.get(sig.ts)
        if sig_idx is None:
            continue
        entry_idx = sig_idx + 1
        if entry_idx >= n:
            continue

        is_long = sig.side.is_bullish
        entry = o[entry_idx]
        stop = sig.stop
        target = sig.targets[0] if sig.targets else None
        outcome = SignalOutcome.TIME
        exit_idx = min(entry_idx + max_hold_bars - 1, n - 1)
        exit_price = c[exit_idx]
        bars_held = exit_idx - entry_idx

        # Gap-open handling.
        if is_long:
            if o[entry_idx] <= stop:
                exit_idx = entry_idx
                exit_price = o[entry_idx]
                outcome = SignalOutcome.STOP
                bars_held = 0
            elif target is not None and o[entry_idx] >= target:
                exit_idx = entry_idx
                exit_price = o[entry_idx]
                outcome = SignalOutcome.TARGET
                bars_held = 0
        else:
            if o[entry_idx] >= stop:
                exit_idx = entry_idx
                exit_price = o[entry_idx]
                outcome = SignalOutcome.STOP
                bars_held = 0
            elif target is not None and o[entry_idx] <= target:
                exit_idx = entry_idx
                exit_price = o[entry_idx]
                outcome = SignalOutcome.TARGET
                bars_held = 0

        if outcome is SignalOutcome.TIME:
            for j in range(entry_idx, min(entry_idx + max_hold_bars - 1, n - 1) + 1):
                if is_long:
                    if low[j] <= stop:
                        exit_idx, exit_price, outcome = j, stop, SignalOutcome.STOP
                        bars_held = j - entry_idx
                        break
                    if target is not None and h[j] >= target:
                        exit_idx, exit_price, outcome = j, target, SignalOutcome.TARGET
                        bars_held = j - entry_idx
                        break
                else:
                    if h[j] >= stop:
                        exit_idx, exit_price, outcome = j, stop, SignalOutcome.STOP
                        bars_held = j - entry_idx
                        break
                    if target is not None and low[j] <= target:
                        exit_idx, exit_price, outcome = j, target, SignalOutcome.TARGET
                        bars_held = j - entry_idx
                        break

        per_share = (exit_price - entry) if is_long else (entry - exit_price)
        pnl_cents = round(per_share * 100)
        results.append(
            LabeledSignal(signal=sig, outcome=outcome, pnl_cents=pnl_cents, bars_held=bars_held)
        )
    return results


def _build_report(items: list[LabeledSignal]) -> AccuracyReport:
    total = len(items)
    if total == 0:
        return _empty()
    wins = sum(1 for x in items if x.outcome is SignalOutcome.TARGET)
    losses = sum(1 for x in items if x.outcome is SignalOutcome.STOP)
    times = sum(1 for x in items if x.outcome is SignalOutcome.TIME)
    pnls = [x.pnl_cents for x in items]
    return AccuracyReport(
        total=total,
        wins=wins,
        losses=losses,
        times=times,
        win_rate=wins / total,
        loss_rate=losses / total,
        time_rate=times / total,
        expectancy_cents=sum(pnls) / total,
    )


def accuracy_report(
    labeled: list[LabeledSignal],
    *,
    min_quality_score: float | None = None,
) -> AccuracyReport:
    """Aggregate accuracy, optionally filtering to signals above a quality threshold."""
    if min_quality_score is not None:
        labeled = [x for x in labeled if x.signal.quality_score >= min_quality_score]
    report = _build_report(labeled)

    by_kind: dict[str, list[LabeledSignal]] = {}
    by_tod: dict[str, list[LabeledSignal]] = {}
    for x in labeled:
        by_kind.setdefault(x.signal.kind.value, []).append(x)
        by_tod.setdefault(x.signal.time_of_day_bucket, []).append(x)

    object.__setattr__(report, "per_kind", {k: _build_report(v) for k, v in by_kind.items()})
    object.__setattr__(report, "per_tod", {k: _build_report(v) for k, v in by_tod.items()})
    return report
