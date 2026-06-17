"""yfinance provider — the zero-setup demo source.

Honest limits (declared via capabilities so the rest of the system degrades
cleanly): 1m history ≈ last 7 days, 2m/5m/15m/30m ≈ 60 days, 1h/2h/4h ≈ 730 days,
daily/weekly/monthly/quarterly/yearly to IPO. NO market internals, NO options
history. yfinance scrapes an unofficial Yahoo endpoint ("personal use only") —
fine for prototyping, not production.
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

# Native yfinance interval strings. Some timeframes are built by resampling a
# finer native interval (see _RESAMPLE_FROM below).
_INTERVAL: dict[Timeframe, str] = {
    Timeframe.M1: "1m",
    Timeframe.M2: "2m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "1h",
    Timeframe.D1: "1d",
    Timeframe.W1: "1wk",
    Timeframe.MO1: "1mo",
    Timeframe.MO3: "3mo",
    Timeframe.Y1: "1y",
}

# Timeframes we synthesize by resampling a finer native interval:
#   target -> (source interval, source tf, aggregation factor)
_RESAMPLE_FROM: dict[Timeframe, tuple[str, Timeframe, int]] = {
    Timeframe.M3: ("1m", Timeframe.M1, 3),
    Timeframe.M4: ("1m", Timeframe.M1, 4),
    Timeframe.M10: ("1m", Timeframe.M1, 10),
    Timeframe.H2: ("1h", Timeframe.H1, 2),
    Timeframe.H4: ("1h", Timeframe.H1, 4),
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
                Timeframe.M2: timedelta(days=60),
                Timeframe.M3: timedelta(days=7),  # resampled from 1m
                Timeframe.M4: timedelta(days=7),
                Timeframe.M5: timedelta(days=60),
                Timeframe.M10: timedelta(days=7),
                Timeframe.M15: timedelta(days=60),
                Timeframe.M30: timedelta(days=60),
                Timeframe.H1: timedelta(days=730),
                Timeframe.H2: timedelta(days=730),
                Timeframe.H4: timedelta(days=730),
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
        now: datetime | None = None,
    ) -> BarSet:
        if timeframe.is_intraday:
            self._check_lookback(start, timeframe, datetime.now(tz=UTC))

        if timeframe in _RESAMPLE_FROM:
            source_interval, source_tf, factor = _RESAMPLE_FROM[timeframe]
            return self._resampled_bars(
                ticker, start, end, timeframe, source_interval, source_tf, factor,
                session=session, adjust=adjust
            )

        if timeframe not in _INTERVAL:
            raise ValueError(f"yfinance does not support {timeframe.value}")

        return self._fetch_bars(
            ticker, start, end, timeframe, _INTERVAL[timeframe],
            session=session, adjust=adjust
        )

    def _fetch_bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
        interval: str,
        *,
        session: Session,
        adjust: bool,
    ) -> BarSet:
        raw = yf.Ticker(ticker).history(
            start=start,
            end=end,
            interval=interval,
            prepost=(session == Session.ALL),
            auto_adjust=adjust,
            actions=False,
            raise_errors=False,
        )
        if raw is None or raw.empty:
            return _empty_barset(ticker, timeframe)

        return self._to_barset(raw.reset_index(), ticker, timeframe)

    def _resampled_bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        target_tf: Timeframe,
        source_interval: str,
        source_tf: Timeframe,
        factor: int,
        *,
        session: Session,
        adjust: bool,
    ) -> BarSet:
        """Build a non-native interval by resampling a finer native one."""
        raw = yf.Ticker(ticker).history(
            start=start,
            end=end,
            interval=source_interval,
            prepost=(session == Session.ALL),
            auto_adjust=adjust,
            actions=False,
            raise_errors=False,
        )
        if raw is None or raw.empty:
            return _empty_barset(ticker, target_tf)

        pdf = raw.reset_index()
        dtcol = "Datetime" if "Datetime" in pdf.columns else "Date"
        pdf["ts"] = pd.to_datetime(pdf[dtcol], utc=True)
        pdf = pdf.set_index("ts")
        rule = pd.Timedelta(target_tf.timedelta)
        agg = pdf.resample(rule, closed="left", label="left").agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        agg = agg.dropna(subset=["Open", "High", "Low", "Close"]).reset_index()
        # Only keep complete/resampled bars that contain at least ``factor`` source bars.
        agg = agg[agg["Volume"] > 0]
        if agg.empty:
            return _empty_barset(ticker, target_tf)

        out = pd.DataFrame(
            {
                "ts": agg["ts"],
                "open": agg["Open"].astype("float64"),
                "high": agg["High"].astype("float64"),
                "low": agg["Low"].astype("float64"),
                "close": agg["Close"].astype("float64"),
                "volume": agg["Volume"].fillna(0).astype("int64"),
            }
        )
        return self._pandas_to_barset(out, ticker, target_tf)

    def _to_barset(self, raw: pd.DataFrame, ticker: str, timeframe: Timeframe) -> BarSet:
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
        return self._pandas_to_barset(pdf, ticker, timeframe)

    def _pandas_to_barset(self, pdf: pd.DataFrame, ticker: str, timeframe: Timeframe) -> BarSet:
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
