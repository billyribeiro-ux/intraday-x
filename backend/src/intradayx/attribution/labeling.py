"""Move labeling for supervised learning (López de Prado triple-barrier).

Barriers are VOLATILITY-SCALED (k·σ), not fixed % — so a "significant move" means
the same thing across quiet and volatile names. Labels are forward-looking BY
CONSTRUCTION (that's correct for a target); the features fed to the model must
stay strictly backward-looking, and the last `max_hold` bars get no label (no
full forward window) to avoid a truncated-horizon bias.
"""

from __future__ import annotations

import numpy as np
import polars as pl

DEFAULT_VOL_SPAN = 50
DEFAULT_PT = 2.0  # profit-taking barrier in volatility units
DEFAULT_SL = 2.0  # stop-loss barrier in volatility units
DEFAULT_MAX_HOLD = 24  # vertical (time) barrier, in bars


def ewma_volatility(close: pl.Series, span: int = DEFAULT_VOL_SPAN) -> np.ndarray:
    """EWMA std of log returns — the per-bar volatility used to scale barriers."""
    log_ret = close.log().diff()
    return log_ret.ewm_std(span=span).to_numpy()


def triple_barrier_labels(
    df: pl.DataFrame,
    *,
    pt: float = DEFAULT_PT,
    sl: float = DEFAULT_SL,
    max_hold: int = DEFAULT_MAX_HOLD,
    vol_span: int = DEFAULT_VOL_SPAN,
) -> np.ndarray:
    """Label each bar +1 / -1 / 0 by which barrier is hit first within max_hold.

    Returns a float array (NaN where unlabelable: no volatility yet, or no full
    forward window in the last `max_hold` bars).
    """
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    vol = ewma_volatility(df["close"], vol_span)
    n = len(close)
    labels = np.full(n, np.nan)

    for i in range(n - 1):
        v = vol[i]
        if not np.isfinite(v) or v <= 0:
            continue
        up = close[i] * (1.0 + pt * v)
        dn = close[i] * (1.0 - sl * v)
        end = min(i + max_hold, n - 1)
        outcome = 0
        for j in range(i + 1, end + 1):
            if high[j] >= up:
                outcome = 1
                break
            if low[j] <= dn:
                outcome = -1
                break
        labels[i] = outcome

    # Tail bars lack a full forward window → no honest label.
    if max_hold > 0:
        labels[max(0, n - max_hold) :] = np.nan
    return labels
