"""Volatility-regime features from the CBOE VIX family (capability-gated).

These are the first market-internals features the engine consumes. They are
*context*, not triggers: the deterministic scanner still fires on price/volume,
but each signal carries the prevailing volatility regime so the learned
meta-filter can discover where edge concentrates (mean-reversion historically
pays better in high-vol / panic, and when the term structure inverts — VIX9D
above VIX3M — which flags acute near-term stress).

Inputs are :class:`InternalsSeries` (ts -> index level). Every column is added
by an as-of (backward) join, so each bar sees only the most recent VIX print at
or before its own timestamp — causal, no lookahead. A missing series simply
omits its column (honest degradation; never fabricated).
"""

from __future__ import annotations

import polars as pl

from intradayx.domain.internals import InternalsSeries, InternalSymbol

# Feature columns this module can add (added to SIGNAL_SNAPSHOT_FEATURES so the
# meta-filter picks them up automatically).
VOLATILITY_REGIME_FEATURES: tuple[str, ...] = (
    "vix_level",  # VIX spot at the bar
    "vix_roc",  # VIX rate-of-change over the last hour (rising fear)
    "vix_term_slope",  # VIX9D/VIX3M - 1; > 0 = backwardation = acute near-term stress
)

_ROC_BARS = 12  # ~1h on 5m bars


def _asof(df: pl.DataFrame, series: InternalsSeries | None, alias: str) -> pl.DataFrame:
    """Backward as-of join the internal's level onto ``df`` as column ``alias``.

    No-op (column absent) when the series is missing/empty, so downstream stays
    honest about what data actually backed the feature.
    """
    if series is None or series.is_empty():
        return df
    right = series.df.select(["ts", pl.col("value").alias(alias)]).sort("ts")
    return df.sort("ts").join_asof(right, on="ts", strategy="backward")


def add_volatility_regime(
    df: pl.DataFrame,
    *,
    vix: InternalsSeries | None = None,
    vix9d: InternalsSeries | None = None,
    vix3m: InternalsSeries | None = None,
) -> pl.DataFrame:
    """Attach volatility-regime columns to a bar frame (causal as-of joins).

    ``df`` must have a UTC ``ts`` column. Returns ``df`` with whichever of
    :data:`VOLATILITY_REGIME_FEATURES` the supplied series allow.
    """
    if df.is_empty():
        return df

    out = _asof(df, vix, "vix_level")
    if "vix_level" in out.columns:
        # Rate of change vs the level _ROC_BARS ago; null-safe, 0.0 when undefined.
        prev = pl.col("vix_level").shift(_ROC_BARS)
        out = out.with_columns(
            pl.when(prev.is_not_null() & (prev != 0))
            .then(pl.col("vix_level") / prev - 1.0)
            .otherwise(0.0)
            .alias("vix_roc")
        )

    if vix9d is not None and vix3m is not None and not vix9d.is_empty() and not vix3m.is_empty():
        out = _asof(out, vix9d, "_vix9d")
        out = _asof(out, vix3m, "_vix3m")
        out = out.with_columns(
            pl.when(pl.col("_vix3m").is_not_null() & (pl.col("_vix3m") != 0))
            .then(pl.col("_vix9d") / pl.col("_vix3m") - 1.0)
            .otherwise(0.0)
            .alias("vix_term_slope")
        ).drop("_vix9d", "_vix3m")

    return out.sort("ts")


def fetch_volatility_internals(
    provider: object,
    start: object,
    end: object,
    timeframe: object,
) -> dict[InternalSymbol, InternalsSeries]:
    """Best-effort fetch of the VIX family from a provider that supports it.

    Returns only the series that came back non-empty; any CapabilityError /
    DataError (provider can't serve a symbol) is swallowed so the engine simply
    runs without that context rather than failing. Kept here so every call site
    (scan / backtest / live poller) fetches the same way.
    """
    wanted = (InternalSymbol.VIX, InternalSymbol.VIX9D, InternalSymbol.VIX3M)
    out: dict[InternalSymbol, InternalsSeries] = {}
    fetch = getattr(provider, "internals", None)
    if fetch is None:
        return out
    for sym in wanted:
        try:
            series = fetch(sym, start, end, timeframe)
        except Exception:  # volatility context is optional; never fail the scan
            continue
        if series is not None and not series.is_empty():
            out[sym] = series
    return out
