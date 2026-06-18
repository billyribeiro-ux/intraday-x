"""Read-through cache — serve bars from the local lake, fetch only when missing.

Wraps any provider: on a bars request it first reads the Parquet lake; if the
cached range covers the request it's served with no vendor call; otherwise it
fetches from the inner provider, upserts into the lake (idempotent), and serves.
Coverage is a coarse span check (cached spans [start, end]); gap-minimal fetching
is a later refinement. Internals/options/short/earnings calls pass through to the
inner provider unchanged.
"""

from __future__ import annotations

from datetime import date, datetime

from intradayx.data.provider import DataProvider, Session
from intradayx.domain.bars import BarSet, Timeframe
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.domain.catalysts import CatalystEvent
from intradayx.domain.internals import InternalsSeries, InternalSymbol
from intradayx.domain.options import OptionChain
from intradayx.domain.shorts import BorrowRate, ShortInterest, ShortVolume
from intradayx.storage.lake import Lake


class CachingProvider(DataProvider):
    """Lake-backed read-through cache around an inner provider."""

    def __init__(self, inner: DataProvider, lake: Lake) -> None:
        self.inner = inner
        self.lake = lake
        self.name = f"cache:{inner.name}"

    def capabilities(self) -> ProviderCapabilities:
        return self.inner.capabilities()

    def is_configured(self) -> bool:
        return self.inner.is_configured()

    @staticmethod
    def _covers(bs: BarSet, start: datetime, end: datetime) -> bool:
        if bs.is_empty() or bs.start is None or bs.end is None:
            return False
        return bs.start <= start and bs.end >= end

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
        cached = self.lake.read_bars(ticker.upper(), timeframe, start, end)
        if self._covers(cached, start, end):
            return cached
        fresh = self.inner.bars(
            ticker, start, end, timeframe, session=session, adjust=adjust, now=now
        )
        if fresh.is_empty():
            return cached  # honest: serve whatever (possibly empty) we had
        self.lake.write_bars(fresh)
        return self.lake.read_bars(ticker.upper(), timeframe, start, end)

    # --- pass-through (not cached in v1) ---

    def internals(
        self, symbol: InternalSymbol, start: datetime, end: datetime, timeframe: Timeframe
    ) -> InternalsSeries:
        return self.inner.internals(symbol, start, end, timeframe)

    def options_chain(self, underlying: str, asof: datetime | None = None) -> OptionChain:
        return self.inner.options_chain(underlying, asof)

    def short_interest(self, ticker: str, start: datetime, end: datetime) -> list[ShortInterest]:
        return self.inner.short_interest(ticker, start, end)

    def short_volume(self, ticker: str, start: datetime, end: datetime) -> list[ShortVolume]:
        return self.inner.short_volume(ticker, start, end)

    def borrow_rate(self, ticker: str, start: datetime, end: datetime) -> list[BorrowRate]:
        return self.inner.borrow_rate(ticker, start, end)

    def earnings_dates(self, ticker: str) -> list[date]:
        return self.inner.earnings_dates(ticker)

    def catalyst_events(
        self, ticker: str, start: datetime, end: datetime
    ) -> list[CatalystEvent]:
        return self.inner.catalyst_events(ticker, start, end)
