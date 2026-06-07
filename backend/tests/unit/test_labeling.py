"""Triple-barrier labeling — direction is correct and the tail is unlabelled."""

from __future__ import annotations

import numpy as np

from intradayx.attribution.labeling import triple_barrier_labels
from tests.fixtures.synthetic import make_bars


def test_monotonic_rise_labels_up() -> None:
    bars = make_bars(closes=[100.0 + i for i in range(20)])
    labels = triple_barrier_labels(bars.df, vol_span=5, max_hold=5, pt=2.0, sl=2.0)
    valid = labels[np.isfinite(labels)]
    assert (valid == 1).any()
    assert (valid == -1).sum() == 0  # nothing labelled "down" in a steady rise


def test_monotonic_fall_labels_down() -> None:
    bars = make_bars(closes=[120.0 - i for i in range(20)])
    labels = triple_barrier_labels(bars.df, vol_span=5, max_hold=5, pt=2.0, sl=2.0)
    valid = labels[np.isfinite(labels)]
    assert (valid == -1).any()
    assert (valid == 1).sum() == 0


def test_tail_bars_are_unlabelled() -> None:
    bars = make_bars(closes=[100.0 + (i % 3) for i in range(30)])
    labels = triple_barrier_labels(bars.df, vol_span=5, max_hold=5)
    # The last `max_hold` bars have no full forward window → NaN (no biased 0).
    assert np.isnan(labels[-1])
    assert np.isnan(labels[-3:]).all()
