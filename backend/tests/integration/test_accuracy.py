"""Signal-level accuracy audit harness."""

from __future__ import annotations

from intradayx.backtest.runner import simulate_trades
from intradayx.domain.bars import BarSet, Timeframe
from intradayx.domain.signals import Side, Signal, SignalKind, uncertain_attribution
from intradayx.signals.accuracy import SignalOutcome, accuracy_report, label_outcomes
from tests.fixtures.synthetic import make_bars


def _signal(
    bars: BarSet, idx: int, *, kind: SignalKind, side: Side, stop: float, target: float
) -> Signal:
    return Signal.create(
        symbol=bars.symbol,
        ts=bars.df["ts"].item(idx),
        kind=kind,
        side=side,
        confidence=0.5,
        entry=bars.df["close"].item(idx),
        stop=stop,
        targets=(target,),
        time_of_day_bucket="lunch",
        attribution=uncertain_attribution(0.5),
    )


def test_long_signal_labeled_target() -> None:
    bars = make_bars(
        closes=[100, 100, 100, 101, 100],
        opens=[100, 100, 100, 100, 100],
        highs=[100.5, 100.5, 100.5, 101.5, 100.5],
        lows=[99.5, 99.5, 99.5, 99.8, 99.5],
        timeframe=Timeframe.M5,
    )
    sig = _signal(bars, 1, kind=SignalKind.REVERSAL_BOTTOM, side=Side.BUY, stop=99.0, target=101.0)
    labeled = label_outcomes([sig], bars)
    assert len(labeled) == 1
    assert labeled[0].outcome is SignalOutcome.TARGET
    assert labeled[0].pnl_cents == 100  # (101 - 100) * 100


def test_short_signal_labeled_stop() -> None:
    bars = make_bars(
        closes=[100, 100, 100, 101, 100],
        opens=[100, 100, 100, 100, 100],
        highs=[100.5, 100.5, 100.5, 101.5, 100.5],
        lows=[99.5, 99.5, 99.5, 99.8, 99.5],
        timeframe=Timeframe.M5,
    )
    sig = _signal(bars, 1, kind=SignalKind.REVERSAL_TOP, side=Side.SELL, stop=101.0, target=98.0)
    labeled = label_outcomes([sig], bars)
    assert labeled[0].outcome is SignalOutcome.STOP


def test_gap_open_hits_stop_immediately() -> None:
    bars = make_bars(
        closes=[100, 95],
        opens=[100, 95],
        highs=[100.5, 96],
        lows=[99.5, 94],
        timeframe=Timeframe.M5,
    )
    sig = _signal(bars, 0, kind=SignalKind.REVERSAL_BOTTOM, side=Side.BUY, stop=98.0, target=102.0)
    labeled = label_outcomes([sig], bars)
    # Entry bar opens at 95, already through the 98 stop.
    assert labeled[0].outcome is SignalOutcome.STOP
    assert labeled[0].bars_held == 0


def test_accuracy_report_aggregates_win_rate() -> None:
    bars = make_bars(
        closes=[100, 100, 100, 101, 100],
        opens=[100, 100, 100, 100, 100],
        highs=[100.5, 100.5, 100.5, 101.5, 100.5],
        lows=[99.5, 99.5, 99.5, 99.8, 99.5],
        timeframe=Timeframe.M5,
    )
    sigs = [
        _signal(bars, 1, kind=SignalKind.REVERSAL_BOTTOM, side=Side.BUY, stop=99.0, target=101.0),
        _signal(bars, 1, kind=SignalKind.REVERSAL_TOP, side=Side.SELL, stop=101.0, target=98.0),
    ]
    report = accuracy_report(label_outcomes(sigs, bars))
    assert report.total == 2
    assert report.win_rate == 0.5
    assert report.loss_rate == 0.5
    assert "reversal_bottom" in report.per_kind
    assert "reversal_top" in report.per_kind


def test_accuracy_matches_backtest_outcome_for_single_trade() -> None:
    bars = make_bars(
        closes=[100, 100, 100, 101, 100],
        opens=[100, 100, 100, 100, 100],
        highs=[100.5, 100.5, 100.5, 101.5, 100.5],
        lows=[99.5, 99.5, 99.5, 99.8, 99.5],
        timeframe=Timeframe.M5,
    )
    sig = _signal(bars, 1, kind=SignalKind.REVERSAL_BOTTOM, side=Side.BUY, stop=99.0, target=101.0)
    labeled = label_outcomes([sig], bars)[0]
    bt = simulate_trades([sig], bars)
    # Both label the same directional outcome.
    assert bt.trades[0].exit_reason.value == labeled.outcome.value
