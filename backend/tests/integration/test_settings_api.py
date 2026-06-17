"""Settings store round-trip + FastAPI endpoint contract (no network).

Covers: tmp-path-backed save/load + chmod 0o600 on the store; and the
GET/PUT/POST vendor-key/DELETE contract via TestClient, asserting the
``configured`` flag flips with a key and that NO key value ever appears in a
response body.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from intradayx.api import settings_store
from intradayx.api.settings_store import StoredSettings

_SECRET = "fmp-secret-key-abc123"


@pytest.fixture(autouse=True)
def _tmp_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the store at a tmp dir and clear any keyed env vars between tests."""
    monkeypatch.setattr(settings_store, "app_data_dir", lambda: tmp_path)
    for env_var in settings_store.VENDOR_ENV_VARS.values():
        monkeypatch.delenv(env_var, raising=False)


def test_store_round_trip_and_chmod() -> None:
    stored = StoredSettings(
        theme="dark",
        providers=["yfinance"],
        watched_symbols=["NVDA"],
        default_scanner="scalping",
        vendor_keys={"twelvedata": _SECRET},
    )
    settings_store.save_settings(stored)

    path = settings_store.settings_path()
    assert path.exists()
    # 0o600: holds API keys, must not be group/world readable.
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600

    loaded = settings_store.load_settings()
    assert loaded.theme == stored.theme
    assert loaded.providers == ["fmp"]
    assert loaded.watched_symbols == stored.watched_symbols
    assert loaded.default_scanner == stored.default_scanner
    assert loaded.vendor_keys == {}


def test_load_missing_returns_defaults() -> None:
    loaded = settings_store.load_settings()
    assert loaded.theme == "system"
    assert loaded.default_scanner == "reversal"
    assert loaded.vendor_keys == {}


@pytest.fixture
def client() -> TestClient:
    # Import here so the autouse tmp-dir patch is already applied.
    from intradayx.api.app import app

    return TestClient(app)


def test_get_settings_lists_vendors(client: TestClient) -> None:
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"] == "system"
    assert body["default_scanner"] == "reversal"
    names = {v["name"]: v for v in body["vendors"]}
    assert set(names) == {"fmp"}
    assert names["fmp"]["configured"] is False
    assert names["fmp"]["env_var"] == "FMP_API_KEY"


def test_put_settings_validates_and_persists(client: TestClient) -> None:
    resp = client.put(
        "/api/settings",
        json={
            "theme": "light",
            "watched_symbols": ["tsla", "spy"],
            "default_scanner": "scalping",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"] == "light"
    assert body["watched_symbols"] == ["TSLA", "SPY"]
    assert body["default_scanner"] == "scalping"

    # Bad theme is rejected loud.
    assert client.put("/api/settings", json={"theme": "neon"}).status_code == 400
    # Unknown provider is rejected loud.
    assert client.put("/api/settings", json={"providers": ["alpaca"]}).status_code == 400


def test_vendor_key_set_flips_configured_and_hides_key(client: TestClient) -> None:
    resp = client.post(
        "/api/settings/vendor-key",
        json={"vendor": "fmp", "api_key": _SECRET},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"vendor": "fmp", "configured": True}
    assert _SECRET not in resp.text  # key value must never be echoed

    # The key took effect live: env var set + GET reflects configured.
    assert os.environ.get("FMP_API_KEY") == _SECRET
    get_body = client.get("/api/settings").json()
    assert _SECRET not in client.get("/api/settings").text
    fmp = next(v for v in get_body["vendors"] if v["name"] == "fmp")
    assert fmp["configured"] is True

    # And it persisted to the store file (the value lives there, not in responses).
    assert settings_store.load_settings().vendor_keys["fmp"] == _SECRET


def test_vendor_key_delete_flips_back(client: TestClient) -> None:
    client.post("/api/settings/vendor-key", json={"vendor": "fmp", "api_key": _SECRET})
    resp = client.delete("/api/settings/vendor-key/fmp")
    assert resp.status_code == 200
    assert resp.json() == {"vendor": "fmp", "configured": False}

    assert "FMP_API_KEY" not in os.environ
    assert "fmp" not in settings_store.load_settings().vendor_keys
    fmp = next(v for v in client.get("/api/settings").json()["vendors"] if v["name"] == "fmp")
    assert fmp["configured"] is False


def test_vendor_key_unknown_vendor_rejected(client: TestClient) -> None:
    resp = client.post("/api/settings/vendor-key", json={"vendor": "yfinance", "api_key": "x"})
    assert resp.status_code == 400
    assert client.delete("/api/settings/vendor-key/yfinance").status_code == 400


def test_app_starts_without_fmp_key_and_reports_configuration_gap() -> None:
    from intradayx.api.app import app

    with TestClient(app) as live_client:
        assert live_client.get("/healthz").status_code == 200
        assert live_client.get("/api/settings").status_code == 200

        caps = live_client.get("/api/providers/capabilities")
        assert caps.status_code == 503
        assert "FMP_API_KEY is required" in caps.json()["detail"]

        with live_client.websocket_connect("/ws/signals") as ws:
            status = ws.receive_json()
            assert status["type"] == "status"
            assert status["data"]["source"] == "fmp"
            assert status["data"]["configured"] is False
            assert "FMP_API_KEY is required" in status["data"]["detail"]


def test_app_startup_applies_persisted_fmp_key() -> None:
    from intradayx.api.app import app

    settings_store.save_settings(StoredSettings(vendor_keys={"fmp": _SECRET}))

    with TestClient(app) as live_client:
        caps = live_client.get("/api/providers/capabilities")
        assert caps.status_code == 200
        assert caps.json()["provider"] == "fmp"
        assert _SECRET not in caps.text

        with live_client.websocket_connect("/ws/signals") as ws:
            status = ws.receive_json()
            assert status["type"] == "status"
            assert status["data"]["source"] == "fmp"
            assert status["data"]["configured"] is True
            assert status["data"]["detail"] is None
