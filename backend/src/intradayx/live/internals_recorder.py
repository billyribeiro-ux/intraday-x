"""Internals self-recorder — banks $TICK/$TRIN/$ADD/$VOLD history.

Deep historical intraday breadth internals are not commercially purchasable
cheaply (see docs/DATA_PROVIDERS.md), so the strategy is to record our own from a
realtime feed — the earlier we start, the more backtest history we accumulate.

This scaffold is built now and runs against any provider. Under a price/volume
vendor (yfinance/Alpaca) every internal is honestly SKIPPED (the provider raises
CapabilityError); it captures nothing rather than fabricating. The moment a
capable feed (Schwab/IBKR/Polygon) is registered, the same code starts writing
real series into the lake with no change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from intradayx.data.provider import DataError, DataProvider
from intradayx.domain.bars import Timeframe
from intradayx.domain.capabilities import Capability, CapabilityError
from intradayx.domain.internals import InternalSymbol
from intradayx.storage.lake import Lake

logger = logging.getLogger(__name__)

# Which capability each internal requires from the provider.
CAPABILITY_FOR_INTERNAL: dict[InternalSymbol, Capability] = {
    InternalSymbol.TICK: Capability.INTERNALS_TICK,
    InternalSymbol.TRIN: Capability.INTERNALS_TRIN,
    InternalSymbol.ADD: Capability.INTERNALS_ADD,
    InternalSymbol.VOLD: Capability.INTERNALS_VOLD,
    InternalSymbol.UVOL: Capability.INTERNALS_VOLD,
    InternalSymbol.DVOL: Capability.INTERNALS_VOLD,
    InternalSymbol.VIX: Capability.INTERNALS_VIX,
    InternalSymbol.VIX9D: Capability.INTERNALS_VIX_TERM,
    InternalSymbol.VIX3M: Capability.INTERNALS_VIX_TERM,
    InternalSymbol.VVIX: Capability.INTERNALS_VIX_TERM,
    InternalSymbol.SKEW: Capability.INTERNALS_SKEW,
    InternalSymbol.PCALL: Capability.INTERNALS_PUTCALL,
}

# The core breadth set the reversal scanner most wants recorded.
DEFAULT_BREADTH: tuple[InternalSymbol, ...] = (
    InternalSymbol.TICK,
    InternalSymbol.TRIN,
    InternalSymbol.ADD,
    InternalSymbol.VOLD,
)


@dataclass(frozen=True, slots=True)
class RecordResult:
    symbol: InternalSymbol
    rows: int
    skipped_reason: str | None = None  # set when the feed can't supply this internal

    @property
    def captured(self) -> bool:
        return self.skipped_reason is None


class InternalsRecorder:
    """Records internals series from a capable provider into the lake."""

    def __init__(self, provider: DataProvider, lake: Lake) -> None:
        self.provider = provider
        self.lake = lake

    def record(
        self,
        symbols: tuple[InternalSymbol, ...],
        start: datetime,
        end: datetime,
        timeframe: Timeframe = Timeframe.M1,
    ) -> list[RecordResult]:
        """Fetch and persist each internal the provider supports; skip the rest honestly."""
        caps = self.provider.capabilities()
        results: list[RecordResult] = []
        for sym in symbols:
            needed = CAPABILITY_FOR_INTERNAL[sym]
            if not caps.supports(needed):
                logger.info("internals %s skipped: no %s capability", sym.value, needed.value)
                results.append(RecordResult(sym, 0, f"no {needed.value} feed"))
                continue
            try:
                series = self.provider.internals(sym, start, end, timeframe)
                rows = self.lake.write_internals(series)
                results.append(RecordResult(sym, rows))
            except (CapabilityError, DataError) as exc:
                logger.warning("internals %s skipped: %s", sym.value, exc)
                results.append(RecordResult(sym, 0, str(exc)))
        return results
