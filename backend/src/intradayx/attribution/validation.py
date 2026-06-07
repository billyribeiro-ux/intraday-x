"""Leak-free validation — purged/embargoed K-fold + Deflated Sharpe.

Standard K-fold leaks in finance: a label spans a forward window, so a training
sample whose window overlaps the test block has peeked. Purging drops those;
the embargo drops a few samples right after each test block (serial
correlation). The Deflated Sharpe Ratio discounts the multiple-testing overfit
that kills most intraday edges (Bailey & López de Prado 2014).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.stats import kurtosis as _kurt
from scipy.stats import norm
from scipy.stats import skew as _skew

_EULER = 0.5772156649015329

Returns = Sequence[float] | np.ndarray


def purged_kfold(
    n_samples: int,
    *,
    n_splits: int = 5,
    label_horizon: int = 24,
    embargo: int = 5,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Time-ordered folds with purging (label-window overlap) + embargo.

    Returns a list of (train_idx, test_idx). Training samples whose label window
    overlaps a test block — or fall in the embargo just after it — are removed.
    """
    idx = np.arange(n_samples)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for test_block in np.array_split(idx, n_splits):
        if test_block.size == 0:
            continue
        t0, t1 = int(test_block[0]), int(test_block[-1])
        train_mask = np.ones(n_samples, dtype=bool)
        train_mask[test_block] = False
        # Purge: any sample whose label window [i, i+horizon] overlaps the test
        # block, i.e. within `label_horizon` on either side.
        purge_lo = max(0, t0 - label_horizon)
        purge_hi = min(n_samples - 1, t1 + label_horizon)
        train_mask[purge_lo : purge_hi + 1] = False
        # Embargo: a few more samples right after the (purged) test region.
        emb_hi = min(n_samples - 1, purge_hi + embargo)
        train_mask[t1 + 1 : emb_hi + 1] = False
        folds.append((idx[train_mask], test_block))
    return folds


def _sr_moments(returns: Returns) -> tuple[int, float, float, float]:
    r = np.asarray(returns, dtype=float)
    t = len(r)
    sd = r.std(ddof=1) if t > 1 else 0.0
    sr = float(r.mean() / sd) if sd > 0 else 0.0
    g3 = float(_skew(r, bias=False)) if t > 2 and sd > 0 else 0.0
    g4 = float(_kurt(r, fisher=False, bias=False)) if t > 3 and sd > 0 else 3.0
    return t, sr, g3, g4


def probabilistic_sharpe_ratio(returns: Returns, sr_star: float = 0.0) -> float:
    """P(true SR > sr_star), skew/kurtosis-adjusted. Per-observation SR."""
    t, sr, g3, g4 = _sr_moments(returns)
    if t < 3:
        return 0.0
    denom = 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return 0.0
    z = (sr - sr_star) * np.sqrt(t - 1) / np.sqrt(denom)
    return float(norm.cdf(z))


def deflated_sharpe_ratio(returns: Returns, n_trials: int) -> float:
    """PSR against the expected-maximum SR of `n_trials` zero-skill strategies.

    Returns a probability in [0, 1]: low values mean the observed Sharpe is
    plausibly just the best of many overfit tries.
    """
    t, sr, g3, g4 = _sr_moments(returns)
    if t < 3:
        return 0.0
    n = max(int(n_trials), 1)
    if n == 1:
        return probabilistic_sharpe_ratio(returns, 0.0)
    var_sr = (1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr) / (t - 1)
    sd_sr = float(np.sqrt(max(var_sr, 1e-12)))
    expected_max = sd_sr * (
        (1.0 - _EULER) * norm.ppf(1.0 - 1.0 / n)
        + _EULER * norm.ppf(1.0 - 1.0 / (n * np.e))
    )
    return probabilistic_sharpe_ratio(returns, sr_star=float(expected_max))
