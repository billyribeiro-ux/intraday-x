"""Core indicators — all CAUSAL (only past/current bar data) and unit-tested.

We own these rather than depend on ``pandas-ta`` (sustainability risk) so the
exact maths is testable against hand-computed values.

* ``vwap_session`` — session-anchored VWAP (resets at each RTH open).
* ``rvol`` — relative volume, TIME-OF-DAY MATCHED (today's bar vs the mean of the
  same minutes-from-open slot over the prior N sessions). Time-of-day matching is
  essential intraday: 10:05 volume must be compared to historical 10:05, not the
  daily average.
* ``rvol_day`` — cumulative session volume vs the same-slot prior-session mean
  (session participation).
* ``atr`` — Wilder-style ATR via rolling mean of true range.

All require ``session_date`` + ``minutes_from_open`` (see :mod:`.session`).
"""

from __future__ import annotations

import polars as pl

DEFAULT_RVOL_SESSIONS = 14
DEFAULT_ATR_WINDOW = 14


def add_vwap_session(df: pl.DataFrame) -> pl.DataFrame:
    """Session-anchored VWAP using the typical price (H+L+C)/3."""
    tp = (pl.col("high") + pl.col("low") + pl.col("close")) / 3.0
    cum_pv = (tp * pl.col("volume")).cum_sum().over("session_date")
    cum_v = pl.col("volume").cum_sum().over("session_date")
    return df.with_columns(
        vwap_session=pl.when(cum_v > 0).then(cum_pv / cum_v).otherwise(tp),
    )


def add_rvol(df: pl.DataFrame, sessions: int = DEFAULT_RVOL_SESSIONS) -> pl.DataFrame:
    """Time-of-day-matched relative volume (causal).

    For each minutes-from-open slot, the expectation is the mean over the prior
    ``sessions`` days at that slot — ``shift(1)`` excludes today, so a bar's own
    volume never leaks into its own expectation.
    """
    cum_vol = pl.col("volume").cum_sum().over("session_date")
    df = df.with_columns(_cum_vol=cum_vol)

    # Order within each slot by session so the rolling window walks prior days.
    df = df.sort(["minutes_from_open", "session_date"])
    expected_bar = (
        pl.col("volume")
        .shift(1)
        .rolling_mean(window_size=sessions, min_samples=3)
        .over("minutes_from_open")
    )
    expected_day = (
        pl.col("_cum_vol")
        .shift(1)
        .rolling_mean(window_size=sessions, min_samples=3)
        .over("minutes_from_open")
    )
    df = df.with_columns(
        rvol=pl.when(expected_bar > 0).then(pl.col("volume") / expected_bar).otherwise(None),
        rvol_day=pl.when(expected_day > 0).then(pl.col("_cum_vol") / expected_day).otherwise(None),
    )
    return df.drop("_cum_vol").sort("ts")


def add_atr(df: pl.DataFrame, window: int = DEFAULT_ATR_WINDOW) -> pl.DataFrame:
    """Average True Range (causal rolling mean of true range)."""
    prev_close = pl.col("close").shift(1)
    tr = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    return df.with_columns(
        true_range=tr,
        atr=tr.rolling_mean(window_size=window, min_samples=window),
    )
