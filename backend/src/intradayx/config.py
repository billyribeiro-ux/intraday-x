"""Typed, env-driven configuration — one source of truth.

All operational knobs (which data vendors, in what priority; watched symbols;
poll interval; lake location; log level) live here instead of being scattered as
hardcoded constants. Override any field via an ``INTRADAYX_`` env var or a
``.env`` file, e.g. ``INTRADAYX_PROVIDERS='["polygon","yfinance"]'`` or
``INTRADAYX_WATCHED_SYMBOLS='["NVDA","TSLA"]'``.

Vendor *credentials* (``ALPACA_API_KEY``, ``POLYGON_API_KEY``, …) stay as their
own conventional env vars, read by each provider — this object only decides which
vendors to *try* and in what order.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INTRADAYX_",
        env_file=(".env", "../.env"),  # run from repo root or backend/
        extra="ignore",
    )

    # Data-vendor priority order (lower index = preferred). Unknown names and
    # vendors whose credentials are absent are skipped; yfinance is the floor.
    providers: list[str] = ["polygon", "alpaca", "yfinance"]

    # Live monitor.
    watched_symbols: list[str] = ["AAPL", "SPY"]
    poll_interval_s: int = 30

    # Storage + logging.
    data_dir: Path = Path("data/lake")
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
