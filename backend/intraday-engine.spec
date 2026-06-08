# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the intraday-x desktop sidecar.
# =====================================================
#
# Produces ONE self-contained, console executable named "intraday-engine"
# from backend/src/intradayx/desktop_sidecar.py. Build it via
# backend/scripts/build_sidecar.sh; the result is copied to
#   src-tauri/binaries/intraday-engine-aarch64-apple-darwin
# which matches Tauri's externalBin entry "binaries/intraday-engine" suffixed
# with the Rust host target triple.
#
# WHY ONEFILE (not onedir):
#   Tauri's `externalBin` expects to spawn a SINGLE invocable file at
#   `binaries/intraday-engine-<triple>`. A onedir build is a folder
#   (`intraday-engine/intraday-engine` + `_internal/`) that Tauri's bundler
#   will NOT relocate as one sidecar — you'd have to hand-flatten it. Onefile
#   gives exactly the one path the bundler signs, notarizes, and ships.
#   Trade-off: onefile self-extracts to a temp dir on each launch (~1-3s cold
#   start for this stack); that's acceptable for a desktop app that starts once.
#   See docs/DESKTOP.md "PyInstaller pitfalls".
#
# WHY the aggressive collect_all/collect_submodules below:
#   The scientific stack (sklearn, scipy, lightgbm, xgboost, catboost,
#   statsmodels, shap, tsfresh, polars, duckdb, pyarrow) loads code via
#   importlib / __import__ / C-extension side modules that PyInstaller's static
#   analysis CANNOT see. Left to defaults the binary builds fine and then dies
#   at runtime with ModuleNotFoundError / missing-.dylib. collect_all pulls the
#   submodules + data files + compiled binaries for each so the engine actually
#   boots inside the Tauri shell, where there is no Python env to fall back to.

import os
import sys
from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    collect_data_files,
)

block_cipher = None

# --- Paths --------------------------------------------------------------------
# This spec lives in backend/. pathex must point at backend/src so that
# `import intradayx...` resolves during analysis (the package is under src/).
SPECDIR = os.path.abspath(os.getcwd())          # build_sidecar.sh cd's to backend/
SRC = os.path.join(SPECDIR, "src")
ENTRYPOINT = os.path.join(SRC, "intradayx", "desktop_sidecar.py")

# --- Accumulators -------------------------------------------------------------
datas = []
binaries = []
hiddenimports = []


def _collect(pkg):
    """collect_all a package, tolerating ones not installed in this build.

    We sync only --extra api/ml/export/desktop; if a package is absent (e.g.
    numba is only pulled transitively in some resolutions) we skip it rather
    than fail the whole spec. Anything genuinely required will surface as a
    runtime ImportError that we then add explicitly.
    """
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas.extend(pkg_datas)
        binaries.extend(pkg_binaries)
        hiddenimports.extend(pkg_hidden)
    except Exception as exc:  # noqa: BLE001 — spec-time best effort, logged below
        print(f"[intraday-engine.spec] skip collect_all({pkg!r}): {exc}", file=sys.stderr)


# Full collect_all for the packages that hide submodules / data / native libs
# from static analysis. Order is irrelevant; duplicates are de-duped by build.
_COLLECT_ALL = [
    # Data engines (Rust/C extensions + Arrow data files)
    "polars",
    "duckdb",
    "pyarrow",
    # Core scientific stack
    "scipy",
    "sklearn",          # distribution name scikit-learn; import name sklearn
    "statsmodels",
    # Gradient boosting (each ships a compiled native lib — see libomp note)
    "lightgbm",
    "xgboost",
    "catboost",
    # Explainability / feature extraction
    "shap",
    "tsfresh",
    # Plotting / reporting (export extra)
    "matplotlib",
    "reportlab",
    # Web stack (api extra)
    "uvicorn",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_core",    # pydantic v2's compiled core
    "apscheduler",
    # Data vendor (free, non-broker) + its parsers
    "yfinance",
]
for _pkg in _COLLECT_ALL:
    _collect(_pkg)

# numba is an optional/transitive dep of parts of the ML stack (e.g. shap,
# tsfresh paths). If present it MUST be collected whole — it loads its own
# llvmlite native lib dynamically. Skipped cleanly if not installed.
_collect("numba")
_collect("llvmlite")

