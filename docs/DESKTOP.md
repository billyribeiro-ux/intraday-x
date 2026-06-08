# Desktop app — packaging the Python engine as a Tauri sidecar

The intraday-x desktop app is a Tauri shell (`src-tauri/`) that runs the Python
engine as a bundled **sidecar binary**. The engine is a FastAPI server; the Tauri
Rust core spawns it, reads `INTRADAYX_READY <port>` from its stdout, and points
the webview at `http://127.0.0.1:<port>`.

Sidecar path (Tauri `externalBin` `"binaries/intraday-engine"` + host triple):

```
src-tauri/binaries/intraday-engine-aarch64-apple-darwin
```

It is ONE self-contained executable produced by PyInstaller. `src-tauri/binaries/`
is gitignored, so a fresh checkout has no sidecar until you build one (real or
placeholder).

---

## Dev flow

In dev the Rust core does **not** spawn the engine — the frontend talks to a
separately-run server. You still need a placeholder file at the sidecar path or
`cargo check` / `tauri dev` fail on the missing `externalBin`.

```bash
# 1. once per fresh checkout — drop the no-op stub so Tauri builds
bash backend/scripts/dev_placeholder.sh

# 2. run the engine standalone (terminal A)
cd backend
uv run intradayx serve            # FastAPI on http://127.0.0.1:8000

# 3. run the Tauri dev shell (terminal B)
cd ..
pnpm tauri dev
```

---

## Release flow

Build the real self-contained engine, then bundle the app:

```bash
# 1. build the sidecar (slow — minutes; needs `brew install libomp` first)
bash backend/scripts/build_sidecar.sh
# -> src-tauri/binaries/intraday-engine-aarch64-apple-darwin

# 2. bundle + sign + notarize the desktop app
pnpm tauri build
```

`build_sidecar.sh` runs `uv sync --extra desktop --extra api --extra ml
--extra export` then `pyinstaller intraday-engine.spec`, and copies the result
to the triple-suffixed sidecar path.

**Other architectures:** the triple is hardcoded to `aarch64-apple-darwin`
(Apple Silicon). On Intel, change the filename + `target_arch="x86_64"` in
`intraday-engine.spec` to match `rustc -vV | grep host`
(`x86_64-apple-darwin`).

---

## Size

Expect a **~150–300 MB** sidecar. The scientific stack (scipy, scikit-learn,
lightgbm, xgboost, catboost, statsmodels, shap, tsfresh, polars, duckdb,
pyarrow, matplotlib) is large and ships compiled native libs. This is normal for
a bundled-Python data app; the spec already excludes GUI backends
(tkinter/Qt/IPython) to trim what it can.

---

## Known PyInstaller pitfalls (encoded in the spec)

1. **`libomp.dylib` for lightgbm / xgboost.** Both link an OpenMP runtime that
   is *not* part of macOS and *not* in the wheels. Without it the engine dies on
   first ML import: `Library not loaded: @rpath/libomp.dylib`. The spec locates
   it via `brew --prefix libomp` (with `/opt/homebrew` fallbacks) and bundles it
   at the binary root. **Install it first:** `brew install libomp`.

2. **Hidden imports the static analyzer can't see.** sklearn, scipy, shap,
   tsfresh, statsmodels, polars, duckdb, pyarrow, and the gradient-boosting libs
   load submodules / data / native code dynamically. The spec uses
   `collect_all` / `collect_submodules` / `collect_data_files` for each so the
   binary builds *and boots*, instead of building clean then dying with
   `ModuleNotFoundError` inside the Tauri shell where there's no Python fallback.

3. **uvicorn's string-named plumbing.** uvicorn picks its event loop, HTTP, and
   websocket implementations by name at runtime (`uvicorn.loops.auto`,
   `uvicorn.protocols.*`, `uvicorn.lifespan.*`). These are pinned as
   `hiddenimports`, and uvloop/httptools/websockets are collected whole, so the
   `[standard]` "auto" picks resolve.

