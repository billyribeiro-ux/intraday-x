"""Catalyst attribution — name the culprit when it's a scheduled event.

Earnings are the one catalyst we can name for free (yfinance exposes the dates).
When a signal lands within `window_days` of an earnings date we add an EARNINGS
cause to its attribution — turning "cause uncertain" into a named reason. This
runs at the service/CLI layer (it needs provider I/O), keeping
``SignalEngine.evaluate`` pure.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from intradayx.domain.signals import Attribution, Cause, CauseKind, CauseSource, Signal

EARNINGS_SCORE = 0.7  # a scheduled catalyst is a strong named cause


def is_near_earnings(d: date, earnings_dates: set[date], window_days: int) -> date | None:
    """Return the earnings date within `window_days` of `d`, or None."""
    for offset in range(-window_days, window_days + 1):
        candidate = d + timedelta(days=offset)
        if candidate in earnings_dates:
            return candidate
    return None


def enrich_with_earnings(
    signals: list[Signal],
    earnings_dates: list[date],
    *,
    window_days: int = 1,
) -> list[Signal]:
    """Prepend an EARNINGS cause to signals whose session lands near an earnings date."""
    if not earnings_dates:
        return signals
    edates = set(earnings_dates)
    out: list[Signal] = []
    for s in signals:
        hit = is_near_earnings(s.ts.date(), edates, window_days)
        if hit is None:
            out.append(s)
            continue
        cause = Cause(
            kind=CauseKind.EARNINGS,
            score=EARNINGS_SCORE,
            source=CauseSource.RULE,
            label=f"Coincides with scheduled earnings ({hit.isoformat()})",
            evidence={"earnings_offset_days": (s.ts.date() - hit).days},
        )
        a = s.attribution
        enriched = Attribution(
            ranked_causes=(cause, *a.ranked_causes),
            data_completeness=a.data_completeness,
            uncertain=False,  # we now have a named catalyst
            caveat=a.caveat,
        )
        out.append(replace(s, attribution=enriched))
    return out
