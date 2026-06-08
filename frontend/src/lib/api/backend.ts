// Resolves WHERE the Python engine is listening — the one place that knows the
// difference between dev and the bundled app.
//
//  • Bundled .app  — the Tauri Rust core spawns the engine on a dynamic
//    127.0.0.1 port and exposes it via the `get_backend_port` command and the
//    `backend-ready` event. We use absolute `http://127.0.0.1:<port>` URLs.
//  • Dev (browser OR `tauri dev`) — no sidecar is spawned; the Vite proxy
//    forwards relative `/api` + `/ws` to the FastAPI backend on :8000, so we use
//    relative URLs and the page-origin host.
//
// Resolution is cached after the first successful call.

export interface Backend {
	/** '' (relative, dev) or 'http://127.0.0.1:<port>' (bundled app). */
	httpBase: string;
	/** 'ws[s]://<host>' (dev) or 'ws://127.0.0.1:<port>' (bundled app). */
	wsBase: string;
}

function inTauri(): boolean {
	return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

function devBackend(): Backend {
	const host = typeof location !== 'undefined' ? location.host : 'localhost:5173';
	const wsProto =
		typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss:' : 'ws:';
	return { httpBase: '', wsBase: `${wsProto}//${host}` };
}

async function resolvePort(): Promise<number | null> {
	// Lazy-import the Tauri APIs so the plain browser build never loads them.
	const { invoke } = await import('@tauri-apps/api/core');
	const existing = await invoke<number | null>('get_backend_port');
	if (typeof existing === 'number') return existing;
	// The engine may not have finished its stdout handshake yet — wait once.
	const { once } = await import('@tauri-apps/api/event');
	return new Promise<number | null>((resolve) => {
		const timer = setTimeout(() => resolve(null), 15000);
		void once<{ port: number }>('backend-ready', (event) => {
			clearTimeout(timer);
			resolve(event.payload.port);
		});
	});
}

let cached: Promise<Backend> | null = null;

export function resolveBackend(): Promise<Backend> {
	if (cached) return cached;
	cached = (async () => {
		if (!inTauri()) return devBackend();
		const port = await resolvePort();
		// `tauri dev` has no sidecar → port is null → fall back to the proxy/host.
		if (port == null) return devBackend();
		return { httpBase: `http://127.0.0.1:${port}`, wsBase: `ws://127.0.0.1:${port}` };
	})();
	return cached;
}

/** Absolute HTTP base for REST calls ('' in dev → relative, proxied). */
export async function apiBase(): Promise<string> {
	return (await resolveBackend()).httpBase;
}

/** Full websocket URL for the live signal stream. */
export async function wsUrlAsync(): Promise<string> {
	return `${(await resolveBackend()).wsBase}/ws/signals`;
}
