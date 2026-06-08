"""Capability-gated squeeze detectors (Phases 8 & 9).

These need data a price/volume-only vendor doesn't have, so today they return
:meth:`DetectedEvent.insufficient` — never a guess. When SHORT_*/OPTIONS_* caps
become available, the real logic activates here with no change to callers.
"""

from __future__ import annotations

from datetime import datetime

from intradayx.domain.capabilities import OPTIONS_FULL, SHORT_FULL, ProviderCapabilities
from intradayx.domain.events import DetectedEvent
from intradayx.domain.signals import CauseKind


def short_squeeze_event(caps: ProviderCapabilities, ts: datetime) -> DetectedEvent:
    if not caps.supports_all(SHORT_FULL):
        return DetectedEvent.insufficient(
            CauseKind.SHORT_SQUEEZE,
            ts,
            "no short-interest / borrow-rate feed (FINRA is biweekly & lagged)",
        )
    # Phase 8: days-to-cover + borrow-fee spike + price/volume signature.
    raise NotImplementedError("short-squeeze detection activates with SHORT_* capabilities")


def gamma_squeeze_event(caps: ProviderCapabilities, ts: datetime) -> DetectedEvent:
    if not caps.supports_all(OPTIONS_FULL):
        return DetectedEvent.insufficient(
            CauseKind.GAMMA_SQUEEZE,
            ts,
            "no options-chain history / greeks; GEX cannot be computed",
        )
    # Phase 9: dealer GEX sign/magnitude, gamma flip, strike pinning.
    raise NotImplementedError("gamma-squeeze detection activates with OPTIONS_* capabilities")
