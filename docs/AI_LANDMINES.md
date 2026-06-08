# intraday-x — AI LANDMINES

Stack-specific scar tissue: bugs that **compile and pass docs/snippets but break
at runtime** — or worse, make a backtest look amazing while it would trade
catastrophically. Read this before writing code. Each entry is **the trap →
why it bites → the rule.**

These are in addition to the global money/i64, Svelte-MCP, and no-`.catch(()=>{})`
rules in the user-level CLAUDE.md.

---

## Frontend (SvelteKit / Lightweight Charts / Phosphor)

### 1. Lightweight Charts v5 removed `series.setMarkers()`

- **Trap:** Pre-v5 snippets call `series.setMarkers([...])` for buy/sell arrows.
  It is gone in v5.
- **Why it bites:** The old code is all over the docs/tutorials and *compiles*
  fine — it fails only at runtime when the method is undefined.
- **Rule:** Use the standalone `createSeriesMarkers(series, markers)` primitive
  (v5). Treat any pre-v5 charting snippet as suspect.

### 2. Lightweight Charts has NO native timezone support

- **Trap:** Passing exchange-local timestamps and expecting the chart to localize.
- **Why it bites:** All LWC times are **UTC epoch seconds**. The library does no
  timezone math — intraday bars will plot at the wrong wall-clock time and your
  ToD buckets will look shifted.
- **Rule:** UTC-shift intraday timestamps yourself (a dedicated helper). Note the
  domain side already standardizes: `BAR_SCHEMA.ts` is UTC tz-aware.

### 3. phosphor-svelte: use the `*Icon` suffix

- **Trap:** `import { TrendUp } from 'phosphor-svelte'`.
- **Why it bites:** Un-suffixed names are the **deprecated** path.
- **Rule:** Import with the `*Icon` suffix, e.g. `TrendUpIcon`, via per-icon lib
  imports.

---

## Python dependencies (licensing & sustainability)

### 4. Do NOT depend on `pandas-ta`; do NOT use `vectorbt`

- **Trap:** Reaching for `pandas-ta` for indicators or `vectorbt` for backtesting.
- **Why it bites:** `pandas-ta` is a **sustainability risk** (maintenance). More
  seriously, `vectorbt`'s **Commons-Clause license forbids SELLING the product** —
  a non-starter for a commercial scanner.
- **Rule:** **Own the core indicators** (VWAP / RVOL / ATR / POC) for testability
  and license safety. Use `nautilus_trader` (LGPLv3) for backtest/live. Optional
  TA-Lib only behind a wrapper.

---

## ML validation & labeling (the "looks amazing, trades catastrophically" class)

### 5. SHAP: use `interventional`, not the default `tree_path_dependent`

- **Trap:** `TreeExplainer(model)` with default perturbation.
- **Why it bites:** The default `tree_path_dependent` mode **mis-credits
  correlated features** — it hands the "culprit" to the wrong feature, which is
  fatal for an attribution engine whose entire job is naming the right cause.
- **Rule:** Use `interventional` perturbation mode. (And remember: SHAP explains
  the *model*, not the *market* — `MODEL_ATTRIBUTION_CAVEAT` rides along.)

### 6. Labeling leakage: ZigZag / centered / fractal pivots are NON-CAUSAL

- **Trap:** Using ZigZag or centered/fractal swing pivots as model features or
  backtest triggers.
- **Why it bites:** They use **future bars** to confirm a pivot. A backtest built
  on them looks spectacular and then **trades catastrophically live**, because
  the future isn't available at decision time.
- **Rule:** Non-causal pivots are fine for *visualization* and *candidate
  generation* only — **NEVER** as a model feature or backtest trigger. Use
  **causal (lookback-only)** pivots as features (the Phase 2 `find_peaks`
  approach is lookback-only).

### 7. Triple-barrier labels must be volatility-scaled

- **Trap:** Fixed-% upper/lower barriers.
- **Why it bites:** A fixed % is too tight in calm regimes and too loose in
  volatile ones, biasing the label distribution.
- **Rule:** Scale barriers by **k×σ** (volatility), not a fixed percentage.

### 8. Normalization leakage: fit scalers on the TRAIN fold only

