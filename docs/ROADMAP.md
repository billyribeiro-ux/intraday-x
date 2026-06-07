# intraday-x — ROADMAP

The master "so we don't forget" plan. Every phase has a **Goal**, concrete
**Deliverables**, the **Data dependency** it rides on, and an **Exit gate** —
the *runtime evidence* that proves the phase is done. "Tests pass" is necessary
but never sufficient: each gate names an artifact (a CLI run, a query result, a
parity assertion, a Playwright CLS measurement) that demonstrates the feature
actually works.

## Status legend

| Marker | Meaning |
|---|---|
| ✅ DONE | Shipped and meets its exit gate. |
| 🔵 IN PROGRESS | Partially landed; remaining items called out. |
| ⬜ TODO | Not started. |

## Status at a glance

| Phase | Title | Status |
|---|---|---|
| 0 | Scaffold | ✅ DONE |
| 1 | Data + lake + internals-recorder scaffold | ✅ DONE |
| 2 | Features + Reversal SignalEngine (first scanner) | ✅ DONE |
| 3 | Backtester + Live monitor, in parallel | ✅ DONE (custom engine; Nautilus deferred to go-live) |
| 4 | Export (CSV + PDF) | ✅ DONE |
| 5 | API + Svelte dashboard (live-wired) | ✅ DONE |
| 6 | Attribution ML ("self-learning culprit") | ✅ DONE (core) |
| 7 | Capable vendor adapters (the real sub) | 🔒 BLOCKED — needs paid data sub (interface ready) |
| 8 | Short-squeeze detector | ⬜ TODO — FINRA SI is free (biweekly/lagged); detector stub in place |
| 9 | Gamma-squeeze / GEX | 🔒 BLOCKED — needs options-chain data (paid); detector stub in place |
| 10 | Scalping scanner | ✅ DONE |
| 11 | ThinkScript export | ✅ DONE |
| 12 | Hardening / scale | ⬜ TODO — deploy (Vercel/Railway), TimescaleDB, model monitoring |

**Current state:** everything achievable on free data is done (Phases 0–6, 10,
11 + earnings catalyst). Both scanners (reversal + scalping) run through one
strategy-driven engine. Phases 7 & 9 are gated on the paid data subscription —
the capability system + dormant detector stubs mean they activate with no rewrite
once a vendor is wired. Phase 8 (FINRA short interest, free) and Phase 12 (deploy)
are the remaining extensions.

**Bonus — earnings-catalyst attribution (extends Phase 6).** Earnings are the
one catalyst nameable for free (`Capability.EARNINGS_CALENDAR`, yfinance). A
signal landing within ±1 day of a scheduled-earnings date is attributed
`CauseKind.EARNINGS` (`attribution/catalysts.py`), turning "cause uncertain" into
"Coincides with scheduled earnings". Wired into `scan`, the API, and a new
`intradayx earnings <TICKER>` command. Verified on AAPL (04-30 earnings →
post-earnings reversal signals correctly tagged).

---

## Phase 0 — Scaffold ✅ DONE

**Goal.** Stand up a working monorepo skeleton — backend + frontend both boot —
with the immovable foundations in place: pinned toolchain, pure domain types,
and the capability system that the entire honesty contract leans on.

**Deliverables.**
- Monorepo layout (`backend/`, `frontend/`, `data/`, `config/`, `docs/`).
- `uv` + Python **3.12** pinned via `.python-version`; `ruff` + `mypy` +
  `pytest` + `pre-commit`; CI.
- `domain/` pure value types, no I/O:
  - `bars.py` — `Timeframe`, `Bar`, `BarSet`, canonical `BAR_SCHEMA`.
  - `capabilities.py` — `Capability` enum, `ProviderCapabilities`,
    `CapabilityError`, convenience groupings (`INTERNALS_BREADTH`, etc.).
  - `signals.py` — `Signal`, `Attribution`, `Cause`, `uncertain_attribution`,
    `make_signal_id`, `MODEL_ATTRIBUTION_CAVEAT`.
  - `internals.py`, `options.py`, `shorts.py`, `events.py` — the schemas the
    later gated detectors will share with their providers.
- SvelteKit scaffold + Vite `/api` + `/ws` dev proxy → `:8000` +
  `phosphor-svelte` (`*Icon` suffix).
- The four `docs/` files (this set).