# --- intradayx itself ---------------------------------------------------------
# desktop_sidecar imports intradayx.api.app and intradayx.config statically, but
# the API/service/route/detector graph pulls many submodules dynamically (route
# registration, detector plugins). Collect the whole package so nothing is
# pruned. Data files (bundled config templates, etc.) ride along too.
hiddenimports += collect_submodules("intradayx")
datas += collect_data_files("intradayx")

# --- uvicorn worker/loop/protocol plumbing ------------------------------------
# uvicorn picks its event loop, HTTP, and websocket protocol implementations by
# STRING name at runtime (e.g. "uvicorn.loops.auto"), so PyInstaller's static
# analysis never sees them. desktop_sidecar runs `uvicorn[standard]` with the
# default "auto" choices, which resolve to uvloop + httptools + websockets.
# collect_all("uvicorn") above grabs most; pin the critical ones explicitly so a
# pruning change upstream can't silently break startup.
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.loops.uvloop",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]
# Their backing libs, collected whole so the "auto" picks have something to find.
for _pkg in ("uvloop", "httptools", "websockets", "wsproto", "h11", "h2", "anyio", "sniffio"):
    _collect(_pkg)

# prometheus-client (api extra) — small, but its multiprocess module is imported
# lazily; pin it so /metrics doesn't 500 inside the bundle.
hiddenimports += collect_submodules("prometheus_client")

# --- macOS OpenMP runtime (libomp.dylib) --------------------------------------
# lightgbm and xgboost (and parts of sklearn) link against an OpenMP runtime.
# On macOS that is libomp.dylib, which is NOT part of the OS and NOT shipped by
# the wheels — it comes from Homebrew. Without it the sidecar dies on first
# import of lightgbm/xgboost with:
#   "Library not loaded: @rpath/libomp.dylib".
# We locate it via `brew --prefix libomp` and bundle it at the binary root so the
# @rpath lookup resolves inside the onefile extraction dir.
#
# If brew/libomp is absent the build still succeeds but the ML stack will fail at
# runtime — build_sidecar.sh prints a warning, and docs/DESKTOP.md lists this as
# pitfall #1. Install with: `brew install libomp`.
def _bundle_libomp():
    import shutil
    import subprocess

    brew = shutil.which("brew")
    candidates = []
    if brew:
        try:
            prefix = subprocess.check_output(
                [brew, "--prefix", "libomp"], text=True, stderr=subprocess.DEVNULL
            ).strip()
            if prefix:
                candidates.append(os.path.join(prefix, "lib", "libomp.dylib"))
        except Exception as exc:  # noqa: BLE001
            print(f"[intraday-engine.spec] `brew --prefix libomp` failed: {exc}", file=sys.stderr)
    # Common Apple-Silicon Homebrew fallbacks if `brew` isn't on PATH at build time.
    candidates += [
        "/opt/homebrew/opt/libomp/lib/libomp.dylib",
        "/opt/homebrew/lib/libomp.dylib",
        "/usr/local/opt/libomp/lib/libomp.dylib",  # Intel Homebrew prefix
    ]
    for path in candidates:
        if os.path.exists(path):
            # ("." => place at the bundle/extraction root so @rpath/libomp.dylib resolves)
            print(f"[intraday-engine.spec] bundling libomp from {path}", file=sys.stderr)
            return [(path, ".")]
    print(
        "[intraday-engine.spec] WARNING: libomp.dylib not found — lightgbm/xgboost "
        "will fail at runtime. Run `brew install libomp` and rebuild.",
        file=sys.stderr,
    )
    return []


binaries += _bundle_libomp()

# ------------------------------------------------------------------------------
a = Analysis(
    [ENTRYPOINT],
    pathex=[SRC],          # so `import intradayx...` resolves
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim weight: the engine is headless. matplotlib's interactive GUI backends
    # (tkinter/Qt) are never used — the export path uses the Agg backend. Excluding
    # them avoids dragging in Tk/Qt and shrinks the binary.
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "notebook"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="intraday-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,            # keep symbols; macOS notarization is happier, size diff is small
    upx=False,              # UPX corrupts macOS dylibs / breaks codesigning — never on darwin
    upx_exclude=[],
    runtime_tmpdir=None,    # default per-launch temp extraction (onefile)
    console=True,           # MUST be a console app: Tauri reads the stdout handshake
                            # ("INTRADAYX_READY <port>" / "INTRADAYX_FATAL <msg>").
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",    # Apple Silicon; change to "x86_64" for Intel Macs.
    codesign_identity=None, # signing is done by Tauri's bundler at `tauri build`.
    entitlements_file=None,
)
