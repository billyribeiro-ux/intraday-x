# intraday-x — ARCHITECTURE

How the system is put together and *why*. The non-obvious design choices all
serve one goal: a scanner that **degrades honestly** instead of overpromising —
a vendor-agnostic data layer, leak-free validation, and an attribution engine
that says "cause uncertain" rather than inventing a reason.

---

## Monorepo layout

```
intraday-x/
  backend/
    pyproject.toml  uv.lock  .python-version          # uv, py3.12
    src/intradayx/
      domain/        bars internals options shorts signals events capabilities   # pure types, no I/O
      data/          provider.py(ABC) composite.py cache.py
                     providers/{yfinance,twelvedata,polygon,schwab,databento,finra_shorts}.py
      storage/       lake.py duck.py schema.py catalog.py
      features/      indicators volume_profile pivots session gaps climax internals_ctx pipeline
      attribution/   detectors/{volume_surge,climax_reversal,vwap_reclaim,gap_and_go,short_squeeze*,gamma_squeeze*}
                     registry.py labeling.py model.py explain.py engine.py
      signals/       engine.py reversal.py scalping.py(later) params.py        # SINGLE SOURCE OF TRUTH
      backtest/      runner.py walkforward.py metrics.py fills.py
      live/          monitor.py feed.py internals_recorder.py
      export/        csv_export.py pdf_report.py charts.py
      api/           app.py routes/ ws.py schemas.py
    tests/           unit/ fixtures/ integration/ golden/
  frontend/                                            # SvelteKit 5, pnpm
    src/lib/{api,realtime,chart,components,icons}/  src/routes/{monitor,backtest,symbol}/
    vite.config.ts                                     # /api + /ws dev proxy → :8000
  data/              # gitignored: parquet lake + meta.duckdb
  config/            settings.toml instruments.toml
  docs/              ROADMAP.md ARCHITECTURE.md DATA_PROVIDERS.md AI_LANDMINES.md
```

The Python backend owns everything from data ingestion through features,
attribution, signals, backtest, live, export, and the API. The SvelteKit
frontend is the monitor/backtest dashboard. `domain/` is pure value types with
**no I/O** — so the contracts can be imported and tested anywhere without
touching a network or disk.

---

## Principle 1 — one shared SignalEngine

The backtester and the live poller call the **same** `SignalEngine.evaluate()`.
It is never forked. This is the single most important structural rule in the
system: a backtested edge is only trustworthy if the live path runs identical
logic, bar for bar.

```
                    ┌──────────────────────────┐
   historical bars ▶│                          │◀ live polled bars
                    │   SignalEngine.evaluate() │
                    │   (signals/engine.py)     │
                    └──────────────┬────────────┘
                                   │ identical Signal objects
              ┌────────────────────┴────────────────────┐
              ▼                                          ▼
   backtest/runner.py                              live/monitor.py
   (event-driven sim, fill-on-next-bar)            (APScheduler poller → WS)
```

- The engine lives **outside** the execution runtime. `backtest/runner.py` is a
  custom event-driven backtester that drives the engine; `live/monitor.py` drives
  the same engine from an APScheduler `AsyncIOScheduler`. Neither owns signal
  logic. (`nautilus_trader` is deferred to the go-live phase as a thin adapter
  for real broker execution — see ADR 0002.)
- Identity is deterministic: `make_signal_id(symbol, ts, kind, params_version)`
  (`domain/signals.py`) hashes those four fields, so a re-poll of the same window
  never re-fires and backtest vs live agree on signal identity.
- This is enforced by a **parity test** (Phase 3): the same OHLCV fixture run
  through the backtest adapter and a live-monitor replay must emit a
  byte-identical `Signal` set.

---

## Principle 2 — the Capability system is the linchpin

Every provider declares a `frozenset[Capability]`. Features and detectors that
need a capability the active provider lacks stay **dormant** instead of
fabricating data, and the absence **lowers** a signal's `data_completeness`
(surfaced in the UI and PDF). When a capable vendor is added later, the gated
code activates with **zero rewrites**.

### The types (`domain/capabilities.py`)

- **`Capability`** (`StrEnum`) — the catalog: bar capabilities
  (`DAILY_BARS`, `INTRADAY_BARS_1M/5M`, `EXTENDED_HISTORY_INTRADAY`,
  `PREPOST_MARKET`, `LIVE_STREAM`), breadth/volatility internals
  (`INTERNALS_TICK/TRIN/ADD/VOLD/VIX/VIX_TERM/SKEW/PUTCALL`), options
  (`OPTIONS_CHAIN_LIVE/HISTORY`, `OPTIONS_GREEKS`), and short data
  (`SHORT_INTEREST`, `SHORT_VOLUME`, `BORROW_RATE`).
