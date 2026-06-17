"""Provider contract + registry/config tests (no network).

The contract suite runs EVERY importable provider through the interface
invariants, so a new vendor can't ship a subtly-wrong adapter. The registry tests
prove runtime data assembly is locked to FMP.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intradayx.config import Settings
from intradayx.data.provider import CapabilityError, DataProvider, MissingCredentialsError
from intradayx.data.providers.fmp_provider import FMPProvider
from intradayx.data.providers.polygon_provider import PolygonProvider
from intradayx.data.providers.twelvedata_provider import TwelveDataProvider
from intradayx.data.providers.yfinance_provider import YFinanceProvider
from intradayx.data.registry import build_provider, registered_names
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability, ProviderCapabilities
from intradayx.domain.internals import InternalSymbol

PROVIDER_CLASSES: list[type[DataProvider]] = [
    FMPProvider,
    YFinanceProvider,
    PolygonProvider,
    TwelveDataProvider,
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
    assert {"fmp", "yfinance", "twelvedata", "polygon"} <= set(names)
    assert "alpaca" not in names  # no brokers — data vendors only


def test_build_provider_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FMP_API_KEY", "dummy")
    provider = build_provider(Settings(providers=["fmp"]))
    assert provider.name == "fmp"


def test_unknown_provider_does_not_fallback() -> None:
    with pytest.raises(MissingCredentialsError, match="FMP_API_KEY is required"):
        build_provider(Settings(providers=["does-not-exist"]))


def test_non_fmp_vendors_are_ignored_even_when_keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    monkeypatch.setenv("TWELVEDATA_API_KEY", "dummy")
    with pytest.raises(MissingCredentialsError, match="FMP_API_KEY is required"):
        build_provider(Settings(providers=["polygon", "twelvedata", "yfinance"]))
