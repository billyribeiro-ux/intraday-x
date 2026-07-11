"""Post-Earnings-Announcement Drift (PEAD) — profitable raw, but mostly beta.

Hard evidence from this repo's adversarially-verified research fleet
(61 names, strict next-session entry so after-close announcements can't leak):

* RAW sign-of-EPS-surprise drift, H=20: 4y n=953 t=4.4; 10y n=2,265 t=6.1 —
  looks like a strong edge.
* MARKET-ADJUSTED (each trade minus SPY over the same window): 10y mean
  +0.32%/trade t=1.9 (not significant); 2021-2026 half +0.12% t=0.5 (dead).
  The book is ~85% long (positive surprises dominate), so raw PEAD P&L is
  substantially disguised market beta — and the residual alpha that existed
  pre-2021 has decayed, matching the literature on post-publication anomaly
  decay.

Both numbers are therefore first-class citizens here: ``trade_return`` (raw)
and ``adjusted_return`` (market-hedged truth serum). Anything presenting raw
PEAD performance MUST surface the adjusted stats alongside it.

This module stays simple and pure (BarSet + surprises in, signals out) so it
backtests and runs live through the same code. Direction: long a positive
surprise, short a negative one; hold ``hold_days`` trading days, entering at
the close of the first session STRICTLY AFTER the announcement date.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from intradayx.domain.bars import BarSet
from intradayx.domain.earnings import EarningsSurprise

_ANNOUNCE_SEARCH_DAYS = 5  # map an earnings date to the next trading session


@dataclass(frozen=True, slots=True)
class PeadSignal:
    """A PEAD trade: enter the session after the surprise, hold ``hold_days``."""

    symbol: str
    announce_date: date
    entry_date: date
    side: str  # "buy" (positive surprise) | "sell" (negative surprise)
    surprise: float
    sue: float  # standardized unexpected earnings: surprise / std(prior surprises)
    entry: float
    hold_days: int
    exit_date: date | None  # None while still inside the drift window (live/open)
    exit: float | None
    trade_return: float | None  # realized, direction-adjusted (None if open)
    is_open: bool
    # Market-hedged truth serum: trade_return minus the sign-adjusted SPY return
    # over the same window. None when open or when no market series was supplied.
    adjusted_return: float | None = None


_SUE_MIN_PRIORS = 4  # need a few prior reports before a surprise std is meaningful


def _sue(surprise: float, priors: list[float]) -> float:
    """Standardized unexpected earnings: surprise / std(prior surprises).

    SUE is the literature-standard PEAD signal — it normalizes a $-surprise by
    how surprising it is *for this name*. Falls back to 0.0 until enough priors
    exist (so a min-SUE filter naturally skips the unstandardizable early ones).
    """
    if len(priors) < _SUE_MIN_PRIORS:
        return 0.0
    mean = sum(priors) / len(priors)
    sd = math.sqrt(sum((x - mean) ** 2 for x in priors) / (len(priors) - 1))
    return surprise / sd if sd > 0 else 0.0


def build_pead_signals(
    symbol: str,
    bars: BarSet,
    surprises: list[EarningsSurprise],
    *,
    hold_days: int = 20,
    min_abs_surprise: float = 0.0,
    min_abs_sue: float = 0.0,
    market: BarSet | None = None,
) -> list[PeadSignal]:
    """Generate PEAD signals from daily ``bars`` + reported ``surprises``.

    Causal and leak-proof: each trade enters at the close of the first session
    STRICTLY AFTER the announcement date (an after-close report can never be
    traded before it is public) and exits ``hold_days`` sessions later.
    ``min_abs_sue`` gates on standardized surprise. ``market`` (e.g. SPY daily
    bars) enables the per-trade market-adjusted return — the number that
    separates alpha from beta. Events whose exit is beyond the available bars
    are returned ``is_open`` (actionable now), never fabricated.
    """
    df = bars.df.sort("ts")
    ts = [t.date() for t in df["ts"].to_list()]
    close = df["close"].to_list()
    if not ts:
        return []
    idx = {d: i for i, d in enumerate(ts)}

    mkt_idx: dict[date, int] = {}
    mkt_close: list[float] = []
    if market is not None and not market.is_empty():
        mdf = market.df.sort("ts")
        mkt_close = mdf["close"].to_list()
        mkt_idx = {t.date(): i for i, t in enumerate(mdf["ts"].to_list())}

    out: list[PeadSignal] = []
    priors: list[float] = []  # past surprises for this symbol (for SUE), causal
    for ev in sorted(surprises, key=lambda e: e.date):
        sue = _sue(ev.surprise, priors)
        priors.append(ev.surprise)
        if abs(ev.surprise) < min_abs_surprise or ev.surprise == 0.0:
            continue
        if abs(sue) < min_abs_sue:
            continue
        # STRICTLY after the announce date (offsets 1..N): after-market-close
        # reports announced on date D are first tradable at the close of D+1.
        d0 = next(
            (idx[ev.date + timedelta(days=o)] for o in range(1, _ANNOUNCE_SEARCH_DAYS + 1)
             if ev.date + timedelta(days=o) in idx),
            None,
        )
        if d0 is None:
            continue
        side = "buy" if ev.surprise > 0 else "sell"
        sign = 1.0 if side == "buy" else -1.0
        entry = float(close[d0])
        exit_idx = d0 + hold_days
        if exit_idx < len(close):
            exit_px = float(close[exit_idx])
            raw = exit_px / entry - 1.0
            adjusted: float | None = None
            e0 = mkt_idx.get(ts[d0])
            if e0 is not None and e0 + hold_days < len(mkt_close):
                mkt_ret = mkt_close[e0 + hold_days] / mkt_close[e0] - 1.0
                adjusted = sign * (raw - mkt_ret)
            out.append(
                PeadSignal(
                    symbol=symbol.upper(),
                    announce_date=ev.date,
                    entry_date=ts[d0],
                    side=side,
                    surprise=ev.surprise,
                    sue=sue,
                    entry=entry,
                    hold_days=hold_days,
                    exit_date=ts[exit_idx],
                    exit=exit_px,
                    trade_return=raw if side == "buy" else -raw,
                    is_open=False,
                    adjusted_return=adjusted,
                )
            )
        else:
            out.append(
                PeadSignal(
                    symbol=symbol.upper(),
                    announce_date=ev.date,
                    entry_date=ts[d0],
                    side=side,
                    surprise=ev.surprise,
                    sue=sue,
                    entry=entry,
                    hold_days=hold_days,
                    exit_date=None,
                    exit=None,
                    trade_return=None,
                    is_open=True,
                )
            )
    return out


@dataclass(frozen=True, slots=True)
class PeadStats:
    n: int
    mean_return: float
    t_stat: float
    hit_rate: float
    total_return: float
    # Market-adjusted (SPY-hedged) — the alpha-vs-beta separator. Zero when no
    # market series was supplied to build_pead_signals.
    adj_n: int = 0
    adj_mean_return: float = 0.0
    adj_t_stat: float = 0.0
    adj_hit_rate: float = 0.0


def pead_stats(signals: list[PeadSignal]) -> PeadStats:
    """Aggregate realized (closed) PEAD trades into honest edge statistics.

    Raw stats describe the long-biased book (substantially market beta over
    2016-2026); the ``adj_*`` fields are the market-hedged truth serum computed
    from ``adjusted_return`` when a market series was supplied.
    """

    def _agg(rets: list[float]) -> tuple[int, float, float, float]:
        n = len(rets)
        if n == 0:
            return 0, 0.0, 0.0, 0.0
        mean = sum(rets) / n
        t = 0.0
        if n > 1:
            sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / (n - 1))
            t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
        return n, mean, t, sum(1 for x in rets if x > 0) / n

    raw = [s.trade_return for s in signals if s.trade_return is not None]
    adj = [s.adjusted_return for s in signals if s.adjusted_return is not None]
    n, mean, t, hit = _agg(raw)
    adj_n, adj_mean, adj_t, adj_hit = _agg(adj)
    return PeadStats(
        n=n, mean_return=mean, t_stat=t, hit_rate=hit, total_return=sum(raw),
        adj_n=adj_n, adj_mean_return=adj_mean, adj_t_stat=adj_t, adj_hit_rate=adj_hit,
    )


def open_signals(signals: list[PeadSignal], *, now: datetime | None = None) -> list[PeadSignal]:
    """The currently-actionable trades: announced, still inside the drift window."""
    return [s for s in signals if s.is_open]
