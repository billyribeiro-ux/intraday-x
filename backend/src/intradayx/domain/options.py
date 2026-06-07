"""Options value types — used by the Phase 9 gamma/GEX detector.

Defined now so the capability-gated ``gamma_squeeze`` detector and a future
options-capable provider share one contract. No GEX number is ever computed or
displayed without a real chain (see the honesty contract).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class OptionRight(StrEnum):
    CALL = "C"
    PUT = "P"


@dataclass(frozen=True, slots=True)
class OptionContract:
    underlying: str
    expiry: date
    strike: float
    right: OptionRight
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    vega: float | None = None
    theta: float | None = None


@dataclass(frozen=True, slots=True)
class OptionChain:
    underlying: str
    asof: datetime
    contracts: tuple[OptionContract, ...] = field(default_factory=tuple)
