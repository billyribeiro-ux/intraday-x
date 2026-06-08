"""Volume profile — POC at the modal price; Value Area invariant VAH≥POC≥VAL."""

from __future__ import annotations

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from intradayx.features.volume_profile import session_profile


def test_poc_at_modal_price() -> None:
    typical = np.array([10.0, 10.0, 10.0, 11.0, 9.0])
    volume = np.array([100.0, 100.0, 100.0, 10.0, 10.0])
    poc, vah, val = session_profile(typical, volume, n_bins=50)
    assert abs(poc - 10.0) < 0.1
    assert val <= poc <= vah


@given(
    prices=st.lists(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=5,
        max_size=200,
    ),
)
def test_value_area_ordering_invariant(prices: list[float]) -> None:
    typical = np.array(prices)
    volume = np.ones_like(typical)
    poc, vah, val = session_profile(typical, volume, n_bins=30)
    assert val <= poc <= vah
