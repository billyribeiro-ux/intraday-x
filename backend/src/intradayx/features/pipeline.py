"""Feature pipeline — builds a :class:`FeatureSet` from a BarSet.

Everything is computed CAUSALLY (rolling/expanding windows over past bars,
confirmed pivots only). Internals/options/short features are *capability-gated*:
absent under a price/volume-only vendor, which lowers ``data_completeness`` (the
honest "attribution limited by available data" signal) rather than fabricating
columns.
"""

from __future__ import annotations

import polars as pl

from intradayx.domain.bars import BarSet
from intradayx.domain.capabilities import (
    INTERNALS_BREADTH,
    INTERNALS_VOLATILITY,
    OPTIONS_FULL,
    SHORT_FULL,
    ProviderCapabilities,
)
from intradayx.domain.internals import InternalsSeries, InternalSymbol
from intradayx.features.climax import add_climax
from intradayx.features.gaps import add_gaps
from intradayx.features.indicators import (
    add_adx,
    add_atr,
    add_bar_strength,
    add_momentum,
    add_rvol,
    add_trend_regime,
    add_volume_delta_proxy,
    add_vwap_extension,
    add_vwap_session,
)
from intradayx.features.pivots import add_pivots
from intradayx.features.session import add_session_columns
from intradayx.features.squeeze import add_squeeze_signature
from intradayx.features.volatility import VOLATILITY_REGIME_FEATURES, add_volatility_regime
from intradayx.features.volume_profile import add_volume_profile

# Feature columns this pipeline produces (used to build the manifest).
PRICE_VOLUME_FEATURES: tuple[str, ...] = (
    "session_date",
    "minutes_from_open",
    "tod_bucket",
    "vwap_session",
    "rvol",
    "rvol_day",
    "atr",
    "true_range",
    "prior_poc",
    "prior_vah",
    "prior_val",
    "dist_to_prior_poc",
    "ib_high",
    "ib_low",
    "gap_pct",
    "gap_atr",
    "confirmed_swing_high",
    "confirmed_swing_low",
    "swing_high_price",
    "swing_low_price",
    "range_atr",
    "upper_wick_frac",
    "lower_wick_frac",
    "close_position",
    "climax_up_score",
    "climax_down_score",
    "squeeze_signature_score",
    # quality/confirmation layer
    "plus_di",
    "minus_di",
    "adx",
    "trend_regime",
    "bar_strength",
    "volume_delta_proxy",
    "momentum_3bar",
    "vwap_extension",
)


def data_completeness_for(caps: ProviderCapabilities) -> float:
    """Share of the ideal data the active provider can supply (0–1).

    Price/volume is always present (0.5). Breadth internals add 0.3, volatility
    internals (VIX family) 0.15, options 0.1, shorts 0.1. Under a
    price/volume-only vendor (yfinance/Twelve Data) this is 0.5; with FMP's VIX
    family it is 0.65 — and a signal's confidence is scaled by it, so the UI/PDF
    can honestly say "attribution limited by available data".
    """
    score = 0.5
    if caps.supported & INTERNALS_BREADTH:
        score += 0.3
    if caps.supported & INTERNALS_VOLATILITY:
        score += 0.15
    if caps.supports_all(OPTIONS_FULL):
        score += 0.1
    if caps.supports_all(SHORT_FULL):
        score += 0.1
    return min(score, 1.0)


class FeatureSet:
    """Bars enriched with causal features, plus what data backed them."""

    __slots__ = ("_df", "data_completeness", "feature_manifest", "symbol", "timeframe")

    def __init__(
        self,
        symbol: str,
        timeframe: object,
        df: pl.DataFrame,
        feature_manifest: frozenset[str],
        data_completeness: float,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self._df = df
        self.feature_manifest = feature_manifest
        self.data_completeness = data_completeness

    @property
    def df(self) -> pl.DataFrame:
        return self._df

    def __len__(self) -> int:
        return self._df.height

    def __repr__(self) -> str:
        return (
            f"FeatureSet(symbol={self.symbol!r}, n={len(self)}, "
            f"features={len(self.feature_manifest)}, "
            f"data_completeness={self.data_completeness:.2f})"
        )


def build_features(
    bars: BarSet,
    caps: ProviderCapabilities,
    *,
    internals: dict[InternalSymbol, InternalsSeries] | None = None,
) -> FeatureSet:
    """Compute the full causal feature set for ``bars``.

    Order matters: session anchors VWAP/RVOL/profile; ATR precedes the
    gap/climax features that consume it. ``internals`` (the VIX family) is
    optional context; when supplied and the provider declares volatility
    internals, volatility-regime columns are added for the meta-filter.
    """
    df = bars.df
    df = add_session_columns(df)
    df = add_vwap_session(df)
    df = add_rvol(df)
    df = add_atr(df)
    # Quality / confirmation primitives (all optional downstream).
    df = add_adx(df)
    df = add_trend_regime(df)
    df = add_bar_strength(df)
    df = add_volume_delta_proxy(df)
    df = add_momentum(df)
    df = add_vwap_extension(df)
    df = add_volume_profile(df)
    df = add_gaps(df)
    df = add_pivots(df)
    df = add_climax(df)
    df = add_squeeze_signature(df)  # needs range_atr + close_position from climax

    # Internals features, gated on caps.supported. Dormant under price/volume-only
    # vendors by design. Volatility regime (VIX family) is the first wired.
    if internals and caps.supported & INTERNALS_VOLATILITY:
        df = add_volatility_regime(
            df,
            vix=internals.get(InternalSymbol.VIX),
            vix9d=internals.get(InternalSymbol.VIX9D),
            vix3m=internals.get(InternalSymbol.VIX3M),
        )

    manifest = frozenset(
        c for c in (*PRICE_VOLUME_FEATURES, *VOLATILITY_REGIME_FEATURES) if c in df.columns
    )
    return FeatureSet(
        symbol=bars.symbol,
        timeframe=bars.timeframe,
        df=df.sort("ts"),
        feature_manifest=manifest,
        data_completeness=data_completeness_for(caps),
    )
