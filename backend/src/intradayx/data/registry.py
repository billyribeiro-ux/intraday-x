"""Provider registry — make multi-vendor first-class and config-driven.

Vendors register by name; the active data layer is assembled from
``Settings.providers`` (order = priority), skipping any vendor whose credentials
are absent. Adding a new vendor is two lines — ``register_provider("x", XProvider)``
plus listing ``"x"`` in ``INTRADAYX_PROVIDERS`` — with no edits to call sites.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from intradayx.config import Settings, get_settings
from intradayx.data.composite import CompositeProvider
from intradayx.data.provider import DataProvider
from intradayx.data.providers.alpaca_provider import AlpacaProvider
from intradayx.data.providers.polygon_provider import PolygonProvider
from intradayx.data.providers.yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[], DataProvider]
_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    _REGISTRY[name] = factory


def registered_names() -> list[str]:
    return list(_REGISTRY)


# Built-in vendors.
register_provider("yfinance", YFinanceProvider)
register_provider("alpaca", AlpacaProvider)
register_provider("polygon", PolygonProvider)


def build_provider(settings: Settings | None = None) -> DataProvider:
    """Assemble the CompositeProvider from settings, skipping unconfigured vendors."""
    settings = settings or get_settings()
    chosen: list[tuple[DataProvider, int]] = []
    for priority, name in enumerate(settings.providers):
        factory = _REGISTRY.get(name)
        if factory is None:
            logger.warning("unknown provider %r in config; skipping", name)
            continue
        provider = factory()
        if not provider.is_configured():
            logger.info("provider %r not configured (no credentials); skipping", name)
            continue
        chosen.append((provider, priority))

    if not chosen:
        logger.warning("no configured providers; falling back to yfinance")
        chosen = [(YFinanceProvider(), 99)]

    logger.info("data layer: %s", [p.name for p, _ in chosen])
    return CompositeProvider(chosen)
