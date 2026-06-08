//! intraday-x desktop core.
//!
//! Responsibilities of the Rust shell:
//! * **Engine sidecar** — spawn the bundled Python engine, read its stdout for the
//!   `INTRADAYX_READY <port>` handshake, store the port, emit `backend-ready` to
//!   the webview, and kill the child on exit. In `tauri dev` the bundled binary is
//!   absent, so the spawn fails gracefully and the frontend falls back to a
//!   separately-run `intradayx serve` on :8000 (see `frontend/src/lib/api/backend.ts`).
//! * **Auto-update** — the `updater` + `process` plugins power the in-app
//!   "Update available" flow (check → signed download → install → relaunch),
//!   driven from the Settings screen.

use std::sync::Mutex;

use tauri::{Emitter, Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Shared state: the engine's port (once the handshake lands) and the child
/// handle so we can terminate it when the app quits.
#[derive(Default)]
struct EngineState {
    port: Mutex<Option<u16>>,
    child: Mutex<Option<CommandChild>>,
}

#[derive(Clone, serde::Serialize)]
struct BackendReady {
    port: u16,
}

/// The frontend calls this to discover where the engine is listening. Returns
/// `None` in dev (no sidecar spawned) so the frontend uses its :8000 fallback.
#[tauri::command]
fn get_backend_port(state: tauri::State<'_, EngineState>) -> Option<u16> {
    *state.port.lock().unwrap()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
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
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(child) = app_handle
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

/// Spawn the Python engine sidecar and pump its stdout. Failure is non-fatal:
/// in dev there is no bundled binary, and the frontend talks to :8000 instead.
fn spawn_engine(handle: tauri::AppHandle) {
    let command = match handle.shell().sidecar("intraday-engine") {
        Ok(command) => command,
        Err(err) => {
            eprintln!("[engine] sidecar unavailable ({err}); falling back to dev backend on :8000");
            return;
        }
    };

    let (mut rx, child) = match command.spawn() {
        Ok(pair) => pair,
        Err(err) => {
            eprintln!("[engine] failed to spawn sidecar ({err}); falling back to dev backend on :8000");
            return;
        }
    };

    *handle.state::<EngineState>().child.lock().unwrap() = Some(child);

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    handle_engine_line(&handle, line.trim());
                }
                CommandEvent::Stderr(bytes) => {
                    eprintln!("[engine] {}", String::from_utf8_lossy(&bytes).trim());
                }
                CommandEvent::Terminated(payload) => {
                    let _ = handle.emit("backend-exited", payload.code);
                }
                _ => {}
            }
        }
    });
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
