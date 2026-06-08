"""Prometheus metrics for the live monitor.

Labels are deliberately BOUNDED (scanner/side/code are small enums) — never the
ticker or any free-form input, which would explode cardinality (see
docs/AI_LANDMINES.md). Exposed at GET /metrics.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

SIGNALS_EMITTED = Counter(
    "intradayx_signals_emitted_total",
    "Live signals emitted by the poller",
    ["scanner", "side"],  # scanner: reversal|scalping ; side: buy|sell
)
POLL_SECONDS = Histogram(
    "intradayx_poll_seconds",
    "Wall-clock duration of one poll cycle",
)
VENDOR_ERRORS = Counter(
    "intradayx_vendor_errors_total",
    "Vendor errors during polling",
    ["code"],  # bounded: e.g. 'poll_failed'
)
WS_CLIENTS = Gauge(
    "intradayx_ws_clients",
    "Currently connected websocket clients",
)


def render() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics response."""
    return generate_latest(), CONTENT_TYPE_LATEST
