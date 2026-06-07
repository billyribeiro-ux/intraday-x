"""Earnings catalyst enrichment — names the culprit, clears 'uncertain'."""

from __future__ import annotations

from datetime import UTC, date, datetime

from intradayx.attribution.catalysts import enrich_with_earnings, is_near_earnings
from intradayx.domain.signals import (
    CauseKind,
    Side,
    Signal,
    SignalKind,
    uncertain_attribution,
)


def _signal(day: int) -> Signal:
    return Signal.create(
        symbol="AAPL",
        ts=datetime(2024, 5, day, 16, 0, tzinfo=UTC),
        kind=SignalKind.REVERSAL_TOP,
        side=Side.SELL,
        confidence=0.3,
        entry=100.0,
        stop=101.0,
        targets=(98.0,),
        time_of_day_bucket="afternoon",
        attribution=uncertain_attribution(0.5),
    )


def test_is_near_earnings_window() -> None:
    edates = {date(2024, 5, 2)}
    assert is_near_earnings(date(2024, 5, 3), edates, 1) == date(2024, 5, 2)  # +1 day
    assert is_near_earnings(date(2024, 5, 5), edates, 1) is None  # outside window


def test_enrich_adds_earnings_cause_and_clears_uncertain() -> None:
    earnings = [date(2024, 5, 2)]
    near = _signal(3)  # 1 day after earnings → enriched
    far = _signal(20)  # nowhere near → untouched
    out = enrich_with_earnings([near, far], earnings, window_days=1)

    enriched, untouched = out[0], out[1]
    assert enriched.attribution.primary_cause is not None
    assert enriched.attribution.primary_cause.kind is CauseKind.EARNINGS
    assert enriched.attribution.uncertain is False
    # The far signal is unchanged (still the uncertain attribution).
    assert untouched.attribution.uncertain is True


def test_no_earnings_dates_is_noop() -> None:
    sig = _signal(3)
    assert enrich_with_earnings([sig], []) == [sig]