**Data dependency.** None — pure types and tooling.

**Exit gate.** `uv run` boots the backend and `pnpm dev` boots the frontend;
the (empty/minimal) test suite is green. The `domain/` types import with no I/O
and `Capability`/`ProviderCapabilities` round-trip in a unit test.

---

## Phase 1 — Data + lake + internals-recorder scaffold ✅ DONE

**Goal.** A vendor-agnostic data layer that degrades honestly: declare what each
vendor can do, route to the best one, write to a local Parquet/DuckDB lake, and
stand up the internals self-recorder *now* so banked breadth history starts
accumulating as early as a realtime feed exists.

**Deliverables.**
- ✅ `DataProvider` ABC (`data/provider.py`) — `capabilities()` + `bars()`
  abstract; `internals`/`options_chain`/`short_interest`/`short_volume`/
  `borrow_rate` default to raising `CapabilityError`; `Session`, `DataError`,
  `LookbackExceededError`, `MissingCredentialsError`, `_check_lookback`.
- ✅ **yfinance** provider (`providers/yfinance_provider.py`) — zero-setup demo;
  declares lookbacks (1m≈7d, 5m/15m/30m≈60d, 1h≈730d) and raises
  `LookbackExceededError` past them; tz-aware → UTC conversion.
- ✅ **Alpaca** provider (`providers/alpaca_provider.py`) — free IEX feed, the
  ~7–10yr 1-minute backbone; lazy `alpaca-py` import; `MissingCredentialsError`
  when keys absent; passes through `vwap` + `trade_count`→`trades`.
- ✅ `CompositeProvider` (`data/composite.py`) — routes each request to the
  highest-priority capable vendor that can reach far enough back, falls through
  on capability/lookback/empty, unions capabilities, retains the `source` column.
- ✅ Parquet/DuckDB lake (`storage/lake.py`, `duck.py`, `catalog.py`) — Hive
  partitioning by `(timeframe, symbol, year, month)`, idempotent upsert on `ts`,
  Polars read path + DuckDB SQL views, coverage stats via `Catalog`.
- ✅ `live/internals_recorder.py` scaffold — runs against any provider; honestly
  SKIPS every breadth internal under a price/volume vendor (no fabrication),
  ready to bank $TICK/$TRIN/$ADD/$VOLD the moment a realtime feed is registered.
- ✅ `intradayx ingest` CLI wired end-to-end into the lake.
- ⬜ **Deferred refinements:** fine-grained intraday gap detection (today it's
  coverage-based), `cache.py` read-through, and the free daily VIX/SKEW
  (Cboe/FRED) bootstrap for the recorder.

**Data dependency.** yfinance (no creds) for the demo path; **Alpaca**
(`ALPACA_API_KEY` + `ALPACA_SECRET_KEY`) for the multi-year backbone. Free daily
VIX/SKEW from Cboe/FRED for the internals-recorder bootstrap.

**Exit gate.** `intradayx ingest SPY` lands multi-year 1-minute Parquet sourced
from Alpaca into the lake; a DuckDB query returns those bars; the default test
suite blocks network sockets (a stray real call fails loud), with an opt-in
`@pytest.mark.network` smoke test hitting a tiny recent yfinance/Alpaca window.

---

## Phase 2 — Features + Reversal SignalEngine (FIRST scanner) ✅ DONE

**Goal.** Build the reversal feature set and the single `SignalEngine` that
turns features into ranked, attributed signals. This is the first scanner
(reversal / tops-bottoms); scalping comes in Phase 10.

**Deliverables.**
- Polars indicators (`features/indicators.py`): VWAP + bands, **time-of-day-
  matched** RVOL, ATR. Own the core for testability.
- Volume profile (`features/volume_profile.py`): POC/VAH/VAL + Initial Balance
  from OHLCV binning — documented as an *approximation* (no delta without tick
  data).
- **Causal** swing pivots (`features/pivots.py`): `scipy.signal.find_peaks`,
  lookback-only — never centered/fractal (those leak the future; see
  AI_LANDMINES).
- Gaps (`features/gaps.py`), climax/exhaustion (`features/climax.py`).
- Time-of-day buckets (`features/session.py`):
  `open_drive/morning/lunch/afternoon/power_hour`.
- Internals-context features (`features/internals_ctx.py`) — **capability-gated**
  and dormant now.
