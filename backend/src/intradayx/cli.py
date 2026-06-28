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


def _load_meta_filter(path: str):
    """Load a joblib-serialized MetaFilter, returning None for an empty path."""
    if not path:
        return None
    from pathlib import Path

    import joblib

    p = Path(path)
    if not p.exists():
        raise typer.BadParameter(f"meta-filter not found: {path}")
    return joblib.load(p)


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
    scanner: str = typer.Option("reversal", help="Scanner: reversal | scalping"),
    quality_threshold: float = typer.Option(
        0.0, "--quality-threshold", help="Only emit signals with quality_score >= this (0-1)"
    ),
    meta_filter: str = typer.Option(
        "", "--meta-filter", help="Path to a joblib meta-filter trained with 'tune'"
    ),
    meta_threshold: float = typer.Option(
        0.5, "--meta-threshold", help="Only emit signals with meta_score >= this (0-1)"
    ),
) -> None:
    """Scan TICKER for reversal (tops/bottoms) or scalping signals and print them."""
    from intradayx.signals.strategy import make_strategy

    try:
        strategy = make_strategy(scanner)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=days)
    provider = default_provider()
    bars = provider.bars(ticker.upper(), start, end, tf)
    if bars.is_empty():
        console.print(f"[yellow]No bars returned for {ticker.upper()} — nothing to scan.[/]")
        raise typer.Exit(code=0)

    mf = _load_meta_filter(meta_filter)
    caps = provider.capabilities()
    signals = SignalEngine(strategy, meta_filter=mf).scan(bars, caps)
    signals = [s for s in signals if s.quality_score >= quality_threshold]
    if mf is not None:
        signals = [
            s for s in signals if s.meta_score is not None and s.meta_score >= meta_threshold
        ]
    from intradayx.attribution.catalysts import (
        catalyst_events_from_earnings_dates,
        enrich_with_catalysts,
    )
    from intradayx.data.provider import DataError
    from intradayx.domain.capabilities import Capability, CapabilityError

    events = []
    try:
        events = provider.catalyst_events(ticker.upper(), start, end)
    except (CapabilityError, DataError):
        if caps.supports(Capability.EARNINGS_CALENDAR):
            try:
                dates = provider.earnings_dates(ticker.upper())
                events = catalyst_events_from_earnings_dates(dates)
            except (CapabilityError, DataError):
                events = []
    signals = enrich_with_catalysts(signals, events)
    filters = []
    if quality_threshold > 0:
        filters.append(f"quality >= {quality_threshold:.2f}")
    if mf is not None:
        filters.append(f"meta >= {meta_threshold:.2f}")
    filter_text = f" ({', '.join(filters)})" if filters else ""
    console.print(
        f"Scanned [bold]{ticker.upper()}[/] {tf.value} — {len(bars)} bars, "
        f"[bold cyan]{len(signals)}[/] signal(s){filter_text}."
    )
    if not signals:
        return

    show_meta = mf is not None
    cols = ["Time (UTC)", "Kind", "Side", "Conf", "Qual"]
    if show_meta:
        cols.append("Meta")
    cols.extend(["ToD", "Entry", "Stop", "Why"])
    table = Table(title=f"{ticker.upper()} {scanner} signals", show_lines=False)
    for col in cols:
        table.add_column(col, overflow="fold")
    for s in signals:
        side_color = "green" if s.side.is_bullish else "red"
        row = [
            s.ts.strftime("%Y-%m-%d %H:%M"),
            s.kind.value.replace("reversal_", "").replace("scalp_", ""),
            f"[{side_color}]{s.side.value}[/]",
            f"{s.confidence:.2f}",
            f"{s.quality_score:.2f}",
        ]
        if show_meta:
            row.append(f"{s.meta_score:.2f}" if s.meta_score is not None else "-")
        row.extend(
            [
                s.time_of_day_bucket,
                f"{s.entry:.2f}",
                f"{s.stop:.2f}",
                s.attribution.summary,
            ]
        )
        table.add_row(*row)
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
    scanner: str = typer.Option("reversal", help="Scanner: reversal | scalping"),
    quality_threshold: float = typer.Option(
        0.0, "--quality-threshold", help="Only trade signals with quality_score >= this (0-1)"
    ),
    meta_filter: str = typer.Option(
        "", "--meta-filter", help="Path to a joblib meta-filter trained with 'tune'"
    ),
    meta_threshold: float = typer.Option(
        0.5, "--meta-threshold", help="Only trade signals with meta_score >= this (0-1)"
    ),
    export_dir: str = typer.Option(
        "", "--export", help="Write signals.csv, trades.csv & report.pdf to this directory"
    ),
) -> None:
    """Backtest a scanner on TICKER and print performance metrics."""
    from intradayx.backtest.runner import simulate_trades
    from intradayx.signals.strategy import make_strategy

    try:
        strategy = make_strategy(scanner)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=days)
    provider = default_provider()
    bars = provider.bars(ticker.upper(), start, end, tf)
    if bars.is_empty():
        console.print(f"[yellow]No bars for {ticker.upper()} — nothing to backtest.[/]")
        raise typer.Exit(code=0)

    mf = _load_meta_filter(meta_filter)
    signals = SignalEngine(strategy, meta_filter=mf).scan(bars, provider.capabilities())
    signals = [s for s in signals if s.quality_score >= quality_threshold]
    if mf is not None:
        signals = [
            s for s in signals if s.meta_score is not None and s.meta_score >= meta_threshold
        ]
    res = simulate_trades(signals, bars, max_hold_bars=max_hold)
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
def accuracy(
    ticker: str,
    timeframe: str = typer.Option("5m", help="Bar interval"),
    days: int = typer.Option(60, help="How many days back to audit"),
    scanner: str = typer.Option("reversal", help="Scanner: reversal | scalping"),
    max_hold: int = typer.Option(24, help="Max bars to hold a signal (time-stop)"),
) -> None:
    """Audit signal-level accuracy: what % of emitted signals hit target first."""
    from intradayx.signals.accuracy import accuracy_report, label_outcomes
    from intradayx.signals.strategy import make_strategy

    if scanner not in ("reversal", "scalping"):
        raise typer.BadParameter("scanner must be 'reversal' or 'scalping'")

    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    provider = default_provider()
    bars = provider.bars(ticker.upper(), end - timedelta(days=days), end, tf)
    if bars.is_empty():
        console.print(f"[yellow]No bars for {ticker.upper()}.[/]")
        raise typer.Exit(code=0)

    signals = SignalEngine(make_strategy(scanner)).scan(bars, provider.capabilities())
    labeled = label_outcomes(signals, bars, max_hold_bars=max_hold)
    report = accuracy_report(labeled)

    console.print(
        f"\n[bold]{ticker.upper()}[/] {tf.value} {scanner} — signal accuracy audit"
    )
    summary = Table(show_header=False, box=None)
    summary.add_row("Signals audited", str(report.total))
    summary.add_row("Win rate (target first)", f"[bold]{report.win_rate:.1%}[/]")
    summary.add_row("Stop rate", f"{report.loss_rate:.1%}")
    summary.add_row("Time-stop rate", f"{report.time_rate:.1%}")
    summary.add_row("Expectancy / signal", _usd(report.expectancy_cents))
    console.print(summary)

    if report.per_kind:
        kt = Table(title="By signal kind")
        kt.add_column("Kind")
        kt.add_column("Signals", justify="right")
        kt.add_column("Win rate", justify="right")
        for kind, r in report.per_kind.items():
            kt.add_row(kind, str(r.total), f"{r.win_rate:.1%}")
        console.print(kt)

    # Show how tightening the quality score changes precision.
    qt = Table(title="Quality-threshold sweep (recall → precision)")
    qt.add_column("Quality >=", justify="right")
    qt.add_column("Signals", justify="right")
    qt.add_column("Win rate", justify="right")
    for thr in (0.0, 0.5, 0.6, 0.7, 0.8):
        r = accuracy_report(labeled, min_quality_score=thr)
        qt.add_row(f"{thr:.1f}", str(r.total), f"{r.win_rate:.1%}")
    console.print(qt)
    console.print(
        "[dim]Raise --quality-threshold to trade only the highest-quality signals; "
        "win rate usually rises, but sample size shrinks.[/]"
    )


