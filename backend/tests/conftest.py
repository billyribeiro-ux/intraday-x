"""Shared test config — block real network by default.

Tests that genuinely need a vendor must be marked ``@pytest.mark.network`` and
are skipped in the default run. Everything else fails loud if it tries to open a
socket, so a stray real yfinance/Alpaca call can't sneak into the unit suite.
"""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("network"):
        return

    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network is blocked in tests; mark with @pytest.mark.network")

    monkeypatch.setattr(socket, "socket", _blocked)
