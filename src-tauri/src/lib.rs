//! intraday-x desktop core.
//!
//! Responsibilities of the Rust shell:
//! * **Engine** — spawn the bundled Python engine (a PyInstaller *onedir* shipped
//!   as a Tauri resource under `engine/`), read its stdout for the
//!   `INTRADAYX_READY <port>` handshake, store the port, emit `backend-ready` to
//!   the webview, and kill the child on exit. In `tauri dev` the resource isn't
//!   bundled, so the spawn is skipped and the frontend falls back to a
//!   separately-run `intradayx serve` on :8000 (see frontend/src/lib/api/backend.ts).
//! * **Auto-update** — the `updater` + `process` plugins power the in-app
//!   "Update available" flow (check → signed download → install → relaunch).

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::path::BaseDirectory;
use tauri::{Emitter, Manager, RunEvent};

/// Shared state: the engine's port (once the handshake lands) and the child
/// handle so we can terminate it when the app quits.
#[derive(Default)]
struct EngineState {
    port: Mutex<Option<u16>>,
    child: Mutex<Option<Child>>,
}

#[derive(Clone, serde::Serialize)]
struct BackendReady {
    port: u16,
}

/// The frontend calls this to discover where the engine is listening. Returns
/// `None` in dev (no engine spawned) so the frontend uses its :8000 fallback.
#[tauri::command]
fn get_backend_port(state: tauri::State<'_, EngineState>) -> Option<u16> {
    *state.port.lock().unwrap()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(EngineState::default())
        .invoke_handler(tauri::generate_handler![get_backend_port])
        .setup(|app| {
            spawn_engine(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // Kill the engine on BOTH ExitRequested and the terminal Exit event —
            // on macOS ExitRequested is unreliable (Cmd-Q / last-window-close), so
            // Exit is the backstop. .take() makes the double-fire idempotent.
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                if let Some(mut child) = app_handle
                    .state::<EngineState>()
                    .child
                    .lock()
                    .unwrap()
                    .take()
                {
                    let _ = child.kill();
                }
            }
        });
}

/// Spawn the bundled Python engine and pump its stdout. Non-fatal on failure:
/// in dev the resource isn't bundled, so the frontend talks to :8000 instead.
fn spawn_engine(handle: tauri::AppHandle) {
    // The engine onedir is bundled at <Resources>/engine/. Its inner exe locates
    // its own `_internal/` relative to its real path, so we spawn it in place.
    let exe = match handle
        .path()
        .resolve("engine/intraday-engine", BaseDirectory::Resource)
    {
        Ok(path) if path.exists() => path,
        Ok(path) => {
            eprintln!("[engine] not bundled at {path:?} (dev?) — frontend uses :8000");
            return;
        }
        Err(err) => {
            eprintln!("[engine] failed to resolve engine resource ({err}); dev backend :8000");
            return;
        }
    };

    let mut child = match Command::new(&exe)
        .stdout(Stdio::piped())
        // Engine logs flow to the app's stderr — no unread pipe to fill (deadlock).
        .stderr(Stdio::inherit())
        .spawn()
    {
        Ok(child) => child,
        Err(err) => {
            eprintln!("[engine] failed to spawn {exe:?} ({err}); dev backend :8000");
            return;
        }
    };

    let stdout = child.stdout.take();
    *handle.state::<EngineState>().child.lock().unwrap() = Some(child);

    // BufReader::lines() splits on '\n', so the handshake line can't be missed by
    // chunk boundaries. A dedicated OS thread is fine — it just blocks on read.
    if let Some(stdout) = stdout {
        std::thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines().map_while(Result::ok) {
                handle_engine_line(&handle, line.trim());
            }
            // Stream closed → the engine process exited.
            let _ = handle.emit("backend-exited", ());
        });
    }
}

/// Parse one engine stdout line against the handshake contract.
fn handle_engine_line(handle: &tauri::AppHandle, line: &str) {
    if let Some(rest) = line.strip_prefix("INTRADAYX_READY ") {
        if let Ok(port) = rest.trim().parse::<u16>() {
            *handle.state::<EngineState>().port.lock().unwrap() = Some(port);
            let _ = handle.emit("backend-ready", BackendReady { port });
        }
    } else if let Some(msg) = line.strip_prefix("INTRADAYX_FATAL ") {
        let _ = handle.emit("backend-error", msg.to_string());
    } else if !line.is_empty() {
        println!("[engine] {line}");
    }
}
