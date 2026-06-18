"""FMP provider: honest capabilities, key-gating, and factory/registry wiring (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from intradayx.config import get_settings
from intradayx.data.factory import default_provider
from intradayx.data.provider import DataError, MissingCredentialsError
from intradayx.data.providers.fmp_provider import FMPProvider
from intradayx.data.registry import registered_names
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability
from intradayx.domain.catalysts import CatalystKind


def test_fmp_capabilities_are_honest() -> None:
    caps = FMPProvider(api_key=None).capabilities()
    assert caps.supports(Capability.DAILY_BARS)
    assert caps.supports(Capability.EXTENDED_HISTORY_INTRADAY)
    assert caps.supports(Capability.EARNINGS_CALENDAR)
    assert caps.supports(Capability.STOCK_NEWS)
    assert caps.supports(Capability.PRESS_RELEASES)
    assert caps.supports(Capability.ANALYST_GRADES)
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
    # Runtime data is FMP-only: a configured FMP provider is returned directly.
    monkeypatch.setenv("FMP_API_KEY", "dummy")
    monkeypatch.setenv("INTRADAYX_PROVIDERS", '["fmp"]')
    monkeypatch.setenv("INTRADAYX_CACHE_ENABLED", "false")
    get_settings.cache_clear()
    provider = default_provider()
    assert isinstance(provider, FMPProvider)
    assert provider.name == "fmp"


def test_factory_requires_fmp_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("INTRADAYX_PROVIDERS", '["fmp"]')
    get_settings.cache_clear()
    with pytest.raises(MissingCredentialsError, match="FMP_API_KEY is required"):
        default_provider()


def test_fmp_catalyst_events_parse_timestamped_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FMPProvider(api_key="test")

    def fake_request(path: str, params: dict[str, str]) -> Any:
        assert params.get("symbol") == "AAPL" or params.get("symbols") == "AAPL"
        match path:
            case "earnings-calendar":
                return [
                    {
                        "date": "2024-05-02",
                        "time": "amc",
                        "eps": "1.10",
                        "epsEstimated": "1.00",
                    }
                ]
            case "news/stock":
                return [
                    {
                        "publishedDate": "2024-05-03 14:30:00",
                        "title": "AAPL raises guidance after strong demand",
                        "site": "Example Wire",
                        "url": "https://example.test/news",
                    }
                ]
            case "news/press-releases":
                return [
                    {
                        "date": "2024-05-03 13:00:00",
                        "title": "Apple announces new buyback authorization",
                    }
                ]
            case "grades":
                return [
                    {
                        "date": "2024-05-03",
                        "gradingCompany": "Example Bank",
                        "action": "upgrade",
                        "previousGrade": "Neutral",
                        "newGrade": "Buy",
                    }
                ]
            case "grades-historical":
                return []
        return []

    monkeypatch.setattr(provider, "_request", fake_request)
    start = datetime(2024, 5, 1, tzinfo=UTC)
    end = datetime(2024, 5, 4, tzinfo=UTC)

    events = provider.catalyst_events("aapl", start, end)

    kinds = {event.kind for event in events}
    assert kinds == {
        CatalystKind.EARNINGS,
        CatalystKind.NEWS,
        CatalystKind.PRESS_RELEASE,
        CatalystKind.ANALYST_GRADE,
    }
    assert provider.earnings_dates("AAPL") == [datetime(2024, 5, 2, tzinfo=UTC).date()]
    news = next(event for event in events if event.kind is CatalystKind.NEWS)
    assert news.score > 0.56
    assert news.url == "https://example.test/news"


def test_fmp_optional_catalyst_endpoint_failure_is_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FMPProvider(api_key="test")

    def fake_request(path: str, params: dict[str, str]) -> Any:
        if path == "news/stock":
            raise DataError("plan does not include stock news")
        return []

    monkeypatch.setattr(provider, "_request", fake_request)

    assert provider.catalyst_events(
        "AAPL",
        datetime(2024, 5, 1, tzinfo=UTC),
        datetime(2024, 5, 4, tzinfo=UTC),
    ) == []
