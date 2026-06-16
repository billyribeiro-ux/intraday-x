"""FMP provider: honest capabilities, key-gating, and factory/registry wiring (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intradayx.data.factory import default_provider
from intradayx.data.provider import MissingCredentialsError
from intradayx.data.providers.fmp_provider import FMPProvider
from intradayx.data.registry import registered_names
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability


def test_fmp_capabilities_are_honest() -> None:
    caps = FMPProvider(api_key=None).capabilities()
    assert caps.supports(Capability.DAILY_BARS)
    assert caps.supports(Capability.EXTENDED_HISTORY_INTRADAY)
    # internals/options aren't wired yet → not advertised (no fabrication).
    assert not caps.supports(Capability.INTERNALS_TICK)
    assert not caps.supports(Capability.OPTIONS_CHAIN_HISTORY)


def test_fmp_is_registered() -> None:
    assert "fmp" in registered_names()


def test_fmp_bars_without_key_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    p = FMPProvider(api_key=None)
    now = datetime.now(tz=UTC)
    with pytest.raises(MissingCredentialsError):
        p.bars("AAPL", now, now, Timeframe.M5)


def test_factory_uses_fmp_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only FMP keyed → it must appear in the composite ahead of the yfinance floor.
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.setenv("FMP_API_KEY", "dummy")
    names = [pr.name for pr in default_provider()._providers]
    assert "fmp" in names
    assert names.index("fmp") < names.index("yfinance")


def test_factory_skips_fmp_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    names = [pr.name for pr in default_provider()._providers]
    assert "fmp" not in names
