"""Earnings-event value types shared by the data layer and the PEAD strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class EarningsSurprise:
    """A reported earnings event: actual vs estimated EPS on a report date."""

    date: date
    eps_actual: float
    eps_estimated: float

    @property
    def surprise(self) -> float:
        """Absolute EPS surprise (actual − estimated); sign drives PEAD direction."""
        return self.eps_actual - self.eps_estimated
