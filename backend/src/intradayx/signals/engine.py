"""SignalEngine — THE single source of truth for signals.

The exact same ``evaluate(FeatureSet)`` is called by the backtester and the live
monitor; only the source of bars differs. Keeping signal logic here (and out of
Nautilus) is what guarantees backtest↔live parity.
"""

from __future__ import annotations

from intradayx.attribution.engine import reversal_attribution
from intradayx.domain.bars import BarSet
from intradayx.domain.capabilities import ProviderCapabilities
from intradayx.domain.signals import Side, Signal, SignalKind
from intradayx.features.pipeline import FeatureSet, build_features
from intradayx.signals.params import ReversalParams
from intradayx.signals.reversal import reversal_signal_frame


def _targets(t1: float | None, t2: float | None) -> tuple[float, ...]:
    return tuple(t for t in (t1, t2) if t is not None)


class SignalEngine:
    """Evaluates the reversal strategy over a FeatureSet into ``Signal`` objects."""

    def __init__(self, params: ReversalParams | None = None) -> None:
        self.params = params or ReversalParams()

    def evaluate(self, fs: FeatureSet) -> list[Signal]:
        frame = reversal_signal_frame(fs, self.params)
        signals: list[Signal] = []
        for row in frame.iter_rows(named=True):
            is_top = row["kind"] == SignalKind.REVERSAL_TOP.value
            attribution = reversal_attribution(
                is_top=is_top,
                c_climax=row["c_climax"] or 0.0,
                c_volume=row["c_volume"] or 0.0,
                c_value_area=row["c_value_area"] or 0.0,
                c_poc=row["c_poc"] or 0.0,
                params=self.params,
                data_completeness=fs.data_completeness,
            )
            # Honesty: confidence is the confluence scaled by how much data backed it.
            confidence = float(row["confluence"]) * fs.data_completeness
            signals.append(
                Signal.create(
                    symbol=fs.symbol,
                    ts=row["ts"],
                    kind=SignalKind(row["kind"]),
                    side=Side(row["side"]),
                    confidence=confidence,
                    entry=float(row["entry"]),
                    stop=float(row["stop"]) if row["stop"] is not None else float(row["entry"]),
                    targets=_targets(row["target1"], row["target2"]),
                    time_of_day_bucket=row["tod_bucket"],
                    attribution=attribution,
                    triggered_rules=tuple(
                        c.kind.value for c in attribution.ranked_causes if c.score > 0.05
                    ),
                    params_version=self.params.version,
                    feature_snapshot={
                        "confluence": float(row["confluence"]),
                        "c_climax": float(row["c_climax"] or 0.0),
                        "c_volume": float(row["c_volume"] or 0.0),
                        "c_value_area": float(row["c_value_area"] or 0.0),
                        "c_poc": float(row["c_poc"] or 0.0),
                    },
                )
            )
        return signals

    def scan(self, bars: BarSet, caps: ProviderCapabilities) -> list[Signal]:
        """Convenience: build features then evaluate. Used by the CLI and live poller."""
        if bars.is_empty():
            return []
        fs = build_features(bars, caps)
        return self.evaluate(fs)
