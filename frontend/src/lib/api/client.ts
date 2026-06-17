// Typed API client. The base URL is resolved by `backend.ts`: relative '' in dev
// (the Vite proxy forwards /api to FastAPI on :8000), or absolute
// 'http://127.0.0.1:<port>' in the bundled Tauri app. Pass the SvelteKit load
// `fetch` so relative URLs resolve correctly.

import { apiBase } from '$lib/api/backend';
import type { BarsPayload, ScanPayload, Scanner } from '$lib/api/types';

type Fetch = typeof globalThis.fetch;

async function getJson<T>(fetchFn: Fetch, url: string): Promise<T> {
	const base = await apiBase();
	const res = await fetchFn(`${base}${url}`);
	if (!res.ok) {
		throw new Error(`API ${url} failed: ${res.status} ${res.statusText}`);
	}
	return (await res.json()) as T;
}

export function getBars(
	fetchFn: Fetch,
	symbol: string,
	timeframe = '5m',
	days = 7,
	scanner: Scanner = 'reversal'
): Promise<BarsPayload> {
	const q = new URLSearchParams({ symbol, timeframe, days: String(days), scanner });
	return getJson<BarsPayload>(fetchFn, `/api/bars?${q}`);
}

export async function scan(
	fetchFn: Fetch,
	symbol: string,
	timeframe = '5m',
	days = 7,
	scanner: Scanner = 'reversal'
): Promise<ScanPayload> {
	const base = await apiBase();
	const res = await fetchFn(`${base}/api/scan`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ symbol, timeframe, days, scanner })
	});
	if (!res.ok) throw new Error(`API /api/scan failed: ${res.status}`);
	return (await res.json()) as ScanPayload;
}

/**
 * Websocket URL for the live signal stream, from the page origin. Works in dev
 * and `tauri dev` (the Vite proxy forwards /ws to :8000). In the bundled app the
 * engine is on a dynamic port — the store will migrate to `wsUrlAsync` (in
 * backend.ts) when the Monitor is adapted for Tauri.
 */
export function wsUrl(): string {
	if (typeof location === 'undefined') return '';
	const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
	return `${proto}//${location.host}/ws/signals`;
}
