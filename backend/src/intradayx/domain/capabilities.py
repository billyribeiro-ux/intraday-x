"""The capability system — the linchpin of honest, vendor-agnostic data access.

Every :class:`~intradayx.data.provider.DataProvider` declares which
:class:`Capability` values it supports. Features and detectors that need a
capability the active provider lacks stay *dormant* instead of fabricating data,
and the absence lowers a signal's ``data_completeness`` (surfaced in the UI/PDF).
When a capable vendor is added later, the gated code activates with no rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from intradayx.domain.bars import Timeframe


class Capability(StrEnum):
    """A unit of data a provider may or may not supply."""

    # --- bars ---
    DAILY_BARS = "daily_bars"
    INTRADAY_BARS_1M = "intraday_bars_1m"
    INTRADAY_BARS_5M = "intraday_bars_5m"
    EXTENDED_HISTORY_INTRADAY = "extended_history_intraday"  # multi-year intraday
    PREPOST_MARKET = "prepost_market"
    LIVE_STREAM = "live_stream"  # true push; absent => poll-only

    # --- market internals (breadth + volatility) ---
    INTERNALS_TICK = "internals_tick"  # $TICK
    INTERNALS_TRIN = "internals_trin"  # $TRIN / Arms
    INTERNALS_ADD = "internals_add"  # $ADD advance-decline
    INTERNALS_VOLD = "internals_vold"  # $UVOL/$DVOL/$VOLD volume breadth
    INTERNALS_VIX = "internals_vix"  # VIX spot
    INTERNALS_VIX_TERM = "internals_vix_term"  # VIX9D/VIX3M/VVIX term structure
    INTERNALS_SKEW = "internals_skew"  # CBOE SKEW
    INTERNALS_PUTCALL = "internals_putcall"  # put/call ratios

    # --- options (for gamma / GEX) ---
    OPTIONS_CHAIN_LIVE = "options_chain_live"
    OPTIONS_CHAIN_HISTORY = "options_chain_history"
    OPTIONS_GREEKS = "options_greeks"

    # --- short data (for short-squeeze) ---
    SHORT_INTEREST = "short_interest"
    SHORT_VOLUME = "short_volume"
    BORROW_RATE = "borrow_rate"


# Convenience groupings used by feature/detector gating.
INTERNALS_BREADTH: frozenset[Capability] = frozenset(
    {
        Capability.INTERNALS_TICK,
        Capability.INTERNALS_TRIN,
        Capability.INTERNALS_ADD,
        Capability.INTERNALS_VOLD,
    }
)
INTERNALS_VOLATILITY: frozenset[Capability] = frozenset(
    {
        Capability.INTERNALS_VIX,
        Capability.INTERNALS_VIX_TERM,
        Capability.INTERNALS_SKEW,
        Capability.INTERNALS_PUTCALL,
    }
)
OPTIONS_FULL: frozenset[Capability] = frozenset(
    {
        Capability.OPTIONS_CHAIN_HISTORY,
        Capability.OPTIONS_GREEKS,
    }
)
SHORT_FULL: frozenset[Capability] = frozenset(
    {
        Capability.SHORT_INTEREST,
        Capability.SHORT_VOLUME,
        Capability.BORROW_RATE,
    }
)


class CapabilityError(RuntimeError):
    """Raised when a provider is asked for a capability it does not support.

    Callers MUST gate on :meth:`ProviderCapabilities.supports` first. Raising
    (rather than returning empty) keeps degradation explicit — a missing
    internal can never be silently misread as "no extreme".
    """

    def __init__(self, provider: str, capability: Capability) -> None:
        super().__init__(f"provider {provider!r} does not support capability {capability.value!r}")
        self.provider = provider
        self.capability = capability


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What a provider can do, and how deep its intraday history reaches."""

    provider_name: str
    supported: frozenset[Capability]
    # Per-timeframe maximum lookback window (e.g. yfinance 1m ≈ 7 days).
    max_intraday_lookback: dict[Timeframe, timedelta] = field(default_factory=dict)
    rate_limit_hint: str | None = None

    def supports(self, capability: Capability) -> bool:
        return capability in self.supported

    def supports_all(self, capabilities: frozenset[Capability]) -> bool:
        return capabilities <= self.supported

    def require(self, capability: Capability) -> None:
        """Raise :class:`CapabilityError` unless ``capability`` is supported."""
        if not self.supports(capability):
            raise CapabilityError(self.provider_name, capability)

    def lookback_for(self, timeframe: Timeframe) -> timedelta | None:
        return self.max_intraday_lookback.get(timeframe)
