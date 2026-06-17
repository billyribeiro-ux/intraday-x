"""Settings routes: manage theme, multi-vendor API keys, and scanner defaults.

Lets the desktop Settings screen drive the engine without a terminal or .env
edit. Keys are persisted (chmod 0o600), pushed into os.environ, and the provider
is rebuilt so a new key takes effect live. A key value is NEVER echoed back in
any response.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from intradayx.api import settings_store
from intradayx.api.settings_store import (
    VALID_SCANNERS,
    VALID_THEMES,
    VENDOR_ENV_VARS,
    StoredSettings,
)
from intradayx.data.registry import registered_names

router = APIRouter(prefix="/api", tags=["settings"])


# --- response/request models ---


class VendorStatusDTO(BaseModel):
    name: str
    env_var: str | None  # None for credential-free vendors (yfinance)
    configured: bool


class SettingsResponse(BaseModel):
    theme: str
    providers: list[str]
    watched_symbols: list[str]
    default_scanner: str
    vendors: list[VendorStatusDTO]


class SettingsUpdateRequest(BaseModel):
    theme: str | None = None
    providers: list[str] | None = None
    watched_symbols: list[str] | None = None
    default_scanner: str | None = None


class VendorKeyRequest(BaseModel):
    vendor: str
    api_key: str


class VendorKeyResponse(BaseModel):
    vendor: str
    configured: bool


# --- helpers ---


def _to_response(stored: StoredSettings) -> SettingsResponse:
    return SettingsResponse(
        theme=stored.theme,
        providers=stored.providers,
        watched_symbols=stored.watched_symbols,
        default_scanner=stored.default_scanner,
        vendors=[VendorStatusDTO(**v) for v in settings_store.vendor_status()],
    )


# --- endpoints ---


@router.get("/settings", response_model=SettingsResponse)
def get_settings_endpoint() -> SettingsResponse:
    return _to_response(settings_store.load_settings())


@router.put("/settings", response_model=SettingsResponse)
def update_settings(req: SettingsUpdateRequest) -> SettingsResponse:
    stored = settings_store.load_settings()

    if req.theme is not None:
        if req.theme not in VALID_THEMES:
            raise HTTPException(
                status_code=400, detail=f"theme must be one of {list(VALID_THEMES)}"
            )
        stored.theme = req.theme

    if req.providers is not None:
        known = set(registered_names())
        unknown = [p for p in req.providers if p not in known]
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"unknown providers: {unknown} (known: {sorted(known)})"
            )
        if not req.providers:
            raise HTTPException(status_code=400, detail="providers must not be empty")
        stored.providers = req.providers

    if req.watched_symbols is not None:
        symbols = [s.strip().upper() for s in req.watched_symbols if s.strip()]
        if not symbols:
            raise HTTPException(status_code=400, detail="watched_symbols must not be empty")
        stored.watched_symbols = symbols

    if req.default_scanner is not None:
        if req.default_scanner not in VALID_SCANNERS:
            raise HTTPException(
                status_code=400, detail=f"default_scanner must be one of {list(VALID_SCANNERS)}"
            )
        stored.default_scanner = req.default_scanner

    settings_store.save_settings(stored)
    # A changed providers list must take effect live (no restart).
    settings_store.apply_to_env(stored)
    settings_store.rebuild_provider()
    return _to_response(stored)


@router.post("/settings/vendor-key", response_model=VendorKeyResponse)
def set_vendor_key(req: VendorKeyRequest) -> VendorKeyResponse:
    if req.vendor not in VENDOR_ENV_VARS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"vendor {req.vendor!r} takes no API key "
                f"(keyed vendors: {sorted(VENDOR_ENV_VARS)})"
            ),
        )
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="api_key must not be empty")

    stored = settings_store.load_settings()
    stored.vendor_keys[req.vendor] = key
    settings_store.save_settings(stored)
    settings_store.apply_to_env(stored)
    settings_store.rebuild_provider()
    # NEVER echo the key — only whether the vendor is now configured.
    return VendorKeyResponse(
        vendor=req.vendor, configured=settings_store.vendor_is_configured(req.vendor)
    )


@router.delete("/settings/vendor-key/{vendor}", response_model=VendorKeyResponse)
def delete_vendor_key(vendor: str) -> VendorKeyResponse:
    if vendor not in VENDOR_ENV_VARS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"vendor {vendor!r} takes no API key (keyed vendors: {sorted(VENDOR_ENV_VARS)})"
            ),
        )
    stored = settings_store.load_settings()
    stored.vendor_keys.pop(vendor, None)
    settings_store.save_settings(stored)
    settings_store.apply_to_env(stored)
    settings_store.rebuild_provider()
    return VendorKeyResponse(vendor=vendor, configured=False)


class VendorKeyValueResponse(BaseModel):
    vendor: str
    api_key: str


@router.get("/settings/vendor-key/{vendor}/value", response_model=VendorKeyValueResponse)
def get_vendor_key_value(vendor: str) -> VendorKeyValueResponse:
    """Return the raw API key for a vendor so the desktop UI can open vendor
    streaming endpoints (e.g. FMP WebSocket). Only keyed vendors are supported.
    The request is still local to the bundled app; the key never leaves the host.
    """
    if vendor not in VENDOR_ENV_VARS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"vendor {vendor!r} takes no API key (keyed vendors: {sorted(VENDOR_ENV_VARS)})"
            ),
        )
    stored = settings_store.load_settings()
    key = stored.vendor_keys.get(vendor) or os.environ.get(VENDOR_ENV_VARS[vendor])
    if not key:
        raise HTTPException(status_code=404, detail=f"no API key configured for {vendor}")
    return VendorKeyValueResponse(vendor=vendor, api_key=key)
