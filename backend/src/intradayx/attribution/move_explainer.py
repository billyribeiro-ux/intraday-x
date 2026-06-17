"""Bar-level move explanation from causal FMP-derived features.

This is not a claim of ultimate causality. It ranks observable evidence available
at the bar: direction, volume participation, VWAP displacement, trend strength,
gap, compression/expansion, exhaustion, and value-area/POC interaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import polars as pl


@dataclass(frozen=True, slots=True)
class MoveDriver:
    kind: str
    score: float
    label: str
    evidence: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MoveExplanation:
    direction: str
    regime: str
    confidence: float
    summary: str
    drivers: tuple[MoveDriver, ...]


def _num(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _score_driver(kind: str, score: float, label: str, **evidence: float) -> MoveDriver | None:
    score = _clip(score)
    if score < 0.12:
        return None
    return MoveDriver(kind=kind, score=score, label=label, evidence=evidence)


def explain_latest_move(df: pl.DataFrame, data_completeness: float) -> MoveExplanation | None:
    """Explain the latest bar in an enriched feature frame.

    All inputs must be causal columns from :mod:`intradayx.features.pipeline`.
    """
    if df.is_empty():
        return None
    row = df.tail(1).to_dicts()[0]
    close = _num(row, "close")
    open_ = _num(row, "open", close)
    atr = max(_num(row, "atr", 0.0), 1e-9)
    bar_change_atr = (close - open_) / atr
    momentum = _num(row, "momentum_3bar")
    direction_score = abs(bar_change_atr)
    if direction_score < 0.18 and abs(momentum) < 0.35:
        direction = "sideways"
    elif bar_change_atr > 0 or momentum > 0:
        direction = "up"
    else:
        direction = "down"

    rvol = max(_num(row, "rvol"), _num(row, "rvol_day"))
    range_atr = _num(row, "range_atr")
    adx = _num(row, "adx")
    trend = str(row.get("trend_regime") or "range")
    squeeze = _num(row, "squeeze_signature_score")
    gap_atr = abs(_num(row, "gap_atr"))
    vwap_extension = _num(row, "vwap_extension")
    volume_delta = _num(row, "volume_delta_proxy")
    climax_up = _num(row, "climax_up_score")
    climax_down = _num(row, "climax_down_score")
    dist_poc = abs(_num(row, "dist_to_prior_poc"))

    drivers: list[MoveDriver] = []
    labels: list[str] = []

    if d := _score_driver(
        "directional_momentum",
        min(abs(momentum) / 2.5, 1.0) * 0.55 + min(abs(bar_change_atr), 2.0) / 2.0 * 0.45,
        f"{direction.title()} directional momentum",
        bar_change_atr=bar_change_atr,
        momentum_3bar=momentum,
    ):
        drivers.append(d)
        labels.append("momentum")

    if d := _score_driver(
        "volume_participation",
        (rvol / 3.0),
        f"Relative volume {rvol:.1f}x",
        rvol=rvol,
    ):
        drivers.append(d)
        labels.append(f"{rvol:.1f}x RVOL")

    if d := _score_driver(
        "trend_pressure",
        min(adx / 45.0, 1.0) if trend in ("bull", "bear") else min(adx / 70.0, 0.45),
        f"{trend.title()} trend pressure" if trend != "range" else "Range-bound trend pressure",
        adx=adx,
    ):
        drivers.append(d)
        labels.append(f"{trend} trend")

    if d := _score_driver(
        "vwap_displacement",
        min(abs(vwap_extension) / 2.5, 1.0),
        "Above VWAP" if vwap_extension > 0 else "Below VWAP",
        vwap_extension=vwap_extension,
    ):
        drivers.append(d)
        labels.append("VWAP displacement")

    if d := _score_driver(
        "auction_expansion",
        min(range_atr / 2.2, 1.0),
        "Auction range expansion",
        range_atr=range_atr,
    ):
        drivers.append(d)

    if d := _score_driver("gap", min(gap_atr / 1.5, 1.0), "Opening gap influence", gap_atr=gap_atr):
        drivers.append(d)

    if d := _score_driver(
        "compression",
        squeeze,
        "Compression / squeeze conditions",
        squeeze_signature_score=squeeze,
    ):
        drivers.append(d)

    exhaustion = climax_up if direction == "up" else climax_down if direction == "down" else max(
        climax_up, climax_down
    )
    if d := _score_driver(
        "exhaustion",
        exhaustion,
        "Climax / exhaustion signature",
        climax_up_score=climax_up,
        climax_down_score=climax_down,
    ):
        drivers.append(d)

    if d := _score_driver(
        "value_area_interaction",
        min(dist_poc / 2.0, 1.0),
        "Prior POC / value-area displacement",
        dist_to_prior_poc=dist_poc,
    ):
        drivers.append(d)

    if d := _score_driver(
        "orderflow_proxy",
        min(abs(volume_delta) / 2.0, 1.0),
        "Directional volume-delta proxy",
        volume_delta_proxy=volume_delta,
    ):
        drivers.append(d)

    drivers.sort(key=lambda x: x.score, reverse=True)
    top = tuple(drivers[:5])

    if direction == "sideways":
        regime = "compression" if squeeze >= 0.55 else "balance"
    elif range_atr >= 1.35 and rvol >= 1.3:
        regime = "expansion"
    elif max(climax_up, climax_down) >= 0.7:
        regime = "exhaustion"
    elif trend in ("bull", "bear") and adx >= 22:
        regime = "trend"
    else:
        regime = "rotation"

    evidence_score = sum(d.score for d in top) / max(len(top), 1)
    confidence = _clip(evidence_score * 0.75 + data_completeness * 0.25)
    label_text = ", ".join(labels[:3]) or "limited observable evidence"
    summary = f"{direction.title()} {regime}: {label_text}."

    return MoveExplanation(
        direction=direction,
        regime=regime,
        confidence=confidence,
        summary=summary,
        drivers=top,
    )