- `features/pipeline.py` — capability-gated `FeatureSet` builder feeding the
  engine and (later) ML.
- Weighted confluence/divergence scoring (TICK+TRIN+VOLD core, VIX/PCR overlay,
  SKEW context-only).
- Deterministic detectors (`attribution/detectors/`): `volume_surge`,
  `climax_reversal`, `vwap_reclaim`, `gap_and_go`; `short_squeeze` /
  `gamma_squeeze` as stubs that return `DetectedEvent.insufficient(...)`.
- `signals/engine.py` (`SignalEngine.evaluate()`), `signals/reversal.py`,
  `signals/params.py`.

**Data dependency.** Phase 1 lake (Alpaca 1m bars). Internals features stay
dormant until Phase 7.

**Exit gate.** ✅ MET — `intradayx scan AAPL --scanner reversal` prints
timestamped tops/bottoms each with side, confidence (scaled by
`data_completeness`), time-of-day bucket, entry/stop, and a ranked "why"; 15
unit/integration tests pass (indicator maths vs hand-computed values, the
`VAH ≥ POC ≥ VAL` `hypothesis` invariant, pivot causality, and a deterministic
signal-engine anchor proving the exact confluence maths + signal-id determinism).

**As built (minor deltas from the deliverables above).**
- Causal pivots use a Polars centered rolling-extreme + `shift(k)` (mathematically
  equivalent, no extra dep) rather than `scipy.find_peaks`.
- Detectors live in `attribution/detectors/price_volume.py` (volume_surge,
  climax_top/bottom, value_area_edge, poc_proximity) + `squeezes.py` (the
  capability-gated short/gamma stubs), rather than one file per detector.
- v1 confluence weights climax 0.45 / volume 0.20 / value-area 0.25 / POC 0.10.
- `internals_ctx.py` and `vwap_reclaim`/`gap_and_go` detectors are deferred (they
  earn their keep with internals data / for the scalping scanner).
- `attribution/engine.py` builds the ranked-cause Attribution (rule-based);
  SHAP/ML is Phase 6.

---

## Phase 3 — Backtester + Live monitor, in parallel ✅ DONE

**Goal.** Run the **same** `SignalEngine` through a historical backtest and a
live poller, and prove they agree. Built together because the parity guarantee
is the whole point.

**Engine decision (deviation from the plan, documented).** We built a **custom
event-driven backtester** rather than `nautilus_trader`. The plan explicitly
preserved this as the sanctioned fallback "in case Nautilus's data model proves
too heavy for early iteration" — and because all signal logic already lives
*outside* the runtime in `SignalEngine`, backtest↔live parity holds regardless of
the executor. Nautilus is a heavy Rust-backed dep whose value is realistic broker
execution + a live gateway; it's deferred to the **go-live phase** (a thin
`nautilus_adapter.py` wrapping the same `SignalEngine`). The custom engine is the
research backtester.

**Deliverables.**
- ✅ `backtest/fills.py` — `FillModel`: **fill-on-next-bar** open + adverse
  slippage (bps) + per-share commission; money in integer cents.
- ✅ `backtest/runner.py` — `simulate_trades()` (pure, deterministic) +
  `run_backtest()` (scan via shared engine → simulate); single-position, stop +
  first-target + bar-count time-stop; `Trade` / `BacktestResult`.
- ✅ `backtest/metrics.py` — win rate, expectancy, profit factor, max drawdown,
  per-trade Sharpe (unannualized), and the **per-time-of-day breakdown**.
- ✅ `live/monitor.py` — `LiveMonitor` poll→evaluate→dedup core using the **same**
  `SignalEngine`; signal dedupe by deterministic `signal_id`.
- ✅ `intradayx backtest <TICKER>` CLI.
- ⬜ **Deferred:** APScheduler loop + websocket fan-out (Phase 5); walk-forward
  runner + Deflated Sharpe (Phase 6); `nautilus_adapter.py` (go-live).

**Data dependency.** Phase 1 lake / providers for backtest; live poll from
yfinance/Alpaca for the monitor.

