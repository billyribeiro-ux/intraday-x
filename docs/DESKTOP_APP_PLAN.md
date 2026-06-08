# intraday-x — Desktop App Implementation Plan (macOS, Tauri)

Goal: a **professional native macOS app** — double-click an icon, it opens, it
works. No terminal. Everything in-app: live monitor, backtesting, scanner
selection, full settings (theme + multi-vendor API keys), and **auto-update**
(an "Update available" banner → one click → it updates and relaunches).

## Architecture (decided)

```
┌─ intraday-x.app  (one signed icon) ─────────────────────────────┐
│  Tauri core  (Rust)                                             │
│   ├─ window · native menu · notifications                       │
│   ├─ AUTO-UPDATE: tauri-plugin-updater + tauri-plugin-process    │
│   └─ spawns + supervises ▼ (reads stdout for the port, kills it) │
│  Python engine sidecar  (PyInstaller binary)                    │
│   └─ FastAPI + Polars + LightGBM + SHAP  (127.0.0.1:<free port>) │
│  Svelte 5 SPA  ◀── HTTP / WebSocket ──┘                         │
│   └─ Monitor · Backtest · Settings                              │
└──────────────────────────────────────────────────────────────────┘
```

- **Rust = the shell & supervisor** (`src-tauri/`). It launches the engine,
  learns its port via the `INTRADAYX_READY <port>` stdout handshake, emits
  `backend-ready` to the UI, kills the engine on quit, and drives auto-update.
- **Python = the engine** (unchanged): packaged once by PyInstaller into a single
  sidecar binary. Keeps 100% of the ML/data stack you asked for.
- **Svelte 5 = the UI** (`frontend/`), built as a static SPA Tauri serves.
- **Dev vs prod:** in `tauri dev` there's no bundled binary, so the Rust spawn
  fails gracefully and the UI falls back to a separately-run `intradayx serve`
  on :8000. In the shipped `.app`, Rust spawns the bundled engine. Same UI.

## Status (what exists now)

- ✅ Backend engine: data layer (yfinance / Twelve Data / Polygon — free,
  non-broker), features, signals, backtest, ML, FastAPI API
  (`/api/scan`, `/api/backtest`, `/api/bars`, `/api/providers/capabilities`,
  `WS /ws/signals`), `.env`→provider wiring fixed, Alpaca fully removed.
- ✅ Sidecar entrypoint `backend/src/intradayx/desktop_sidecar.py` (port handshake).
- ✅ Tauri Rust core scaffolded: `Cargo.toml`, `build.rs`, `main.rs`,
  `lib.rs` (engine supervisor), `tauri.conf.json`, `capabilities/default.json`,
  with shell + notification + **updater + process** plugins wired.
- ⬜ Everything below.

## Phases

### P1 — Foundation compiles & launches (in progress)
- [x] Sidecar entry + `desktop` PyInstaller extra in `pyproject.toml`.
- [x] Tauri core files + capabilities.
- [ ] Generate app icons (`pnpm tauri icon` from a generated source PNG).
- [ ] `cargo check` clean (verify the Rust; rust-analyzer MCP is pinned to
      another crate, so `cargo check`/`clippy` is the sanctioned fallback here).
- [ ] Frontend → static SPA: `@sveltejs/adapter-static`, `+layout.ts`
      (`ssr=false`, `prerender=true`), Tauri-friendly `vite.config.ts`.
- [ ] `frontend/src/lib/api/backend.ts` — resolve API base (Tauri port event /
      `get_backend_port`, dev fallback :8000) + typed `fetchJson` (no silent catch).
- [ ] `frontend/src/lib/realtime/signals.svelte.ts` — runes WS store
      (reconnect/backoff + heartbeat), parsing the real `ws.py` message shapes.
- **Gate:** `pnpm tauri dev` opens a window that reaches the engine (with
  `intradayx serve` running) and renders live data.

### P2 — Monitor screen (the flagship)
- [ ] Watchlist (live connection dots) · IntradayChart (lightweight-charts v5
      candles + volume pane + `createSeriesMarkers` buy/sell arrows) · live
      SignalFeed of cards (kind/side, confidence, ranked "why", `data_completeness`
      chip, entry/stop/targets, time-of-day, ts).
- [ ] Native desktop notification on a new high-confidence signal.
- **Gate:** Playwright/manual — a live signal appears end-to-end, ~0 CLS on append.
- All `.svelte` via the Svelte MCP (`list-sections` → `get-documentation` →
  `svelte-autofixer`), Svelte 5 runes only, phosphor `*Icon` suffix.

