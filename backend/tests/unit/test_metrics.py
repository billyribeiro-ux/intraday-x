"""Prometheus metrics render with the expected series."""

from __future__ import annotations

from intradayx.api import metrics


def test_metrics_render_exposes_series() -> None:
    metrics.SIGNALS_EMITTED.labels(scanner="reversal", side="sell").inc()
    metrics.POLL_SECONDS.observe(0.01)
    metrics.VENDOR_ERRORS.labels(code="poll_failed").inc()
    metrics.WS_CLIENTS.set(2)

    body, content_type = metrics.render()
    assert b"intradayx_signals_emitted_total" in body
    assert b"intradayx_poll_seconds" in body
    assert b"intradayx_vendor_errors_total" in body
    assert b"intradayx_ws_clients" in body
    assert "text/plain" in content_type