**Exit gate.** ✅ MET — `intradayx backtest AAPL` runs on 55 days of real 5m data
(102 signals → 90 trades) with metrics + per-ToD breakdown; a deterministic
fixture reproduces *exact* trade P&L (`test_backtest.py`); a **parity test**
(`test_parity.py`) asserts incremental/live evaluation equals the batch/backtest
signal set and that the monitor never re-emits a seen signal. 21 tests pass.
(Honest result: the unoptimized v1 reversal scanner *loses* on free data — the
edge needs internals (Phase 7) + ML refinement (Phase 6).)

---

## Phase 4 — Export (CSV + PDF) ✅ DONE

**Goal.** Turn the signal log and backtest results into shareable artifacts that
carry the honesty fields all the way through.

**Deliverables.**
- ✅ `export/csv_export.py` — `signals_to_csv` (one row per Signal incl. primary
  cause, ranked causes, `data_completeness`, uncertain flag) + `trades_to_csv`
  (P&L in both cents and dollars).
- ✅ `export/pdf_report.py` — ReportLab PDF: header + run metadata, metrics
  table, equity curve, per-ToD expectancy chart, and the **"attribution limited
  by available data" + assume-overfit** caveat banner. (ReportLab + matplotlib.)
- ✅ `export/charts.py` — matplotlib (Agg) → PNG helpers embedded in the PDF.
- ✅ `intradayx backtest --export DIR` writes signals.csv, trades.csv, report.pdf.

**Data dependency.** Phase 3 backtest/live signal outputs.

**Exit gate.** ✅ MET — CSV field-level test + a deterministic trades-CSV P&L
assert + a structural PDF test (starts with `%PDF`, embeds chart images); a real
`backtest AAPL --export` run produced an 8KB signals.csv, trades.csv, and a
49KB 1-page report.pdf.

---

## Phase 5 — API + Svelte dashboard (live-wired) ✅ DONE

**Goal.** Expose scan/backtest/bars over a single-instance FastAPI service and
render them live in the SvelteKit dashboard.

**Deliverables.**
- ✅ FastAPI REST (`api/app.py`, `api/routes/{market,analysis}.py`,
  `api/schemas.py`, `api/service.py`): `GET /healthz`,
  `GET /api/providers/capabilities`, `GET /api/bars` (chart-ready),
  `POST /api/scan`, `POST /api/backtest`. CORS for the dev origin.
- ✅ WebSocket (`api/ws.py`): `ConnectionManager` + `SignalPoller` (APScheduler
  `AsyncIOScheduler`, 30s) running the **same** SignalEngine via `LiveMonitor`;
  `status/heartbeat/signal/error` envelope carrying `source`/`mode`/session
  provenance. **`--workers 1`** enforced via the `intradayx serve` command (the
  poller + WS manager must be single-instance — AI_LANDMINES).
- ✅ Frontend wired live: `api/client.ts` + `+page.ts` load (ssr=false) fetch
  `/api/bars` + `/api/scan`; `signal-store.svelte.ts` connects the WS
  (reconnect/backoff/heartbeat); `$derived` merge of live + historical signals.
- ⬜ **Deferred:** backtest-results route in the UI, CSV/PDF download buttons,
  filters, and the Playwright CLS spec (next iteration of the dashboard).

**Data dependency.** Phase 3 live signals over WS; Phase 1 providers for bars.

**Exit gate.** ✅ MET — `intradayx serve` boots; curl verified `/healthz`,
`/api/providers/capabilities`, `/api/scan` (390 bars → 5 signals), `/api/bars`
(390 candles + markers + levels), `/api/backtest` (40 signals → 35 trades); the
Vite dev proxy round-trip (`:5173/api/* → :8000`) returns live data; frontend
`svelte-check` 0/0 and production build pass.

---

## Phase 6 — Attribution ML ("self-learning culprit") ✅ DONE (core)

**Goal.** Layer a leak-free ML attribution model on top of the deterministic
detectors — ranking which features the model keyed on, never claiming causation.

**Deliverables.**
- ✅ Labeling (`attribution/labeling.py`): **volatility-scaled triple-barrier**
  (k×σ EWMA vol, not fixed %); tail bars left unlabelled (no truncated-horizon
  bias).
- ✅ Leak-free validation (`attribution/validation.py`): **purged + embargoed
  K-fold**, Probabilistic Sharpe Ratio, and the **Deflated Sharpe Ratio**
  (discounts multiple-testing overfit; wired into `intradayx backtest` as
  `P(Sharpe>0)`).
