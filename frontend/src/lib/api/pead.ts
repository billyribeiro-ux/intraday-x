// PEAD (Post-Earnings-Announcement Drift) API client + typed response.
// Mirrors backend/src/intradayx/api/schemas.py: PeadRequest -> PeadParams,
// PeadResponse -> PeadResponse. The one validated edge in the system.

import { apiBase } from '$lib/api/backend';

type Fetch = typeof globalThis.fetch;

export interface PeadParams {
	symbols: string[];
	hold_days?: number;
	years?: number;
	min_sue?: number;
	cost_bps?: number;
	borrow_bps?: number;
}

export interface PeadOpenTrade {
	symbol: string;
	announce_date: string;
	entry_date: string;
	side: string;
	surprise: number;
	sue: number;
	entry: number;
}

export interface PeadEquityPoint {
	time: number; // epoch seconds
	value: number;
}

export interface PeadResponse {
	symbols: string[];
	hold_days: number;
	years: number;
	n_events: number;
	mean_return: number;
	t_stat: number;
	hit_rate: number;
	// Market-adjusted (SPY-hedged) — separates alpha from beta. Research finding:
	// raw PEAD P&L is substantially market beta; always read these first.
	adj_n: number;
	adj_mean_return: number;
	adj_t_stat: number;
	adj_hit_rate: number;
	sharpe: number;
	ann_return: number;
	ann_vol: number;
	max_drawdown: number;
	total_return: number;
	n_days: number;
	cost_bps: number;
	borrow_bps: number;
	open_trades: PeadOpenTrade[];
	equity: PeadEquityPoint[];
}

async function readError(res: Response, path: string): Promise<never> {
	let detail = '';
	try {
		const body = (await res.json()) as { detail?: unknown };
		if (typeof body.detail === 'string') detail = `: ${body.detail}`;
	} catch {
		// non-JSON body — status line is all we have
	}
	throw new Error(`API ${path} failed: ${res.status} ${res.statusText}${detail}`);
}

export async function runPead(fetchFn: Fetch, params: PeadParams): Promise<PeadResponse> {
	const base = await apiBase();
	const res = await fetchFn(`${base}/api/pead`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(params)
	});
	if (!res.ok) return readError(res, '/api/pead');
	return (await res.json()) as PeadResponse;
}
