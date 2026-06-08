"""Desktop sidecar entrypoint — launched by the Tauri Rust core as a bundled binary.

The Tauri shell (``src-tauri/``) spawns this as an external binary and reads its
stdout. The handshake (see the contract in ``src-tauri/src/lib.rs``):

* Bind uvicorn to an OS-assigned free port on 127.0.0.1.
* Print exactly one line ``INTRADAYX_READY <port>`` and flush — BEFORE the server
  blocks — so the Rust supervisor learns the port and points the webview at it.
* On a fatal startup error, print ``INTRADAYX_FATAL <message>`` and exit non-zero
  so the supervisor can surface it instead of hanging on a dead backend.

In dev (``pnpm tauri dev``) the Rust core does NOT spawn this — the frontend talks
to a separately-run ``intradayx serve`` on :8000. This binary is only spawned in
the bundled/release app, packaged via ``backend/intraday-engine.spec``.
"""

from __future__ import annotations

import socket
import sys


def _free_port() -> int:
    """Ask the OS for a free 127.0.0.1 port, then release it for uvicorn to bind.

    The reuse window is a negligible race on loopback for a single-user desktop
    app; if uvicorn fails to bind it we fail loud via the FATAL handshake below.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    try:
        import uvicorn

        from intradayx.api.app import app
        from intradayx.config import get_settings

        port = _free_port()
        # Handshake FIRST: the Rust supervisor blocks on this exact line.
        print(f"INTRADAYX_READY {port}", flush=True)

        settings = get_settings()
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
    except Exception as exc:  # fail loud to the supervisor, never hang on a dead backend
        print(f"INTRADAYX_FATAL {exc}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