4. **Onefile temp-extraction startup latency.** A onefile binary unpacks itself
   to a temp dir on every launch → ~1–3 s cold start for this stack. We accept
   it because Tauri's `externalBin` wants exactly one invocable file (a onedir
   folder is not a single sidecar). The handshake is printed *before* uvicorn
   blocks, so the Rust supervisor isn't left hanging during extraction.

5. **First-run macOS code-signing / notarization.** The sidecar is an unsigned
   Mach-O until `tauri build` signs it; Gatekeeper will quarantine a hand-copied
   binary run outside the bundle. Let `pnpm tauri build` sign + notarize it as
   part of the app — don't distribute the raw `dist/intraday-engine`. (UPX is
   disabled in the spec because it corrupts macOS dylibs and breaks signing.)

> Data vendors: the engine uses **free, non-broker** sources only (yfinance et
> al.). No broker data dependency ships in the sidecar.

---

## Auto-update setup

The desktop app ships an in-app updater: on launch (or from
**Settings → Software update**) it checks GitHub Releases for a newer signed
build, shows a non-blocking banner, and — on click — downloads, installs, and
relaunches. The release CI (`.github/workflows/release.yml`) builds, **signs**,
and publishes the `.app`/`.dmg` plus the updater manifest (`latest.json`) every
time you push a `v*` tag.

Tauri's updater verifies every download against **your** signing keypair, so it
will not run until you generate that keypair and wire it in. This is the **only
manual step** — and it is manual on purpose: the signing key is yours to own and
must never live in the repo. If it leaked, anyone could publish an "update" your
installed apps would trust and install. So you generate it locally, keep the
private half off-disk-of-record, and hand only the public half to the app.

Until you complete the steps below, the app still **builds and runs** — the
updater simply degrades to `unconfigured` (Settings shows "Updates aren't
configured for this build") and the banner stays hidden. Dev/unsigned builds
never error on a missing config.

### 1. Generate the signing keypair (once, locally)

```bash
pnpm tauri signer generate -w ~/.intradayx/updater.key
```

This writes the **private** key to `~/.intradayx/updater.key` and prints the
**public** key + a password prompt. Two rules:

- **NEVER commit `~/.intradayx/updater.key`** (or its contents) to the repo. It
  is the private key. Treat it like a production secret.
- Remember the password you set — the CI needs it (next step). An empty password
  is allowed; if you use one, set the corresponding secret to an empty string.

### 2. Add the two GitHub repo secrets

In **GitHub → repo → Settings → Secrets and variables → Actions → New
repository secret**, add:

| Secret name | Value |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | the full contents of `~/.intradayx/updater.key` |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | the password from step 1 (empty string if none) |

`GITHUB_TOKEN` is provided automatically — no need to add it.

### 3. Paste the PUBLIC key into `tauri.conf.json`

Add a `plugins.updater` block to `src-tauri/tauri.conf.json` (a sibling of the
existing `bundle` block). Paste the **public** key (the line `tauri signer
generate` printed in step 1) in place of `<PASTE_PUBLIC_KEY_HERE>`:

```json
  "plugins": {
    "updater": {
      "endpoints": [
        "https://github.com/billyribeiro-ux/intraday-x/releases/latest/download/latest.json"
      ],
      "pubkey": "<PASTE_PUBLIC_KEY_HERE>"
    }
  }
```

The `endpoints` URL is the `latest.json` manifest the release workflow uploads
to every GitHub Release; `releases/latest/download/` always resolves to the
newest published (non-draft) release.

> The repo intentionally ships **without** this block so the build never depends
> on a key you haven't generated yet. Adding a placeholder/fake `pubkey` would
> break the build — only paste the real public key from your own `tauri signer
> generate` run.

### 4. Ship a release

```bash
git tag v0.1.0
git push origin v0.1.0
```

The workflow builds the sidecar, then signs + publishes the app and
`latest.json` to a **draft** GitHub Release. Review it, then publish. Installed
apps pointing at `releases/latest/download/latest.json` will see the new version
on their next check.
