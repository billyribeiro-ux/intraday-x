"""Capability gating, honest errors, and composite routing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intradayx.data.composite import CompositeProvider, required_capability
from intradayx.data.providers.twelvedata_provider import TwelveDataProvider
from intradayx.data.providers.yfinance_provider import YFinanceProvider
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability, CapabilityError
from intradayx.domain.internals import InternalSymbol
from intradayx.features.pipeline import data_completeness_for


def test_yfinance_declares_no_internals() -> None:
    caps = YFinanceProvider().capabilities()
    assert caps.supports(Capability.INTRADAY_BARS_1M)
    assert not caps.supports(Capability.INTERNALS_TICK)


def test_internals_raise_capability_error_not_empty() -> None:
    p = YFinanceProvider()
    now = datetime.now(tz=UTC)
    with pytest.raises(CapabilityError):
        p.internals(InternalSymbol.TICK, now, now, Timeframe.M1)


def test_required_capability_mapping() -> None:
    assert required_capability(Timeframe.D1) is Capability.DAILY_BARS
    assert required_capability(Timeframe.M1) is Capability.INTRADAY_BARS_1M
    assert required_capability(Timeframe.M5) is Capability.INTRADAY_BARS_5M


def test_composite_union_and_deep_lookback() -> None:
    comp = CompositeProvider([(YFinanceProvider(), 10), (TwelveDataProvider(), 5)])
    caps = comp.capabilities()
    # Union exposes Twelve Data's extended history...
    assert caps.supports(Capability.EXTENDED_HISTORY_INTRADAY)
    # ...and the merged 1m lookback is the deeper of the two (Twelve Data's).
    lb = caps.lookback_for(Timeframe.M1)
    assert lb is not None and lb.days > 1000


def test_data_completeness_price_volume_only_is_half() -> None:
    assert data_completeness_for(YFinanceProvider().capabilities()) == 0.5
