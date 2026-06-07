"""Default provider wiring.

The default is a CompositeProvider preferring Alpaca (deep free history) and
falling back to yfinance (zero-setup). Without Alpaca credentials the composite
transparently routes to yfinance for recent windows.
"""

from __future__ import annotations

from intradayx.data.composite import CompositeProvider
from intradayx.data.provider import DataProvider
from intradayx.data.providers.alpaca_provider import AlpacaProvider
from intradayx.data.providers.yfinance_provider import YFinanceProvider


def default_provider() -> DataProvider:
    """Alpaca (priority 5, deep history) then yfinance (priority 10, fallback)."""
    return CompositeProvider(
        [
            (AlpacaProvider(), 5),
            (YFinanceProvider(), 10),
        ]
    )
