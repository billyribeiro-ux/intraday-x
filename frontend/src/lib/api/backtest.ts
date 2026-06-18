// Backtest Studio API client + typed response, kept SEPARATE from the shared
// client.ts/types.ts on purpose (this screen owns this module).
//
// Mirrors backend/src/intradayx/api/schemas.py exactly:
//   BacktestRequest  -> BacktestParams
//   BacktestResponse -> BacktestResponse
//   MetricsDTO       -> BacktestMetrics
//   TodStatDTO       -> TodStat
//   TradeDTO         -> BacktestTrade
//   EquityPointDTO   -> EquityPoint
//
// Money values are integer CENTS on the wire (i64 on the backend, `number` in
// JS — exact to 2^53). Divide by 100 only for display, never for arithmetic.

import { apiBase } from '$lib/api/backend';
import type { Attribution, CatalystEvent, MoveExplanation, Scanner } from '$lib/api/types';

type Fetch = typeof globalThis.fetch;

export type Timeframe =
	| '1m'
	| '2m'
	| '3m'
	| '4m'
	| '5m'
	| '10m'
	| '15m'
	| '30m'
	| '1h'
	| '2h'
	| '4h'
	| '1d'
	| '1w'
	| '1mo'
	| '3mo'
	| '1y';

export interface BacktestParams {
	symbol: string;
	timeframe: Timeframe;
	days: number;
	max_hold: number;
	/** Drives the backtest engine: the backend builds SignalEngine(make_strategy(scanner)). */
	scanner: Scanner;
	use_learning: boolean;
	meta_threshold: number;
}

export interface LearnParams {
	symbol: string;
	timeframe: Timeframe;
	days: number;
	max_hold: number;
	scanner: Scanner;
	min_samples: number;
}

/** Mirrors TodStatDTO. expectancy_cents is a float (can be fractional cents). */
export interface TodStat {
	bucket: string;
	n: number;
	win_rate: number; // 0..1
	expectancy_cents: number;
}

/** Mirrors MetricsDTO. profit_factor === null encodes "infinite" (wins, no losses). */
export interface BacktestMetrics {
	n_trades: number;
	win_rate: number; // 0..1
	expectancy_cents: number; // float cents per trade
	profit_factor: number | null;
	total_pnl_cents: number; // i64 cents
	max_drawdown_cents: number; // i64 cents (>= 0)
	sharpe_per_trade: number;
	/** P(true SR > 0) in [0,1], IN-SAMPLE (deflated for skew/kurtosis + sample
	 *  size only, n_trials=1). null when < 3 trades. Caption must say "in-sample". */
	deflated_sharpe: number | null;
	n_trials: number;
	per_tod: TodStat[];
}

/** Mirrors TradeDTO. */
export interface BacktestTrade {
	signal_id: string;
	signal_ts: string;
	kind: string;
	side: string;
	is_long: boolean;
	entry_ts: string; // ISO-8601 UTC
	exit_ts: string; // ISO-8601 UTC
	entry: number; // price
	exit: number; // price
	shares: number;
	pnl_cents: number; // i64 cents
	exit_reason: string;
	tod_bucket: string;
	confidence: number;
	quality_score: number;
	meta_score?: number | null;
	attribution: Attribution;
	catalysts: CatalystEvent[];
	entry_explanation?: MoveExplanation | null;
	exit_explanation?: MoveExplanation | null;
	diagnosis: string;
}

/** Mirrors EquityPointDTO. */
export interface EquityPoint {
	ts: string; // ISO-8601 UTC
	equity_cents: number; // cumulative equity, i64 cents
}

/** Mirrors BacktestResponse. */
export interface BacktestResponse {
	symbol: string;
	timeframe: string;
	n_signals: number;
	n_raw_signals: number;
	data_completeness: number;
	learning: BacktestLearning;
	metrics: BacktestMetrics;
	baseline_metrics: BacktestMetrics;
	trades: BacktestTrade[];
	equity_curve: EquityPoint[];
	catalysts: CatalystEvent[];
}

export interface BacktestLearning {
	enabled: boolean;
	model_loaded: boolean;
	model_path?: string | null;
	meta_threshold: number;
	scored_signals: number;
	selected_signals: number;
	rejected_signals: number;
	avg_meta_score?: number | null;
	pnl_delta_cents: number;
	summary: string;
}

export interface LearnResponse {
	symbol: string;
	timeframe: string;
	scanner: Scanner;
	saved: boolean;
	model_path?: string | null;
	n_samples: number;
	pos_rate: number;
	cv_accuracy: number;
	cv_precision: number;
	cv_recall: number;
	cv_roc_auc: number;
	insufficient: boolean;
	reason: string;
	feature_importance: [string, number][];
}

/**
 * POST /api/backtest. Pass the SvelteKit `fetch` so relative URLs resolve in
 * dev (Vite proxy) and absolute ones in the bundled Tauri app.
 *
 * No silent catch: a non-2xx response throws so the caller can surface it in
 * the error banner.
 */
export async function runBacktest(
	fetchFn: Fetch,
	params: BacktestParams
): Promise<BacktestResponse> {
	const base = await apiBase();
	const res = await fetchFn(`${base}/api/backtest`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({
			symbol: params.symbol.trim().toUpperCase(),
			timeframe: params.timeframe,
			days: params.days,
			max_hold: params.max_hold,
			scanner: params.scanner,
			use_learning: params.use_learning,
			meta_threshold: params.meta_threshold
		})
	});
	if (!res.ok) {
		let detail = '';
		try {
			const body = (await res.json()) as { detail?: string };
			if (body?.detail) detail = ` — ${body.detail}`;
		} catch {
			// non-JSON error body; status line is enough.
		}
		throw new Error(`Backtest failed: ${res.status} ${res.statusText}${detail}`);
	}
	return (await res.json()) as BacktestResponse;
}

export async function trainBacktestModel(
	fetchFn: Fetch,
	params: LearnParams
): Promise<LearnResponse> {
	const base = await apiBase();
	const res = await fetchFn(`${base}/api/learn`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({
			symbol: params.symbol.trim().toUpperCase(),
			timeframe: params.timeframe,
			days: params.days,
			max_hold: params.max_hold,
			scanner: params.scanner,
			min_samples: params.min_samples
		})
	});
	if (!res.ok) {
		let detail = '';
		try {
			const body = (await res.json()) as { detail?: string };
			if (body?.detail) detail = ` — ${body.detail}`;
		} catch {
			// non-JSON error body; status line is enough.
		}
		throw new Error(`Learning failed: ${res.status} ${res.statusText}${detail}`);
	}
	return (await res.json()) as LearnResponse;
}

/** Cents -> "$1,234.56" (display only). */
export function formatUsd(cents: number): string {
	return (cents / 100).toLocaleString(undefined, {
		style: 'currency',
		currency: 'USD'
	});
}
