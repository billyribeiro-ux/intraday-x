"""Typed, env-driven configuration — one source of truth.

All operational knobs (watched symbols, poll interval, lake location, log level)
live here instead of being scattered as hardcoded constants. Override fields via
an ``INTRADAYX_`` env var or a ``.env`` file, e.g.
``INTRADAYX_WATCHED_SYMBOLS='["NVDA","TSLA"]'``.

FMP is the canonical market-data provider. Its credential stays in
``FMP_API_KEY`` so the provider can read it directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load a .env file into os.environ. Providers read their credentials
# (FMP_API_KEY) via os.environ directly — NOT through the Settings object below.
# override=False so a real shell env var still wins over the file. Mirrors the
# env_file tuple below.
load_dotenv(".env", override=False)
load_dotenv("../.env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INTRADAYX_",
        env_file=(".env", "../.env"),  # run from repo root or backend/
        extra="ignore",
    )

    # Market-data provider. Runtime data is locked to FMP; a missing FMP key fails
    # loudly instead of silently falling back to a different data source.
    providers: list[str] = ["fmp"]

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