- **Trap:** `StandardScaler().fit(X_all)` / z-scoring over the whole dataset
  before splitting.
- **Why it bites:** Whole-dataset fitting **leaks future statistics** into the
  training distribution — an invisible look-ahead that inflates OOS metrics.
- **Rule:** Fit StandardScaler / z-score parameters on the **train fold only**.
  Use **purged + embargoed CV** (`skfolio` `CombinatorialPurgedCV`) so labels
  spanning the split boundary don't leak either.

### 9. Backtest realism: fill on the NEXT bar, model costs, discount overfit

- **Trap:** Filling at the signal bar's close/high/low; ignoring slippage/costs;
  reading a single high Sharpe as proof.
- **Why it bites:** The signal bar's close/high/low **aren't known at decision
  time** — same-bar fills are a look-ahead. Frictionless fills and a single
  Sharpe ignore costs and multiple-testing overfit.
- **Rule:** **Fill on the NEXT bar, never same-bar.** Model realistic slippage +
  commission. Use **Deflated Sharpe** to discount multiple-testing. Walk-forward,
  not a single in-sample fit.

---

## Backend runtime (FastAPI / Nautilus / money)

### 10. FastAPI: run with `--workers 1`

- **Trap:** Default/multiple uvicorn workers.
- **Why it bites:** Each worker is a separate process — the APScheduler poller
  **double-polls** the vendor (rate-limit + duplicate signals) and the WebSocket
  connection manager **splits** across processes (a client connected to worker B
  never sees a broadcast from worker A).
- **Rule:** Run with **`--workers 1`**. The poller and WS manager must be a
  single instance. (Same in deployment — Railway `--workers 1`.)

### 11. nautilus_trader: keep domain/signal logic OUTSIDE it

- **Trap:** Implementing signal logic inside a Nautilus `Strategy`.
- **Why it bites:** It forks the engine — live and backtest can drift, breaking
  the parity guarantee that the whole design rests on.
- **Rule:** All domain/signal logic lives outside Nautilus. A **thin adapter**
  wraps `SignalEngine` as a Strategy, so backtest and live share **one** engine.

### 12. Money / P&L in cents = i64 / BIGINT end-to-end

- **Trap:** Using `i32` / `INTEGER` for a `*_cents` value "because it's small."
- **Why it bites:** `i32` caps at ~$21.5M — fine per-trade, but **overflows on
  rollups** (cumulative P&L, equity curve sums).
- **Rule:** `i64` / `BIGINT` for money everywhere, never `i32`. (Row counts like
  `revisions` may stay `i32`.)

---

## Data correctness (the honesty contract, enforced in code)

### 13. BarSet `ts` is the bar START time, UTC tz-aware

- **Trap:** Treating `ts` as the bar's close/end, or as exchange-local time.
- **Why it bites:** yfinance intraday timestamps are **tz-aware exchange time** —
  if not converted, every ToD bucket and internals join is off by the UTC offset,
  and an off-by-one on start-vs-end shifts fills.
- **Rule:** `ts` is the bar **START**, **UTC tz-aware** (`BAR_SCHEMA`). Convert
  yfinance intraday to UTC on ingest (the provider already does
  `pd.to_datetime(..., utc=True)`).

### 14. GEX: never compute/display a number without a real options chain

- **Trap:** Estimating gamma exposure from a proxy when the chain is missing.
- **Why it bites:** A fabricated GEX is a confident-wrong answer — exactly what
  the honesty contract forbids.
- **Rule:** No GEX number is computed or displayed without a real `OptionChain`.
  Flag **"insufficient data"** instead.

### 15. Detectors must say "insufficient data," never guess

- **Trap:** A detector returning a low-confidence guess when its inputs are
  missing (short interest stale, no options chain, internals dormant).
- **Why it bites:** A guess pollutes the attribution ranking and the
  `data_completeness` story — the system silently overstates what it measured.
- **Rule:** A detector lacking inputs returns `DetectedEvent.insufficient(...)`
  (`domain/events.py`) — counted as dormant, never a guess. Every `Signal`
  carries `data_completeness`; when measured internals don't explain a move the
  engine returns `uncertain_attribution(...)` → **"cause uncertain."**
  Fail-loud / say-uncertain beats a confident wrong answer.