- ✅ Model + explanation (`attribution/learn.py`): **LightGBM** classifier
  ("significant move imminent") evaluated under purged CV; **SHAP `TreeExplainer`
  in `interventional` mode** → ranked feature attribution. `intradayx learn`.
- ✅ **Honesty enforced:** `MODEL_ATTRIBUTION_CAVEAT` printed; the real AAPL run
  showed **CV macro-F1 ≈ 0.51** (barely above chance) — the truth on free data.
- ⬜ **Deferred:** XGBoost/CatBoost ensemble compare, `tsfresh` auto-features,
  `arch`/`ruptures`/`hmmlearn` regime tags, meta-labeling on signals, model
  calibration, walk-forward retraining (the libs are installed; these are
  refinements that mainly pay off with Phase 7–9 data). PyTorch → Phase 12.
- *Note (macOS):* the `ml` extra's LightGBM/XGBoost need `brew install libomp`.

**Data dependency.** Phase 1–2 lake + features; far richer once Phases 7–9 add
internals/options/short truth.

**Exit gate.** ✅ MET — purged CV produces out-of-sample F1; `deflated_sharpe_ratio`
+ leakage test (`test_validation.py` asserts zero train/test overlap within the
label horizon) pass; `intradayx learn AAPL` trains LightGBM on 2,726 real bars
and prints SHAP attribution (top: minutes_from_open, gaps, dist-to-POC) with the
correlation≠causation caveat.

---

## Phase 7 — Capable vendor adapters (the real sub) ⬜ TODO

**Goal.** Plug in paid/credentialed vendors so the internals- and options-gated
features that have been dormant since Phase 2 **auto-activate** with zero rewrites.

**Deliverables.**
- Providers: Polygon/Massive (indices incl. VIX + options), Schwab-TOS (realtime
  internals feed for the recorder), Databento — each declaring the relevant
  `INTERNALS_*` / `OPTIONS_*` capabilities.
- Internals-divergence features + internals-gated reversal confirmations light
  up automatically once a provider declares the capability.
- Wire `live/internals_recorder.py` to the live realtime feed so breadth history
  banks continuously.

**Data dependency.** Polygon/Massive (~$79+/mo), Schwab-TOS (free w/ account,
OAuth2), Databento (pay-as-you-go). Note: deep pre-2023 intraday index history
needs paid Cboe DataShop; breadth internals still rely on the self-recorded series.

**Exit gate.** With a capable provider registered, `/providers/capabilities`
shows the new `INTERNALS_*`/`OPTIONS_*` flags and a re-scan emits signals whose
`data_completeness` rose and whose attributions now include internals causes —
without touching feature/detector code.

---

## Phase 8 — Short-squeeze detector ⬜ TODO

**Goal.** Activate the `short_squeeze` detector using short-interest, short-
volume, and borrow data — flagging stale data rather than guessing.

**Deliverables.**
- Providers: FINRA short interest (free, biweekly, ~2-week lag — flagged stale)
  + daily short-volume; Ortex/S3 (paid: fresh SI + cost-to-borrow + utilization);
  IBKR borrow rate/availability.
- `attribution/detectors/short_squeeze.py` activated via the `SHORT_*`
  capabilities (days-to-cover + borrow-spike + price/volume signature).

**Data dependency.** FINRA (free), Ortex/S3 (paid), IBKR TWS (funded account).
The `ShortInterest.published_date` vs `settlement_date` split lets the detector
flag staleness (treating a stale figure as live would also be a leakage bug).

**Exit gate.** A constructed squeeze fixture triggers the detector with a
non-stale feed and returns `insufficient` (never a guess) when SI is stale or
missing; the emitted signal's attribution names `SHORT_SQUEEZE` with evidence.

---

## Phase 9 — Gamma-squeeze / GEX ⬜ TODO

**Goal.** Activate the `gamma_squeeze` detector from real options chains — and
**never** display a GEX number without one.

**Deliverables.**
- Options providers: ORATS preferred (1-minute greeks/IV since Aug 2020) or
  Polygon/Databento OPRA + our own greeks.
- Per-strike `GEX = γ · 100 · OI · spot² · 0.01`, gamma-flip level, strike
  pinning, 0DTE/charm/vanna EOD flows.
- `attribution/detectors/gamma_squeeze.py` activated via `OPTIONS_*`
  capabilities.

