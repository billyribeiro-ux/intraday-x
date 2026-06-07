"""Signal & attribution value types — the shared currency of the whole system.

The exact same :class:`Signal` object is produced by the reversal/scalping
strategies, persisted, exported to CSV/PDF, replayed in the backtester, and
pushed over the live websocket. One definition, everywhere — which is what keeps
backtest and live in lock-step.

The honesty contract is encoded here:

* every :class:`Attribution` carries ``data_completeness`` (0–1) and an
  ``uncertain`` flag;
* :func:`uncertain_attribution` is the canonical "cause uncertain" output used
  when the available internals do not explain a move.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SignalKind(StrEnum):
    REVERSAL_TOP = "reversal_top"
    REVERSAL_BOTTOM = "reversal_bottom"
    SCALP_LONG = "scalp_long"  # Phase 10
    SCALP_SHORT = "scalp_short"  # Phase 10


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"
    EXIT = "exit"

    @property
    def is_bullish(self) -> bool:
        return self in (Side.BUY, Side.COVER)

    @property
    def ui_direction(self) -> str:
        """Collapse to the dashboard's buy/sell colouring."""
        return "buy" if self.is_bullish else "sell"


class CauseKind(StrEnum):
    """The candidate "culprits" the engine can name. Each maps to a detector
    and/or a feature group. ``UNEXPLAINED`` is the honest fallback."""

    VOLUME_SURGE = "volume_surge"
    CLIMAX_REVERSAL = "climax_reversal"
    VWAP_RECLAIM = "vwap_reclaim"
    GAP_AND_GO = "gap_and_go"
    POC_REJECTION = "poc_rejection"
    VALUE_AREA_EDGE = "value_area_edge"
    INTERNALS_DIVERGENCE = "internals_divergence"  # capability-gated
    INTERNALS_EXTREME = "internals_extreme"  # capability-gated
    SHORT_SQUEEZE = "short_squeeze"  # Phase 8 (gated)
    GAMMA_SQUEEZE = "gamma_squeeze"  # Phase 9 (gated)
    EARNINGS = "earnings"  # move coincides with scheduled earnings (a named catalyst)
    UNEXPLAINED = "unexplained"  # probable external catalyst; cause unidentified


class CauseSource(StrEnum):
    RULE = "rule"  # deterministic detector — trustworthy
    MODEL = "model"  # SHAP-derived — correlational, lower trust


@dataclass(frozen=True, slots=True)
class Cause:
    """One ranked contributor to *why* a move happened.

    ``score`` is a 0–1 contribution weight. For ``MODEL`` causes it is a
    normalized |SHAP| share and describes *what the model keyed on*, NOT what
    caused the move (correlation ≠ causation — see :attr:`Attribution.caveat`).
    """

    kind: CauseKind
    score: float
    source: CauseSource
    label: str
    evidence: dict[str, float] = field(default_factory=dict)


# The caveat that must ride with any model-derived attribution.
MODEL_ATTRIBUTION_CAVEAT = (
    "Attributions describe what the model keyed on, not what caused the move. "
    "They are correlational, computed only from available internals, and can be "
    "confounded by drivers we don't observe (order flow, options hedging, news). "
    "Treat them as hypotheses to investigate, not conclusions."
)


@dataclass(frozen=True, slots=True)
class Attribution:
    """The "why" behind a signal, with mandatory honesty fields."""

    ranked_causes: tuple[Cause, ...] = ()
    data_completeness: float = 0.0  # 0–1: share of relevant capabilities available
    uncertain: bool = False
    caveat: str = MODEL_ATTRIBUTION_CAVEAT

    @property
    def primary_cause(self) -> Cause | None:
        return self.ranked_causes[0] if self.ranked_causes else None

    @property
    def summary(self) -> str:
        if self.uncertain or not self.ranked_causes:
            return "Cause uncertain — move not explained by available internals."
        top = self.ranked_causes[0]
        return f"{top.label} ({top.score:.0%})"


def uncertain_attribution(data_completeness: float, *, note: str | None = None) -> Attribution:
    """Canonical "cause uncertain" attribution.

    Used when measured internals do not explain a move, a detector lacks the
    data it needs, or the move is out-of-distribution. Fail-loud / say-uncertain
    beats a confident wrong answer.
    """
    cause = Cause(
        kind=CauseKind.UNEXPLAINED,
        score=1.0,
        source=CauseSource.RULE,
        label=note or "Unexplained by available internals — probable external catalyst.",
    )
    return Attribution(
        ranked_causes=(cause,),
        data_completeness=data_completeness,
        uncertain=True,
    )


def make_signal_id(symbol: str, ts: datetime, kind: SignalKind, params_version: str) -> str:
    """Deterministic signal id so a re-poll of the same window never re-fires,
    and so backtest and live agree on identity."""
    raw = f"{symbol}|{ts.isoformat()}|{kind.value}|{params_version}"
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Signal:
    """A timestamped buy/sell signal with its reason and confidence."""

    signal_id: str
    symbol: str
    ts: datetime  # bar (close) that produced it, UTC
    kind: SignalKind
    side: Side
    confidence: float  # 0–1, already scaled down by data_completeness
    entry: float
    stop: float
    targets: tuple[float, ...]
    time_of_day_bucket: str
    attribution: Attribution
    triggered_rules: tuple[str, ...] = ()
    params_version: str = "0"
    feature_snapshot: dict[str, float] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        ts: datetime,
        kind: SignalKind,
        side: Side,
        confidence: float,
        entry: float,
        stop: float,
        targets: tuple[float, ...],
        time_of_day_bucket: str,
        attribution: Attribution,
        triggered_rules: tuple[str, ...] = (),
        params_version: str = "0",
        feature_snapshot: dict[str, float] | None = None,
    ) -> Signal:
        """Build a Signal, deriving the deterministic ``signal_id``."""
        return cls(
            signal_id=make_signal_id(symbol, ts, kind, params_version),
            symbol=symbol,
            ts=ts,
            kind=kind,
            side=side,
            confidence=confidence,
            entry=entry,
            stop=stop,
            targets=targets,
            time_of_day_bucket=time_of_day_bucket,
            attribution=attribution,
            triggered_rules=triggered_rules,
            params_version=params_version,
            feature_snapshot=feature_snapshot or {},
        )
