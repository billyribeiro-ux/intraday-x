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
#   - Homebrew libomp for lightgbm/xgboost OpenMP:  brew install libomp
#     (without it the binary builds but the ML stack dies at runtime —
#      the spec prints a warning; see docs/DESKTOP.md pitfall #1)
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

# 1. Sync the build env: pyinstaller (desktop) + all runtime extras the engine
#    imports at startup (api + ml + export). Without ml/export/api the spec's
#    collect_all calls for those packages no-op and the bundled engine would
#    crash on first import inside Tauri.
echo "==> [1/4] uv sync (desktop + api + ml + export)"
uv sync --extra desktop --extra api --extra ml --extra export

# Soft check for libomp so the operator isn't surprised at runtime.
if ! { [ -e /opt/homebrew/opt/libomp/lib/libomp.dylib ] \
       || [ -e /usr/local/opt/libomp/lib/libomp.dylib ] \
       || { command -v brew >/dev/null 2>&1 && brew --prefix libomp >/dev/null 2>&1; }; }; then
  echo "    WARNING: libomp.dylib not found. lightgbm/xgboost will fail at runtime."
  echo "             Install with: brew install libomp"
fi

# 2. Run PyInstaller against the spec. --clean wipes stale caches (stale hooks
#    are a classic source of "works on my machine"); separate work/dist dirs.
echo "==> [2/4] pyinstaller (this is slow — minutes — and produces ~150-300MB)"
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
