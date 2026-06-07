"""Trading-session & time-of-day features.

US equity RTH is 09:30–16:00 America/New_York. Bars are stored in UTC, so we
convert per-row to NY local time to derive the session date, minutes-from-open,
and the time-of-day bucket the reversal scanner is explicitly aware of.
"""

from __future__ import annotations

import polars as pl

NY_TZ = "America/New_York"

# Minutes-from-open bucket boundaries (RTH open = 0 min, close = 390 min).
TOD_BUCKETS: tuple[str, ...] = (
    "premarket",
    "open_drive",  # 09:30–10:00
    "morning",  # 10:00–11:30
    "lunch",  # 11:30–13:30
    "afternoon",  # 13:30–15:00
    "power_hour",  # 15:00–16:00
    "afterhours",
)


def add_session_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Add ``session_date``, ``minutes_from_open`` and ``tod_bucket`` columns.

    ``minutes_from_open`` is minutes since 09:30 NY (negative premarket). The
    session date is the NY calendar date, so a bar's intraday context groups
    correctly across the UTC day boundary.
    """
    ny = pl.col("ts").dt.convert_time_zone(NY_TZ)
    mfo = (ny.dt.hour().cast(pl.Int32) * 60 + ny.dt.minute().cast(pl.Int32)) - (9 * 60 + 30)
    out = df.with_columns(
        session_date=ny.dt.date(),
        minutes_from_open=mfo,
    )
    m = pl.col("minutes_from_open")
    bucket = (
        pl.when(m < 0)
        .then(pl.lit("premarket"))
        .when(m < 30)
        .then(pl.lit("open_drive"))
        .when(m < 120)
        .then(pl.lit("morning"))
        .when(m < 240)
        .then(pl.lit("lunch"))
        .when(m < 330)
        .then(pl.lit("afternoon"))
        .when(m <= 390)
        .then(pl.lit("power_hour"))
        .otherwise(pl.lit("afterhours"))
    )
    return out.with_columns(tod_bucket=bucket)