### P3 — Backtest studio
- [ ] Form (ticker / timeframe / date-range / max-hold / **scanner: reversal |
      scalping**) → `POST /api/backtest` → equity curve + underwater drawdown,
      per-time-of-day table, Deflated Sharpe, ranked attribution, CSV/PDF export.
- **Gate:** a real Twelve Data backtest renders with the honest metrics.

### P4 — Settings (theme + multi-vendor keys) — needs new backend
Backend (new):
- [ ] `intradayx/api/settings_store.py` — a JSON settings file in the OS app-data
      dir (`~/Library/Application Support/com.intradayx.desktop/settings.json`):
      `{ theme, providers[], watched_symbols[], default_scanner, vendor_keys{} }`.
- [ ] `intradayx/api/routes/settings.py` — `GET /api/settings`,
      `PUT /api/settings`, `POST /api/settings/vendor-key` (write a vendor key),
      `GET /api/providers/capabilities` (already exists) to show which vendors are
      live. On change: persist, push keys into `os.environ`, and **rebuild the
      provider** (`build_provider`) so new keys take effect without a restart.
- [ ] Keys are written to the settings file (chmod 600), never logged, never
      committed; the file lives in app-data, not the repo.

Frontend (new):
- [ ] Settings screen: **theme** toggle (dark/light/system, CSS variables, no
      flash), **API keys** per vendor (Twelve Data, Polygon, … add/edit/clear,
      with a "configured ✓ / not set" status from `/providers/capabilities`),
      **default scanner**, watched symbols.
- **Gate:** enter a Twelve Data key in-app → the capabilities panel flips to
      "configured ✓" and a scan/backtest uses it — no terminal, no `.env` edit.

### P5 — Auto-update (signed, in-app)
- [ ] Generate the updater signing keypair: `pnpm tauri signer generate`
      (Tauri's own minisign key — **separate** from Apple signing). Public key →
      `tauri.conf.json` `plugins.updater.pubkey`. Private key → a GitHub Actions
      secret `TAURI_SIGNING_PRIVATE_KEY` (NEVER committed).
- [ ] `tauri.conf.json` `plugins.updater.endpoints` →
      `https://github.com/billyribeiro-ux/intraday-x/releases/latest/download/latest.json`.
- [ ] Release CI (`.github/workflows/release.yml`): on a `v*` tag → build the
      signed `.app`/`.dmg` + the update artifact + `latest.json` manifest, attach
      to a GitHub Release. (Each new version = tag + push; CI does the rest.)
- [ ] Frontend updater service: on launch + a Settings "Check for updates"
      button, `check()`; if an update exists show a non-blocking **"Update
      available — vX.Y.Z"** banner; on click `downloadAndInstall()` with a
      progress bar, then `relaunch()`. This is the "click → updates to newest" UX.
- **Gate:** tag `v0.0.2`, let CI publish; a running `v0.0.1` app shows the banner
      and updates itself on click.

### P6 — Signing, notarization, distribution
- [ ] macOS code-signing + **notarization** (needs an Apple Developer account,
      ~$99/yr) so Gatekeeper opens it without warnings — the bar for "professional".
      Without it the app still runs (right-click → Open) and auto-update still
      works, but users see an "unidentified developer" prompt. Flag for decision.
- [ ] `.dmg` with a styled background + Applications drop target.
- **Gate:** a notarized `.dmg` opens clean on a second Mac.

## Hard rules carried in (from CLAUDE.md)
- Money/P&L in integer cents (i64) end-to-end.
- Every `.svelte` through the Svelte MCP; Svelte 5 runes only; phosphor `*Icon`.
- Every `.rs` through rust-analyzer when its workspace matches; else `cargo check`
  + `cargo clippy -D warnings` as the gate, stated explicitly.
- No `fetch().catch(() => {})`; surface errors to a toast/banner.
- Free, non-broker data vendors only (Twelve Data / Polygon / yfinance).

## Risks
- **PyInstaller packaging the scientific stack** (lightgbm + libomp.dylib, shap,
  polars, duckdb) is the riskiest step — needs explicit hidden-imports/hooks. The
  `.spec` is the deliverable that de-risks it.
- **App size** ~150–300MB (bundled Python + native ML libs) — acceptable for a
  desktop ML app; documented.
- **Two signing systems**: Apple (Gatekeeper/notarization) and Tauri updater
  (minisign). Both needed for a clean professional release; don't conflate them.
