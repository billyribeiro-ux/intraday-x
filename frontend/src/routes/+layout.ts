// The whole app is a client-rendered SPA: Tauri serves static files (no Node
// server), and the live websocket + the engine's port are browser-only. So no
// SSR and no prerender — data loads at runtime in the webview.
export const ssr = false;
export const prerender = false;
