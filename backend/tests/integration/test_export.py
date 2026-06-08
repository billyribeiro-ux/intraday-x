"""CSV golden-ish + PDF structural tests for the export layer."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from intradayx.attribution.engine import reversal_attribution
from intradayx.backtest.runner import simulate_trades
from intradayx.domain.bars import Timeframe
from intradayx.domain.signals import Side, Signal, SignalKind, uncertain_attribution
from intradayx.export.csv_export import signals_to_csv, trades_to_csv
from intradayx.export.pdf_report import backtest_report_pdf
from intradayx.signals.params import ReversalParams
from tests.fixtures.synthetic import make_bars


def _signal() -> Signal:
    attr = reversal_attribution(
        is_top=True,
        c_climax=0.9,
        c_volume=1.0,
        c_value_area=1.0,
        c_poc=0.0,
        params=ReversalParams(),
        data_completeness=0.5,
    )
    return Signal.create(
        symbol="TEST",
        ts=datetime(2024, 1, 2, 16, 0, tzinfo=UTC),
        kind=SignalKind.REVERSAL_TOP,
        side=Side.SELL,
        confidence=0.42,
        entry=100.0,
        stop=101.25,
        targets=(98.0, 97.0),
        time_of_day_bucket="lunch",
        attribution=attr,
    )


def test_signals_csv_fields(tmp_path: Path) -> None:
    s = _signal()
    out = tmp_path / "signals.csv"
    assert signals_to_csv([s], out) == 1
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    r = rows[0]
    assert r["signal_id"] == s.signal_id
    assert r["kind"] == "reversal_top"
    assert r["side"] == "sell"
    assert r["confidence"] == "0.4200"
    assert r["targets"] == "98.0000|97.0000"
    assert r["primary_cause"] == "climax_reversal"
    assert r["data_completeness"] == "0.50"
    assert r["uncertain"] == "False"


def _result():  # type: ignore[no-untyped-def]
    bars = make_bars(
        closes=[100, 100, 100, 101, 100, 100],
        opens=[100, 100, 100, 100, 100, 100],
        highs=[100.5, 100.5, 100.5, 101.5, 100.5, 100.5],
        lows=[99.5, 99.5, 99.5, 99.8, 99.5, 99.5],
        timeframe=Timeframe.M5,
    )
    sig = Signal.create(
        symbol=bars.symbol,
        ts=bars.df["ts"].item(2),
        kind=SignalKind.REVERSAL_BOTTOM,
        side=Side.BUY,
        confidence=0.5,
        entry=100.0,
        stop=99.0,
        targets=(101.0,),
        time_of_day_bucket="lunch",
        attribution=uncertain_attribution(0.5),
    )
    return simulate_trades([sig], bars)


def test_trades_csv_has_pnl(tmp_path: Path) -> None:
    res = _result()
    out = tmp_path / "trades.csv"
    assert trades_to_csv(res, out) == 1
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["pnl_cents"] == "9701"
    assert rows[0]["side"] == "long"
    assert rows[0]["exit_reason"] == "target"


def test_pdf_report_is_valid_pdf(tmp_path: Path) -> None:
    res = _result()
    out = tmp_path / "report.pdf"
    backtest_report_pdf(res, out)
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 1500  # has embedded chart images
