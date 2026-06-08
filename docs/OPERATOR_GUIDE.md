# intraday-x — Operator Guide (everything *you* need to do)

This is your step-by-step runbook. The code (Phases 0–6, 10, 11 + earnings +
squeeze-signature) is built and tested on free data; what remains genuinely
needs **you** — your data subscription, your accounts, your judgment. Work top
to bottom; each step says exactly what to do and how.

---

## 0. One-time setup

**Prerequisites** (install once):

| Tool | What | Install |
|---|---|---|
| `uv` | Python toolchain (installs Python 3.12 for you) | `brew install uv` (macOS) or https://docs.astral.sh/uv/ |
| Node 24 + `pnpm` | frontend | `brew install node pnpm` (or your version manager) |
| `libomp` | OpenMP for LightGBM/XGBoost (the `ml` extra) | **macOS only:** `brew install libomp` |

**Get the code** (it's on a branch + PR right now):

```bash
git clone https://github.com/billyribeiro-ux/intraday-x.git
cd intraday-x
git checkout feat/phase-0-2-foundation      # until PR #1 is merged to main
```

**Install backend** (pick the extras you need; `ml` is the heaviest):

```bash
cd backend
uv sync --extra export --extra api --extra ml      # Twelve Data/Polygon need no extra (httpx)
uv run pytest                                # sanity: should be all green
```

**Install frontend:**

```bash
cd ../frontend
pnpm install
```

---

## 1. Run it locally (works today on free yfinance data)

**CLI** (no servers needed):

```bash
cd backend
uv run intradayx scan AAPL --scanner reversal       # tops/bottoms + ranked "why"
uv run intradayx scan AAPL --scanner scalping        # momentum/VWAP entries
uv run intradayx backtest AAPL --scanner reversal --export /tmp/out   # metrics + CSV/PDF in /tmp/out
uv run intradayx squeeze AAPL                         # short-squeeze price/volume signature
uv run intradayx learn AAPL                           # LightGBM + SHAP "culprit" attribution
uv run intradayx earnings AAPL                        # scheduled-earnings catalyst dates
uv run intradayx thinkscript --out reversal.ts        # thinkorSwim study → paste into ToS
```

**Live dashboard** (two terminals):

```bash
# terminal 1 — backend API + websocket
cd backend && uv run intradayx serve            # http://localhost:8000  (docs at /docs)

# terminal 2 — frontend
cd frontend && pnpm dev                          # http://localhost:5173
```

Open http://localhost:5173 — candles + volume + VWAP + POC/VAH/VAL + signal
arrows, the live signal table, and the data-completeness caveat.

> ⚠️ **Read the honesty banner.** On free data the scanners *lose money* and the
> ML is ~coin-flip. That is the truth, not a bug. Do not trade off this yet —
> see step 4 (validate) first.

---

## 2. Get the free Twelve Data key → multi-year backtests (do this first)

yfinance only gives ~7 days of 1-minute / ~60 days of 5-minute data. **Twelve
Data** is a FREE, **non-broker** vendor whose free tier (API key, **no credit
card**) has **1-minute bars back to 2020** + multi-year 5-minute — the biggest
quality jump available at $0. (Researched & verified Jun 2026; it had the least-
bad free limits of the non-broker sources.)

1. Sign up free (no card): https://twelvedata.com/  → copy the API key from the dashboard.
2. Create `.env` from the template and paste it:
   ```bash
   cp .env.example .env        # at the repo root
   # edit .env: TWELVEDATA_API_KEY=...
   ```
3. Export it (or use `direnv`):
   ```bash
   export $(grep -v '^#' .env | xargs)     # quick-and-dirty load
   ```
4. Run a real multi-year backtest — the composite router auto-prefers Twelve Data
   over yfinance once the key is set:
   ```bash
   cd backend
   uv run intradayx backtest AAPL --timeframe 5m --days 1095 --scanner reversal   # ~3 years
   ```

Free-tier limits: ~800 requests/day, 8/min, 5000 bars/request (the layer
paginates by date). Turn on the read-through cache to stay under quota:
`export INTRADAYX_CACHE_ENABLED=true`. **No brokers involved.** (yfinance remains
the zero-setup fallback; Polygon — a pure data vendor, not a broker — is also
wired if you ever want it: set `POLYGON_API_KEY`.)

Notes: the free feed is **IEX** (a slice of volume, fine for building/validating;
thinner than full SIP). Keys are secret — `.env` is gitignored; never commit them.

---

## 3. Validate before you trust ANYTHING (do not skip)

The v1 scanners are unoptimized and lose on free data. Before believing any edge:

1. **Get years of data first** (step 2) — 60 days of yfinance proves nothing.
2. **Walk-forward, not a single backtest.** A good in-sample number is usually
   overfit. (Walk-forward retraining is a Phase-6 refinement — wire it before
   trusting results.)
3. **Watch `P(Sharpe > 0)`** in the backtest output — it discounts multiple-
   testing overfit. Low = don't trust it.
4. **Model realistic costs** — they're in the fill model; keep them honest for
   your broker.
5. **Paper-trade for weeks** before any real capital. This is not investment
   advice; the v1 logic is a starting point, not a strategy.

---

## 4. Add a paid data vendor for market internals (Phase 7 — your big unlock)

> **Already wired for you: Polygon.io.** Full-market intraday bars need ZERO code
> — sign up at https://polygon.io/ (free tier exists), put `POLYGON_API_KEY` in
> `.env`, and the composite router auto-prefers it over yfinance. That
> alone replaces the thin IEX feed. (Polygon's internals/options *endpoints*
> aren't wired yet — that's the "add a vendor" work below.)

The reversal scanner leans on internals ($TICK / $TRIN / $ADD / $VOLD) that no
one sells cheaply as deep history. The code is **built to receive them** — the
`Capability` system keeps internals features/detectors dormant until a capable
provider exists, then they activate with **no rewrite**.

### How to wire a new vendor (concrete steps)

1. Create `backend/src/intradayx/data/providers/<vendor>_provider.py`, subclass
   `DataProvider` (see `yfinance_provider.py` / `twelvedata_provider.py` as templates):
   - In `capabilities()`, add the `Capability.INTERNALS_*` flags it supports.
   - Implement `internals(symbol, start, end, timeframe)` returning an
     `InternalsSeries`; implement `bars(...)` if it also serves equities.
2. Register it in `backend/src/intradayx/data/factory.py` inside the
   `CompositeProvider` list with a priority (lower = preferred).
3. Put its API key in `.env` (and read it in the provider via `os.environ`).
4. That's it — `features/pipeline.py` and the attribution detectors gate on
   `capabilities()`, so internals-divergence features + internals-gated reversal
   confirmations turn on automatically.

### Which vendor? (your call — pick by budget/need)

| Vendor | Unlocks | Rough cost | Sign-up |
|---|---|---|---|
| **Polygon.io ("Massive")** | full-SIP intraday + VIX/indices (history ~2023+) + options | ~$30–200/mo | https://polygon.io/ |
| **Databento** | institutional intraday + OPRA options; **no index/internals** | pay-as-you-go/GB | https://databento.com/ |
| **Schwab / thinkorSwim API** | matches what you see in ToS ($TICK/$TRIN live); shallow history | free w/ account | https://developer.schwab.com/ |
| **IBKR (TWS API)** | $TICK/$TRIN chartable + borrow rates | free w/ funded acct | https://www.interactivebrokers.com/ |

> **Honest flag:** even paid, deep *historical intraday* NYSE breadth internals
> barely exist. The real strategy is **record your own going forward** — see step 5.

---

## 5. Start the internals self-recorder (the earlier, the more history)

`backend/src/intradayx/live/internals_recorder.py` is built to bank
$TICK/$TRIN/$ADD/$VOLD history from a realtime feed. Today it honestly *skips*
(no feed). Once you have a realtime internals source (Schwab/IBKR streamer or
Polygon indices):

1. Make sure your provider (step 4) declares the `INTERNALS_*` capabilities.
2. Run the recorder on a schedule (it writes into the Parquet lake):
   - Wire `InternalsRecorder(provider, lake).record(DEFAULT_BREADTH, start, end)`
     into a daily cron / the APScheduler poller.
3. Every day it records is backtest history you'll never get retroactively — so
   start as soon as you have a feed, even before the strategy is finished.

---

## 6. Options / gamma-squeeze (Phase 9 — later)

For GEX you need an options chain + greeks. Best path: **ORATS** (1-minute
greeks since 2020, https://orats.com/) or Polygon/Databento OPRA (compute greeks
yourself). Then:

1. Implement `options_chain(...)` in a provider + declare
   `Capability.OPTIONS_CHAIN_HISTORY` / `OPTIONS_GREEKS`.
2. The `gamma_squeeze` detector (`attribution/detectors/squeezes.py`) activates
   via those caps — until then it correctly returns "insufficient data" (never a
   fake GEX number).

---

## 7. Short-interest-confirmed squeeze (Phase 8 — finish)

The price/volume squeeze **signature** already works (`intradayx squeeze`). For a
*confirmed* squeeze (SI% + days-to-cover + cost-to-borrow):

- Free-ish: **FINRA** Equity Short Interest (biweekly, ~2-week lag — stale) and
  daily short-volume files. Fresh data: **Ortex / S3** (paid).
- Implement a provider's `short_interest` / `short_volume` / `borrow_rate` +
  `Capability.SHORT_*`; the `short_squeeze` detector then activates.

---

## 8. Deploy (optional, Phase 12 — needs your hosting accounts)

The stack is two services. Recommended split:

- **Frontend → Vercel.** `cd frontend`; the SvelteKit adapter builds to Vercel.
  Set env `PUBLIC_API_BASE` / `PUBLIC_WS_URL` to your backend's public URL
  (see `.env.example`). Connect the repo at https://vercel.com/.
- **Backend → Railway** (or any host that runs a long-lived process):
  - **Must run `--workers 1`** — the APScheduler poller + websocket connection
    manager are single-instance (multiple workers double-poll the vendor and split
    the socket). Start command: `uv run intradayx serve --host 0.0.0.0 --port $PORT`.
  - Set `TWELVEDATA_API_KEY` / `POLYGON_API_KEY` (+ any vendor keys) in the host's
    env, **not** in the repo.
  - Vercel is serverless and can't hold the websocket/poller — that's why the
    backend lives on Railway and the browser connects straight to it.

---

## 9. Review & merge the PR

- PR #1: https://github.com/billyribeiro-ux/intraday-x/pull/1
- Review the diff, run the test suite, then merge into `main` when you're happy.
- After merge: `git checkout main && git pull`.

---

## 10. Where things live

```
backend/src/intradayx/
  domain/        # pure types + the Capability system
  data/          # providers (yfinance, twelvedata, polygon, + your new ones) + composite + factory
  storage/       # Parquet/DuckDB lake
  features/      # VWAP, RVOL, ATR, volume profile, pivots, climax, squeeze
  signals/       # SignalEngine + reversal + scalping strategies
  attribution/   # rule detectors, earnings catalyst, labeling, ML (LightGBM+SHAP), validation
  backtest/      # event-driven backtester + metrics
  live/          # live monitor + internals recorder
  export/        # CSV + PDF + ThinkScript
  api/           # FastAPI REST + websocket
frontend/src/    # SvelteKit 5 dashboard (Lightweight Charts)
docs/            # ROADMAP, ARCHITECTURE, DATA_PROVIDERS, AI_LANDMINES, this guide
```

## 11. Safety & legal

- **yfinance is "personal use only"** (unofficial scrape) — fine for dev, not for
  a sold product. Use a licensed vendor (Twelve Data / Polygon / Databento) before
  productizing.
- **Secrets:** keys live in `.env` (gitignored) or the host's env — never in code.
- **Not investment advice.** Every signal carries a confidence + caveat for a
  reason. Validate, paper-trade, and treat early backtests as overfit until proven.
