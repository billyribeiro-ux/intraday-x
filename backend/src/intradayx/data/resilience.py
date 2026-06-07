"""Retry/backoff for transient vendor failures.

Retries ONLY errors the caller marks retryable (network blips, 429/5xx) — never
capability/credential/lookahead errors, which are deterministic and must fail
fast. Exponential backoff + jitter. The ``sleep`` hook is injectable so tests
run instantly.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class TransientError(Exception):
    """A retryable failure (e.g. HTTP 429/5xx, dropped connection)."""


def with_retries[T](
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retryable: tuple[type[BaseException], ...] = (TransientError,),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn``, retrying on ``retryable`` with exponential backoff + jitter."""
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retryable as exc:
            last_exc = exc
            if attempt == attempts:
                break
            delay = min(base_delay * 2 ** (attempt - 1), max_delay)
            delay *= 0.8 + 0.4 * random.random()  # ±20% jitter, avoid thundering herd
            logger.warning(
                "transient failure (attempt %d/%d): %s; retrying in %.2fs",
                attempt,
                attempts,
                exc,
                delay,
            )
            sleep(delay)
    assert last_exc is not None  # only reachable after a caught exception
    raise last_exc
