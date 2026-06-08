import { getBars, scan } from '$lib/api/client';

import type { PageLoad } from './$types';

// Realtime dashboard → render client-side only (no SSR; the live WS is browser-only).
export const ssr = false;

const SYMBOL = 'AAPL';
const TIMEFRAME = '5m';
const DAYS = 7;

export const load: PageLoad = async ({ fetch }) => {
	const [bars, scanResult] = await Promise.all([
		getBars(fetch, SYMBOL, TIMEFRAME, DAYS),
		scan(fetch, SYMBOL, TIMEFRAME, DAYS)
	]);
	return { symbol: SYMBOL, timeframe: TIMEFRAME, bars, scan: scanResult };
};
