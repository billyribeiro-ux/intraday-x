# intraday-x — DATA PROVIDERS

A capability matrix and a phased vendor-adoption guide. The data layer is
**vendor-agnostic**: each provider declares a `frozenset[Capability]`
(`domain/capabilities.py`), features/detectors gate on those, and a missing
capability lowers a signal's `data_completeness` rather than fabricating data.
Adding a vendor later auto-activates the dormant features with no rewrite.

> **Pricing caveat (as of mid-2026).** Several 2026 vendor prices below are
> sales-gated or unverified — confirm before budgeting. Where a number is
> approximate or unconfirmed it is marked as such.

---

## THE KEY HONEST CONCLUSION — read this first

**Deep historical *intraday* NYSE breadth internals ($TICK / $TRIN / $ADD /
$VOLD) are NOT cheaply purchasable anywhere.** No mainstream vendor sells a deep
intraday history of these series at a retail price:

- Cboe DataShop sells VIX-family / SKEW / put-call but **does not** sell NYSE
  breadth ($TICK/$TRIN/$ADD).
- Schwab/thinkorSwim and IBKR show $TICK/$TRIN/$VOLD in *realtime* but **will not
  export** deep historical intraday internals.
- Polygon/Massive covers indices (incl. VIX) but intraday index history floors
  around **March 2023**, and breadth-symbol coverage is unconfirmed.

**Therefore the strategy is to RECORD OUR OWN going forward.** The
`live/internals_recorder.py` module (scaffolded in Phase 1) banks
$TICK/$TRIN/$ADD/$VOLD from a realtime feed into the lake, starting as early as
possible — the earlier it records, the more backtest history we accumulate.
There is no breadth backtest set at the start; that is an accepted, surfaced
limitation, not a bug.

---

## Capability matrix

Legend: ✅ supported · ⚠️ partial / shallow / caveated · ❌ not available ·
💲 paid.

| Vendor | Daily | Intraday 1m | Deep intraday hist. | Pre/post | Internals (breadth) | VIX family | Options chain | Options greeks/IV hist. | Short interest | Borrow rate | Live stream | Cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **yfinance** | ✅ → IPO | ⚠️ ~7d | ❌ | ✅ | ❌ | ❌ | ✅ live only | ❌ | ❌ | ❌ | ⚠️ poll | Free (unofficial) |
| **Alpaca (free IEX)** | ✅ | ✅ | ✅ ~7–10yr | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | Free (creds) |
| **Polygon / "Massive"** | ✅ | ✅ ~10yr | ⚠️ index floors ~Mar 2023 | ✅ | ⚠️ unconfirmed | ✅ incl. VIX | ✅ | ⚠️ | ❌ | ❌ | ✅ | 💲 ~$79+/mo (unverified) |
| **Databento** | ✅ | ✅ | ✅ 15+yr | ✅ | ❌ no index/internals | ❌ | ✅ OPRA | ⚠️ own greeks | ❌ | ❌ | ✅ | 💲 pay-as-you-go / GB |
| **Schwab / thinkorSwim** | ✅ | ⚠️ ~30–48d | ❌ | ✅ | ✅ realtime only ($TICK/$TRIN/$VOLD) | ✅ realtime | ✅ | ❌ | ❌ | ❌ | ✅ realtime | Free (w/ account) |
| **IBKR TWS API** | ✅ | ⚠️ shallow | ❌ | ✅ | ✅ realtime, shallow hist. | ✅ realtime | ✅ | ❌ | ❌ | ✅ realtime borrow | ✅ | Free (funded acct) |
| **Cboe DataShop / FRED** | ✅ EOD VIX/SKEW/PC (free) | ❌ | ⚠️ intraday VIX paid/custom | ❌ | ❌ no NYSE breadth | ✅ EOD free / intraday 💲 | ❌ | ❌ | ❌ | ❌ | ❌ | Free EOD / 💲 intraday |
| **FINRA** | — | — | — | — | ❌ | ❌ | ❌ | ❌ | ✅ biweekly, ~2wk lag | ❌ | ❌ | Free |
| **Ortex / S3 Partners** | — | — | — | — | ❌ | ❌ | ❌ | ❌ | ✅ fresh SI estimates | ✅ cost-to-borrow + utilization | ⚠️ | 💲 paid |
| **ORATS** | — | — | — | — | ❌ | ❌ | ✅ | ✅ 1-min greeks/IV since Aug 2020 | ❌ | ❌ | ⚠️ | 💲 paid |

---

## Per-vendor detail (verified research, mid-2026)

### yfinance — the zero-setup demo

