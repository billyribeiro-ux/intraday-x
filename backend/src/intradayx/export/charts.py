"""Matplotlib figures rendered to PNG bytes for embedding in the PDF report."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")  # headless; must precede pyplot import
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

if TYPE_CHECKING:
    from intradayx.backtest.metrics import BacktestMetrics
    from intradayx.backtest.runner import BacktestResult


def equity_curve_png(result: BacktestResult) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 2.6))
    if result.equity_curve:
        # matplotlib converts datetimes natively; its stubs are over-strict here.
        xs = [t for t, _ in result.equity_curve]
        ys = [c / 100 for _, c in result.equity_curve]
        ax.plot(xs, ys, color="#2563eb", lw=1.4)  # type: ignore[arg-type]
        ax.axhline(0, color="#999", lw=0.6)
    ax.set_title("Equity curve — cumulative P&L ($)", fontsize=10)
    ax.grid(alpha=0.25)
    ax.tick_params(labelsize=7)
    return _to_png(fig)


def tod_bar_png(metrics: BacktestMetrics) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 2.6))
    if metrics.per_tod:
        buckets = list(metrics.per_tod)
        exp = [metrics.per_tod[b].expectancy_cents / 100 for b in buckets]
        ax.bar(buckets, exp, color=["#16a34a" if e >= 0 else "#dc2626" for e in exp])
        ax.axhline(0, color="#999", lw=0.6)
    ax.set_title("Expectancy by time-of-day ($/trade)", fontsize=10)
    ax.grid(alpha=0.25, axis="y")
    ax.tick_params(labelsize=7)
    return _to_png(fig)


def _to_png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=130)
    plt.close(fig)
    return buf.getvalue()
