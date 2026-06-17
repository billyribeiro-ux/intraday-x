# intraday-x

A **self-learning intraday scanner & backtester** that, given a ticker, finds
*why* it got bought up or sold off — the "culprit" — and emits **buy/sell
signals** from two scanners (**reversal / tops-bottoms** and **scalping**), each
time-of-day aware. It backtests on history, monitors live, exports CSV/PDF, and
generates a thinkorSwim ThinkScript study.

> **Everything happens for a reason** — but this tool only claims a reason it can
> actually *measure*. Every signal carries a `data_completeness` score and a
> caveat; on free data the scanners honestly *lose money* and the ML is *barely
> above chance*. That discipline (surfaced, never faked) is the point — it's the
> foundation worth improving with real data.

## What's inside

```
ticker ─▶ FMP DataProvider (Financial Modeling Prep, capability-gated)
        ─▶ Parquet/DuckDB lake
        ─▶ causal features (VWAP, RVOL, ATR, POC/VAH/VAL, pivots, climax, squeeze)
        ─▶ SignalEngine  ◀── shared ──▶  Backtester  &  Live monitor
        ─▶ Signal{confidence, attribution, data_completeness}
        ─▶ CSV/PDF · FastAPI + WebSocket ─▶ SvelteKit + Lightweight Charts · ThinkScript
```

- **FMP-sourced market data** — Financial Modeling Prep is the canonical data
  provider for charts, scans, backtests, and live quote updates. The `Capability`
  system still gates unavailable surfaces honestly rather than fabricating data.
- **Two scanners, one engine** — reversal + scalping share the backtester, live
  monitor, exporter, API and dashboard (backtest↔live parity is enforced by tests).
- **Honest attribution** — rule-based "why" + a LightGBM/SHAP "culprit" model
  (purged CV + Deflated Sharpe), and earnings-catalyst tagging. Says *"cause
  uncertain"* when it can't measure one.

## Quickstart

**Backend** (Python 3.12 via [uv](https://docs.astral.sh/uv/); macOS ML extra needs `brew install libomp`):

```bash
cd backend
uv sync --extra export --extra api --extra ml
export FMP_API_KEY=your_key_here                   # required: all market data is FMP

uv run intradayx scan AAPL --scanner reversal      # tops/bottoms with ranked "why"
uv run intradayx scan AAPL --scanner scalping       # momentum/VWAP-reclaim entries
uv run intradayx backtest AAPL --scanner reversal --export /tmp/out   # metrics + CSV/PDF
uv run intradayx squeeze AAPL                        # short-squeeze price/volume signature
uv run intradayx learn AAPL                          # LightGBM + SHAP "culprit" attribution
uv run intradayx earnings AAPL                       # scheduled-earnings catalyst dates
uv run intradayx thinkscript                         # thinkorSwim study for the reversal rules
uv run intradayx serve                               # FastAPI + WebSocket on :8000
uv run pytest                                        # the test suite
```

**Frontend** (Node 24 / pnpm — live dashboard; run the backend too):

```bash
cd frontend
pnpm install
pnpm dev            # http://localhost:5173 (proxies /api + /ws to :8000)
```

## Data

All market data is sourced from **Financial Modeling Prep**. Set `FMP_API_KEY`
in your environment or paste it in the desktop Settings screen. There is no
silent yfinance/Twelve Data/Polygon fallback: a missing FMP key fails loudly so
charts, studies, scans, and backtests never mix provenance by accident.
Deep historical intraday market internals ($TICK/$TRIN/…) aren't sold cheaply —
the internals self-recorder banks them once you connect a realtime feed. See
[`docs/DATA_PROVIDERS.md`](docs/DATA_PROVIDERS.md).

## Docs

- [`docs/OPERATOR_GUIDE.md`](docs/OPERATOR_GUIDE.md) — **start here:** everything *you* need to do (setup, data, deploy), step by step.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — phase-by-phase plan + status.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the design + the shared-engine principle.
- [`docs/DATA_PROVIDERS.md`](docs/DATA_PROVIDERS.md) — vendor capability matrix.
- [`docs/AI_LANDMINES.md`](docs/AI_LANDMINES.md) — runtime traps that compile fine but break things.

## Status

Phases 0–6, 10, 11 + earnings + squeeze-signature are done and verified on free
data. Internals (Phase 7) and gamma/GEX (Phase 9) are built to receive a paid
data subscription with no rewrite. Not investment advice.
