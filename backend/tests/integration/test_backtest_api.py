"""Backtest API contract — scanner selection + honest Deflated Sharpe (no network).

Two honesty gaps closed here:

* The ``scanner`` field on ``BacktestRequest`` actually changes which scanner
  the backtest runs (reversal vs scalping produce the engine's respective
  signal kinds), instead of always running the cached default-reversal engine.
* ``MetricsDTO.deflated_sharpe`` is the in-sample, ``n_trials=1`` Deflated
  Sharpe over the realized per-trade returns (same method as the CLI
  ``backtest`` command); present + in ``[0, 1]`` when there are >= 3 trades and
  honestly ``None`` for a degenerate sample, never fabricated.

A synthetic, deterministic bar series (seeded RNG with injected volume
climaxes) is fed through the REAL feature pipeline + SignalEngine via a fake
provider patched onto the service, so the assertions exercise the whole
scan -> simulate -> metrics path with no vendor call.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
import pytest
from fastapi.testclient import TestClient

from intradayx.api import service
from intradayx.data.providers.yfinance_provider import YFinanceProvider
from intradayx.domain.bars import BarSet, Timeframe
from intradayx.domain.capabilities import ProviderCapabilities


def _synthetic_bars(n: int = 400, *, seed: int = 42) -> BarSet:
    """A seeded random walk with periodic volume-climax up/down bars.

    Tuned so the scalping scanner triggers comfortably more than 3 trades
    (enough for the Deflated-Sharpe moments), while remaining fully
    deterministic across runs.
    """
    rng = np.random.default_rng(seed)
    from datetime import UTC, datetime

    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    price = 100.0
    o_, h_, l_, c_, v_, t_ = [], [], [], [], [], []
    for i in range(n):
        o = price
        c = price + float(rng.normal(0, 0.4))
        hi = max(o, c) + abs(float(rng.normal(0, 0.3)))
        lo = min(o, c) - abs(float(rng.normal(0, 0.3)))
        vol = int(abs(rng.normal(1000, 300)))
        if i % 23 == 0:  # bullish volume climax
            c = o + 3.0
            hi = c + 0.5
            vol *= 6
        if i % 29 == 0:  # bearish volume climax
            c = o - 3.0
            lo = c - 0.5
            vol *= 6
        t_.append(start + i * Timeframe.M5.timedelta)
        o_.append(float(o))
        h_.append(float(hi))
        l_.append(float(lo))
        c_.append(float(c))
        v_.append(vol)
        price = c
    df = pl.DataFrame(
        {
            "ts": t_,
            "open": o_,
            "high": h_,
            "low": l_,
            "close": c_,
            "volume": v_,
            "vwap": [None] * n,
            "trades": [None] * n,
            "source": ["test"] * n,
        }
    )
    return BarSet("TEST", Timeframe.M5, df)


class _FakeProvider:
    """Duck-typed provider: serves synthetic bars + real (static) capabilities."""

    def __init__(self, bars: BarSet) -> None:
        self._bars = bars
        self._caps = YFinanceProvider().capabilities()

    def capabilities(self) -> ProviderCapabilities:
        return self._caps

    def bars(self, *_args: object, **_kwargs: object) -> BarSet:
        return self._bars


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from intradayx.api.app import app

    fake = _FakeProvider(_synthetic_bars())
    # Bypass the lru_cache: patch the accessor the service actually calls.
    monkeypatch.setattr(service, "get_provider", lambda: fake)
    return TestClient(app)


def _post(client: TestClient, scanner: str) -> dict[str, Any]:
    resp = client.post(
        "/api/backtest",
        json={"symbol": "TEST", "timeframe": "5m", "days": 5, "max_hold": 24, "scanner": scanner},
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def test_scanner_param_changes_behavior(client: TestClient) -> None:
    scalp = _post(client, "scalping")
    rev = _post(client, "reversal")

    scalp_kinds = {t["kind"] for t in scalp["trades"]}
    rev_kinds = {t["kind"] for t in rev["trades"]}

    # The chosen scanner actually runs: scalping yields scalp_* signals/trades...
    assert scalp["n_signals"] > 0
    assert scalp_kinds  # at least one trade
    assert scalp_kinds <= {"scalp_long", "scalp_short"}
    # ...and reversal NEVER emits scalp_* kinds (a different engine ran). If the
    # scanner were ignored both calls would return the identical (reversal) set.
    assert not (rev_kinds & {"scalp_long", "scalp_short"})
    assert rev_kinds <= {"reversal_top", "reversal_bottom"}
    assert (scalp["n_signals"], scalp_kinds) != (rev["n_signals"], rev_kinds)


def test_deflated_sharpe_present_and_in_unit_interval(client: TestClient) -> None:
    body = _post(client, "scalping")
    m = body["metrics"]
    assert m["n_trades"] >= 3  # fixture guarantees enough trades for the moments
    assert m["n_trials"] == 1  # in-sample single run
    ds = m["deflated_sharpe"]
    assert ds is not None
    assert 0.0 <= ds <= 1.0


def test_backtest_returns_evidence_ledger_fields(client: TestClient) -> None:
    body = _post(client, "scalping")

    assert "learning" in body
    assert "baseline_metrics" in body
    assert body["n_raw_signals"] >= body["n_signals"]
    assert 0.0 <= body["data_completeness"] <= 1.0
    assert body["learning"]["selected_signals"] == body["n_signals"]

    trade = body["trades"][0]
    assert trade["signal_ts"]
    assert trade["side"] in {"buy", "sell", "short", "cover", "exit"}
    assert trade["attribution"]["summary"]
    assert trade.get("diagnosis")
    assert "entry_explanation" in trade
    assert "exit_explanation" in trade
    assert isinstance(trade["catalysts"], list)


def test_deflated_sharpe_none_for_degenerate_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    # A flat 2-bar series can produce at most 1 trade => < 3 returns => no moments.
    from tests.fixtures.synthetic import make_bars

    fake = _FakeProvider(make_bars(closes=[100.0, 100.0], timeframe=Timeframe.M5))
    monkeypatch.setattr(service, "get_provider", lambda: fake)
    from intradayx.api.app import app

    body = _post(TestClient(app), "scalping")
    m = body["metrics"]
    assert m["n_trades"] < 3
    assert m["deflated_sharpe"] is None  # honest, not a fabricated 0.0


def test_invalid_scanner_rejected(client: TestClient) -> None:
    resp = client.post("/api/backtest", json={"symbol": "TEST", "scanner": "momentum"})
    assert resp.status_code == 400


def test_learn_endpoint_returns_training_report(client: TestClient) -> None:
    resp = client.post(
        "/api/learn",
        json={
            "symbol": "TEST",
            "timeframe": "5m",
            "days": 5,
            "max_hold": 24,
            "scanner": "scalping",
            "min_samples": 5,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["symbol"] == "TEST"
    assert body["scanner"] == "scalping"
    assert body["n_samples"] >= 0
    assert "feature_importance" in body
