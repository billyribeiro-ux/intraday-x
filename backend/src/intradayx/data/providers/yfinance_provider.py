"""yfinance provider — the zero-setup demo source.

Honest limits (declared via capabilities so the rest of the system degrades
cleanly): 1m history ≈ last 7 days, 5m/15m/30m ≈ 60 days, 1h ≈ 730 days, daily
to IPO. NO market internals, NO options history. yfinance scrapes an unofficial
Yahoo endpoint ("personal use only") — fine for prototyping, not production.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import polars as pl
import yfinance as yf

from intradayx.data.provider import DataProvider, Session
from intradayx.domain.bars import BAR_SCHEMA, BarSet, Timeframe
from intradayx.domain.capabilities import Capability, ProviderCapabilities

logger = logging.getLogger(__name__)

_INTERVAL: dict[Timeframe, str] = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "1h",
    Timeframe.D1: "1d",
}


def _empty_barset(ticker: str, timeframe: Timeframe) -> BarSet:
    return BarSet(ticker, timeframe, pl.DataFrame(schema=BAR_SCHEMA))


class YFinanceProvider(DataProvider):
    name = "yfinance"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name=self.name,
            supported=frozenset(
                {
                    Capability.DAILY_BARS,
                    Capability.INTRADAY_BARS_1M,
                    Capability.INTRADAY_BARS_5M,
                    Capability.PREPOST_MARKET,
                    Capability.OPTIONS_CHAIN_LIVE,
                    Capability.EARNINGS_CALENDAR,
                    Capability.LIVE_STREAM,  # poll-only
                }
            ),
            max_intraday_lookback={
                Timeframe.M1: timedelta(days=7),
                Timeframe.M5: timedelta(days=60),
                Timeframe.M15: timedelta(days=60),
                Timeframe.M30: timedelta(days=60),
                Timeframe.H1: timedelta(days=730),
            },
            rate_limit_hint="unofficial scrape; ~2 req/s, throttles aggressively",
        )

    def bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
        *,
        session: Session = Session.RTH,
        adjust: bool = True,
        now: datetime | None = None,  # lookback routing is the composite's job
    ) -> BarSet:
        if timeframe.is_intraday:
            self._check_lookback(start, timeframe, datetime.now(tz=UTC))

        raw = yf.Ticker(ticker).history(
            start=start,
            end=end,
            interval=_INTERVAL[timeframe],
            prepost=(session == Session.ALL),
            auto_adjust=adjust,
            actions=False,
            raise_errors=False,
        )
        if raw is None or raw.empty:
            return _empty_barset(ticker, timeframe)

        raw = raw.reset_index()
        dtcol = "Datetime" if "Datetime" in raw.columns else "Date"
        ts = pd.to_datetime(raw[dtcol], utc=True)  # tz-aware → UTC; naive → localized UTC

        pdf = pd.DataFrame(
            {
                "ts": ts,
                "open": raw["Open"].astype("float64"),
                "high": raw["High"].astype("float64"),
                "low": raw["Low"].astype("float64"),
                "close": raw["Close"].astype("float64"),
                "volume": raw["Volume"].fillna(0).astype("int64"),
            }
        ).dropna(subset=["open", "high", "low", "close"])

        frame = pl.from_pandas(pdf).with_columns(
            vwap=pl.lit(None, dtype=pl.Float64),
            trades=pl.lit(None, dtype=pl.Int64),
            source=pl.lit(self.name),
        )
        return BarSet(ticker, timeframe, frame)

    def earnings_dates(self, ticker: str) -> list[date]:
        try:
            df = yf.Ticker(ticker).get_earnings_dates(limit=24)
        except Exception as exc:  # best-effort, but log — never fail silently
            logger.warning("earnings fetch failed for %s: %s", ticker, exc)
            return []
        if df is None or df.empty:
            return []
        # Index is the earnings datetime (US/Eastern). Use the NY session date.
        idx = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
        return sorted({d.date() for d in idx})
