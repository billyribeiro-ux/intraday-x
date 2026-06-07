"""Strategy protocol — what the SignalEngine needs from any scanner.

A strategy produces a Polars frame of triggered signals (universal columns
``ts/kind/side/tod_bucket/entry/stop/target1/target2/confluence`` plus its own
``c_*`` component columns) and builds the Attribution for a triggered row.
"""

from __future__ import annotations

from typing import Any, Protocol

import polars as pl

from intradayx.domain.signals import Attribution
from intradayx.features.pipeline import FeatureSet


class Strategy(Protocol):
    name: str

    @property
    def params_version(self) -> str: ...

    def signal_frame(self, fs: FeatureSet) -> pl.DataFrame: ...

    def attribution(self, row: dict[str, Any], data_completeness: float) -> Attribution: ...


def make_strategy(name: str) -> Strategy:
    """Resolve a scanner name to a Strategy ('reversal' | 'scalping')."""
    from intradayx.signals.reversal import ReversalStrategy
    from intradayx.signals.scalping import ScalpingStrategy

    if name == "reversal":
        return ReversalStrategy()
    if name == "scalping":
        return ScalpingStrategy()
    raise ValueError(f"unknown scanner {name!r} (expected 'reversal' or 'scalping')")
