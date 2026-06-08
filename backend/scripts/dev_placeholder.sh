#!/usr/bin/env bash
#
# dev_placeholder.sh — recreate the dev placeholder sidecar.
# ============================================================================
#
# `src-tauri/binaries/` is gitignored, so a fresh checkout has no sidecar and
# `cargo check` / `pnpm tauri dev` fail because Tauri's externalBin entry
# ("binaries/intraday-engine") points at a missing file. This drops a no-op
# stub there so the Rust core builds and dev runs.
#
# In `tauri dev` the Rust core does NOT spawn the engine — the frontend talks to
# a separately-run `intradayx serve` on :8000 — so the stub just needs to exist
# and be an executable that exits 0. The REAL engine is built by
# build_sidecar.sh and only used in the bundled/release app.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

TARGET_TRIPLE="aarch64-apple-darwin"
DEST_DIR="${BACKEND_DIR}/../src-tauri/binaries"
DEST="${DEST_DIR}/intraday-engine-${TARGET_TRIPLE}"

mkdir -p "${DEST_DIR}"

# Write the stub. It must exit 0 immediately so dev never blocks on a fake
# engine; the frontend uses the standalone `intradayx serve` in dev.
cat > "${DEST}" <<'STUB'
#!/bin/sh
# DEV PLACEHOLDER for the Python engine sidecar. The real binary is produced by
# backend/scripts/build_sidecar.sh (PyInstaller). In `tauri dev` this exits
# immediately, so the frontend falls back to a separately-run `intradayx serve`
# on :8000. /binaries is gitignored — this is a local dev artifact.
exit 0
STUB

chmod +x "${DEST}"

echo "✅ dev placeholder at src-tauri/binaries/intraday-engine-${TARGET_TRIPLE}"
echo "   Dev flow: run \`intradayx serve\` (:8000) + \`pnpm tauri dev\`."
echo "   Release:  build the real engine with backend/scripts/build_sidecar.sh."
