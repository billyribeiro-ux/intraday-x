"""Named FMP-sourced catalysts that may explain a market move.

These are evidence items, not proof of causation. They become stronger when they
land close to a bar/signal and weaker as they drift away in time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CatalystKind(StrEnum):
    EARNINGS = "earnings"
    NEWS = "news"
    PRESS_RELEASE = "press_release"
    ANALYST_GRADE = "analyst_grade"
    PRICE_TARGET = "price_target"
    SECTOR = "sector"
    INDUSTRY = "industry"


@dataclass(frozen=True, slots=True)
class CatalystEvent:
    kind: CatalystKind
    ts: datetime
    title: str
    source: str
    score: float
    url: str | None = None
    evidence: dict[str, float | str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        kind: CatalystKind,
        ts: datetime,
        title: str,
        source: str = "fmp",
        score: float,
        url: str | None = None,
        evidence: dict[str, float | str] | None = None,
    ) -> CatalystEvent:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return cls(
            kind=kind,
            ts=ts.astimezone(UTC),
            title=title.strip() or kind.value.replace("_", " ").title(),
            source=source,
            score=max(0.0, min(float(score), 1.0)),
            url=url,
            evidence=evidence or {},
        )


def parse_fmp_datetime(value: Any) -> datetime | None:
    """Parse common FMP date/datetime fields as UTC-aware datetimes."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[:19] if "T" in text else text, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(UTC)
    except ValueError:
        return None
