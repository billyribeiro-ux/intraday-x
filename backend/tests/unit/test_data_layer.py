"""Provider contract + registry/config tests (no network).

The contract suite runs EVERY provider through the interface invariants, so a new
vendor can't ship a subtly-wrong adapter. The registry tests prove the data layer
is assembled from config and skips unconfigured vendors.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intradayx.config import Settings
from intradayx.data.provider import CapabilityError, DataProvider
from intradayx.data.providers.alpaca_provider import AlpacaProvider
from intradayx.data.providers.polygon_provider import PolygonProvider
from intradayx.data.providers.yfinance_provider import YFinanceProvider
from intradayx.data.registry import build_provider, registered_names
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability, ProviderCapabilities
from intradayx.domain.internals import InternalSymbol

PROVIDER_CLASSES: list[type[DataProvider]] = [
    YFinanceProvider,
    AlpacaProvider,
    PolygonProvider,
]


# ---------- contract: every provider must obey these ----------


@pytest.mark.parametrize("cls", PROVIDER_CLASSES)
def test_capabilities_well_formed(cls: type[DataProvider]) -> None:
    p = cls()
    caps = p.capabilities()
    assert isinstance(caps, ProviderCapabilities)
    assert caps.provider_name == p.name
    assert len(caps.supported) > 0


@pytest.mark.parametrize("cls", PROVIDER_CLASSES)
def test_is_configured_is_bool(cls: type[DataProvider]) -> None:
    assert isinstance(cls().is_configured(), bool)


@pytest.mark.parametrize("cls", PROVIDER_CLASSES)
def test_unsupported_surfaces_raise_not_empty(cls: type[DataProvider]) -> None:
    """An unsupported optional surface MUST raise CapabilityError, never return
    a misleading empty result."""
    p = cls()
    caps = p.capabilities()
    now = datetime.now(tz=UTC)
    if not caps.supports(Capability.SHORT_INTEREST):
        with pytest.raises(CapabilityError):
            p.short_interest("AAPL", now, now)
    if not caps.supports(Capability.INTERNALS_TICK):
        with pytest.raises(CapabilityError):
            p.internals(InternalSymbol.TICK, now, now, Timeframe.M1)
    if not caps.supports(Capability.OPTIONS_CHAIN_LIVE):
        with pytest.raises(CapabilityError):
            p.options_chain("AAPL")


# ---------- registry / config-driven assembly ----------


def test_builtin_providers_registered() -> None:
    names = registered_names()
    assert {"yfinance", "alpaca", "polygon"} <= set(names)


def test_build_provider_from_config() -> None:
    comp = build_provider(Settings(providers=["yfinance"]))
    assert [p.name for p in comp._providers] == ["yfinance"]


def test_unknown_provider_falls_back_to_yfinance() -> None:
    comp = build_provider(Settings(providers=["does-not-exist"]))
    assert [p.name for p in comp._providers] == ["yfinance"]


def test_unconfigured_vendor_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    comp = build_provider(Settings(providers=["polygon", "alpaca", "yfinance"]))
    # No creds → polygon + alpaca skipped → only yfinance remains.
    assert [p.name for p in comp._providers] == ["yfinance"]
