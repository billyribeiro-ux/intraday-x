"""Default provider wiring.

Priority (lower = preferred): Polygon (full-market, if POLYGON_API_KEY set) →
Alpaca (free deep history, if keys set) → yfinance (zero-setup fallback). Adding
a vendor's key changes the data source with no code change — the composite router
picks the best capable provider per request.
"""

from __future__ import annotations

import os

from intradayx.data.composite import CompositeProvider
from intradayx.data.provider import DataProvider
from intradayx.data.providers.alpaca_provider import AlpacaProvider
from intradayx.data.providers.yfinance_provider import YFinanceProvider


def default_provider() -> DataProvider:
    providers: list[tuple[DataProvider, int]] = []
    if os.environ.get("POLYGON_API_KEY"):
        from intradayx.data.providers.polygon_provider import PolygonProvider

        providers.append((PolygonProvider(), 3))
    providers.append((AlpacaProvider(), 5))
    providers.append((YFinanceProvider(), 10))
    return CompositeProvider(providers)
