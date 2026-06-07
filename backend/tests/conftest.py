"""Shared test config — block real network by default.

Tests that genuinely need a vendor must be marked ``@pytest.mark.network`` and
are skipped in the default run. Everything else fails loud if it tries to OPEN A
CONNECTION, so a stray real yfinance/vendor call can't sneak into the suite. We
block ``connect``/``connect_ex`` (outbound), not socket *creation* — so local
machinery like the asyncio event loop's self-pipe still works.
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

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
