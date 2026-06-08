"""Retry/backoff: retries transient errors, fails fast on everything else."""

from __future__ import annotations

import pytest

from intradayx.data.resilience import TransientError, with_retries


def _noop(_: float) -> None:
    pass


def test_retries_then_succeeds() -> None:
    state = {"n": 0}

    def fn() -> str:
        state["n"] += 1
        if state["n"] < 3:
            raise TransientError("blip")
        return "ok"

    assert with_retries(fn, attempts=5, base_delay=0.0, sleep=_noop) == "ok"
    assert state["n"] == 3


def test_raises_after_exhausting_attempts() -> None:
    def fn() -> str:
        raise TransientError("always down")

    with pytest.raises(TransientError):
        with_retries(fn, attempts=3, base_delay=0.0, sleep=_noop)


def test_non_retryable_fails_fast() -> None:
    state = {"n": 0}

    def fn() -> str:
        state["n"] += 1
        raise ValueError("deterministic — do not retry")

    # default retryable is (TransientError,), so a ValueError is not retried
    with pytest.raises(ValueError):
        with_retries(fn, attempts=5, base_delay=0.0, sleep=_noop)
    assert state["n"] == 1  # tried exactly once
