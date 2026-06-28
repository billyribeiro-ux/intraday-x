"""Signal feature snapshots for learning and audit.

Every value here is known at the signal bar. The snapshot is intentionally broad:
the deterministic scanner emits the signal, and the meta-filter learns from the
full local market state instead of only the rule-confluence columns.
"""

from __future__ import annotations

import math
from typing import Any

SIGNAL_SNAPSHOT_FEATURES: tuple[str, ...] = (
    "confluence",
    "c_climax",
    "c_volume",
    "c_value_area",
    "c_poc",
    "c_vwap",
    "c_momentum",
    "c_breakout",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "atr",
    "true_range",
    "rvol",
    "rvol_day",
    "range_atr",
    "close_position",
    "upper_wick_frac",
    "lower_wick_frac",
    "gap_pct",
    "gap_atr",
    "dist_to_prior_poc",
    "vwap_extension",
    "bar_strength",
    "momentum_3bar",
    "volume_delta_proxy",
    "adx",
    "plus_di",
    "minus_di",
    "climax_up_score",
    "climax_down_score",
    "squeeze_signature_score",
    "minutes_from_open",
    # Volatility-regime internals (VIX family); present only when the provider
    # supplies them, else absent (meta-filter defaults them to 0.0).
    "vix_level",
    "vix_roc",
    "vix_term_slope",
)

TREND_REGIME_SNAPSHOT_FEATURES: tuple[str, ...] = (
    "trend_bull",
    "trend_bear",
    "trend_range",
)


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        out = float(value)
        return out if math.isfinite(out) else None
    return None


def snapshot_from_row(row: dict[str, Any]) -> dict[str, float]:
    """Extract stable numeric features from a strategy/context joined row."""
    snapshot: dict[str, float] = {}
    for key in SIGNAL_SNAPSHOT_FEATURES:
        value = _float_or_none(row.get(key))
        if value is not None:
            snapshot[key] = value

    regime = row.get("trend_regime")
    if isinstance(regime, str):
        normalized = regime.lower()
        snapshot["trend_bull"] = 1.0 if normalized == "bull" else 0.0
        snapshot["trend_bear"] = 1.0 if normalized == "bear" else 0.0
        snapshot["trend_range"] = 1.0 if normalized == "range" else 0.0
    return snapshot