- **Convenience groupings** — `INTERNALS_BREADTH`, `INTERNALS_VOLATILITY`,
  `OPTIONS_FULL`, `SHORT_FULL` — so a feature can gate on a whole family at once.
- **`ProviderCapabilities`** — `supported: frozenset[Capability]` plus a
  per-`Timeframe` `max_intraday_lookback` map and a `rate_limit_hint`. Methods:
  `supports`, `supports_all`, `require` (raises), `lookback_for`.
- **`CapabilityError`** — raised (never an empty return) when a provider is asked
  for something it does not support. Raising keeps degradation explicit — a
  missing internal can never be silently misread as "no extreme."

### How gating works in the data layer (`data/provider.py`)

The `DataProvider` ABC makes `capabilities()` and `bars()` abstract; the optional
surfaces (`internals`, `options_chain`, `short_interest`, `short_volume`,
`borrow_rate`) all default to **raising `CapabilityError`**. A concrete provider
therefore only overrides what it genuinely supplies, and the rest of the system
gates on `capabilities().supports(...)` before calling — degrading honestly.

`_check_lookback()` raises `LookbackExceededError` when a requested `start` is
older than the timeframe's `max_intraday_lookback` — so a backtest can't quietly
run on a shorter window than the caller asked for.

### CompositeProvider (`data/composite.py`)

Registers providers with a priority (lower = preferred). For a bars request it
picks the highest-priority provider that (a) supports the timeframe's required
capability and (b) can reach back far enough, then falls through on
capability/lookback/empty. `capabilities()` unions every member's support set
and takes the *deepest* lookback per timeframe. The merged `BarSet` retains the
`source` column, keeping every row auditable. This is what makes "add a vendor
later" free: a deep-history 1m request automatically routes to Twelve Data over
yfinance, and internals/options route to whichever vendor declares them.

### How completeness flows into a Signal

`data_completeness` (0–1, on every `Attribution`) is the share of *relevant*
capabilities that were actually available. A `Signal.confidence` is already
scaled down by it. When the available internals don't explain a move, the engine
returns `uncertain_attribution(...)` — a first-class **"cause uncertain"**
output, not a silent gap.

---

## Principle 3 — honest, leak-free attribution

- **Deterministic detectors first.** `attribution/detectors/*` inspect the
  causal feature row at a bar and return `DetectedEvent`s
  (`domain/events.py`) — grounded, explainable candidate causes with evidence.
  A detector lacking its inputs returns `DetectedEvent.insufficient(...)`
  (counted as dormant), never a guess.
- **ML explains the model, not the market.** SHAP-derived `Cause`s carry
  `source = MODEL` and a normalized |SHAP| share; they describe *what the model
  keyed on*. `MODEL_ATTRIBUTION_CAVEAT` (correlation ≠ causation) rides with
  every model attribution.
- **Leak-free or it doesn't ship.** Causal (lookback-only) features,
  fill-on-next-bar, purged/embargoed CPCV, walk-forward, Deflated Sharpe,
  scalers fit on the train fold only. (Enforced in Phases 2–6; see AI_LANDMINES.)

---

## Data flow

```
ticker
  ▼
DataProvider  (yfinance │ Twelve Data │ Polygon │ … via CompositeProvider, capability-gated)
  ▼
Parquet lake + DuckDB   (storage/ — Hive-partitioned, gap-detected)
  ▼
FeatureSet   (features/pipeline.py — VWAP/POC/VAH/VAL, RVOL, causal pivots,
              climax, ToD buckets, internals context* — *capability-gated)
  ▼
Attribution engine   (attribution/ — rule detectors + LightGBM/SHAP →
                      ranked "culprit", or "cause uncertain")
  ▼
SignalEngine.evaluate()   ◀── SHARED ──▶   Backtester (custom)  &  Live poller
  ▼
Signal { confidence, attribution, data_completeness }
  ▼
CSV / PDF export   +   FastAPI REST / WebSocket
  ▼
SvelteKit dashboard   (later: ThinkScript export)
```

The internals self-recorder (`live/internals_recorder.py`) runs alongside this
flow, banking $TICK/$TRIN/$ADD/$VOLD from a realtime feed into the same lake —
because that history is not cheaply purchasable (see DATA_PROVIDERS.md).

---

## Key domain types

All under `backend/src/intradayx/domain/`. Pure values, no I/O.

### Bars — `domain/bars.py`

- **`Timeframe`** (`StrEnum`): `1m/5m/15m/30m/1h/1d`, with `timedelta`,
  `is_intraday`, and `pandas_freq` helpers.
