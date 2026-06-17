"""SignalEngine — THE single source of truth for signals.

Strategy-driven: the engine handles the universal signal columns and delegates
the per-scanner frame + attribution to a :class:`~intradayx.signals.strategy.Strategy`
(reversal today, scalping too). The exact same ``evaluate(FeatureSet)`` is called
by the backtester and the live monitor — only the source of bars differs — which
is what guarantees backtest<->live parity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from intradayx.domain.bars import BarSet
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.domain.signals import Side, Signal, SignalKind
from intradayx.features.pipeline import FeatureSet, build_features
from intradayx.signals.reversal import ReversalStrategy
from intradayx.signals.strategy import Strategy

if TYPE_CHECKING:
    from intradayx.signals.meta_filter import MetaFilter


def _targets(t1: float | None, t2: float | None) -> tuple[float, ...]:
    return tuple(t for t in (t1, t2) if t is not None)


class SignalEngine:
    """Evaluates a strategy over a FeatureSet into ``Signal`` objects."""

    def __init__(
        self,
        strategy: Strategy | None = None,
        *,
        meta_filter: MetaFilter | None = None,
    ) -> None:
        self.strategy: Strategy = strategy or ReversalStrategy()
        self.meta_filter: MetaFilter | None = meta_filter

    @property
    def params_version(self) -> str:
        return self.strategy.params_version

    def evaluate(self, fs: FeatureSet) -> list[Signal]:
        frame = self.strategy.signal_frame(fs)
        signals: list[Signal] = []
        for row in frame.iter_rows(named=True):
            attribution = self.strategy.attribution(row, fs.data_completeness)
            # Clamp to enforce the Signal's documented 0–1 invariant (a future
            # weight retune that sums > 1 must not leak a > 1 confidence).
            confidence = min(float(row["confluence"]) * fs.data_completeness, 1.0)
            stop = float(row["stop"]) if row["stop"] is not None else float(row["entry"])
            snapshot = {
                k: float(v)
                for k, v in row.items()
                if (k == "confluence" or k.startswith("c_")) and v is not None
            }
            raw_qs = row.get("quality_score")
            quality_score = 1.0 if raw_qs is None else float(raw_qs)
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
                    quality_score=quality_score,
                )
            )
        if self.meta_filter is not None and self.meta_filter.is_fitted:
            scores = self.meta_filter.predict(signals)
            signals = [
                Signal.create(
                    symbol=s.symbol,
                    ts=s.ts,
                    kind=s.kind,
                    side=s.side,
                    confidence=s.confidence,
                    entry=s.entry,
                    stop=s.stop,
                    targets=s.targets,
                    time_of_day_bucket=s.time_of_day_bucket,
                    attribution=s.attribution,
                    triggered_rules=s.triggered_rules,
                    params_version=s.params_version,
                    feature_snapshot=s.feature_snapshot,
                    quality_score=s.quality_score,
                    meta_score=score,
                )
                for s, score in zip(signals, scores, strict=True)
            ]
        return signals

    def scan(self, bars: BarSet, caps: ProviderCapabilities) -> list[Signal]:
        """Convenience: build features then evaluate. Used by the CLI and live poller."""
        if bars.is_empty():
            return []
        return self.evaluate(build_features(bars, caps))
