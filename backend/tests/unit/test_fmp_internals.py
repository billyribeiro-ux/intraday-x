"""FMP market-internals (VIX family) + its lift to data_completeness.

FMP serves the CBOE volatility family (VIX/VIX9D/VIX3M/VVIX) as index symbols;
breadth/SKEW/put-call are not available and must raise (honest degradation, no
fabrication). Wiring the VIX family lifts data_completeness 0.50 -> 0.65.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from intradayx.data.providers.fmp_provider import FMPProvider
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability, CapabilityError
from intradayx.domain.internals import InternalSymbol
from intradayx.features.pipeline import data_completeness_for


def test_fmp_declares_vix_capabilities() -> None:
    caps = FMPProvider(api_key=None).capabilities()
    assert caps.supports(Capability.INTERNALS_VIX)
    assert caps.supports(Capability.INTERNALS_VIX_TERM)
    # Honest: breadth / skew / put-call are NOT served by FMP, so not advertised.
    assert not caps.supports(Capability.INTERNALS_TICK)
    assert not caps.supports(Capability.INTERNALS_SKEW)


def test_data_completeness_lifted_to_065_with_vix() -> None:
    caps = FMPProvider(api_key=None).capabilities()
    # 0.5 base + 0.15 volatility internals; no breadth/options/shorts on FMP.
    assert data_completeness_for(caps) == pytest.approx(0.65)


def test_internals_vix_returns_series(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FMPProvider(api_key="test")

    def fake_request(path: str, params: dict[str, str]) -> Any:
        assert path == "historical-chart/5min"
        assert params["symbol"] == "^VIX"  # mapped from $VIX
        return [
            {"date": "2026-06-26 15:55:00", "open": 18.3, "high": 18.6, "low": 18.2, "close": 18.5},
            {"date": "2026-06-26 15:50:00", "open": 18.1, "high": 18.4, "low": 18.0, "close": 18.3},
        ]

    monkeypatch.setattr(provider, "_request", fake_request)
    series = provider.internals(
        InternalSymbol.VIX,
        datetime(2026, 6, 25, tzinfo=UTC),
        datetime(2026, 6, 26, tzinfo=UTC),
        Timeframe.M5,
    )
    assert len(series) == 2
    # newest-first input is sorted ascending; value is the index close.
    assert series.df["value"].to_list() == [18.3, 18.5]
    assert series.df["source"].to_list() == ["fmp", "fmp"]


def test_internals_unsupported_symbol_raises() -> None:
    provider = FMPProvider(api_key="test")
    with pytest.raises(CapabilityError):
        provider.internals(
            InternalSymbol.TICK,  # breadth — not served by FMP
            datetime(2026, 6, 25, tzinfo=UTC),
            datetime(2026, 6, 26, tzinfo=UTC),
            Timeframe.M5,
        )
