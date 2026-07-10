"""PEAD signal logic: direction from surprise, causal entry/exit, open trades."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl

from intradayx.domain.bars import BAR_SCHEMA, BarSet, Timeframe
from intradayx.domain.earnings import EarningsSurprise
from intradayx.signals.pead import build_pead_signals, open_signals, pead_stats


def _daily_bars(n: int, closes: list[float]) -> BarSet:
    t0 = datetime(2026, 1, 2, tzinfo=UTC)
    rows = {
        "ts": [t0 + timedelta(days=i) for i in range(n)],
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [1_000] * n,
        "vwap": [None] * n,
        "trades": [None] * n,
        "source": ["test"] * n,
    }
    return BarSet("AAPL", Timeframe.D1, pl.DataFrame(rows, schema=BAR_SCHEMA))


def test_positive_surprise_is_long_and_entry_is_strictly_after_announce() -> None:
    closes = [100.0 + i for i in range(30)]  # steadily rising
    bars = _daily_bars(30, closes)
    # surprise announced 2026-01-07 (day index 5); STRICT entry = next session
    # (an after-close report can never be traded before it is public)
    ev = EarningsSurprise(date=date(2026, 1, 7), eps_actual=1.2, eps_estimated=1.0)
    sigs = build_pead_signals("AAPL", bars, [ev], hold_days=10)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.side == "buy" and not s.is_open
    assert s.entry_date == date(2026, 1, 8)  # strictly after the announce date
    # entry close[6]=106, exit close[16]=116 → +9.43% long
    assert s.entry == 106.0 and s.exit == 116.0
    assert s.trade_return is not None and s.trade_return > 0.09
    assert s.adjusted_return is None  # no market series supplied


def test_market_adjusted_return_subtracts_spy() -> None:
    closes = [100.0 * (1.01**i) for i in range(30)]  # +1%/day stock
    bars = _daily_bars(30, closes)
    spy = _daily_bars(30, closes)  # market moves identically
    ev = EarningsSurprise(date=date(2026, 1, 7), eps_actual=1.2, eps_estimated=1.0)
    s = build_pead_signals("AAPL", bars, [ev], hold_days=10, market=spy)[0]
    # stock == market → all "drift" is beta → adjusted return is ~0
    assert s.trade_return is not None and s.trade_return > 0.09
    assert s.adjusted_return is not None and abs(s.adjusted_return) < 1e-9
    st = pead_stats([s])
    assert st.adj_n == 1 and abs(st.adj_mean_return) < 1e-9


def test_negative_surprise_is_short_and_profits_when_price_falls() -> None:
    closes = [200.0 - i for i in range(30)]  # steadily falling
    bars = _daily_bars(30, closes)
    ev = EarningsSurprise(date=date(2026, 1, 7), eps_actual=0.8, eps_estimated=1.0)
    s = build_pead_signals("AAPL", bars, [ev], hold_days=10)[0]
    assert s.side == "sell"
    # price fell → short is profitable → positive direction-adjusted return
    assert s.trade_return is not None and s.trade_return > 0


def test_event_without_room_is_open_not_fabricated() -> None:
    bars = _daily_bars(10, [100.0 + i for i in range(10)])
    ev = EarningsSurprise(date=date(2026, 1, 9), eps_actual=1.1, eps_estimated=1.0)  # day idx 7
    sigs = build_pead_signals("AAPL", bars, [ev], hold_days=20)  # exit beyond data
    assert len(sigs) == 1 and sigs[0].is_open
    assert sigs[0].exit is None and sigs[0].trade_return is None
    assert open_signals(sigs) == sigs
    assert pead_stats(sigs).n == 0  # open trades don't count as realized


def test_zero_surprise_skipped() -> None:
    bars = _daily_bars(30, [100.0] * 30)
    ev = EarningsSurprise(date=date(2026, 1, 7), eps_actual=1.0, eps_estimated=1.0)
    assert build_pead_signals("AAPL", bars, [ev], hold_days=5) == []
