"""PEAD long/short portfolio backtest: costs applied, Sharpe/equity sane."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl

from intradayx.domain.bars import BAR_SCHEMA, BarSet, Timeframe
from intradayx.signals.pead import PeadSignal
from intradayx.signals.pead_portfolio import pead_portfolio_backtest


def _bars(closes: list[float]) -> BarSet:
    t0 = datetime(2026, 1, 2, tzinfo=UTC)
    n = len(closes)
    return BarSet("X", Timeframe.D1, pl.DataFrame({
        "ts": [t0 + timedelta(days=i) for i in range(n)],
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1] * n, "vwap": [None] * n, "trades": [None] * n, "source": ["t"] * n,
    }, schema=BAR_SCHEMA))


def _sig(entry_i: int, exit_i: int, side: str) -> PeadSignal:
    base = date(2026, 1, 2)
    return PeadSignal(
        symbol="X", announce_date=base + timedelta(days=entry_i),
        entry_date=base + timedelta(days=entry_i), side=side, surprise=1.0, sue=1.0,
        entry=0.0, hold_days=exit_i - entry_i,
        exit_date=base + timedelta(days=exit_i), exit=0.0, trade_return=0.0, is_open=False,
    )


def test_long_winner_makes_money_after_costs() -> None:
    closes = [100.0 * (1.01 ** i) for i in range(11)]  # +1%/day
    bars = {"X": _bars(closes)}
    sigs = {"X": [_sig(0, 10, "buy")]}
    r = pead_portfolio_backtest(bars, sigs, cost_bps=5.0, borrow_bps_annual=0.0)
    assert r.n_trades == 1
    assert r.n_days == 10
    assert r.total_return > 0.08  # ~+10% gross minus ~10bps cost
    assert r.sharpe > 0


def test_costs_and_borrow_reduce_return() -> None:
    closes = [100.0 * (1.01 ** i) for i in range(11)]
    bars = {"X": _bars(closes)}
    sigs = {"X": [_sig(0, 10, "buy")]}
    cheap = pead_portfolio_backtest(bars, sigs, cost_bps=0.0, borrow_bps_annual=0.0)
    pricey = pead_portfolio_backtest(bars, sigs, cost_bps=50.0, borrow_bps_annual=0.0)
    assert pricey.total_return < cheap.total_return  # costs bite


def test_open_trades_excluded_and_empty_is_safe() -> None:
    r = pead_portfolio_backtest({}, {})
    assert r.n_trades == 0 and r.sharpe == 0.0 and r.equity == []
