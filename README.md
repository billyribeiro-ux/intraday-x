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
ticker ─▶ DataProvider (yfinance + Twelve Data + Polygon + …, capability-gated)
        ─▶ Parquet/DuckDB lake
        ─▶ causal features (VWAP, RVOL, ATR, POC/VAH/VAL, pivots, climax, squeeze)
        ─▶ SignalEngine  ◀── shared ──▶  Backtester  &  Live monitor
        ─▶ Signal{confidence, attribution, data_completeness}
        ─▶ CSV/PDF · FastAPI + WebSocket ─▶ SvelteKit + Lightweight Charts · ThinkScript
```

- **Vendor-agnostic data** — a `Capability` system: providers declare what they
  support; features/detectors that need missing data stay **dormant** rather than
  fabricate. Add a paid vendor later and internals/options light up with no rewrite.
- **Two scanners, one engine** — reversal + scalping share the backtester, live
  monitor, exporter, API and dashboard (backtest↔live parity is enforced by tests).
- **Honest attribution** — rule-based "why" + a LightGBM/SHAP "culprit" model
  (purged CV + Deflated Sharpe), and earnings-catalyst tagging. Says *"cause
  uncertain"* when it can't measure one.

## Quickstart

**Backend** (Python 3.12 via [uv](https://docs.astral.sh/uv/); macOS ML extra needs `brew install libomp`):

```bash
cd backend
uv sync --extra export --extra api --extra ml      # Twelve Data/Polygon need no extra (httpx)

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

Works out of the box on **yfinance** (zero setup; ~7 days of 1-minute, ~60 days
of 5-minute). For real multi-year backtests, add a free, **non-broker**
**Twelve Data** key (1-minute back to 2020; see [`.env.example`](.env.example)) —
the composite router prefers it automatically. Polygon (data vendor) is also
wired. (Alpaca is a broker — registered but opt-in only.)
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
