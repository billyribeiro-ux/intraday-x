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
* ``adx`` / ``trend_regime`` — trend strength + direction, strictly causal.
* ``bar_strength`` / ``volume_delta_proxy`` / ``momentum_3bar`` / ``vwap_extension``
  — microstructure & confirmation proxies used by the signal-quality layer.

All require ``session_date`` + ``minutes_from_open`` (see :mod:`.session`).
"""

from __future__ import annotations

import polars as pl

DEFAULT_RVOL_SESSIONS = 14
DEFAULT_ATR_WINDOW = 14
DEFAULT_ADX_WINDOW = 14
DEFAULT_TREND_ADX_THRESHOLD = 25.0


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


def add_adx(df: pl.DataFrame, window: int = DEFAULT_ADX_WINDOW) -> pl.DataFrame:
    """Average Directional Index (+DI, -DI, ADX) — causal Wilder smoothing.

    Returns nulls until ``window`` samples are available; downstream scanners
    treat null ADX as "no strong trend" (conservative default).
    """
    prev_high = pl.col("high").shift(1)
    prev_low = pl.col("low").shift(1)
    prev_close = pl.col("close").shift(1)

    tr = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )

    up_move = pl.col("high") - prev_high
    down_move = prev_low - pl.col("low")

    plus_dm = pl.when((up_move > down_move) & (up_move > 0)).then(up_move).otherwise(0.0)
    minus_dm = pl.when((down_move > up_move) & (down_move > 0)).then(down_move).otherwise(0.0)

    tr_smooth = tr.rolling_mean(window_size=window, min_samples=window)
    plus_dm_smooth = plus_dm.rolling_mean(window_size=window, min_samples=window)
    minus_dm_smooth = minus_dm.rolling_mean(window_size=window, min_samples=window)

    plus_di = 100.0 * plus_dm_smooth / tr_smooth
    minus_di = 100.0 * minus_dm_smooth / tr_smooth

    dx = (
        100.0
        * (plus_di - minus_di).abs()
        / (plus_di + minus_di).clip(lower_bound=1e-9)
    )
    adx = dx.rolling_mean(window_size=window, min_samples=window)

    return df.with_columns(
        plus_di=plus_di,
        minus_di=minus_di,
        adx=adx,
    )


def add_trend_regime(
    df: pl.DataFrame,
    adx_threshold: float = DEFAULT_TREND_ADX_THRESHOLD,
) -> pl.DataFrame:
    """Classify each bar as ``bull`` / ``bear`` / ``range`` using ADX + DI."""
    plus_di = pl.col("plus_di").fill_null(0.0)
    minus_di = pl.col("minus_di").fill_null(0.0)
    adx = pl.col("adx").fill_null(0.0)

    regime = (
        pl.when((adx >= adx_threshold) & (plus_di > minus_di))
        .then(pl.lit("bull"))
        .when((adx >= adx_threshold) & (minus_di > plus_di))
        .then(pl.lit("bear"))
        .otherwise(pl.lit("range"))
    )
    return df.with_columns(trend_regime=regime)


def add_bar_strength(df: pl.DataFrame) -> pl.DataFrame:
    """Signed body/range in [-1, 1].  Null-safe (flat bar => 0)."""
    rng = (pl.col("high") - pl.col("low")).clip(lower_bound=1e-9)
    strength = ((pl.col("close") - pl.col("open")) / rng).clip(-1.0, 1.0)
    return df.with_columns(bar_strength=strength.fill_null(0.0))


def add_volume_delta_proxy(df: pl.DataFrame) -> pl.DataFrame:
    """Signed volume proxy: up-bar => +volume, down-bar => -volume."""
    signed = pl.when(pl.col("close") >= pl.col("open")).then(pl.col("volume")).otherwise(
        -pl.col("volume")
    )
    return df.with_columns(volume_delta_proxy=signed.fill_null(0))


def add_momentum(df: pl.DataFrame, window: int = 3) -> pl.DataFrame:
    """Causal signed-return momentum over the last ``window`` bars."""
    ret = pl.col("close") - pl.col("close").shift(1)
    signed = pl.when(ret > 0).then(1).when(ret < 0).then(-1).otherwise(0)
    return df.with_columns(momentum_3bar=signed.rolling_sum(window_size=window, min_samples=1))


def add_vwap_extension(df: pl.DataFrame) -> pl.DataFrame:
    """Distance from session VWAP in ATR units (mean-reversion/pullback gauge)."""
    return df.with_columns(
        vwap_extension=(pl.col("close") - pl.col("vwap_session"))
        / pl.col("atr").clip(lower_bound=1e-9)
    )
