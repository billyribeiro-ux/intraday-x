"""Volume profile — Point of Control, Value Area, Initial Balance.

Computed from OHLCV bars (an approximation: each bar's volume is assigned to the
bin of its typical price; true intrabar distribution and buy/sell delta require
tick data — see docs/AI_LANDMINES.md). Two causal references the reversal scanner
uses:

* ``prior_poc`` / ``prior_vah`` / ``prior_val`` — the PREVIOUS session's profile,
  attached to the current session as "naked" support/resistance magnets. Fully
  causal (the prior session is complete).
* ``ib_high`` / ``ib_low`` — the current session's Initial Balance (first 60 min);
  null until formed, then attached to later bars.
"""

from __future__ import annotations

from datetime import date
from itertools import pairwise

import numpy as np
import polars as pl

N_BINS = 50
VALUE_AREA_FRACTION = 0.70
IB_MINUTES = 60


def session_profile(
    typical: np.ndarray, volume: np.ndarray, n_bins: int = N_BINS
) -> tuple[float, float, float]:
    """Return (POC, VAH, VAL) for one session via a volume-by-price histogram.

    Value area expands outward from the POC bin, each step taking the neighbour
    (above/below) with the larger volume, until ``VALUE_AREA_FRACTION`` of total
    volume is enclosed.
    """
    lo, hi = float(typical.min()), float(typical.max())
    if hi <= lo:  # flat session
        return lo, lo, lo
    edges = np.linspace(lo, hi, n_bins + 1)
    hist, _ = np.histogram(typical, bins=edges, weights=volume)
    centers = (edges[:-1] + edges[1:]) / 2.0

    poc_idx = int(hist.argmax())
    total = hist.sum()
    target = total * VALUE_AREA_FRACTION
    lo_idx = hi_idx = poc_idx
    acc = hist[poc_idx]
    while acc < target and (lo_idx > 0 or hi_idx < len(hist) - 1):
        below = hist[lo_idx - 1] if lo_idx > 0 else -1.0
        above = hist[hi_idx + 1] if hi_idx < len(hist) - 1 else -1.0
        if above >= below:
            hi_idx += 1
            acc += hist[hi_idx]
        else:
            lo_idx -= 1
            acc += hist[lo_idx]
    return float(centers[poc_idx]), float(centers[hi_idx]), float(centers[lo_idx])


def add_volume_profile(df: pl.DataFrame, n_bins: int = N_BINS) -> pl.DataFrame:
    """Attach prior-session POC/VAH/VAL and current-session Initial Balance."""
    # --- per-session profiles (Python loop; #sessions is small) ---
    profiles: dict[date, tuple[float, float, float]] = {}
    for sess, grp in df.group_by("session_date"):
        session_date = sess[0]
        typical = ((grp["high"] + grp["low"] + grp["close"]) / 3.0).to_numpy()
        vol = grp["volume"].to_numpy().astype("float64")
        if len(typical) == 0 or vol.sum() <= 0:
            continue
        profiles[session_date] = session_profile(typical, vol, n_bins)

    ordered = sorted(profiles)
    prior = {cur: profiles[prev] for prev, cur in pairwise(ordered)}
    prior_rows = [
        {"session_date": d, "prior_poc": poc, "prior_vah": vah, "prior_val": val_}
        for d, (poc, vah, val_) in prior.items()
    ]
    prior_df = (
        pl.DataFrame(prior_rows)
        if prior_rows
        else pl.DataFrame(
            schema={
                "session_date": pl.Date,
                "prior_poc": pl.Float64,
                "prior_vah": pl.Float64,
                "prior_val": pl.Float64,
            }
        )
    )
    out = df.join(prior_df, on="session_date", how="left")

    # --- Initial Balance: first IB_MINUTES of each session ---
    ib = (
        df.filter((pl.col("minutes_from_open") >= 0) & (pl.col("minutes_from_open") < IB_MINUTES))
        .group_by("session_date")
        .agg(ib_high=pl.col("high").max(), ib_low=pl.col("low").min())
    )
    out = out.join(ib, on="session_date", how="left")

    # IB is only "known" once the first hour is complete; null it out before then.
    formed = pl.col("minutes_from_open") >= IB_MINUTES
    return out.with_columns(
        ib_high=pl.when(formed).then(pl.col("ib_high")).otherwise(None),
        ib_low=pl.when(formed).then(pl.col("ib_low")).otherwise(None),
        dist_to_prior_poc=(pl.col("close") - pl.col("prior_poc")),
    )
