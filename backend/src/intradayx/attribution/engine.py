"""Rule-based attribution for v1 (the "why" behind a reversal signal).

Phase 2 attribution is deterministic and trustworthy: it ranks the confluence
components (climax, volume, value-area edge, POC) by their actual contribution to
the score, and labels each in plain English. The ML/SHAP layer (Phase 6) layers
on top later. Every Attribution still carries ``data_completeness`` so the report
can say "attribution limited by available data" under a price/volume-only vendor.
"""

from __future__ import annotations

from intradayx.domain.signals import (
    Attribution,
    Cause,
    CauseKind,
    CauseSource,
)
from intradayx.signals.params import ReversalParams

RULE_CAVEAT = (
    "Deterministic rule-based attribution computed from price/volume only "
    "(data_completeness {dc:.0%}). Market internals, options and short data were "
    "not available, so this explains the chart structure — not order flow, dealer "
    "hedging, or news. Verify before trading."
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
    """Rank the weighted confluence components into a ranked-cause Attribution."""
    edge = "highs" if is_top else "lows"
    va = "Value Area High" if is_top else "Value Area Low"
    contributions: list[tuple[CauseKind, float, str]] = [
        (
            CauseKind.CLIMAX_REVERSAL,
            params.w_climax * c_climax,
            f"Volume climax / exhaustion rejecting the {edge}",
        ),
        (CauseKind.VOLUME_SURGE, params.w_volume * c_volume, "Relative-volume surge"),
        (CauseKind.VALUE_AREA_EDGE, params.w_value_area * c_value_area, f"Rejection at prior {va}"),
        (CauseKind.POC_REJECTION, params.w_poc * c_poc, "Test of prior Point of Control"),
    ]
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