@app.command()
def tune(
    ticker: str,
    timeframe: str = typer.Option("5m", help="Bar interval"),
    days: int = typer.Option(180, help="How many days back to train on"),
    scanner: str = typer.Option("reversal", help="Scanner: reversal | scalping"),
    max_hold: int = typer.Option(24, help="Max bars to hold a signal (time-stop)"),
    out_dir: str = typer.Option(
        "data/meta_filters", "--out", help="Directory to write the fitted model"
    ),
) -> None:
    """Self-learn a meta-filter on TICKER(S) and save it. TICKER may be a comma-
    separated basket (e.g. AAPL,MSFT,NVDA) — signals are pooled across symbols so
    the learned layer clears its sample floor (one symbol rarely does)."""
    from pathlib import Path

    import joblib

    from intradayx.domain.signals import Signal
    from intradayx.features.volatility import fetch_volatility_internals
    from intradayx.signals.meta_filter import train_meta_filter_multi
    from intradayx.signals.strategy import make_strategy

    if scanner not in ("reversal", "scalping"):
        raise typer.BadParameter("scanner must be 'reversal' or 'scalping'")

    tickers = [t.strip().upper() for t in ticker.split(",") if t.strip()]
    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=days)
    provider = default_provider()
    caps = provider.capabilities()
    engine = SignalEngine(make_strategy(scanner))

    samples: list[tuple[list[Signal], object]] = []
    total_bars = 0
    for sym in tickers:
        bars = provider.bars(sym, start, end, tf)
        if bars.is_empty():
            console.print(f"[yellow]No bars for {sym}; skipping.[/]")
            continue
        total_bars += len(bars)
        vol = fetch_volatility_internals(provider, start, end, tf)
        signals = engine.scan(bars, caps, internals=vol)
        samples.append((signals, bars))

    if not samples:
        console.print("[yellow]No bars for any requested ticker.[/]")
        raise typer.Exit(code=0)

    label = tickers[0] if len(tickers) == 1 else f"{len(tickers)} symbols"
    console.print(
        f"\n[bold]{label}[/] {tf.value} {scanner} — training meta-filter on "
        f"{total_bars} bars across {len(samples)} symbol(s)..."
    )
    mf, result = train_meta_filter_multi(
        samples, max_hold_bars=max_hold, min_samples=50
    )

    if result.insufficient:
        console.print(f"[yellow]Cannot train meta-filter: {result.reason}[/]")
        raise typer.Exit(code=0)

    summary = Table(show_header=False, box=None)
    summary.add_row("Signals labeled", str(result.n_samples))
    summary.add_row("Positive rate (target-first)", f"{result.pos_rate:.1%}")
    summary.add_row("CV accuracy", f"{result.cv_accuracy:.1%}")
    summary.add_row("CV precision", f"{result.cv_precision:.1%}")
    summary.add_row("CV recall", f"{result.cv_recall:.1%}")
    summary.add_row("CV ROC-AUC", f"{result.cv_roc_auc:.3f}")
    console.print(summary)

    ft = Table(title="Top meta-filter features (permutation importance)")
    ft.add_column("Feature")
    ft.add_column("Importance", justify="right")
    for feature, val in result.feature_importance[:10]:
        ft.add_row(feature, f"{val:.4f}")
    console.print(ft)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    model_name = tickers[0] if len(tickers) == 1 else "universe"
    model_file = out_path / f"{model_name}_{scanner}.joblib"
    joblib.dump(mf, model_file)
    console.print(
        f"Saved meta-filter → [green]{model_file}[/]\n"
        "Use it with: [bold]intradayx scan/backtest ... "
        f"--meta-filter {model_file} --meta-threshold 0.6[/]"
    )


