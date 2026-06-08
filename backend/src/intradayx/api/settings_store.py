"""Persistence for desktop-managed settings (theme, vendor keys, scanner defaults).

The desktop app must let the user manage theme, multi-vendor API keys, and
scanner defaults WITHOUT a terminal or editing ``.env``. This module owns the
on-disk store (JSON in the OS app-data dir, mode 0o600 because it holds API
keys), the vendor-name -> env-var mapping, and the two side effects that make a
key take effect live: pushing keys into ``os.environ`` and rebuilding the
provider singleton (so no restart is needed).

NEVER log a key value. The store file is chmod 0o600 on every save.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from intradayx.config import get_settings
from intradayx.data.registry import registered_names

logger = logging.getLogger(__name__)

_APP_ID = "com.intradayx.desktop"
_FILENAME = "settings.json"

# Vendor name -> the env var its provider reads via os.environ.get(...). yfinance
# is credential-free (no env var, always configured) so it is intentionally
# absent. Mirrors the providers' own os.environ lookups; keep in sync if a new
# keyed vendor is registered.
VENDOR_ENV_VARS: dict[str, str] = {
    "twelvedata": "TWELVEDATA_API_KEY",
    "polygon": "POLYGON_API_KEY",
}

VALID_THEMES = ("dark", "light", "system")
VALID_SCANNERS = ("reversal", "scalping")


def app_data_dir() -> Path:
    """Return (creating if missing) the OS app-data dir for the desktop app.

    macOS: ``~/Library/Application Support/com.intradayx.desktop/``. Other
    platforms fall back to ``~/.intradayx`` (a sensible, hidden home dir) so the
    engine still works when run outside the bundled desktop app.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / _APP_ID
    else:
        base = Path.home() / ".intradayx"
    base.mkdir(parents=True, exist_ok=True)
    return base


def settings_path() -> Path:
    return app_data_dir() / _FILENAME


@dataclass
class StoredSettings:
    """The persisted shape. Defaults mirror :mod:`intradayx.config`.

    ``vendor_keys`` maps a vendor name to its raw API key — this is the sensitive
    part of the file (hence chmod 0o600 on save, and never logged).
    """

    theme: str = "system"
    providers: list[str] = field(default_factory=lambda: list(get_settings().providers))
    watched_symbols: list[str] = field(
        default_factory=lambda: list(get_settings().watched_symbols)
    )
    default_scanner: str = "reversal"
    vendor_keys: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredSettings:
        defaults = cls()
        return cls(
            theme=str(data.get("theme", defaults.theme)),
            providers=list(data.get("providers", defaults.providers)),
            watched_symbols=list(data.get("watched_symbols", defaults.watched_symbols)),
            default_scanner=str(data.get("default_scanner", defaults.default_scanner)),
            vendor_keys=dict(data.get("vendor_keys", {})),
        )


def load_settings() -> StoredSettings:
    """Load the store, returning defaults if the file is missing or unreadable.

    A corrupt/unreadable file degrades to defaults (the app stays usable) but we
    log the failure WITHOUT echoing file contents (it holds keys).
    """
    path = settings_path()
    if not path.exists():
        return StoredSettings()
    try:
        raw = path.read_text(encoding="utf-8")
        data: dict[str, Any] = json.loads(raw)
    except (OSError, ValueError) as exc:
        logger.warning("settings store unreadable (%s); using defaults", type(exc).__name__)
        return StoredSettings()
    return StoredSettings.from_dict(data)


def save_settings(stored: StoredSettings) -> None:
    """Write the store as JSON and chmod 0o600 — it holds API keys.

    Never logs key values.
    """
    path = settings_path()
    path.write_text(json.dumps(asdict(stored), indent=2), encoding="utf-8")
    os.chmod(path, 0o600)


def apply_to_env(stored: StoredSettings) -> None:
    """Push stored vendor keys into os.environ under each vendor's env var.

    Only known/keyed vendors are mapped; an empty key clears the var so a deleted
    key really drops the vendor. Never logs key values.
    """
    for vendor, env_var in VENDOR_ENV_VARS.items():
        key = stored.vendor_keys.get(vendor)
        if key:
            os.environ[env_var] = key
        else:
            os.environ.pop(env_var, None)


def rebuild_provider() -> None:
    """Make new keys/providers take effect live (no restart).

    Clears the ``get_settings`` lru_cache (so a changed providers list is re-read)
    and resets the provider singleton in :mod:`intradayx.api.service` (the
    ``get_provider`` lru_cache), then rebuilds it so the next request gets a
    CompositeProvider assembled from the current env + settings.
    """
    from intradayx.api import service
    from intradayx.data.registry import build_provider

    get_settings.cache_clear()
    service.get_provider.cache_clear()
    # Eagerly rebuild so a misconfiguration surfaces now, not on the next request.
    build_provider()


def vendor_is_configured(vendor: str) -> bool:
    """Whether a vendor currently has a usable key.

    Mirrors each provider's ``is_configured()``: a credential-free vendor
    (no env var, e.g. yfinance) is always configured; a keyed vendor is
    configured iff its env var is set and non-empty.
    """
    env_var = VENDOR_ENV_VARS.get(vendor)
    if env_var is None:
        return True
    return bool(os.environ.get(env_var))


def vendor_status() -> list[dict[str, Any]]:
    """List every registered provider with its env var and configured flag."""
    out: list[dict[str, Any]] = []
    for name in registered_names():
        out.append(
            {
                "name": name,
                "env_var": VENDOR_ENV_VARS.get(name),
                "configured": vendor_is_configured(name),
            }
        )
    return out
