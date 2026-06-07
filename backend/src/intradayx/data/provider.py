"""The vendor-agnostic data provider contract.

Every concrete provider subclasses :class:`DataProvider`, declares its
:class:`~intradayx.domain.capabilities.ProviderCapabilities`, and implements
:meth:`DataProvider.bars`. Everything else (internals, options, shorts,
streaming) has a default implementation that raises
:class:`~intradayx.domain.capabilities.CapabilityError` — so a provider only
overrides what it genuinely supports, and the rest of the system can gate on
``capabilities()`` and degrade *honestly* rather than receive fabricated data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from enum import StrEnum

from intradayx.domain.bars import BarSet, Timeframe
from intradayx.domain.capabilities import (
    Capability,
    CapabilityError,
    ProviderCapabilities,
)
from intradayx.domain.internals import InternalsSeries, InternalSymbol
from intradayx.domain.options import OptionChain
from intradayx.domain.shorts import BorrowRate, ShortInterest, ShortVolume


class Session(StrEnum):
    """Which part of the trading day to fetch."""

    RTH = "rth"  # regular hours only
    ALL = "all"  # include pre/post market


class DataError(RuntimeError):
    """Base class for data-layer errors (distinct from CapabilityError)."""


class LookbackExceededError(DataError):
    """Requested start is older than the provider's max intraday lookback.

    Raised — never silently truncated — so a backtest can't quietly run on a
    shorter window than the caller asked for.
    """

    def __init__(self, provider: str, timeframe: Timeframe, requested: datetime, limit: datetime):
        super().__init__(
            f"{provider}: {timeframe.value} history only reaches back to {limit:%Y-%m-%d}; "
            f"requested start {requested:%Y-%m-%d} is too old."
        )


class MissingCredentialsError(DataError):
    """Provider needs API credentials that aren't configured."""


class DataProvider(ABC):
    """Abstract base for all market-data providers. Returns domain types only."""

    name: str = "abstract"

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declare what this provider supports and how deep its history reaches."""

    def is_configured(self) -> bool:
        """Whether this provider has the credentials it needs. Credential-free
        providers (e.g. yfinance) are always configured; the registry skips
        unconfigured vendors so a missing key silently drops the vendor rather
        than erroring on every request."""
        return True

    @abstractmethod
    def bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
        *,
        session: Session = Session.RTH,
        adjust: bool = True,
        now: datetime | None = None,
    ) -> BarSet:
        """Fetch OHLCV bars for ``ticker`` in ``[start, end]`` at ``timeframe``.

        ``now`` pins the lookback clock (for as-of replay); honored by the
        composite router and ignored by single vendors. Part of the contract so
        decorators (e.g. the cache) stay transparent.
        """

    # --- optional surfaces: default to raising CapabilityError ---

    def internals(
        self,
        symbol: InternalSymbol,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
    ) -> InternalsSeries:
        raise CapabilityError(self.name, Capability.INTERNALS_TICK)

    def options_chain(
        self, underlying: str, asof: datetime | None = None
    ) -> OptionChain:
        raise CapabilityError(self.name, Capability.OPTIONS_CHAIN_LIVE)

    def short_interest(self, ticker: str, start: datetime, end: datetime) -> list[ShortInterest]:
        raise CapabilityError(self.name, Capability.SHORT_INTEREST)

    def short_volume(self, ticker: str, start: datetime, end: datetime) -> list[ShortVolume]:
        raise CapabilityError(self.name, Capability.SHORT_VOLUME)

    def borrow_rate(self, ticker: str, start: datetime, end: datetime) -> list[BorrowRate]:
        raise CapabilityError(self.name, Capability.BORROW_RATE)

    def earnings_dates(self, ticker: str) -> list[date]:
        """Scheduled-earnings dates (past + upcoming), ascending. A named catalyst."""
        raise CapabilityError(self.name, Capability.EARNINGS_CALENDAR)

    # --- shared helpers ---

    def _check_lookback(self, start: datetime, timeframe: Timeframe, now: datetime) -> None:
        """Raise :class:`LookbackExceededError` if ``start`` is beyond the limit."""
        window = self.capabilities().lookback_for(timeframe)
        if window is None:
            return
        limit = now - window
        if start < limit:
            raise LookbackExceededError(self.name, timeframe, start, limit)
