# intraday-x — Operator TODO (everything *you* need to do)

This is the human-only checklist: the steps that need your credentials, your
accounts, or your decisions. The code is done and verified — these are the things
I can't do for you (secrets, paid accounts, irreversible publishes).

Cross-references:
- `docs/DESKTOP.md` — packaging, the exact auto-update keypair steps, sizes/pitfalls.
- `docs/OPERATOR_GUIDE.md` — engine/CLI operations + adding a data vendor.
- `docs/DESKTOP_APP_PLAN.md` — the full architecture + phase plan.

Legend: 🔴 do-now / security · 🟡 to run or ship it · 🟢 optional / later.

---

## 🔴 0. Rotate the leaked Twelve Data key (do this first)

A Twelve Data API key (`76ca…`) was pasted into chat, so treat it as
**compromised**. It is in gitignored `backend/.env` and was never committed, but:

1. Go to https://twelvedata.com/ → dashboard → regenerate the API key.
2. Put the NEW key in `backend/.env`:
   ```
   TWELVEDATA_API_KEY=<your-new-key>
   ```
   (`.env` is gitignored — never commit it. `backend/src/intradayx/config.py`
   loads it automatically.)

---

## 🟡 1. Data API keys (free, non-broker only)

The app works out-of-the-box on yfinance (no key), but for real multi-year
history add a free, non-broker vendor:

| Vendor | Why | Where |
|---|---|---|
| **Twelve Data** | 1-min bars back to 2020 (the backtest backbone) | `TWELVEDATA_API_KEY` in `backend/.env` |
| Polygon (optional) | another data vendor | `POLYGON_API_KEY` in `backend/.env` |

You can also set/clear these **in the app** — Settings → API keys (no terminal,
no `.env` editing). **No brokers** — we use data vendors only.

---

## 🟡 2. Run it in dev (see the real window)

One-time prereqs (already installed on your machine; for a fresh Mac): `uv`,
Node 24 + `pnpm`, Rust + `cargo tauri` (tauri-cli). **No `libomp` needed** anymore.

```bash
# once per fresh checkout — the engine folder is gitignored, so drop a dev stub
bash backend/scripts/dev_placeholder.sh

# terminal A — the Python engine (FastAPI on :8000)
cd backend && uv run intradayx serve

# terminal B — the desktop app (opens the real window; talks to :8000 in dev)
cargo tauri dev
```

---

## 🟡 3. Build the desktop app (unsigned — works today)

```bash
# 1. build the engine (PyInstaller onedir → src-tauri/binaries/engine/)
bash backend/scripts/build_sidecar.sh

# 2. bundle the .app  (drop --bundles app to also make the .dmg)
cargo tauri build --bundles app
# → src-tauri/target/release/bundle/macos/intraday-x.app
```

Because it's **unsigned**, the first open needs **right-click → Open** (Gatekeeper
prompt). Steps 4–5 below remove that. First-ever launch takes ~14s (one-time cold
read of the 564 MB engine); every launch after is ~0.6s.

---

## 🟡 4. Enable in-app auto-update (your signing key)

Auto-update needs a signing key **you own** (a Tauri/minisign key — separate from
Apple signing). Full detail in `docs/DESKTOP.md` → "Auto-update setup".

```bash
# 1. generate the keypair (keep the private key OUT of the repo)
cargo tauri signer generate -w ~/.intradayx/updater.key
```

2. Copy the printed **public key** into `src-tauri/tauri.conf.json` — add a
   `plugins.updater` block with the pubkey + the GitHub-releases endpoint (exact
   JSON to paste is in `docs/DESKTOP.md`). This is the only file edit you make.
3. Add two **GitHub repo secrets** (Settings → Secrets → Actions):
   - `TAURI_SIGNING_PRIVATE_KEY` — contents of `~/.intradayx/updater.key`
   - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` — the password you set
4. **Never commit the private key.**

Until this is done, the app's "Check for updates" honestly reports
"updates aren't configured for this build" (it won't error).

---

## 🟡 5. Apple code-sign + notarize (Gatekeeper-clean `.dmg`)

Needs an **Apple Developer account (~$99/yr)**. This is what makes the app open
with a double-click on any Mac (no "unidentified developer" prompt).

1. Enroll at https://developer.apple.com/ → create a **"Developer ID
   Application"** certificate; note your **Team ID**.
2. Create an **app-specific password** for notarization (appleid.apple.com).
3. Add these as GitHub secrets (for CI) or env vars (for local `tauri build`):
   - `APPLE_CERTIFICATE` (base64 of the .p12), `APPLE_CERTIFICATE_PASSWORD`
   - `APPLE_SIGNING_IDENTITY` (e.g. "Developer ID Application: Name (TEAMID)")
   - `APPLE_ID`, `APPLE_PASSWORD` (the app-specific one), `APPLE_TEAM_ID`
4. `cargo tauri build` then signs + notarizes the `.app`/`.dmg` automatically.

---

## 🟡 6. Publish a release (triggers auto-update for users)

Once steps 4–5 are set, shipping a new version is just a tag:

```bash
git tag v0.0.2 && git push origin v0.0.2
```

`.github/workflows/release.yml` then builds the engine, builds + signs the app,
and publishes the `.app`/`.dmg` + `latest.json` to a GitHub Release. Running older
copies show "Update available — v0.0.2" → click → it updates + relaunches.

> Confirm the repo owner in the updater endpoint URL (`docs/DESKTOP.md`) matches
> your GitHub repo before the first tag.

---

## 🟢 7. Prove the edge on real data

With a Twelve Data key set, run a real multi-year backtest (the honest
Deflated-Sharpe number is the one that matters):

```bash
cd backend && uv run intradayx backtest AAPL --timeframe 5m --days 1095
```

Mind the free tier's ~800 requests/day. The same scan/backtest run **in the app**
(Backtest tab + scanner picker) once the engine is running.

---

## 🟢 8. Decisions / known follow-ups (your call)

- **Branch/PR split** (you said yes): the engine and the desktop app are both on
  `feat/phase-0-2-foundation`. Splitting the desktop app into its own PR stacked
  on the engine requires a **force-push** to rewind that branch to the last engine
  commit (`8e1d829`) and move the 7 desktop commits to `feat/desktop-app`. I held
  off because it rewrites a pushed branch — **tell me to proceed and I'll do it**
  (it's reversible; nothing is lost).
- **App size** — 664 MB (onedir engine). Acceptable for a bundled-Python ML app;
  revisit only if distribution size matters.
- **ML attribution** (`intradayx learn`, LightGBM/SHAP) is **CLI-only by design** —
  not bundled in the desktop engine (the app never calls it), which is why the
  sidecar is api-only and far smaller.
- **Data depth** — deep historical market internals ($TICK/$TRIN/…) aren't sold
  cheaply; the self-recorder banks them once you connect a realtime feed.

---

## Quick reference — where things live

| Thing | Path |
|---|---|
| Your secrets / keys | `backend/.env` (gitignored) |
| Engine entrypoint (sidecar) | `backend/src/intradayx/desktop_sidecar.py` |
| Build the engine | `backend/scripts/build_sidecar.sh` |
| Tauri config (updater pubkey goes here) | `src-tauri/tauri.conf.json` |
| Release CI | `.github/workflows/release.yml` |
| Packaging + auto-update detail | `docs/DESKTOP.md` |
