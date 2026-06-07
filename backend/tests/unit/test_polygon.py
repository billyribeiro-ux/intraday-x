"""Polygon provider: honest capabilities, key-gating, and factory wiring (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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


def test_factory_prefers_polygon_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    names = [pr.name for pr in default_provider()._providers]
    assert names[0] == "polygon"  # priority 3 => first/preferred


def test_factory_skips_polygon_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    names = [pr.name for pr in default_provider()._providers]
    assert "polygon" not in names
