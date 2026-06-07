"""Short-data value types — used by the Phase 8 short-squeeze detector.

FINRA short interest is biweekly and lagged (~2 weeks); ``as_of`` vs
``published`` is tracked so the detector can flag staleness and never treat a
stale value as live (which would also be a leakage bug).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class ShortInterest:
    ticker: str
    settlement_date: date  # the position date the figure reflects
    published_date: date  # when FINRA actually released it
    short_interest: int
    avg_daily_volume: int
    days_to_cover: float


@dataclass(frozen=True, slots=True)
class ShortVolume:
    ticker: str
    date: date
    short_volume: int
    total_volume: int

    @property
    def short_volume_ratio(self) -> float:
        return self.short_volume / self.total_volume if self.total_volume else 0.0


@dataclass(frozen=True, slots=True)
class BorrowRate:
    ticker: str
    date: date
    fee_rate: float  # annualized cost-to-borrow, %
    utilization: float | None = None  # % of lendable shares on loan
