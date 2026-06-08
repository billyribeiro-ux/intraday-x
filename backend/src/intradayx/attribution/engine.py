"""Rule-based attribution (the "why" behind a signal).

Deterministic and trustworthy: ranks each strategy's confluence components by
their actual weighted contribution and labels them in plain English. The ML/SHAP
layer (Phase 6) layers on top. Every Attribution carries ``data_completeness`` so
a report can say "attribution limited by available data" under a price/volume vendor.
"""

from __future__ import annotations

from intradayx.domain.signals import (
    Attribution,
    Cause,
    CauseKind,
    CauseSource,
)
from intradayx.signals.params import ReversalParams, ScalpingParams

RULE_CAVEAT = (
    "Deterministic rule-based attribution computed from price/volume only "
    "(data_completeness {dc:.0%}). Market internals, options and short data were "
    "not available, so this explains the chart structure — not order flow, dealer "
    "hedging, or news. Verify before trading."
)


def _rank(
    contributions: list[tuple[CauseKind, float, str]], data_completeness: float
) -> Attribution:
    """Turn weighted (kind, weight, label) contributions into a ranked Attribution."""
    total = sum(w for _, w, _ in contributions)
    if total <= 0:
        return Attribution(data_completeness=data_completeness, uncertain=True)
    ranked = sorted(
        (
            Cause(
                kind=kind,
                score=w / total,
                source=CauseSource.RULE,
                label=label,
                evidence={"weighted_contribution": w},
            )
            for kind, w, label in contributions
            if w > 0
        ),
        key=lambda c: c.score,
        reverse=True,
    )
    return Attribution(
        ranked_causes=tuple(ranked),
        data_completeness=data_completeness,
        uncertain=False,
        caveat=RULE_CAVEAT.format(dc=data_completeness),
    )


def reversal_attribution(
    *,
    is_top: bool,
    c_climax: float,
    c_volume: float,
    c_value_area: float,
    c_poc: float,
    params: ReversalParams,
    data_completeness: float,
) -> Attribution:
    edge = "highs" if is_top else "lows"
    va = "Value Area High" if is_top else "Value Area Low"
    return _rank(
        [
            (
                CauseKind.CLIMAX_REVERSAL,
                params.w_climax * c_climax,
                f"Volume climax / exhaustion rejecting the {edge}",
            ),
            (CauseKind.VOLUME_SURGE, params.w_volume * c_volume, "Relative-volume surge"),
            (
                CauseKind.VALUE_AREA_EDGE,
                params.w_value_area * c_value_area,
                f"Rejection at prior {va}",
            ),
            (CauseKind.POC_REJECTION, params.w_poc * c_poc, "Test of prior Point of Control"),
        ],
        data_completeness,
    )


def scalping_attribution(
    *,
    is_long: bool,
    c_vwap: float,
    c_volume: float,
    c_momentum: float,
    c_breakout: float,
    params: ScalpingParams,
    data_completeness: float,
) -> Attribution:
    vwap_label = "VWAP reclaim from below" if is_long else "VWAP rejection from above"
    side = "up" if is_long else "down"
    return _rank(
        [
            (CauseKind.VWAP_RECLAIM, params.w_vwap * c_vwap, vwap_label),
            (CauseKind.VOLUME_SURGE, params.w_volume * c_volume, "Relative-volume surge"),
            (CauseKind.MOMENTUM, params.w_momentum * c_momentum, f"Momentum bar ({side})"),
            (CauseKind.BREAKOUT, params.w_breakout * c_breakout, "Initial-balance / range break"),
        ],
        data_completeness,
    )
