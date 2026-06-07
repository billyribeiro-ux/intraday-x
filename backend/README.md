# intradayx (backend)

Python backend for **intraday-x** — the self-learning intraday scanner &
backtester. See [`../docs/ROADMAP.md`](../docs/ROADMAP.md) for the phased plan
and [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) for the design.

## Quick start

```bash
uv sync --extra alpaca          # base + dev + Alpaca provider
uv run intradayx version
uv run pytest
```

## Dependency groups

| Extra        | Phase | What it adds                                            |
|--------------|-------|---------------------------------------------------------|
| (base)       | 0–2   | numpy/pandas/polars/scipy/duckdb/yfinance/typer …       |
| `alpaca`     | 1     | `alpaca-py` — free ~7–10yr 1-minute backtest backbone   |
| `backtest`   | 3     | `nautilus_trader` — backtest↔live parity engine         |
| `export`     | 4     | `reportlab` + `matplotlib` — CSV/PDF reports            |
| `api`        | 5     | `fastapi` + `uvicorn` + `apscheduler` — API & live WS   |
| `ml`         | 6     | LightGBM/XGBoost/CatBoost/SHAP/tsfresh/arch/skfolio …   |

The base install stays lean so iteration is fast; heavier/native stacks load
only when their phase needs them.
