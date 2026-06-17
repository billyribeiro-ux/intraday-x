"""Desktop sidecar entrypoint — launched by the Tauri Rust core as a bundled binary.

The Tauri shell (``src-tauri/``) spawns this as an external binary and reads its
stdout. The handshake (see the contract in ``src-tauri/src/lib.rs``):

* Bind AND ``listen()`` on an OS-assigned free 127.0.0.1 port, THEN print exactly
  one line ``INTRADAYX_READY <port>`` and flush — so the port is already accepting
  connections the instant the Rust supervisor points the webview at it (announcing
  before uvicorn bound caused the first /api request to be refused → a manual retry).
* On a fatal startup error, print ``INTRADAYX_FATAL <message>`` and exit non-zero
  so the supervisor can surface it instead of hanging on a dead backend.

In dev (``pnpm tauri dev``) the Rust core does NOT spawn this — the frontend talks
to a separately-run ``intradayx serve`` on :8000. This binary is only spawned in
the bundled/release app, packaged via ``backend/intraday-engine.spec``.
"""

from __future__ import annotations

import socket
import sys


def _start_orphan_watchdog() -> None:
    """Exit if the parent (the Tauri app) dies. The Rust core kills us on a clean
    quit, but it can't on the paths where no Rust runs (panic=abort, SIGKILL). On
    macOS an orphaned child is reparented to launchd (pid 1), so a ppid of 1 means
    the app is gone — don't outlive it (a zombie engine would hold its port).
    """
    import os
    import threading
    import time

    def _watch() -> None:
        while True:
            if os.getppid() == 1:
                os._exit(0)
            time.sleep(2.0)

    threading.Thread(target=_watch, daemon=True).start()


def main() -> None:
    try:
        import uvicorn

        from intradayx.api import settings_store
        from intradayx.api.app import app
        from intradayx.config import get_settings

        # Load persisted desktop settings (API keys, provider order, watched symbols)
        # BEFORE building the config so the bundled app starts with the user's choices.
        stored = settings_store.load_settings()
        settings_store.apply_to_env(stored)

        settings = get_settings()

        # Bind AND listen() BEFORE announcing, so the port is already accepting
        # connections when we print READY. The kernel queues any connection that
        # arrives before uvicorn's accept loop is up (in the listen backlog) and
        # serves it once startup completes — instead of refusing it, which is what
        # forced the "couldn't reach the engine → click Retry" first-load failure.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = int(sock.getsockname()[1])

        print(f"INTRADAYX_READY {port}", flush=True)
        _start_orphan_watchdog()

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
        uvicorn.Server(config).run(sockets=[sock])
    except Exception as exc:  # fail loud to the supervisor, never hang on a dead backend
        print(f"INTRADAYX_FATAL {exc}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
