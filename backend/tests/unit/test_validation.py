"""Leak-free CV + Deflated Sharpe sanity."""

from __future__ import annotations

import numpy as np

from intradayx.attribution.validation import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    purged_kfold,
)


def test_purged_kfold_purges_label_window() -> None:
    folds = purged_kfold(100, n_splits=5, label_horizon=10, embargo=5)
    assert len(folds) == 5
    for train, test in folds:
        assert set(train.tolist()).isdisjoint(test.tolist())
        t0, t1 = int(test.min()), int(test.max())
        # No training sample within the label window of the test block.
        for ti in train.tolist():
            assert not (t0 - 10 <= ti <= t1 + 10)


def test_psr_higher_for_better_returns() -> None:
    rng = np.random.default_rng(0)
    good = rng.normal(0.01, 0.01, 200)  # SR ~ 1
    noise = rng.normal(0.0, 0.01, 200)  # SR ~ 0
    assert probabilistic_sharpe_ratio(good, 0.0) > probabilistic_sharpe_ratio(noise, 0.0)


def test_dsr_deflates_with_more_trials() -> None:
    rng = np.random.default_rng(1)
    r = rng.normal(0.005, 0.01, 200)
    # More trials => the observed Sharpe is less impressive => lower confidence.
    assert deflated_sharpe_ratio(r, 1) >= deflated_sharpe_ratio(r, 100)
