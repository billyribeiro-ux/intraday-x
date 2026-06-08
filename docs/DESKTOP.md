# Desktop app — packaging the Python engine as a Tauri resource

The intraday-x desktop app is a Tauri shell (`src-tauri/`) that runs the Python
engine as a bundled **PyInstaller onedir folder**, shipped as a Tauri *resource*.
The engine is a FastAPI server; the Tauri Rust core spawns it via `std::process`,
reads `INTRADAYX_READY <port>` from its stdout, and points the webview at
`http://127.0.0.1:<port>`.

Engine location (built here, bundled into the app's `Resources/engine/`):

```
src-tauri/binaries/engine/intraday-engine   (+ engine/_internal/)
   → bundled to  intraday-x.app/Contents/Resources/engine/intraday-engine
```

It's a PyInstaller **onedir** build (a folder, not one file). `src-tauri/binaries/`
is gitignored, so a fresh checkout has no engine until you build one (real or
placeholder). tauri.conf maps it via `bundle.resources: {"binaries/engine":"engine"}`.

---

## Dev flow

In dev the Rust core does **not** spawn the engine (the resource isn't bundled in
a dev run) — the frontend talks to a separately-run server. You still need a
placeholder at the engine resource path or `cargo check` / `tauri dev` fail on the
missing `bundle.resources` folder.

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
# 1. build the engine onedir (a few minutes)
bash backend/scripts/build_sidecar.sh
# -> src-tauri/binaries/engine/  (intraday-engine + _internal/)

# 2. bundle the desktop app (add --bundles app to skip the slow DMG)
pnpm tauri build
```

`build_sidecar.sh` runs `uv sync --extra desktop --extra api` (NOT ml/export — the
app's API surface never imports the ML stack) then `pyinstaller
intraday-engine.spec`, and copies the onedir folder to `src-tauri/binaries/engine/`.
Verified end-to-end: the bundled engine handshakes from inside the built `.app`
in ~3 s (`Resources/engine/intraday-engine` → `/healthz` 200).

**Other architectures:** the engine folder name (`engine/`) is arch-agnostic, but
the spec's `target_arch="arm64"` is Apple-Silicon-specific. On Intel, set
`target_arch="x86_64"` in `intraday-engine.spec` to match `rustc -vV | grep host`.

---

## Size

Measured: the **onedir engine is ~564 MB** on disk (uncompressed) and the bundled
**`.app` is ~664 MB**. The bulk is the data stack (polars, duckdb, pyarrow,
pandas, scipy) + the Python runtime — the heavy ML libs (lightgbm/xgboost/shap/
tsfresh/sklearn) are intentionally NOT bundled (the app never imports them; they
live in the CLI `learn` path). The spec also excludes GUI backends
(tkinter/Qt/IPython). Onedir trades disk size for startup speed (see pitfall #4).

---

## Known PyInstaller pitfalls (encoded in the spec)

1. **(N/A — api-only build.)** Earlier builds bundled lightgbm/xgboost, which need
   an OpenMP runtime (`libomp.dylib`) not shipped in the wheels. The trimmed
   api-only sidecar drops those libs, so no libomp is needed. If you ever add the
   ML stack back to the sidecar, restore the libomp bundling in the spec
   (`brew install libomp`) or it dies with `Library not loaded: @rpath/libomp.dylib`.

2. **Hidden imports the static analyzer can't see.** polars, duckdb, pyarrow,
   pandas, scipy, and the uvicorn/fastapi web stack load submodules / data /
   native code dynamically. The spec uses `collect_all` / `collect_submodules` /
   `collect_data_files` for each so the binary builds *and boots*, instead of
   building clean then dying with `ModuleNotFoundError` inside the Tauri shell
   where there's no Python fallback.

3. **uvicorn's string-named plumbing.** uvicorn picks its event loop, HTTP, and
   websocket implementations by name at runtime (`uvicorn.loops.auto`,
   `uvicorn.protocols.*`, `uvicorn.lifespan.*`). These are pinned as
   `hiddenimports`, and uvloop/httptools/websockets are collected whole, so the
   `[standard]` "auto" picks resolve.

4. **onedir vs onefile startup.** A *onefile* binary self-extracts to a temp dir
   on EVERY launch — measured ~17 s cold start for this data stack, every time. We
   use *onedir* instead (shipped as a Tauri resource folder + spawned via
   `std::process`, not `externalBin`): no per-launch extraction → **~0.6 s warm,
   ~14 s only on the first-ever launch** (cold disk read of the 564 MB folder).
   The frontend resolver allows 30 s for the handshake to cover that first launch.

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
