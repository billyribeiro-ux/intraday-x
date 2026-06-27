"""SignalPoller live status self-heals when the FMP key is added at runtime.

Regression: the WS status carried a cached ``_provider_error`` set once at
construction and was only sent on connect, so the Monitor's "FMP key needed"
badge stayed stuck after a key was added live (in-app Settings) even though
chart/scan data already loaded. ``status_data()`` must re-check the provider.
"""

from __future__ import annotations

import pytest

from intradayx.api import ws as ws_mod
from intradayx.api.ws import ConnectionManager, SignalPoller
from intradayx.data.provider import DataError


class _Caps:
    provider_name = "fmp"


class _Provider:
    def capabilities(self) -> _Caps:
        return _Caps()


class _Engine:
    params_version = "test"


def test_status_self_heals_when_key_added_live(monkeypatch: pytest.MonkeyPatch) -> None:
    # No usable provider at construction → configured False ("FMP key needed").
    def _raise() -> _Provider:
        raise DataError("FMP_API_KEY is required. Market data is FMP-only.")

    monkeypatch.setattr(ws_mod, "get_engine", lambda: _Engine())
    monkeypatch.setattr(ws_mod, "get_provider", _raise)
    poller = SignalPoller(ConnectionManager(), ["AAPL"])

    before = poller.status_data()
    assert before["configured"] is False
    assert before["detail"]  # surfaces the missing-key message

    # Key added live → provider usable. status_data() must re-evaluate without a
    # reconnect/restart and flip configured → True.
    monkeypatch.setattr(ws_mod, "get_provider", lambda: _Provider())
    after = poller.status_data()
    assert after["configured"] is True
    assert after["source"] == "fmp"
    assert after["detail"] is None
