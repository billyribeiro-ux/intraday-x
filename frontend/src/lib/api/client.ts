// Typed API client. In dev, requests go to the relative /api path which the
// Vite proxy forwards to the FastAPI backend on :8000 (no CORS needed). Pass the
// SvelteKit load `fetch` so SSR/relative URLs resolve correctly.

import type { BarsPayload, ScanPayload } from '$lib/api/types';

type Fetch = typeof globalThis.fetch;

const API_BASE = ''; // relative; Vite proxy handles /api in dev

async function getJson<T>(fetchFn: Fetch, url: string): Promise<T> {
	const res = await fetchFn(`${API_BASE}${url}`);
	if (!res.ok) {
		throw new Error(`API ${url} failed: ${res.status} ${res.statusText}`);
	}
	return (await res.json()) as T;
}

export function getBars(
	fetchFn: Fetch,
	symbol: string,
	timeframe = '5m',
	days = 7
): Promise<BarsPayload> {
	const q = new URLSearchParams({ symbol, timeframe, days: String(days) });
	return getJson<BarsPayload>(fetchFn, `/api/bars?${q}`);
}

export async function scan(
	fetchFn: Fetch,
	symbol: string,
	timeframe = '5m',
	days = 7
): Promise<ScanPayload> {
	const res = await fetchFn('/api/scan', {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ symbol, timeframe, days, scanner: 'reversal' })
	});
	if (!res.ok) throw new Error(`API /api/scan failed: ${res.status}`);
	return (await res.json()) as ScanPayload;
}

/** Build the websocket URL for the live signal stream from the page origin. */
export function wsUrl(): string {
	if (typeof location === 'undefined') return '';
	const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
	return `${proto}//${location.host}/ws/signals`;
}
