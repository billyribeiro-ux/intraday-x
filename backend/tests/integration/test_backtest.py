"""Deterministic backtester anchor — hand-crafted signals + bars → exact P&L."""

from __future__ import annotations

from intradayx.backtest.fills import FillModel
from intradayx.backtest.runner import ExitReason, simulate_trades
from intradayx.domain.bars import BarSet, Timeframe
from intradayx.domain.signals import Side, Signal, SignalKind, uncertain_attribution
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


def test_long_hits_target() -> None:
    bars = make_bars(
        closes=[100, 100, 100, 101, 100, 100],
        opens=[100, 100, 100, 100, 100, 100],
        highs=[100.5, 100.5, 100.5, 101.5, 100.5, 100.5],
        lows=[99.5, 99.5, 99.5, 99.8, 99.5, 99.5],
        timeframe=Timeframe.M5,
    )
    sig = _signal(bars, 2, kind=SignalKind.REVERSAL_BOTTOM, side=Side.BUY, stop=99.0, target=101.0)
    res = simulate_trades([sig], bars)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.is_long is True
    assert t.exit_reason is ExitReason.TARGET
    # entry on next bar's open (100) + 1bp slippage = 100.01; $10k notional => 99 shares
    assert t.shares == 99
    assert t.pnl_cents == 9701  # (101 - 100.01)*99*100 - 100 commission
    assert res.metrics.total_pnl_cents == 9701


def test_short_hits_stop() -> None:
    bars = make_bars(
        closes=[100, 100, 100, 101, 100, 100],
        opens=[100, 100, 100, 100, 100, 100],
        highs=[100.5, 100.5, 100.5, 101.5, 100.5, 100.5],
        lows=[99.5, 99.5, 99.5, 99.8, 99.5, 99.5],
        timeframe=Timeframe.M5,
    )
    sig = _signal(bars, 2, kind=SignalKind.REVERSAL_TOP, side=Side.SELL, stop=101.0, target=98.0)
    res = simulate_trades([sig], bars)
    t = res.trades[0]
    assert t.is_long is False
    assert t.exit_reason is ExitReason.STOP
    assert t.shares == 100
    assert t.pnl_cents == -10200  # (99.99 - 101)*100*100 - 100 commission


def test_time_stop_exit() -> None:
    bars = make_bars(
        closes=[100, 100, 100, 100, 100, 100],
        timeframe=Timeframe.M5,
    )
    # stop/target far away so neither triggers within the hold window
    sig = _signal(bars, 1, kind=SignalKind.REVERSAL_BOTTOM, side=Side.BUY, stop=90.0, target=110.0)
    res = simulate_trades([sig], bars, max_hold_bars=2)
    assert res.trades[0].exit_reason is ExitReason.TIME


def test_time_stop_holds_exactly_max_hold_bars() -> None:
    bars = make_bars(closes=[100.0] * 8, timeframe=Timeframe.M5)
    sig = _signal(bars, 1, kind=SignalKind.REVERSAL_BOTTOM, side=Side.BUY, stop=90.0, target=110.0)
    res = simulate_trades([sig], bars, max_hold_bars=3)
    # entry on bar 2; hold EXACTLY 3 bars (entry inclusive) => exit on bar index 4, not 5.
    assert res.trades[0].exit_ts == bars.df["ts"].item(4)
    assert res.trades[0].exit_reason is ExitReason.TIME


def test_commission_charged_on_one_share() -> None:
    # round(0.5) == 0 would waive commission; ceil charges it.
    assert FillModel().commission_cents(1) == 1


def test_no_overlapping_positions() -> None:
    bars = make_bars(closes=[100] * 8, timeframe=Timeframe.M5)
    sigs = [
        _signal(bars, 1, kind=SignalKind.REVERSAL_BOTTOM, side=Side.BUY, stop=90, target=110),
        _signal(bars, 2, kind=SignalKind.REVERSAL_BOTTOM, side=Side.BUY, stop=90, target=110),
    ]
    # The second signal fires while the first trade (held 4 bars) is still open.
    res = simulate_trades(sigs, bars, max_hold_bars=4, fill_model=FillModel())
    assert len(res.trades) == 1
