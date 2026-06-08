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
    """Return the NEAREST earnings date within `window_days` of `d`, or None.

    Scans by increasing |offset| (0, ±1, ±2, …) so an exact-day match wins and the
    closest event is chosen when several are nearby — not the earliest in the window.
    """
    for off in range(window_days + 1):
        for candidate in (d + timedelta(days=off), d - timedelta(days=off)):
            if candidate in earnings_dates:
                return candidate
    return None


def enrich_with_earnings(
    signals: list[Signal],
    earnings_dates: list[date],
    *,
    window_days: int = 1,
) -> list[Signal]:
    """Add an EARNINGS cause to signals whose session lands near an earnings date.

    Inserts BY SCORE (a stronger measured cause keeps the primary slot) rather than
    blindly prepending, and only clears ``uncertain`` when earnings is the sole
    explanation — earnings proximity is a calendar coincidence, not proven causation.
    """
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
            evidence={"earnings_offset_days": float((s.ts.date() - hit).days)},
        )
        a = s.attribution
        # Drop the "unexplained" placeholder if present; insert earnings by score.
        real = tuple(c for c in a.ranked_causes if c.kind is not CauseKind.UNEXPLAINED)
        merged = tuple(sorted((cause, *real), key=lambda c: c.score, reverse=True))
        enriched = Attribution(
            ranked_causes=merged,
            data_completeness=a.data_completeness,
            # Earnings names the catalyst only when nothing measured explained the move;
            # never override a confident measured attribution.
            uncertain=a.uncertain if real else False,
            caveat=(
                a.caveat
                if real
                else "Coincides with scheduled earnings — a calendar coincidence, not "
                "confirmed causation; verify before trading."
            ),
        )
        out.append(replace(s, attribution=enriched))
    return out
