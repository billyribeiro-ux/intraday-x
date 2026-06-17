"""Polygon provider: honest capabilities and key-gating (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intradayx.config import get_settings
from intradayx.data.factory import default_provider
from intradayx.data.provider import MissingCredentialsError
from intradayx.data.providers.polygon_provider import PolygonProvider
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability


def test_polygon_capabilities_are_honest() -> None:
    caps = PolygonProvider(api_key=None).capabilities()
    assert caps.supports(Capability.EXTENDED_HISTORY_INTRADAY)
    # internals/options aren't wired yet → not advertised (no fabrication).
    assert not caps.supports(Capability.INTERNALS_TICK)
    assert not caps.supports(Capability.OPTIONS_CHAIN_HISTORY)


def test_polygon_bars_without_key_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    p = PolygonProvider(api_key=None)
    now = datetime.now(tz=UTC)
    with pytest.raises(MissingCredentialsError):
        p.bars("AAPL", now, now, Timeframe.M5)


def test_runtime_ignores_polygon_even_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("INTRADAYX_PROVIDERS", '["polygon"]')
    get_settings.cache_clear()
    with pytest.raises(MissingCredentialsError, match="FMP_API_KEY is required"):
        default_provider()


def test_runtime_requires_fmp_instead_of_polygon_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("INTRADAYX_PROVIDERS", '["polygon"]')
    get_settings.cache_clear()
    with pytest.raises(MissingCredentialsError, match="FMP_API_KEY is required"):
        default_provider()
