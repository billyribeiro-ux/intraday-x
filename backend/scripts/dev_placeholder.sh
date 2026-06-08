#!/usr/bin/env bash
#
# dev_placeholder.sh — recreate the dev placeholder engine resource.
# ============================================================================
#
# `src-tauri/binaries/` is gitignored, so a fresh checkout has no engine and
# `cargo check` / `pnpm tauri dev` fail because Tauri's bundle.resources entry
# ("binaries/engine") points at a missing folder. This drops a no-op stub there
# so the Rust core builds and dev runs.
#
# In `tauri dev` the Rust core does NOT spawn the engine (the resource isn't
# bundled in a dev run) — the frontend talks to a separately-run `intradayx
# serve` on :8000 — so the stub just needs to exist as the onedir folder shape
# (engine/intraday-engine). The REAL engine is built by build_sidecar.sh and only
# used in the bundled/release app.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

ENGINE_DIR="${BACKEND_DIR}/../src-tauri/binaries/engine"
DEST="${ENGINE_DIR}/intraday-engine"

mkdir -p "${ENGINE_DIR}"

# Write the stub inner exe. It must exit 0 immediately so dev never blocks on a
# fake engine; the frontend uses the standalone `intradayx serve` in dev.
cat > "${DEST}" <<'STUB'
#!/bin/sh
# DEV PLACEHOLDER for the Python engine (onedir). The real folder is produced by
# backend/scripts/build_sidecar.sh (PyInstaller onedir). In `tauri dev` this
# exits immediately; the frontend falls back to a separately-run `intradayx
# serve` on :8000. /binaries is gitignored — this is a local dev artifact.
exit 0
STUB

chmod +x "${DEST}"

echo "✅ dev placeholder at src-tauri/binaries/engine/intraday-engine"
echo "   Dev flow: run \`intradayx serve\` (:8000) + \`pnpm tauri dev\`."
echo "   Release:  build the real engine with backend/scripts/build_sidecar.sh."
