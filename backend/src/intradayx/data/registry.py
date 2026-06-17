"""Provider registry — registered vendors, FMP-locked runtime assembly.

Vendors can still register by name for tests and legacy tooling, but the active
runtime data layer is locked to FMP. A missing FMP key fails loudly; it must never
quietly fall back to another market-data source.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from intradayx.config import Settings, get_settings
from intradayx.data.composite import CompositeProvider
from intradayx.data.provider import DataProvider, MissingCredentialsError
from intradayx.data.providers.fmp_provider import FMPProvider
from intradayx.data.providers.polygon_provider import PolygonProvider
from intradayx.data.providers.twelvedata_provider import TwelveDataProvider
from intradayx.data.providers.yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)
CANONICAL_PROVIDER = "fmp"

ProviderFactory = Callable[[], DataProvider]
_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    _REGISTRY[name] = factory


def registered_names() -> list[str]:
    return list(_REGISTRY)


# Built-in vendors — all pure data vendors (no brokers).
register_provider("yfinance", YFinanceProvider)
register_provider("twelvedata", TwelveDataProvider)
register_provider("polygon", PolygonProvider)
register_provider("fmp", FMPProvider)


def build_provider(settings: Settings | None = None) -> DataProvider:
    """Build the active provider.

    Market data is FMP-only. Other registered providers remain importable, but
    runtime assembly ignores them so a stale env/settings file cannot change the
    provenance of chart, scan, or backtest data.
    """
    settings = settings or get_settings()
    chosen: list[tuple[DataProvider, int]] = []
    for priority, name in enumerate(settings.providers):
        if name != CANONICAL_PROVIDER:
            logger.warning("provider %r ignored; market data is locked to FMP", name)
            continue
        factory = _REGISTRY.get(name)
        if factory is None:
            logger.warning("unknown provider %r in config; skipping", name)
            continue
        prov = factory()
        if not prov.is_configured():
            logger.info("provider %r not configured (no credentials); skipping", name)
            continue
        chosen.append((prov, priority))

    if not chosen:
        raise MissingCredentialsError(
            "FMP_API_KEY is required. Market data is FMP-only; no fallback provider will be used."
        )

    logger.info("data layer: %s", [p.name for p, _ in chosen])
    provider: DataProvider = chosen[0][0] if len(chosen) == 1 else CompositeProvider(chosen)

    if settings.cache_enabled:
        from intradayx.data.cache import CachingProvider
        from intradayx.storage.lake import Lake

        provider = CachingProvider(provider, Lake(settings.data_dir))
    return provider
