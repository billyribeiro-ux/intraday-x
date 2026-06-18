"""Catalyst attribution — name nearby external events without overstating cause.

FMP can provide scheduled earnings, stock news, press releases, and analyst
grade actions. We treat those as evidence items: strongest when close to the
signal timestamp, weaker as they drift away. This runs at the service/CLI layer
(it needs provider I/O), keeping ``SignalEngine.evaluate`` pure.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

from intradayx.domain.catalysts import CatalystEvent, CatalystKind
from intradayx.domain.signals import Attribution, Cause, CauseKind, CauseSource, Signal

EARNINGS_SCORE = 0.7  # a scheduled catalyst is a strong named cause
CATALYST_WINDOW_HOURS = 36.0

_KIND_TO_CAUSE: dict[CatalystKind, CauseKind] = {
    CatalystKind.EARNINGS: CauseKind.EARNINGS,
    CatalystKind.NEWS: CauseKind.NEWS,
    CatalystKind.PRESS_RELEASE: CauseKind.PRESS_RELEASE,
    CatalystKind.ANALYST_GRADE: CauseKind.ANALYST_ACTION,
    CatalystKind.PRICE_TARGET: CauseKind.PRICE_TARGET,
}


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


def _to_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _decayed_score(event_score: float, offset_hours: float, window_hours: float) -> float:
    distance = abs(offset_hours)
    if distance > window_hours:
        return 0.0
    # Keep a small residual for same-session catalyst context; otherwise a
    # perfectly real morning headline would disappear by the afternoon.
    proximity = max(0.2, 1.0 - distance / window_hours)
    return max(0.0, min(event_score * proximity, 1.0))


def nearest_catalysts(
    ts: datetime,
    events: list[CatalystEvent],
    *,
    window_hours: float = CATALYST_WINDOW_HOURS,
) -> list[tuple[CatalystEvent, float, float]]:
    """Rank catalyst events by proximity-adjusted score for a signal timestamp."""
    signal_ts = _to_utc(ts)
    ranked: list[tuple[CatalystEvent, float, float]] = []
    for event in events:
        offset_hours = (signal_ts - _to_utc(event.ts)).total_seconds() / 3600
        score = _decayed_score(event.score, offset_hours, window_hours)
        if score <= 0:
            continue
        ranked.append((event, offset_hours, score))
    return sorted(ranked, key=lambda x: x[2], reverse=True)


def _cause_from_event(event: CatalystEvent, offset_hours: float, score: float) -> Cause | None:
    cause_kind = _KIND_TO_CAUSE.get(event.kind)
    if cause_kind is None or score < 0.12:
        return None
    label_prefix = event.kind.value.replace("_", " ").title()
    return Cause(
        kind=cause_kind,
        score=score,
        source=CauseSource.RULE,
        label=f"{label_prefix}: {event.title}",
        evidence={
            "catalyst_offset_hours": offset_hours,
            "catalyst_score": event.score,
        },
    )


def enrich_with_catalysts(
    signals: list[Signal],
    events: list[CatalystEvent],
    *,
    window_hours: float = CATALYST_WINDOW_HOURS,
    max_causes: int = 2,
) -> list[Signal]:
    """Add FMP catalyst causes to signals near timestamped events.

    Measured price/volume/internal causes keep their rank when stronger. A named
    catalyst only clears ``uncertain`` when it replaces the UNEXPLAINED fallback.
    """
    if not events:
        return signals
    out: list[Signal] = []
    for signal in signals:
        matches = nearest_catalysts(signal.ts, events, window_hours=window_hours)
        causes: list[Cause] = []
        for event, offset_hours, score in matches[:max_causes]:
            cause = _cause_from_event(event, offset_hours, score)
            if cause is not None:
                causes.append(cause)
        if not causes:
            out.append(signal)
            continue
        attribution = signal.attribution
        real = tuple(
            cause
            for cause in attribution.ranked_causes
            if cause.kind is not CauseKind.UNEXPLAINED
        )
        merged = tuple(sorted((*causes, *real), key=lambda c: c.score, reverse=True))
        enriched = Attribution(
            ranked_causes=merged,
            data_completeness=attribution.data_completeness,
            uncertain=attribution.uncertain if real else False,
            caveat=(
                attribution.caveat
                if real
                else "Coincides with named FMP catalyst evidence — proximity is not "
                "proof of causation; verify the event before trading."
            ),
        )
        out.append(replace(signal, attribution=enriched))
    return out


def catalyst_events_from_earnings_dates(earnings_dates: list[date]) -> list[CatalystEvent]:
    """Compatibility helper for providers that still expose only dates."""
    return [
        CatalystEvent.create(
            kind=CatalystKind.EARNINGS,
            ts=datetime.combine(d, time(12, 0), tzinfo=UTC),
            title=f"Scheduled earnings ({d.isoformat()})",
            score=EARNINGS_SCORE,
            evidence={"earnings_date": d.isoformat()},
        )
        for d in earnings_dates
    ]
