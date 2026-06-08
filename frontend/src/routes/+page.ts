import type { PageLoad } from './$types';

// Realtime dashboard → render client-side only (no SSR; the live WS is browser-only).
export const ssr = false;

// Only the view params here — the actual bars/scan fetch happens IN the component
// (+page.svelte) so the page can paint a "starting engine" state instead of
// blocking first render on the engine's one-time cold start.
export const load: PageLoad = async () => {
	return { symbol: 'AAPL', timeframe: '5m', days: 7 };
};
