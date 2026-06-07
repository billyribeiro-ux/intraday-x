"""Strategy parameters (versioned).

The ``version`` string feeds the deterministic ``signal_id`` and is recorded on
every signal, so a backtest run is reproducible and live/backtest signals from
the same params agree on identity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReversalParams:
    version: str = "rev-0.1"
    pivot_k: int = 3
    threshold: float = 0.35  # min confluence score to emit a signal
    # Confluence weights (sum ~1.0).
    w_climax: float = 0.45
    w_volume: float = 0.20
    w_value_area: float = 0.25
    w_poc: float = 0.10
    # Detector tunables.
    rvol_full: float = 3.0  # rvol at/above => full volume conviction
    vae_atr: float = 1.0  # ATRs beyond VAH/VAL for full value-area-edge score
    poc_atr: float = 0.75  # ATRs from prior POC for full proximity score
    # Risk.
    atr_stop_mult: float = 0.25  # stop buffer beyond the pivot extreme, in ATRs


@dataclass(frozen=True, slots=True)
class ScalpingParams:
    """Momentum/VWAP scalping — discrete entry triggers, tight risk."""

    version: str = "scalp-0.1"
    threshold: float = 0.45  # min confluence to emit
    # Confluence weights (sum ~1.0).
    w_vwap: float = 0.30
    w_volume: float = 0.30
    w_momentum: float = 0.25
    w_breakout: float = 0.15
    # Detector tunables.
    rvol_full: float = 2.0  # scalps fire on lower rvol than reversals
    vwap_atr: float = 1.0  # ATRs above/below VWAP for full side score
    # Risk (tight — scalps).
    atr_stop_mult: float = 0.5
    atr_target_mult: float = 1.0
