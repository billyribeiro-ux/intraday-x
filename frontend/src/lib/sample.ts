// Deterministic sample data for the Phase-0 dashboard demo (no backend yet).
// Replaced by live REST/WS data in Phase 5. Deterministic so the demo is stable.

import type { CandlestickData, HistogramData, LineData, UTCTimestamp } from 'lightweight-charts';

import type { Signal } from '$lib/api/types';
import { toChartTime } from '$lib/chart/time';

export interface SampleData {
	candles: CandlestickData<UTCTimestamp>[];
	volume: HistogramData<UTCTimestamp>[];
	vwap: LineData<UTCTimestamp>[];
	signals: Signal[];
	levels: { poc: number; vah: number; val: number };
}

// Tiny seeded LCG so the demo path is identical every load.
function lcg(seed: number): () => number {
	let s = seed >>> 0;
	return () => {
		s = (s * 1664525 + 1013904223) >>> 0;
		return s / 0xffffffff;
	};
}

const N = 90;
const STEP_MS = 5 * 60 * 1000;
const START = Date.UTC(2026, 5, 5, 13, 30, 0); // 2026-06-05 13:30 UTC

export function makeSampleData(): SampleData {
	const rand = lcg(42);
	const candles: CandlestickData<UTCTimestamp>[] = [];
	const volume: HistogramData<UTCTimestamp>[] = [];
	const vwap: LineData<UTCTimestamp>[] = [];

	let price = 312;
	let cumPV = 0;
	let cumV = 0;
	for (let i = 0; i < N; i++) {
		const t = toChartTime(START + i * STEP_MS);
		const drift = Math.sin(i / 9) * 0.9; // a couple of swings to reverse on
		const open = price;
		const close = +(open + drift + (rand() - 0.5) * 0.6).toFixed(2);
		const high = +(Math.max(open, close) + rand() * 0.5).toFixed(2);
		const low = +(Math.min(open, close) - rand() * 0.5).toFixed(2);
		const vol = Math.round(4000 + rand() * 6000 + Math.abs(drift) * 3000);
		price = close;

		candles.push({ time: t, open, high, low, close });
		volume.push({
			time: t,
			value: vol,
			color: close >= open ? 'rgba(38,166,154,0.5)' : 'rgba(239,83,80,0.5)'
		});
		const tp = (high + low + close) / 3;
		cumPV += tp * vol;
		cumV += vol;
		vwap.push({ time: t, value: +(cumPV / cumV).toFixed(2) });
	}

	const topIdx = 18;
	const bottomIdx = 46;
	const signals: Signal[] = [
		{
			signal_id: 'demo-top-1',
			symbol: 'AAPL',
			ts: new Date(START + topIdx * STEP_MS).toISOString(),
			kind: 'reversal_top',
			side: 'sell',
			confidence: 0.41,
			entry: candles[topIdx].close,
			stop: candles[topIdx].high + 0.3,
			targets: [vwap[topIdx].value, 311.2],
			time_of_day_bucket: 'morning',
			attribution: {
				ranked_causes: [
					{ kind: 'climax_reversal', score: 0.52, source: 'rule', label: 'Volume climax rejecting the highs' },
					{ kind: 'value_area_edge', score: 0.3, source: 'rule', label: 'Rejection at prior Value Area High' },
					{ kind: 'volume_surge', score: 0.18, source: 'rule', label: 'Relative-volume surge' }
				],
				data_completeness: 0.5,
				uncertain: false,
				caveat:
					'Rule-based attribution from price/volume only (50%). Internals/options not available.',
				summary: 'Volume climax rejecting the highs (52%)'
			}
		},
		{
			signal_id: 'demo-bottom-1',
			symbol: 'AAPL',
			ts: new Date(START + bottomIdx * STEP_MS).toISOString(),
			kind: 'reversal_bottom',
			side: 'buy',
			confidence: 0.38,
			entry: candles[bottomIdx].close,
			stop: candles[bottomIdx].low - 0.3,
			targets: [vwap[bottomIdx].value, 313.5],
			time_of_day_bucket: 'lunch',
			attribution: {
				ranked_causes: [
					{ kind: 'climax_reversal', score: 0.48, source: 'rule', label: 'Selling climax off the lows' },
					{ kind: 'value_area_edge', score: 0.34, source: 'rule', label: 'Rejection at prior Value Area Low' },
					{ kind: 'poc_rejection', score: 0.18, source: 'rule', label: 'Test of prior Point of Control' }
				],
				data_completeness: 0.5,
				uncertain: false,
				caveat:
					'Rule-based attribution from price/volume only (50%). Internals/options not available.',
				summary: 'Selling climax off the lows (48%)'
			}
		}
	];

	return {
		candles,
		volume,
		vwap,
		signals,
		levels: { poc: 312.0, vah: 313.4, val: 310.6 }
	};
}