**Data dependency.** ORATS (best gamma path), or Polygon/Databento OPRA.

**Exit gate.** With a chain present, a GEX number + gamma-flip level render; with
no chain, the detector returns "insufficient data" and the UI shows that state —
never a fabricated GEX.

---

## Phase 10 — Scalping scanner ✅ DONE

**Goal.** Add the second scanner on the *same* `SignalEngine` interface, reusing
all of backtest/live/export/dashboard.

**Deliverables.**
- ✅ Generalized `SignalEngine` to be **strategy-driven** (`signals/strategy.py`
  `Strategy` protocol + `make_strategy`); `ReversalStrategy` and `ScalpingStrategy`
  share the universal signal columns, so backtest/export/API/dashboard reuse them.
- ✅ `signals/scalping.py` — discrete momentum entries: VWAP reclaim/rejection OR
  Initial-Balance breakout, confirmed by relative volume + a directional bar;
  tight ATR stop/targets; `ScalpingParams`.
- ✅ `scalping_attribution` (VWAP / volume / momentum / breakout causes;
  `CauseKind.MOMENTUM` + `BREAKOUT` added).
- ✅ `--scanner reversal|scalping` on `scan` + `backtest`; API `/api/scan` honors it.
- ⬜ **Deferred:** $TICK-extreme confirmation (needs Phase 7 internals).

**Data dependency.** Phase 1 lake; richer with Phase 7 realtime internals.

**Exit gate.** ✅ MET — `intradayx scan AAPL --scanner scalping` (30 signals,
VWAP/Momentum attribution) and `backtest --scanner scalping` (142 signals → 133
trades, P(Sharpe>0)) run through the shared engine; deterministic scalping anchor
test (`test_scalping.py`) asserts the VWAP-reclaim long + tight stop/target; the
36-test suite (incl. the reversal parity test) stays green after the refactor.

---

## Phase 11 — ThinkScript export ✅ DONE

**Goal.** Translate the finalized reversal rules into a thinkorSwim `study`,
kept in sync with the Python rules.

**Deliverables.**
- ✅ `export/thinkscript.py` — `reversal_thinkscript(params)` generates a ToS
  study from `ReversalParams` (VWAP + relative volume + climax + causal swing
  pivots + VWAP-stretch as a Value-Area proxy → buy/sell arrows). Params injected
  so it can't drift from the engine.
- ✅ `intradayx thinkscript [--out FILE]`.
- ⬜ **Deferred:** dashboard copy-to-clipboard panel; `VolumeProfile` VAH/VAL +
  `close("$TICK")` internals (the latter needs a ToS/Schwab feed).

**Data dependency.** None new — derived from the Phase 2 rules.

**Exit gate.** ✅ MET — `intradayx thinkscript` emits a valid study; a test asserts
the script contains the arrow-plot constructs + causal pivot logic and that the
`ReversalParams` (threshold, pivotK, version) are injected (fails if rules drift).

---

## Phase 12 — Hardening / scale ⬜ TODO

**Goal.** Productionize: storage for high-rate live ticks, model monitoring,
multi-symbol dashboards, optional deep-learning models, and deployment.

**Deliverables.**
- Optional TimescaleDB for high-rate live ticks.
- Model monitoring + retraining cadence.
- Multi-symbol live dashboard.
- PyTorch LSTM/Transformer sequence models *if* data depth supports it (deferred
  from Phase 6 to avoid overfitting thin early data).
- Deploy: SvelteKit → Vercel; FastAPI + scheduler → Railway (**`--workers 1`**);
  WS direct to Railway.

**Data dependency.** All prior phases; deep-learning needs the banked
self-recorded internals depth to be meaningful.

**Exit gate.** Deployed stack serves a live multi-symbol dashboard; model
monitoring reports drift; a retrain run completes and the parity test still
passes against the production engine.

---

## First implementation milestone

**Phases 0 → 2 as the first vertical slice:** scaffold (done) → vendor-agnostic
data layer writing into the Parquet/DuckDB lake → reversal feature set +
`SignalEngine` → a runnable `intradayx scan <TICKER> --scanner reversal` that
prints timestamped signals with a ranked "why" + `data_completeness`. Phase 3
(Nautilus backtest + live poller + parity test) follows immediately, since they
are explicitly built in parallel on the shared engine.
