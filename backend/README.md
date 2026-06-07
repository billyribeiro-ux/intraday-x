# intradayx (backend)

Python backend for **intraday-x** — the self-learning intraday scanner &
backtester. See [`../docs/ROADMAP.md`](../docs/ROADMAP.md) for the phased plan
and [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) for the design.

## Quick start

```bash
uv sync                         # base + dev (yfinance + Twelve Data + Polygon, all free non-broker)
uv run intradayx version
uv run pytest
```

Set `TWELVEDATA_API_KEY` (free, no card, non-broker) in a `.env` for multi-year
1-minute history — see [`../.env.example`](../.env.example).

## Dependency groups

| Extra        | Phase | What it adds                                            |
|--------------|-------|---------------------------------------------------------|
| (base)       | 0–2   | numpy/pandas/polars/scipy/duckdb/yfinance/httpx/typer … (incl. Twelve Data + Polygon, free non-broker) |
| `backtest`   | 3     | `nautilus_trader` — backtest↔live parity engine         |
| `export`     | 4     | `reportlab` + `matplotlib` — CSV/PDF reports            |
| `api`        | 5     | `fastapi` + `uvicorn` + `apscheduler` — API & live WS   |
| `ml`         | 6     | LightGBM/XGBoost/CatBoost/SHAP/tsfresh/arch/skfolio … (macOS: `brew install libomp`) |

The base install stays lean so iteration is fast; heavier/native stacks load
only when their phase needs them.