- **`BAR_SCHEMA`** — the canonical Polars column schema shared by the domain and
  the storage layer: `ts` (Datetime, µs, **UTC**), `open/high/low/close`
  (Float64), `volume` (Int64), `vwap` (Float64, nullable), `trades` (Int64,
  nullable), `source` (String). **`ts` is the bar START time**, tz-aware UTC.
- **`Bar`** — frozen single-row value object for tests / rare row iteration.
- **`BarSet`** — single-symbol, single-timeframe, backed by a Polars DataFrame.
  `_coerce` reorders + casts to `BAR_SCHEMA`, de-dupes on `ts` (keep last), and
  sorts ascending so downstream code can rely on **causal ordering**.

### Signals & attribution — `domain/signals.py`

- **`Signal`** — timestamped buy/sell signal: `signal_id`, `symbol`, `ts`
  (the producing bar's close, UTC), `kind` (`SignalKind`), `side` (`Side`),
  `confidence` (already scaled by `data_completeness`), `entry`/`stop`/`targets`,
  `time_of_day_bucket`, `attribution`, `triggered_rules`, `params_version`,
  `feature_snapshot`. Built via `Signal.create(...)` which derives the
  deterministic `signal_id`.
- **`Attribution`** — the "why," with mandatory honesty fields:
  `ranked_causes`, **`data_completeness`** (0–1), **`uncertain`** flag, and a
  `caveat` (defaults to `MODEL_ATTRIBUTION_CAVEAT`). Its `summary` returns
  **"Cause uncertain — move not explained by available internals."** when
  uncertain or empty.
- **`Cause`** — one ranked contributor: `kind` (`CauseKind`), `score` (0–1),
  `source` (`RULE` = deterministic/trustworthy vs `MODEL` = SHAP/correlational),
  `label`, `evidence`.
- **`uncertain_attribution(...)`** — the canonical "cause uncertain" output
  (a single `UNEXPLAINED` cause, `uncertain=True`).
- `make_signal_id(...)` — SHA1 of `symbol|ts|kind|params_version` (16 hex chars).

### Detected events — `domain/events.py`

- **`DetectedEvent`** — what a deterministic detector emits: `kind`, `ts`,
  `strength`, `evidence`, `sufficient_data`, `note`. `DetectedEvent.insufficient(...)`
  is the dormant/no-guess marker.

### Internals — `domain/internals.py`

- **`InternalSymbol`** (`StrEnum`) — thinkorSwim-style `$` names: `$TICK`,
  `$TRIN`, `$ADD`, `$VOLD`, `$UVOL`, `$DVOL`, `$VIX`, `$VIX9D`, `$VIX3M`,
  `$VVIX`, `$SKEW`, `$PCALL`.
- **`INTERNALS_SCHEMA`** + **`InternalsSeries`** — long/tidy form (`ts`, `value`,
  `source`), one value per timestamp, so a new internal is just a new partition —
  no schema change. Same coerce/de-dupe/sort discipline as `BarSet`.

### Options — `domain/options.py`

- **`OptionRight`**, **`OptionContract`** (incl. greeks), **`OptionChain`** —
  the contract the Phase 9 `gamma_squeeze` detector and a future options-capable
  provider share. No GEX is computed/displayed without a real chain.

### Shorts — `domain/shorts.py`

- **`ShortInterest`** (with `settlement_date` vs `published_date` so staleness
  can be flagged), **`ShortVolume`** (`short_volume_ratio`), **`BorrowRate`** —
  for the Phase 8 `short_squeeze` detector.

---

## Critical files (load-bearing)

| File | Why it matters |
|---|---|
| `backend/src/intradayx/data/provider.py` | `DataProvider` ABC — the contract everything degrades against. |
| `backend/src/intradayx/domain/capabilities.py` | The capability catalog + `ProviderCapabilities` + `CapabilityError`. |
| `backend/src/intradayx/data/composite.py` | The router that makes "add a vendor later" free. |
| `backend/src/intradayx/signals/engine.py` | The single `SignalEngine.evaluate()` shared by backtest + live. |
| `backend/src/intradayx/domain/signals.py` | `Signal` + `Attribution` (with `data_completeness`), used everywhere. |
| `backend/src/intradayx/backtest/runner.py` | Custom event-driven backtester driving the shared engine (parity with live). |
| `backend/src/intradayx/features/pipeline.py` | Capability-gated `FeatureSet` builder feeding engine + ML. |
| `backend/src/intradayx/live/internals_recorder.py` | Banks $TICK/$TRIN/$ADD/$VOLD history (built now, fed later). |
| `frontend/src/lib/realtime/signal-store.svelte.ts` | Runes WS store (reconnect/backoff/heartbeat). |
| `frontend/src/lib/components/IntradayChart.svelte` | LWC v5 candles + volume pane + VWAP/POC + `createSeriesMarkers`. |
