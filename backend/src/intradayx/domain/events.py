"""Detected-event type produced by the deterministic attribution detectors.

A detector inspects the causal feature row at a bar and returns zero or more
:class:`DetectedEvent` objects — each a grounded, explainable candidate cause
with the evidence behind it. A detector that lacks the data it needs returns an
:meth:`DetectedEvent.insufficient` marker rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from intradayx.domain.signals import CauseKind


@dataclass(frozen=True, slots=True)
class DetectedEvent:
    """One candidate cause flagged by a detector at a point in time."""

    kind: CauseKind
    ts: datetime
    strength: float  # 0–1
    evidence: dict[str, float] = field(default_factory=dict)
    sufficient_data: bool = True
    note: str = ""

    @classmethod
    def insufficient(cls, kind: CauseKind, ts: datetime, note: str) -> DetectedEvent:
        """A detector firing 'insufficient data' — counted as dormant, never a guess."""
        return cls(kind=kind, ts=ts, strength=0.0, sufficient_data=False, note=note)
