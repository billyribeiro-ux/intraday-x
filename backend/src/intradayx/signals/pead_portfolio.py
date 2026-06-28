"""Cost-aware long/short PEAD portfolio backtest — the deployable number.

Turns per-event PEAD signals into a tradable book and reports the risk-adjusted
return *after* transaction costs and short-borrow. Construction: each day, hold
every open PEAD position equal-weighted (longs from positive surprises, shorts
from negative) — so the book is roughly dollar-neutral when longs and shorts
balance, stripping most market beta. Daily returns compound into an equity curve;
Sharpe is annualized from daily P&L.

Costs are explicit and conservative: ``cost_bps`` per side on entry and exit, and
``borrow_bps_annual`` accrued daily on shorts. This is what converts a gross
"t≈3 drift" into an honest after-cost Sharpe you could actually run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from intradayx.domain.bars import BarSet
from intradayx.signals.pead import PeadSignal

_TRADING_DAYS = 252


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    n_trades: int
    n_days: int
    total_return: float
    ann_return: float
    ann_vol: float
    sharpe: float
    max_drawdown: float
    equity: list[tuple[date, float]] = field(default_factory=list)


def pead_portfolio_backtest(
    bars_by_symbol: dict[str, BarSet],
    signals_by_symbol: dict[str, list[PeadSignal]],
    *,
    cost_bps: float = 5.0,
    borrow_bps_annual: float = 50.0,
) -> PortfolioResult:
    """Simulate a daily-rebalanced, equal-weight long/short PEAD book after costs."""
    daily_cost = cost_bps / 1e4
    daily_borrow = borrow_bps_annual / 1e4 / _TRADING_DAYS

    # Per-date list of position daily returns (already net of borrow + costs).
    contrib: dict[date, list[float]] = {}
    n_trades = 0

    for sym, bars in bars_by_symbol.items():
        sigs = signals_by_symbol.get(sym, [])
        df = bars.df.sort("ts")
        dates = [t.date() for t in df["ts"].to_list()]
        close = df["close"].to_list()
        pos = {d: i for i, d in enumerate(dates)}
        for s in sigs:
            if s.is_open or s.exit_date is None:
                continue  # only realized trades enter the backtest
            i0, i1 = pos.get(s.entry_date), pos.get(s.exit_date)
            if i0 is None or i1 is None or i1 <= i0:
                continue
            n_trades += 1
            sign = 1.0 if s.side == "buy" else -1.0
            for k in range(i0 + 1, i1 + 1):  # entered at close[i0], realized from next day
                if close[k - 1] <= 0:
                    continue
                r = sign * (close[k] / close[k - 1] - 1.0)
                if sign < 0:  # short pays borrow daily
                    r -= daily_borrow
                if k == i0 + 1:  # entry cost
                    r -= daily_cost
                if k == i1:  # exit cost
                    r -= daily_cost
                contrib.setdefault(dates[k], []).append(r)

    if not contrib:
        return PortfolioResult(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, [])

    # Equal-weight the active book each day → portfolio daily return series.
    cal = sorted(contrib)
    rets = [sum(contrib[d]) / len(contrib[d]) for d in cal]

    equity_vals: list[float] = []
    eq = 1.0
    for r in rets:
        eq *= 1.0 + r
        equity_vals.append(eq)

    n = len(rets)
    mean = sum(rets) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / (n - 1)) if n > 1 else 0.0
    sharpe = (mean / sd * math.sqrt(_TRADING_DAYS)) if sd > 0 else 0.0
    ann_return = equity_vals[-1] ** (_TRADING_DAYS / n) - 1.0 if n > 0 else 0.0
    ann_vol = sd * math.sqrt(_TRADING_DAYS)

    peak = -math.inf
    max_dd = 0.0
    for v in equity_vals:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1.0)

    return PortfolioResult(
        n_trades=n_trades,
        n_days=n,
        total_return=equity_vals[-1] - 1.0,
        ann_return=ann_return,
        ann_vol=ann_vol,
        sharpe=sharpe,
        max_drawdown=max_dd,
        equity=list(zip(cal, equity_vals, strict=True)),
    )
