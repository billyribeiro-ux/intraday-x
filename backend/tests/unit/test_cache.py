"""Read-through cache: second identical request is served from the lake."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from intradayx.data.cache import CachingProvider
from intradayx.data.provider import DataProvider, Session
from intradayx.data.providers.yfinance_provider import YFinanceProvider
from intradayx.domain.bars import BarSet, Timeframe
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.storage.lake import Lake
from tests.fixtures.synthetic import make_bars


class _CountingProvider(DataProvider):
    name = "fake"

    def __init__(self, bars: BarSet) -> None:
        self._bars = bars
        self.calls = 0

    def capabilities(self) -> ProviderCapabilities:
        return YFinanceProvider().capabilities()

    def bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
        *,
        session: Session = Session.RTH,
        adjust: bool = True,
    ) -> BarSet:
        self.calls += 1
        return self._bars


def test_second_request_is_served_from_cache(tmp_path: Path) -> None:
    bars = make_bars(closes=[100.0, 101.0, 102.0, 103.0], timeframe=Timeframe.M5)
    start, end = bars.start, bars.end
    assert start is not None and end is not None

    fake = _CountingProvider(bars)
    cp = CachingProvider(fake, Lake(tmp_path))

    r1 = cp.bars("TEST", start, end, Timeframe.M5)
    assert fake.calls == 1 and len(r1) == 4  # cold: hit the inner provider, wrote the lake

    r2 = cp.bars("TEST", start, end, Timeframe.M5)
    assert fake.calls == 1 and len(r2) == 4  # warm: served from lake, no vendor call


def test_cache_passes_through_capabilities(tmp_path: Path) -> None:
    bars = make_bars(closes=[100.0], timeframe=Timeframe.M5)
    cp = CachingProvider(_CountingProvider(bars), Lake(tmp_path))
    assert cp.capabilities().provider_name == "yfinance"  # delegates to inner
    assert cp.name == "cache:fake"