@app.command()
def forward(
    ticker: str,
    timeframe: str = typer.Option("5m", help="Bar interval"),
    days: int = typer.Option(120, help="Total days of history to walk forward over"),
    train_days: int = typer.Option(40, help="Training window length in days"),
    test_days: int = typer.Option(10, help="Out-of-sample window length in days"),
    step_days: int = typer.Option(10, help="How far to roll forward each window"),
    scanner: str = typer.Option("reversal", help="Scanner: reversal | scalping"),
    max_hold: int = typer.Option(24, help="Max bars to hold a signal"),
    quality_threshold: float = typer.Option(
        0.0, "--quality-threshold", help="Minimum deterministic quality score"
    ),
    meta_threshold: float = typer.Option(
        0.5, "--meta-threshold", help="Minimum learned meta score to trade"
    ),
    out_dir: str = typer.Option(
        "data/meta_filters", "--out", help="Directory to save the final rolled model"
    ),
) -> None:
    """Forward-learning: train meta-filter on past windows, trade OOS windows."""
    from pathlib import Path

    import joblib

    from intradayx.signals.forward import forward_learn

    if scanner not in ("reversal", "scalping"):
        raise typer.BadParameter("scanner must be 'reversal' or 'scalping'")

    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    provider = default_provider()
    bars = provider.bars(ticker.upper(), end - timedelta(days=days), end, tf)
    if bars.is_empty():
        console.print(f"[yellow]No bars for {ticker.upper()}.[/]")
        raise typer.Exit(code=0)

    console.print(
        f"\n[bold]{ticker.upper()}[/] {tf.value} {scanner} — forward-learning: "
        f"train={train_days}d, test={test_days}d, step={step_days}d"
    )
    res = forward_learn(
        bars,
        provider.capabilities(),
        scanner=scanner,
        total_days=days,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        max_hold_bars=max_hold,
        quality_threshold=quality_threshold,
        meta_threshold=meta_threshold,
        min_samples=30,
    )

    wt = Table(title="Out-of-sample windows")
    for col in ("Window", "Train", "Test", "Train sigs", "Test sigs", "Trades", "Win rate", "P&L"):
        wt.add_column(col, justify="right")
    for w in res.windows:
        wt.add_row(
            str(w.index),
            f"{w.train_start:%m-%d}",
            f"{w.test_start:%m-%d}",
            str(w.n_train_signals),
            str(w.n_test_signals),
            str(w.n_test_trades),
            f"{w.test_win_rate:.0%}" if w.n_test_trades else "-",
            _usd(w.test_pnl_cents),
        )
    console.print(wt)

    console.print(
        f"\nAggregated OOS: [bold]{res.n_oos_trades}[/] trades from "
        f"{res.n_oos_signals} signals, win rate [bold]{res.oos_accuracy:.1%}[/], "
        f"P&L [bold]{_usd(res.oos_pnl_cents)}[/]"
    )

    if res.final_model is not None and res.final_model.is_fitted:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        model_file = out_path / f"{ticker.upper()}_{scanner}_forward.joblib"
        joblib.dump(res.final_model, model_file)
        console.print(f"Saved final rolled model → [green]{model_file}[/]")

    console.print(
        "[dim]This is the honest number: every prediction was made after training "
        "only on earlier data. If win rate is weak, the model is telling you the "
        "signal does not generalise on this data/history.[/]"
    )


