// Typed fetchers for the Settings API. Base URL is resolved by `backend.ts`:
// relative '' in dev (Vite proxy → FastAPI :8000) or absolute
// 'http://127.0.0.1:<port>' in the bundled Tauri app.
//
// API keys are WRITE-ONLY: the server never returns a key value, and this
// module never stores or surfaces one. We only ever learn whether a vendor is
// `configured`. Every fetcher throws on a non-OK response — no silent catch.

import { apiBase } from '$lib/api/backend';

export type Theme = 'dark' | 'light' | 'system';
export type ScannerDefault = 'reversal' | 'scalping';

/** A free, non-broker market-data vendor. `env_var` is the backend env name the
 *  key is read from (null when no key is needed, e.g. yfinance). */
export interface Vendor {
	name: string;
	env_var: string | null;
	configured: boolean;
}

export interface Settings {
	theme: Theme;
	providers: string[];
	watched_symbols: string[];
	default_scanner: ScannerDefault;
	vendors: Vendor[];
}

/** Partial update body for PUT /api/settings. Omitted fields are left as-is. */
export interface SettingsUpdate {
	theme?: Theme;
	providers?: string[];
	watched_symbols?: string[];
	default_scanner?: ScannerDefault;
}

export interface VendorKeyResult {
	vendor: string;
	configured: boolean;
}

async function readError(res: Response, path: string): Promise<never> {
	// Surface the backend's message when it sends one; fall back to status.
	let detail = '';
	try {
		const body = (await res.json()) as { detail?: unknown };
		if (typeof body.detail === 'string') detail = `: ${body.detail}`;
	} catch {
		// Non-JSON body — the status line is all we have.
	}
	throw new Error(`API ${path} failed: ${res.status} ${res.statusText}${detail}`);
}

export async function getSettings(): Promise<Settings> {
	const base = await apiBase();
	const res = await fetch(`${base}/api/settings`);
	if (!res.ok) return readError(res, '/api/settings');
	return (await res.json()) as Settings;
}

export async function putSettings(update: SettingsUpdate): Promise<Settings> {
	const base = await apiBase();
	const res = await fetch(`${base}/api/settings`, {
		method: 'PUT',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(update)
	});
	if (!res.ok) return readError(res, '/api/settings');
	return (await res.json()) as Settings;
}

export async function getVendorKey(vendor: string): Promise<string> {
	const base = await apiBase();
	const res = await fetch(`${base}/api/settings/vendor-key/${encodeURIComponent(vendor)}/value`);
	if (!res.ok) {
		let detail = '';
		try {
			const body = (await res.json()) as { detail?: unknown };
			if (typeof body.detail === 'string') detail = `: ${body.detail}`;
		} catch {
			// ignore
		}
		throw new Error(`API /settings/vendor-key/${vendor}/value failed: ${res.status} ${res.statusText}${detail}`);
	}
	const data = (await res.json()) as { api_key: string };
	return data.api_key;
}

export async function setVendorKey(vendor: string, apiKey: string): Promise<VendorKeyResult> {
	const base = await apiBase();
	const res = await fetch(`${base}/api/settings/vendor-key`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		// `api_key` is sent to the server and never read back — write-only.
		body: JSON.stringify({ vendor, api_key: apiKey })
	});
	if (!res.ok) return readError(res, '/api/settings/vendor-key');
	return (await res.json()) as VendorKeyResult;
}

export async function clearVendorKey(vendor: string): Promise<VendorKeyResult> {
	const base = await apiBase();
	const res = await fetch(`${base}/api/settings/vendor-key/${encodeURIComponent(vendor)}`, {
		method: 'DELETE'
	});
	if (!res.ok) return readError(res, `/api/settings/vendor-key/${vendor}`);
	return (await res.json()) as VendorKeyResult;
}