- **History:** 1m ≈ last 7 days; 5m/15m/30m ≈ 60 days; 1h ≈ 730 days; daily → IPO.
- **Has:** OHLCV bars, pre/post market, live options *snapshot*.
- **Does NOT have:** market internals, options *history*.
- **Costs/risks:** free but an **unofficial scrape** of a Yahoo endpoint with a
  "personal use" ToS; fragile; **survivorship bias** (free data = today's
  tickers). Fine for prototyping, not production.
- **Capabilities declared** (`providers/yfinance_provider.py`): `DAILY_BARS`,
  `INTRADAY_BARS_1M`, `INTRADAY_BARS_5M`, `PREPOST_MARKET`, `OPTIONS_CHAIN_LIVE`,
  `LIVE_STREAM` (poll-only). Raises `LookbackExceededError` past the windows
  above.

### Alpaca (free IEX feed) — the backtest backbone

- **History:** ~7–10 years of 1-minute equity/ETF bars — what turns this from a
  7-day demo into a real backtest. Provides **`vwap`** and **`trade_count`** per
  bar (mapped to `trades`).
- **Credentials:** `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` (free at
  alpaca.markets). `capabilities()` works without keys; `bars()` raises
  `MissingCredentialsError` so a missing key fails loud.
- **Capabilities declared** (`providers/alpaca_provider.py`): `DAILY_BARS`,
  `INTRADAY_BARS_1M`, `INTRADAY_BARS_5M`, `EXTENDED_HISTORY_INTRADAY`,
  `PREPOST_MARKET`, `LIVE_STREAM`. Lookback ≈ 9 years (`_DEEP`) per intraday
  timeframe.

### Polygon.io / "Massive"

- Polygon rebranded — `polygon.io/pricing` 301-redirects to
  `massive.com/pricing`. Plans ~**$79+/mo** (unverified, sales-gated).
- Indices incl. **VIX**, but **intraday index history floors ~March 2023**.
- Breadth-symbol ($TICK/$TRIN/$ADD/$VOLD) coverage **unconfirmed**.
- Options chains; up to ~10yr equity intraday.

### Databento

- Pay-as-you-go **by GB**; 15+ years; nanosecond resolution; **OPRA** options.
- **No index / no internals data** — not a breadth source.

### Schwab / thinkorSwim API

- Free with an account, OAuth2. `pricehistory` 1m ≈ **30–48 days**;
  equities/ETFs only.
- Shows **$TICK / $TRIN / $VOLD realtime** — a candidate realtime feed for the
  internals recorder — but **will NOT export deep historical intraday
  internals**.

### IBKR TWS API

- Free with a funded account. **$TICK / $TRIN chartable in realtime with shallow
  history**. Realtime borrow rates / availability (useful for Phase 8).

### Cboe DataShop / FRED

- VIX-family + SKEW + put/call **DAILY EOD free** (also via FRED).
- Intraday VIX-family history is **paid / custom**.
- **Does NOT sell NYSE breadth** ($TICK/$TRIN/$ADD).

### FINRA

- Equity **Short Interest** free but **biweekly with a ~2-week lag** — the data
  layer flags it stale (`ShortInterest.published_date` vs `settlement_date`).
- Daily short-sale volume free.

### Ortex / S3 Partners

- Paid. Fresh SI **estimates** + cost-to-borrow + utilization (Phase 8).

### ORATS

- Paid. Options **1-minute greeks / IV since Aug 2020** — the best path for
  GEX / gamma analysis (Phase 9).

---

## Phased adoption order

| Phase | Vendor(s) added | What it unlocks |
|---|---|---|
| **0** | yfinance | Zero-setup demo; prove the pipeline end-to-end. |
| **1** | **Alpaca (free)** + start **self-recording internals** | The ~7–10yr 1m backtest backbone; begin banking $TICK/$TRIN/$ADD/$VOLD from a realtime feed as soon as one exists. |
| **7** | Polygon/Massive, Schwab-TOS, Databento | Intraday VIX + options; Schwab-TOS as the realtime feed for the recorder; internals/options-gated features auto-activate. |
| **9** | ORATS | 1-minute options greeks/IV → GEX / gamma-squeeze detector. |
| **8** | Ortex + FINRA (+ IBKR borrow) | Fresh + free short data → short-squeeze detector (FINRA flagged stale). |

> Phases 8 and 9 are listed in roadmap order (short-squeeze is Phase 8,
> gamma is Phase 9); the *vendor* adoption is staged so ORATS lands with the
> gamma work and Ortex/FINRA with the short work.

**Why record our own internals from Phase 1:** because deep historical intraday
breadth is not purchasable cheaply (see the conclusion above), every day the
recorder runs is a day of backtest history we could not otherwise buy. Start the
recorder against any available realtime $TICK/$TRIN/$VOLD feed (Schwab-TOS or
IBKR) the moment one is wired up.
