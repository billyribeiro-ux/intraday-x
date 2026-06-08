#!/usr/bin/env bash
#
# build_sidecar.sh — build the intraday-x Python engine into ONE self-contained
# executable and install it as the Tauri sidecar.
# ============================================================================
#
# Output:
#   src-tauri/binaries/intraday-engine-aarch64-apple-darwin
# which is what Tauri's externalBin ("binaries/intraday-engine" + host triple)
# spawns in the bundled/release app. After running this, `pnpm tauri build`
# bundles, signs, and notarizes the engine alongside the app.
#
# Prerequisites:
#   - uv (https://docs.astral.sh/uv/) on PATH
#   (No libomp needed: the sidecar is api-only and bundles no OpenMP-linked ML
#    libs. The app never imports lightgbm/xgboost/shap/etc. — those are CLI-only.)
#
# Target triple note:
#   This script hardcodes aarch64-apple-darwin (Apple Silicon). For an Intel
#   Mac the sidecar filename AND the spec's target_arch must change to match
#   the Rust host: run `rustc -vV | grep host` and use that triple
#   (e.g. x86_64-apple-darwin), and set target_arch="x86_64" in the spec.
#
set -euo pipefail

# Run from backend/ regardless of where invoked: cd to this script's parent dir
# (scripts/ -> backend/). All paths below are relative to backend/.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

TARGET_TRIPLE="aarch64-apple-darwin"
SIDECAR_NAME="intraday-engine"
DEST_DIR="../src-tauri/binaries"
DEST="${DEST_DIR}/${SIDECAR_NAME}-${TARGET_TRIPLE}"

echo "==> intraday-x sidecar build"
echo "    backend:  ${BACKEND_DIR}"
echo "    target:   ${TARGET_TRIPLE}"
echo "    dest:     ${DEST}"

# 1. Sync the build env: pyinstaller (desktop) + the api extra (fastapi/uvicorn/
#    websockets/apscheduler/prometheus). NOT ml/export — the app's API surface
#    never imports them, so bundling them only bloats size + cold start. The base
#    deps (polars/duckdb/pyarrow/pandas/scipy/yfinance) come with the project.
echo "==> [1/4] uv sync (desktop + api)"
uv sync --extra desktop --extra api

# 2. Run PyInstaller against the spec. --clean wipes stale caches (stale hooks
#    are a classic source of "works on my machine"); separate work/dist dirs.
echo "==> [2/4] pyinstaller (a few minutes; api-only build is far smaller than the full ML stack)"
uv run pyinstaller intraday-engine.spec \
  --noconfirm \
  --clean \
  --distpath dist \
  --workpath build/pyinstaller

# 3. Install into the Tauri sidecar location with the host triple suffix.
echo "==> [3/4] install sidecar"
mkdir -p "${DEST_DIR}"
cp "dist/${SIDECAR_NAME}" "${DEST}"
chmod +x "${DEST}"

# 4. Report.
echo "==> [4/4] done"
SIZE="$(du -h "${DEST}" | cut -f1)"
echo "✅ sidecar at src-tauri/binaries/${SIDECAR_NAME}-${TARGET_TRIPLE} (${SIZE})"
echo "   Next: cd ../ && pnpm tauri build"
