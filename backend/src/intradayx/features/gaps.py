"""Overnight gap features.

Gap = (this session's open − prior session's close) / prior close, attached to
every bar of the session, plus the gap measured in ATR units. Causal: the prior
session is complete and the session open is the first bar.
"""

from __future__ import annotations

import polars as pl


def add_gaps(df: pl.DataFrame) -> pl.DataFrame:
    """Add ``gap_pct`` and ``gap_atr`` columns (per session, broadcast to bars)."""
    # Session open = first bar's open; session close = last bar's close (by ts).
    sess = (
        df.sort("ts")
        .group_by("session_date")
        .agg(
            session_open=pl.col("open").first(),
            session_close=pl.col("close").last(),
        )
        .sort("session_date")
    )
    sess = sess.with_columns(prev_close=pl.col("session_close").shift(1))
    sess = sess.with_columns(
        gap_pct=pl.when(pl.col("prev_close") > 0)
        .then((pl.col("session_open") - pl.col("prev_close")) / pl.col("prev_close"))
        .otherwise(None),
    )
    out = df.join(
        sess.select("session_date", "gap_pct", "prev_close"), on="session_date", how="left"
    )
    # gap in ATR units uses the prior close as the price scale anchor.
    return out.with_columns(
        gap_atr=pl.when(pl.col("atr") > 0)
        .then((pl.col("gap_pct") * pl.col("prev_close")) / pl.col("atr"))
        .otherwise(None),
    ).drop("prev_close")
