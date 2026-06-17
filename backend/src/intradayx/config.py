"""Typed, env-driven configuration — one source of truth.

All operational knobs (which data vendors, in what priority; watched symbols;
poll interval; lake location; log level) live here instead of being scattered as
hardcoded constants. Override any field via an ``INTRADAYX_`` env var or a
``.env`` file, e.g. ``INTRADAYX_PROVIDERS='["polygon","yfinance"]'`` or
``INTRADAYX_WATCHED_SYMBOLS='["NVDA","TSLA"]'``.

Vendor *credentials* (``TWELVEDATA_API_KEY``, ``POLYGON_API_KEY``, …) stay as
their own conventional env vars, read by each provider — this object only decides
which vendors to *try* and in what order.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load a .env file into os.environ. Providers read their credentials
# (TWELVEDATA_API_KEY, POLYGON_API_KEY, …) via os.environ directly — NOT through
# the Settings object below — so without this a key in .env would silently never
# reach the provider (it would fall back to yfinance). override=False so a real
# shell env var still wins over the file. Mirrors the env_file tuple below.
load_dotenv(".env", override=False)
load_dotenv("../.env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INTRADAYX_",
        env_file=(".env", "../.env"),  # run from repo root or backend/
        extra="ignore",
    )

    # Data-vendor priority order (lower index = preferred). Unknown names and
    # vendors whose credentials are absent are skipped; yfinance is the floor.
    # Default is free, NON-BROKER data vendors only: Twelve Data (free key,
    # multi-year 1m since 2020) preferred for depth, yfinance (no key) as the
    # zero-setup floor. Polygon and FMP (pure data vendors) are preferred if their
    # keys are set; unconfigured ones are skipped, so the floor stays yfinance.
    # No brokers — add new data vendors via register_provider + INTRADAYX_PROVIDERS.
    providers: list[str] = ["polygon", "twelvedata", "fmp", "yfinance"]

    # Live monitor.
    watched_symbols: list[str] = ["AAPL", "SPY"]
    poll_interval_s: int = 30
    # Live ingestion CHOICE: "poll" (REST every poll_interval_s) or "stream"
    # (consume a websocket feed). Stream mode needs stream_ws_url.
    live_mode: str = "poll"
    stream_ws_url: str = ""  # wss:// vendor feed for stream mode
    stream_timeframe: str = "1m"

    # Storage + logging.
    data_dir: Path = Path("data/lake")
    cache_enabled: bool = False  # read-through lake cache (serve cached, fetch gaps)
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
