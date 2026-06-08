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
	const { once } = await import('@tauri-apps/api/event');
	// Subscribe to the event BEFORE reading the stored port, so a handshake that
	// lands in the gap between the two can't be missed (TOCTOU). Resolve on
	// whichever arrives first; time out so a never-ready engine doesn't hang.
	return new Promise<number | null>((resolve) => {
		let done = false;
		const finish = (port: number | null) => {
			if (done) return;
			done = true;
			clearTimeout(timer);
			resolve(port);
		};
		// 30s margin: a bundled PyInstaller onefile self-extracts on launch, so the
		// engine's first handshake can lag several seconds on a cold start.
		const timer = setTimeout(() => finish(null), 30000);
		void once<{ port: number }>('backend-ready', (event) => finish(event.payload.port));
		void invoke<number | null>('get_backend_port').then(
			(port) => {
				if (typeof port === 'number') finish(port);
			},
			() => {
				/* invoke failed — let the event or the timeout decide */
			}
		);
	});
}

let cached: Promise<Backend> | null = null;

export function resolveBackend(): Promise<Backend> {
	if (cached) return cached;
	const attempt = (async (): Promise<Backend> => {
		if (!inTauri()) return devBackend();
		const port = await resolvePort();
		if (port == null) {
			// Engine not ready yet (slow PyInstaller cold start) or `tauri dev`
			// (no sidecar). Do NOT cache the fallback — clear it so the next call
			// retries once the engine is up; otherwise we'd talk to a dead proxy
			// for the whole session with no recovery.
			cached = null;
			return devBackend();
		}
		return { httpBase: `http://127.0.0.1:${port}`, wsBase: `ws://127.0.0.1:${port}` };
	})();
	cached = attempt;
	return attempt;
}

/** Absolute HTTP base for REST calls ('' in dev → relative, proxied). */
export async function apiBase(): Promise<string> {
	return (await resolveBackend()).httpBase;
}

/** Full websocket URL for the live signal stream. */
export async function wsUrlAsync(): Promise<string> {
	return `${(await resolveBackend()).wsBase}/ws/signals`;
}
