"""Move explanation: classifies latest FMP-derived feature state."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from intradayx.attribution.move_explainer import explain_latest_move


def test_explains_up_expansion_from_volume_and_momentum() -> None:
    df = pl.DataFrame(
        {
            "ts": [datetime(2024, 1, 2, 14, 30, tzinfo=UTC)],
            "open": [100.0],
            "high": [103.0],
            "low": [99.7],
            "close": [102.6],
            "volume": [9_000],
            "atr": [1.0],
            "rvol": [3.2],
            "rvol_day": [2.1],
            "range_atr": [2.4],
            "close_position": [0.9],
            "momentum_3bar": [2.2],
            "trend_regime": ["bull"],
            "adx": [32.0],
            "vwap_extension": [1.8],
            "gap_atr": [0.1],
            "squeeze_signature_score": [0.0],
            "climax_up_score": [0.4],
            "climax_down_score": [0.0],
            "dist_to_prior_poc": [1.2],
            "volume_delta_proxy": [1.3],
        }
    )

    move = explain_latest_move(df, data_completeness=0.5)

    assert move is not None
    assert move.direction == "up"
    assert move.regime == "expansion"
    assert move.confidence > 0.4
    assert move.drivers[0].kind in {"directional_momentum", "volume_participation"}


def test_explains_sideways_compression() -> None:
    df = pl.DataFrame(
        {
            "ts": [datetime(2024, 1, 2, 14, 30, tzinfo=UTC)],
            "open": [100.0],
            "high": [100.2],
            "low": [99.9],
            "close": [100.03],
            "volume": [1_000],
            "atr": [1.0],
            "rvol": [0.8],
            "rvol_day": [0.9],
            "range_atr": [0.3],
            "close_position": [0.5],
            "momentum_3bar": [0.05],
            "trend_regime": ["range"],
            "adx": [10.0],
            "vwap_extension": [0.03],
            "gap_atr": [0.0],
            "squeeze_signature_score": [0.82],
            "climax_up_score": [0.0],
            "climax_down_score": [0.0],
            "dist_to_prior_poc": [0.1],
            "volume_delta_proxy": [0.0],
        }
    )

    move = explain_latest_move(df, data_completeness=0.5)

    assert move is not None
    assert move.direction == "sideways"
    assert move.regime == "compression"
    assert any(d.kind == "compression" for d in move.drivers)