@app.command()
def walkforward(
    ticker: str,
    timeframe: str = typer.Option("5m", help="Bar interval"),
    days: int = typer.Option(60, help="How many days back"),
    scanner: str = typer.Option("reversal", help="Scanner: reversal | scalping"),
    windows: int = typer.Option(4, help="Number of sequential walk-forward windows"),
) -> None:
    """Walk-forward validation: pick the threshold in-sample, trade it out-of-sample."""
    from intradayx.backtest.walkforward import walk_forward

    if scanner not in ("reversal", "scalping"):
        raise typer.BadParameter("scanner must be 'reversal' or 'scalping'")
    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    provider = default_provider()
    bars = provider.bars(ticker.upper(), end - timedelta(days=days), end, tf)
    if bars.is_empty():
        console.print(f"[yellow]No bars for {ticker.upper()}.[/]")
        raise typer.Exit(code=0)

    res = walk_forward(bars, provider.capabilities(), scanner=scanner, n_windows=windows)
    console.print(
        f"\n[bold]{ticker.upper()}[/] {tf.value} {scanner} — walk-forward over "
        f"{res.n_windows} windows ({res.n_trials_per_window} thresholds tried each)"
    )
    wt = Table(title="Out-of-sample by window")
    for col in ("Window", "Chosen thr.", "OOS trades", "OOS P&L"):
        wt.add_column(col, justify="right")
    for w in res.windows:
        wt.add_row(
            str(w.index),
            f"{w.chosen_threshold:.2f}",
            str(w.oos_trades),
            _usd(w.oos_pnl_cents),
        )
    console.print(wt)
    m = res.oos_metrics
    console.print(
        f"Aggregated OOS: [bold]{_usd(m.total_pnl_cents)}[/] over {m.n_trades} trades, "
        f"win rate {m.win_rate:.0%}"
    )
    console.print(
        f"[bold]Deflated Sharpe P(SR>0) = {res.deflated_sharpe:.0%}[/] "
        f"(deflated by {res.n_trials_per_window} trials/window)"
    )
    console.print(
        "[dim]This is the number that matters: it's out-of-sample and discounted for "
        "the thresholds we tried. Low = the edge didn't survive selection. Get years of "
        "data (e.g. Twelve Data) before reading much into it.[/]"
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


@app.command()
def squeeze(
    ticker: str,
    timeframe: str = typer.Option("5m", help="Bar interval"),
    days: int = typer.Option(30, help="How many days back to scan"),
    threshold: float = typer.Option(0.5, help="Min squeeze-signature score (0-1)"),
) -> None:
    """Scan for the price/volume SHORT-SQUEEZE SIGNATURE (not confirmed by short interest)."""
    import polars as pl

    from intradayx.features.pipeline import build_features

    tf = Timeframe(timeframe)
    end = datetime.now(tz=UTC)
    provider = default_provider()
    bars = provider.bars(ticker.upper(), end - timedelta(days=days), end, tf)
    if bars.is_empty():
        console.print(f"[yellow]No bars for {ticker.upper()}.[/]")
        raise typer.Exit(code=0)

    df = build_features(bars, provider.capabilities()).df
    hits = df.filter(pl.col("squeeze_signature_score") >= threshold).sort(
        "squeeze_signature_score", descending=True
    )
    console.print(
        f"[bold]{ticker.upper()}[/] {tf.value} — [bold cyan]{hits.height}[/] "
        f"squeeze-signature bar(s) (score >= {threshold})"
    )
    if hits.height:
        table = Table(title=f"{ticker.upper()} short-squeeze signature")
        for col in ("Time (UTC)", "Close", "RVOL", "Range/ATR", "New high", "Score"):
            table.add_column(col, justify="right")
        for row in hits.head(25).iter_rows(named=True):
            table.add_row(
                row["ts"].strftime("%Y-%m-%d %H:%M"),
                f"{row['close']:.2f}",
                f"{row['rvol']:.1f}" if row["rvol"] is not None else "-",
                f"{row['range_atr']:.1f}" if row["range_atr"] is not None else "-",
                "yes" if row["new_high_break"] else "no",
                f"{row['squeeze_signature_score']:.2f}",
            )
        console.print(table)
    console.print(
        "[dim]Price/volume signature ONLY — NOT confirmed by short interest. A real "
        "squeeze needs SI%, days-to-cover and cost-to-borrow (a paid feed, Phase 8). "
        "This flags the footprint, not the cause.[/]"
    )


@app.command()
def earnings(ticker: str) -> None:
    """Print scheduled-earnings dates (a named catalyst) for TICKER."""
    from intradayx.domain.capabilities import Capability

    provider = default_provider()
    if not provider.capabilities().supports(Capability.EARNINGS_CALENDAR):
        console.print("[yellow]No provider supports an earnings calendar.[/]")
        raise typer.Exit(code=0)
    dates = provider.earnings_dates(ticker.upper())
    if not dates:
        console.print(f"[yellow]No earnings dates found for {ticker.upper()}.[/]")
        raise typer.Exit(code=0)
    today = datetime.now(tz=UTC).date()
    table = Table(title=f"{ticker.upper()} earnings dates")
    table.add_column("Date")
    table.add_column("When")
    for d in dates:
        table.add_row(d.isoformat(), "upcoming" if d >= today else "past")
    console.print(table)


@app.command()
def thinkscript(
    out: str = typer.Option("", "--out", help="Write the study to this file instead of stdout"),
) -> None:
    """Print (or write) the thinkorSwim ThinkScript study for the reversal scanner."""
    from intradayx.export.thinkscript import reversal_thinkscript
    from intradayx.signals.params import ReversalParams

    source = reversal_thinkscript(ReversalParams())
    if out:
        from pathlib import Path

        Path(out).write_text(source)
        console.print(f"Wrote ThinkScript study → {out}")
    else:
        # Plain print (not rich) so it copy-pastes cleanly into thinkorSwim.
        print(source)


@app.command()
def pead(
    tickers: str = typer.Argument(..., help="Comma-separated symbols, e.g. AAPL,MSFT,NVDA"),
    hold_days: int = typer.Option(20, help="Trading days to hold after the surprise"),
    years: int = typer.Option(4, help="Years of daily history to backtest over"),
    min_surprise: float = typer.Option(0.0, help="Minimum |EPS surprise| ($) to trade"),
    min_sue: float = typer.Option(0.0, help="Minimum |SUE| (standardized surprise) to trade"),
    cost_bps: float = typer.Option(5.0, help="Transaction cost per side, bps"),
    borrow_bps: float = typer.Option(50.0, help="Annual short-borrow cost, bps"),
) -> None:
    """Post-Earnings-Announcement Drift: backtest the EPS-surprise edge and list
    currently-open trades. Long a positive surprise, short a negative one, hold
    ``hold_days`` sessions. The one edge validated in/out-of-sample in this repo."""
    from datetime import timedelta

    from intradayx.signals.pead import build_pead_signals, open_signals, pead_stats
    from intradayx.signals.pead_portfolio import pead_portfolio_backtest

    syms = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    provider = default_provider()
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=365 * years)

    bars_by_symbol = {}
    signals_by_symbol = {}
    all_sigs = []
    for sym in syms:
        bars = provider.bars(sym, start, end, Timeframe.D1)
        if bars.is_empty():
            continue
        surprises = provider.earnings_surprises(sym)
        sigs = build_pead_signals(
            sym, bars, surprises,
            hold_days=hold_days, min_abs_surprise=min_surprise, min_abs_sue=min_sue,
        )
        bars_by_symbol[sym] = bars
        signals_by_symbol[sym] = sigs
        all_sigs.extend(sigs)

    stats = pead_stats(all_sigs)
    console.print(
        f"\n[bold]PEAD[/] {len(syms)} symbols · {years}y · hold {hold_days}d — "
        f"backtest on {stats.n} closed events"
    )
    summary = Table(show_header=False, box=None)
    summary.add_row("Closed trades", str(stats.n))
    summary.add_row("Mean trade return", f"{stats.mean_return * 100:+.3f}%")
    summary.add_row("t-stat", f"{stats.t_stat:.2f}")
    summary.add_row("Hit rate", f"{stats.hit_rate * 100:.1f}%")
    summary.add_row("Total (sum of trade returns)", f"{stats.total_return * 100:+.1f}%")
    console.print(summary)
    verdict = "edge present (t>2)" if stats.t_stat > 2 else "not significant on this sample"
    console.print(f"Verdict: [bold]{verdict}[/]")

    # Cost-aware long/short portfolio — the deployable, after-cost number.
    pf = pead_portfolio_backtest(
        bars_by_symbol, signals_by_symbol, cost_bps=cost_bps, borrow_bps_annual=borrow_bps
    )
    pt = Table(
        title=f"Long/short portfolio (after {cost_bps:.0f}bps/side + {borrow_bps:.0f}bps borrow)",
        show_header=False, box=None,
    )
    pt.add_row("Trading days", str(pf.n_days))
    pt.add_row("Total return", f"{pf.total_return * 100:+.1f}%")
    pt.add_row("Annualized return", f"{pf.ann_return * 100:+.1f}%")
    pt.add_row("Annualized vol", f"{pf.ann_vol * 100:.1f}%")
    pt.add_row("Sharpe (net)", f"[bold]{pf.sharpe:.2f}[/]")
    pt.add_row("Max drawdown", f"{pf.max_drawdown * 100:.1f}%")
    console.print(pt)

    live = open_signals(all_sigs)
    if live:
        ot = Table(title="Open PEAD trades (announced, still in the drift window)")
        for col in ("Symbol", "Announced", "Entry date", "Side", "Surprise$", "Entry"):
            ot.add_column(col)
        for s in sorted(live, key=lambda x: x.announce_date, reverse=True):
            ot.add_row(
                s.symbol, s.announce_date.isoformat(), s.entry_date.isoformat(),
                s.side, f"{s.surprise:+.2f}", f"${s.entry:.2f}",
            )
        console.print(ot)
    else:
        console.print("[dim]No open PEAD trades right now.[/]")


if __name__ == "__main__":
    app()
