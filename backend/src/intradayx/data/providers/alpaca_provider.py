"""Alpaca provider — the free, multi-year 1-minute backbone (Phase 1).

Alpaca's free tier (IEX feed) gives ~7–10 years of 1-minute equity/ETF bars,
which is what turns this from a 7-day yfinance demo into a real backtest. Needs
``ALPACA_API_KEY`` + ``ALPACA_SECRET_KEY`` in the environment; ``capabilities()``
works without them, but ``bars()`` raises :class:`MissingCredentialsError` so a
missing key fails loud rather than silently returning nothing.

``alpaca-py`` is an optional extra; imports are lazy so a base-only install can
still import this module (and report the credential/extra requirement clearly).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from intradayx.data.provider import (
    DataError,
    DataProvider,
    MissingCredentialsError,
    Session,
)
from intradayx.domain.bars import BAR_SCHEMA, BarSet, Timeframe
from intradayx.domain.capabilities import Capability, ProviderCapabilities

# ~9 years — generous; an older request gets a clear LookbackExceededError
# rather than a silently short window.
_DEEP = timedelta(days=3300)


class AlpacaProvider(DataProvider):
    name = "alpaca"

    def __init__(self, api_key: str | None = None, secret_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY")
        self._secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY")
        self._client: Any = None

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name=self.name,
            supported=frozenset(
                {
                    Capability.DAILY_BARS,
                    Capability.INTRADAY_BARS_1M,
                    Capability.INTRADAY_BARS_5M,
                    Capability.EXTENDED_HISTORY_INTRADAY,
                    Capability.PREPOST_MARKET,
                    Capability.LIVE_STREAM,
                }
            ),
            max_intraday_lookback={
                Timeframe.M1: _DEEP,
                Timeframe.M5: _DEEP,
                Timeframe.M15: _DEEP,
                Timeframe.M30: _DEEP,
                Timeframe.H1: _DEEP,
            },
            rate_limit_hint="free IEX feed; 200 req/min",
        )

    def _get_client(self) -> Any:
        if not self._api_key or not self._secret_key:
            raise MissingCredentialsError(
                "Alpaca needs ALPACA_API_KEY and ALPACA_SECRET_KEY in the environment "
                "(free at alpaca.markets). Install the extra with `uv sync --extra alpaca`."
            )
        if self._client is None:
            from alpaca.data.historical import StockHistoricalDataClient

            self._client = StockHistoricalDataClient(self._api_key, self._secret_key)
        return self._client

    @staticmethod
    def _timeframe(tf: Timeframe) -> Any:
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        return {
            Timeframe.M1: TimeFrame(1, TimeFrameUnit.Minute),
            Timeframe.M5: TimeFrame(5, TimeFrameUnit.Minute),
            Timeframe.M15: TimeFrame(15, TimeFrameUnit.Minute),
            Timeframe.M30: TimeFrame(30, TimeFrameUnit.Minute),
            Timeframe.H1: TimeFrame(1, TimeFrameUnit.Hour),
            Timeframe.D1: TimeFrame(1, TimeFrameUnit.Day),
        }[tf]

    def bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
        *,
        session: Session = Session.RTH,
        adjust: bool = True,
    ) -> BarSet:
        client = self._get_client()
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.requests import StockBarsRequest

        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=self._timeframe(timeframe),
            start=start,
            end=end,
            adjustment=Adjustment.ALL if adjust else Adjustment.RAW,
            feed=DataFeed.IEX,  # free tier
        )
        try:
            resp = client.get_stock_bars(req)
        except Exception as exc:  # alpaca raises various API errors
            raise DataError(f"alpaca get_stock_bars failed for {ticker}: {exc}") from exc

        pdf = resp.df
        if pdf is None or pdf.empty:
            return BarSet(ticker, timeframe, pl.DataFrame(schema=BAR_SCHEMA))

        # resp.df is a (symbol, timestamp) multi-index frame. Pull whatever
        # columns Alpaca gives us, convert once, then normalize in Polars.
        pdf = pdf.reset_index()
        ts_col = "timestamp" if "timestamp" in pdf.columns else pdf.columns[1]
        keep = [ts_col, "open", "high", "low", "close", "volume"]
        keep += [c for c in ("vwap", "trade_count") if c in pdf.columns]
        frame = pl.from_pandas(pdf[keep]).rename({ts_col: "ts"})

        exprs = [pl.col("volume").cast(pl.Int64), pl.lit(self.name).alias("source")]
        exprs.append(
            pl.col("vwap").cast(pl.Float64)
            if "vwap" in frame.columns
            else pl.lit(None, dtype=pl.Float64).alias("vwap")
        )
        exprs.append(
            pl.col("trade_count").cast(pl.Int64).alias("trades")
            if "trade_count" in frame.columns
            else pl.lit(None, dtype=pl.Int64).alias("trades")
        )
        # BarSet._coerce keeps only the canonical columns (drops leftover trade_count).
        return BarSet(ticker, timeframe, frame.with_columns(exprs))
