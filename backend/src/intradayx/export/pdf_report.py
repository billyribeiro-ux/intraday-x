"""PDF backtest report (ReportLab + embedded matplotlib charts).

Contents: header + run metadata, a metrics table, the equity curve, the
per-time-of-day expectancy chart, and the mandatory data-completeness /
overfitting caveat banner.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from intradayx.export.charts import equity_curve_png, tod_bar_png

if TYPE_CHECKING:
    from intradayx.backtest.runner import BacktestResult

CAVEAT = (
    "<i>Attribution and signals are computed from price/volume only "
    "(data_completeness ~50%); market internals, options and short data were not "
    "available. Realistic costs are modeled, but assume any edge is overfit until "
    "validated with walk-forward analysis + the Deflated Sharpe Ratio (Phase 6). "
    "Not investment advice.</i>"
)


def backtest_report_pdf(
    result: BacktestResult, path: Path | str, *, title: str | None = None
) -> Path:
    path = Path(path)
    doc = SimpleDocTemplate(str(path), pagesize=letter, title="intraday-x backtest report")
    styles = getSampleStyleSheet()
    m = result.metrics
    pf = "∞" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"
    heading = title or f"{result.symbol} · {result.timeframe.value} · reversal backtest"

    story: list[object] = [
        Paragraph(heading, styles["Title"]),
        Paragraph(
            f"{result.n_signals} signals → {m.n_trades} trades · params {result.params_version}",
            styles["Normal"],
        ),
        Spacer(1, 0.18 * inch),
    ]

    metric_rows = [
        ["Metric", "Value"],
        ["Net P&L", f"${m.total_pnl_cents / 100:,.2f}"],
        ["Win rate", f"{m.win_rate:.0%}  ({m.wins}W / {m.losses}L)"],
        ["Expectancy / trade", f"${m.expectancy_cents / 100:,.2f}"],
        ["Avg win / loss", f"${m.avg_win_cents / 100:,.2f} / ${m.avg_loss_cents / 100:,.2f}"],
        ["Profit factor", pf],
        ["Max drawdown", f"${m.max_drawdown_cents / 100:,.2f}"],
        ["Sharpe (per-trade, unannualized)", f"{m.sharpe_per_trade:.2f}"],
    ]
    table = Table(metric_rows, colWidths=[2.6 * inch, 3.4 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.2 * inch))

    story.append(Image(io.BytesIO(equity_curve_png(result)), width=6.5 * inch, height=2.4 * inch))
    if m.per_tod:
        story.append(Image(io.BytesIO(tod_bar_png(m)), width=6.5 * inch, height=2.4 * inch))

    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(CAVEAT, styles["Normal"]))

    doc.build(story)
    return path
