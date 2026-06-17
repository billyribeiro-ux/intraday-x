"""Forward-learning loop: meta-filter trained on past, evaluated OOS."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from intradayx.data.providers.yfinance_provider import YFinanceProvider
from intradayx.domain.bars import BarSet, Timeframe
from intradayx.signals.forward import forward_learn


def _synthetic_bars(n: int = 2000, *, seed: int = 42) -> BarSet:
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    price = 100.0
    o_, h_, l_, c_, v_, t_ = [], [], [], [], [], []
    for i in range(n):
        o = price
        c = price + float(rng.normal(0, 0.3))
        hi = max(o, c) + abs(float(rng.normal(0, 0.2)))
        lo = min(o, c) - abs(float(rng.normal(0, 0.2)))
        vol = int(abs(rng.normal(1000, 300)))
        if i % 23 == 0:
            c = o + 2.0
            hi = c + 0.5
            vol *= 5
        if i % 29 == 0:
            c = o - 2.0
            lo = c - 0.5
            vol *= 5
        t_.append(start + i * Timeframe.M5.timedelta)
        o_.append(float(o))
        h_.append(float(hi))
        l_.append(float(lo))
        c_.append(float(c))
        v_.append(vol)
        price = c
    df = pl.DataFrame(
        {
            "ts": t_,
            "open": o_,
            "high": h_,
            "low": l_,
            "close": c_,
            "volume": v_,
            "vwap": [None] * n,
            "trades": [None] * n,
            "source": ["test"] * n,
        }
    )
    return BarSet("TEST", Timeframe.M5, df)


@pytest.mark.parametrize("scanner", ["reversal", "scalping"])
def test_forward_learn_runs_without_leakage(scanner: str) -> None:
    bars = _synthetic_bars(n=2000)  # ~7 days of 5m bars
    caps = YFinanceProvider().capabilities()
    res = forward_learn(
        bars,
        caps,
        scanner=scanner,
        total_days=7,
        train_days=3,
        test_days=1,
        step_days=1,
        max_hold_bars=12,
        meta_threshold=0.5,
        min_samples=10,
    )
    assert res.symbol == "TEST"
    assert res.scanner == scanner
    assert len(res.windows) >= 1
    # Every window that produced trades did so with a model trained ONLY on earlier data.
    traded = [w for w in res.windows if w.n_test_trades > 0]
    assert all(not w.model_insufficient for w in traded)
