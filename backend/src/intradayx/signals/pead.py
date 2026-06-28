"""Post-Earnings-Announcement Drift (PEAD) — the one validated edge.

Hard evidence (this repo, 391 events, 25 names, 4y daily): the sign of the EPS
surprise predicts ~+2.0% sign-aligned drift over the following 20 trading days
(t≈3.1 full sample; t≈2.1 on a strict temporal out-of-sample half). The
announcement-day *price* reaction has NO drift (t≈0) — the edge is in the
*fundamental* surprise. Because earnings are quarterly, turnover is tiny, so the
transaction costs that sink intraday strategies are negligible here.

This module is deliberately simple and pure (BarSet + surprises in, signals out)
so it backtests and runs live through the same code — and so the edge stays
auditable. Direction: long a positive surprise, short a negative one; hold
``hold_days`` trading days.
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
) -> list[PeadSignal]:
    """Generate PEAD signals from daily ``bars`` + reported ``surprises``.

    Causal: each trade enters at the close of the first session on/after the
    announcement and exits ``hold_days`` sessions later. ``min_abs_sue`` gates on
    standardized surprise (the stronger, scale-free signal). Events whose exit is
    beyond the available bars are returned ``is_open`` (actionable now), never
    fabricated.
    """
    df = bars.df.sort("ts")
    ts = [t.date() for t in df["ts"].to_list()]
    close = df["close"].to_list()
    if not ts:
        return []
    idx = {d: i for i, d in enumerate(ts)}

    out: list[PeadSignal] = []
    priors: list[float] = []  # past surprises for this symbol (for SUE), causal
    for ev in sorted(surprises, key=lambda e: e.date):
        sue = _sue(ev.surprise, priors)
        priors.append(ev.surprise)
        if abs(ev.surprise) < min_abs_surprise or ev.surprise == 0.0:
            continue
        if abs(sue) < min_abs_sue:
            continue
        d0 = next(
            (idx[ev.date + timedelta(days=o)] for o in range(_ANNOUNCE_SEARCH_DAYS)
             if ev.date + timedelta(days=o) in idx),
            None,
        )
        if d0 is None:
            continue
        side = "buy" if ev.surprise > 0 else "sell"
        entry = float(close[d0])
        exit_idx = d0 + hold_days
        if exit_idx < len(close):
            exit_px = float(close[exit_idx])
            raw = exit_px / entry - 1.0
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


def pead_stats(signals: list[PeadSignal]) -> PeadStats:
    """Aggregate realized (closed) PEAD trades into honest edge statistics."""
    rets = [s.trade_return for s in signals if s.trade_return is not None]
    n = len(rets)
    if n == 0:
        return PeadStats(0, 0.0, 0.0, 0.0, 0.0)
    mean = sum(rets) / n
    if n > 1:
        sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / (n - 1))
        t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
    else:
        t = 0.0
    hit = sum(1 for x in rets if x > 0) / n
    return PeadStats(n=n, mean_return=mean, t_stat=t, hit_rate=hit, total_return=sum(rets))


def open_signals(signals: list[PeadSignal], *, now: datetime | None = None) -> list[PeadSignal]:
    """The currently-actionable trades: announced, still inside the drift window."""
    return [s for s in signals if s.is_open]
