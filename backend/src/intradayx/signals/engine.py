"""SignalEngine — THE single source of truth for signals.

Strategy-driven: the engine handles the universal signal columns and delegates
the per-scanner frame + attribution to a :class:`~intradayx.signals.strategy.Strategy`
(reversal today, scalping too). The exact same ``evaluate(FeatureSet)`` is called
by the backtester and the live monitor — only the source of bars differs — which
is what guarantees backtest<->live parity.
"""

from __future__ import annotations

from intradayx.domain.bars import BarSet
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.domain.signals import Side, Signal, SignalKind
from intradayx.features.pipeline import FeatureSet, build_features
from intradayx.signals.reversal import ReversalStrategy
from intradayx.signals.strategy import Strategy


def _targets(t1: float | None, t2: float | None) -> tuple[float, ...]:
    return tuple(t for t in (t1, t2) if t is not None)


class SignalEngine:
    """Evaluates a strategy over a FeatureSet into ``Signal`` objects."""

    def __init__(self, strategy: Strategy | None = None) -> None:
        self.strategy: Strategy = strategy or ReversalStrategy()

    @property
    def params_version(self) -> str:
        return self.strategy.params_version

    def evaluate(self, fs: FeatureSet) -> list[Signal]:
        frame = self.strategy.signal_frame(fs)
        signals: list[Signal] = []
        for row in frame.iter_rows(named=True):
            attribution = self.strategy.attribution(row, fs.data_completeness)
            confidence = float(row["confluence"]) * fs.data_completeness
            stop = float(row["stop"]) if row["stop"] is not None else float(row["entry"])
            snapshot = {
                k: float(v)
                for k, v in row.items()
                if (k == "confluence" or k.startswith("c_")) and v is not None
            }
            signals.append(
                Signal.create(
                    symbol=fs.symbol,
                    ts=row["ts"],
                    kind=SignalKind(row["kind"]),
                    side=Side(row["side"]),
                    confidence=confidence,
                    entry=float(row["entry"]),
                    stop=stop,
                    targets=_targets(row["target1"], row["target2"]),
                    time_of_day_bucket=row["tod_bucket"],
                    attribution=attribution,
                    triggered_rules=tuple(
                        c.kind.value for c in attribution.ranked_causes if c.score > 0.05
                    ),
                    params_version=self.params_version,
                    feature_snapshot=snapshot,
                )
            )
        return signals

    def scan(self, bars: BarSet, caps: ProviderCapabilities) -> list[Signal]:
        """Convenience: build features then evaluate. Used by the CLI and live poller."""
        if bars.is_empty():
            return []
        return self.evaluate(build_features(bars, caps))
