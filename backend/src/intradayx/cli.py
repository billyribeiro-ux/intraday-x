"""Command-line entry point for intradayx.

Commands:
- ``intradayx version``           — print the package version.
- ``intradayx ingest <TICKER>``   — fetch bars into the local Parquet lake.
- ``intradayx scan <TICKER>``     — run the reversal scanner and print signals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import typer
from rich.console import Console
from rich.table import Table

from intradayx import __version__
from intradayx.data.factory import default_provider
from intradayx.domain.bars import Timeframe
from intradayx.signals.engine import SignalEngine

app = typer.Typer(
    name="intradayx",
    help="Self-learning intraday scanner & backtester.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.callback()
def _main() -> None:
    """intradayx — self-learning intraday scanner & backtester."""
    # Presence of a callback forces Typer into multi-command (subcommand) mode.


@app.command()
def version() -> None:
    """Print the intradayx version."""
    console.print(f"intradayx [bold cyan]{__version__}[/]")


@app.command()
def ingest(
    ticker: str,
    timeframe: str = typer.Option("1m", help="Bar interval: 1m,5m,15m,30m,1h,1d"),
    days: int = typer.Option(5, help="How many days back to fetch"),
    lake_dir: str = typer.Option("data/lake", help="Lake root directory"),
) -> None:
    """Fetch bars for TICKER and write them into the local Parquet lake."""
    from intradayx.storage.lake import Lake

    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=days)
    provider = default_provider()
    bars = provider.bars(ticker.upper(), start, end, tf)
    written = Lake(lake_dir).write_bars(bars)
    console.print(
        f"Ingested [bold green]{written}[/] {tf.value} bars for "
        f"[bold]{ticker.upper()}[/] into {lake_dir}"
    )


@app.command()
def scan(
    ticker: str,
    timeframe: str = typer.Option("5m", help="Bar interval: 1m,5m,15m,30m,1h,1d"),
    days: int = typer.Option(7, help="How many days back to scan"),
    scanner: str = typer.Option("reversal", help="Scanner: reversal (scalping later)"),
) -> None:
    """Scan TICKER for reversal (tops/bottoms) signals and print them."""
    if scanner != "reversal":
        raise typer.BadParameter("only 'reversal' is implemented (scalping is a later phase)")

    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=days)
    provider = default_provider()
    bars = provider.bars(ticker.upper(), start, end, tf)
    if bars.is_empty():
        console.print(f"[yellow]No bars returned for {ticker.upper()} — nothing to scan.[/]")
        raise typer.Exit(code=0)

    signals = SignalEngine().scan(bars, provider.capabilities())
    console.print(
        f"Scanned [bold]{ticker.upper()}[/] {tf.value} — {len(bars)} bars, "
        f"[bold cyan]{len(signals)}[/] signal(s)."
    )
    if not signals:
        return

    table = Table(title=f"{ticker.upper()} reversal signals", show_lines=False)
    for col in ("Time (UTC)", "Kind", "Side", "Conf", "ToD", "Entry", "Stop", "Why"):
        table.add_column(col, overflow="fold")
    for s in signals:
        side_color = "green" if s.side.is_bullish else "red"
        table.add_row(
            s.ts.strftime("%Y-%m-%d %H:%M"),
            s.kind.value.replace("reversal_", ""),
            f"[{side_color}]{s.side.value}[/]",
            f"{s.confidence:.2f}",
            s.time_of_day_bucket,
            f"{s.entry:.2f}",
            f"{s.stop:.2f}",
            s.attribution.summary,
        )
    console.print(table)
    # Honesty: surface the data-completeness caveat once.
    if signals[0].attribution.caveat:
        console.print(f"[dim]{signals[0].attribution.caveat}[/]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
) -> None:
    """Run the FastAPI API + websocket (single worker — required by the poller)."""
    import uvicorn

    console.print(f"intraday-x API on http://{host}:{port}  (docs at /docs, ws at /ws/signals)")
    uvicorn.run("intradayx.api.app:app", host=host, port=port, workers=1)


def _usd(cents: int | float) -> str:
    return f"${cents / 100:,.2f}"


@app.command()
def backtest(
    ticker: str,
    timeframe: str = typer.Option("5m", help="Bar interval: 1m,5m,15m,30m,1h,1d"),
    days: int = typer.Option(60, help="How many days back to backtest"),
    max_hold: int = typer.Option(24, help="Max bars to hold a trade (time-stop)"),
    export_dir: str = typer.Option(
        "", "--export", help="Write signals.csv, trades.csv & report.pdf to this directory"
    ),
) -> None:
    """Backtest the reversal scanner on TICKER and print performance metrics."""
    from intradayx.backtest.runner import run_backtest

    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=days)
    provider = default_provider()
    bars = provider.bars(ticker.upper(), start, end, tf)
    if bars.is_empty():
        console.print(f"[yellow]No bars for {ticker.upper()} — nothing to backtest.[/]")
        raise typer.Exit(code=0)

    res = run_backtest(bars, provider.capabilities(), max_hold_bars=max_hold)
    m = res.metrics
    pf = "∞" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"
    from intradayx.attribution.validation import deflated_sharpe_ratio

    returns = [t.pnl_cents / 1_000_000 for t in res.trades]  # /$10k notional
    psr = deflated_sharpe_ratio(returns, 1) if len(returns) >= 3 else 0.0
    console.print(
        f"\n[bold]{ticker.upper()}[/] {tf.value} backtest — {len(bars)} bars, "
        f"{res.n_signals} signals, [bold cyan]{m.n_trades}[/] trades"
    )
    summary = Table(show_header=False, box=None)
    summary.add_row("Net P&L", f"[bold]{_usd(m.total_pnl_cents)}[/]")
    summary.add_row("Win rate", f"{m.win_rate:.0%} ({m.wins}W / {m.losses}L)")
    summary.add_row("Expectancy / trade", _usd(m.expectancy_cents))
    summary.add_row("Avg win / loss", f"{_usd(m.avg_win_cents)} / {_usd(m.avg_loss_cents)}")
    summary.add_row("Profit factor", pf)
    summary.add_row("Max drawdown", _usd(m.max_drawdown_cents))
    summary.add_row("Sharpe (per-trade, unannualized)", f"{m.sharpe_per_trade:.2f}")
    summary.add_row("P(Sharpe > 0) [trials=1]", f"{psr:.0%}")
    console.print(summary)

    if m.per_tod:
        tod = Table(title="By time-of-day", show_lines=False)
        for col in ("Bucket", "Trades", "Win rate", "Expectancy"):
            tod.add_column(col)
        for bucket, st in m.per_tod.items():
            tod.add_row(bucket, str(st.n), f"{st.win_rate:.0%}", _usd(st.expectancy_cents))
        console.print(tod)

    if export_dir:
        from pathlib import Path

        from intradayx.export.csv_export import signals_to_csv, trades_to_csv
        from intradayx.export.pdf_report import backtest_report_pdf

        out = Path(export_dir)
        out.mkdir(parents=True, exist_ok=True)
        signals_to_csv(res.signals, out / "signals.csv")
        trades_to_csv(res, out / "trades.csv")
        backtest_report_pdf(res, out / "report.pdf")
        console.print(
            f"Exported [green]signals.csv[/], [green]trades.csv[/], [green]report.pdf[/] → {out}"
        )

    console.print(
        "[dim]Edge is assumed overfit until proven otherwise: realistic costs are "
        "modeled, but validate with walk-forward + Deflated Sharpe (Phase 6) before "
        "trusting this.[/]"
    )


@app.command()
def learn(
    ticker: str,
    timeframe: str = typer.Option("5m", help="Bar interval"),
    days: int = typer.Option(60, help="How many days back to learn from"),
) -> None:
    """Train the exploratory 'culprit' model and show its SHAP feature attribution."""
    from intradayx.attribution.learn import train_and_evaluate
    from intradayx.domain.signals import MODEL_ATTRIBUTION_CAVEAT
    from intradayx.features.pipeline import build_features

    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    provider = default_provider()
    bars = provider.bars(ticker.upper(), end - timedelta(days=days), end, tf)
    if bars.is_empty():
        console.print(f"[yellow]No bars for {ticker.upper()} — nothing to learn.[/]")
        raise typer.Exit(code=0)

    res = train_and_evaluate(build_features(bars, provider.capabilities()))
    if res.insufficient:
        console.print(f"[yellow]Insufficient data to learn: {res.reason}[/]")
        raise typer.Exit(code=0)

    console.print(
        f"\n[bold]{ticker.upper()}[/] {tf.value} — learned from "
        f"[bold cyan]{res.n_samples}[/] labelled bars "
        f"({res.positive_rate:.0%} significant-move rate)"
    )
    info = Table(show_header=False, box=None)
    info.add_row("Purged-CV macro-F1", f"{res.cv_macro_f1:.3f} ({res.cv_folds} folds)")
    info.add_row("Data completeness", f"{res.data_completeness:.0%}")
    console.print(info)

    shap_table = Table(title="What the model keys on (mean |SHAP|, interventional)")
    shap_table.add_column("Feature")
    shap_table.add_column("Importance", justify="right")
    for feature, val in res.shap_top:
        shap_table.add_row(feature, f"{val:.4f}")
    console.print(shap_table)
    console.print(f"[dim]{MODEL_ATTRIBUTION_CAVEAT}[/]")


if __name__ == "__main__":
    app()
