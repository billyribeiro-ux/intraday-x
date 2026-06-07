"""CompositeProvider — routes each request to the best available vendor.

Providers are registered with a priority (lower = preferred). For a bars
request the composite picks the highest-priority provider that (a) supports the
timeframe's capability and (b) can reach back far enough, then falls through to
the next on capability/lookback/empty. This is what makes "add a vendor later"
free: a deep-history 1m request automatically routes to Alpaca over yfinance,
and internals/options route to whichever vendor declares them.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import polars as pl

from intradayx.data.provider import DataError, DataProvider, LookbackExceededError, Session
from intradayx.domain.bars import BAR_SCHEMA, BarSet, Timeframe
from intradayx.domain.capabilities import (
    Capability,
    CapabilityError,
    ProviderCapabilities,
)
from intradayx.domain.internals import InternalsSeries, InternalSymbol
from intradayx.domain.options import OptionChain
from intradayx.domain.shorts import BorrowRate, ShortInterest, ShortVolume

logger = logging.getLogger(__name__)


def required_capability(timeframe: Timeframe) -> Capability:
    """The capability a provider needs to serve bars at ``timeframe``."""
    if timeframe == Timeframe.D1:
        return Capability.DAILY_BARS
    if timeframe == Timeframe.M1:
        return Capability.INTRADAY_BARS_1M
    return Capability.INTRADAY_BARS_5M


def _empty_barset(ticker: str, timeframe: Timeframe) -> BarSet:
    return BarSet(ticker, timeframe, pl.DataFrame(schema=BAR_SCHEMA))


class CompositeProvider(DataProvider):
    name = "composite"

    def __init__(self, providers: list[tuple[DataProvider, int]]) -> None:
        if not providers:
            raise ValueError("CompositeProvider needs at least one provider")
        # Sort by priority (ascending = preferred first).
        self._providers = [p for p, _ in sorted(providers, key=lambda x: x[1])]

    def capabilities(self) -> ProviderCapabilities:
        supported: set[Capability] = set()
        lookback: dict[Timeframe, timedelta] = {}
        for prov in self._providers:
            caps = prov.capabilities()
            supported |= caps.supported
            for tf, window in caps.max_intraday_lookback.items():
                cur = lookback.get(tf)
                if cur is None or window > cur:
                    lookback[tf] = window
        return ProviderCapabilities(
            provider_name=self.name,
            supported=frozenset(supported),
            max_intraday_lookback=lookback,
        )

    def _providers_for(self, capability: Capability) -> list[DataProvider]:
        return [p for p in self._providers if p.capabilities().supports(capability)]

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
        cap = required_capability(timeframe)
        now = now or datetime.now(tz=UTC)
        attempted = False
        for prov in self._providers_for(cap):
            window = prov.capabilities().lookback_for(timeframe)
            if timeframe.is_intraday and window is not None and start < now - window:
                continue  # this vendor can't reach that far back; try the next
            attempted = True
            try:
                bs = prov.bars(ticker, start, end, timeframe, session=session, adjust=adjust)
            except (CapabilityError, LookbackExceededError, DataError):
                continue
            if not bs.is_empty():
                logger.debug(
                    "bars %s %s [%s..%s] served by %s (%d rows)",
                    ticker,
                    timeframe.value,
                    start.date(),
                    end.date(),
                    prov.name,
                    len(bs),
                )
                return bs
        if not attempted:
            raise DataError(
                f"no registered provider can serve {timeframe.value} bars for {ticker} "
                f"from {start:%Y-%m-%d} (need capability {cap.value!r} within lookback)"
            )
        # Every capable provider returned empty — honest empty, not an error.
        return _empty_barset(ticker, timeframe)

    def internals(
        self,
        symbol: InternalSymbol,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
    ) -> InternalsSeries:
        for prov in self._providers:
            try:
                return prov.internals(symbol, start, end, timeframe)
            except CapabilityError:
                continue
        raise CapabilityError(self.name, Capability.INTERNALS_TICK)

    def options_chain(self, underlying: str, asof: datetime | None = None) -> OptionChain:
        for prov in self._providers:
            try:
                return prov.options_chain(underlying, asof)
            except CapabilityError:
                continue
        raise CapabilityError(self.name, Capability.OPTIONS_CHAIN_LIVE)

    def short_interest(self, ticker: str, start: datetime, end: datetime) -> list[ShortInterest]:
        for prov in self._providers:
            try:
                return prov.short_interest(ticker, start, end)
            except CapabilityError:
                continue
        raise CapabilityError(self.name, Capability.SHORT_INTEREST)

    def short_volume(self, ticker: str, start: datetime, end: datetime) -> list[ShortVolume]:
        for prov in self._providers:
            try:
                return prov.short_volume(ticker, start, end)
            except CapabilityError:
                continue
        raise CapabilityError(self.name, Capability.SHORT_VOLUME)

    def borrow_rate(self, ticker: str, start: datetime, end: datetime) -> list[BorrowRate]:
        for prov in self._providers:
            try:
                return prov.borrow_rate(ticker, start, end)
            except CapabilityError:
                continue
        raise CapabilityError(self.name, Capability.BORROW_RATE)

    def earnings_dates(self, ticker: str) -> list[date]:
        for prov in self._providers:
            try:
                return prov.earnings_dates(ticker)
            except CapabilityError:
                continue
        raise CapabilityError(self.name, Capability.EARNINGS_CALENDAR)
