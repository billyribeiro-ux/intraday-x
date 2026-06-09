<script lang="ts">
	import { onMount } from 'svelte';

	import type {
		CandlestickData,
		HistogramData,
		LineData,
		SeriesMarker,
		UTCTimestamp
	} from 'lightweight-charts';

	import { getBars, scan } from '$lib/api/client';
	import type { BarsPayload, ScanPayload, Signal } from '$lib/api/types';
	import PriceChart from '$lib/chart/PriceChart.svelte';
	import ConnectionStatus from '$lib/components/ConnectionStatus.svelte';
	import SignalTable from '$lib/components/SignalTable.svelte';
	import { SignalStore } from '$lib/realtime/signal-store.svelte';

	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	// Live signals come from the websocket; the historical scan is the baseline.
	const store = new SignalStore();

	$effect(() => {
		store.connect();
		return () => store.destroy();
	});

	// The initial bars + scan are fetched HERE (not in load()) so first paint is
	// instant with a "starting engine" state — the engine's one-time cold start
	// no longer freezes the whole page.
	type LoadState = 'loading' | 'ready' | 'error';
	let loadState = $state<LoadState>('loading');
	let loadError = $state<string | null>(null);
	let bars = $state<BarsPayload | null>(null);
	let scanResult = $state<ScanPayload | null>(null);

	async function loadData() {
		loadState = 'loading';
		loadError = null;
		try {
			const [b, s] = await Promise.all([
				getBars(fetch, data.symbol, data.timeframe, data.days),
				scan(fetch, data.symbol, data.timeframe, data.days)
			]);
			bars = b;
			scanResult = s;
			loadState = 'ready';
		} catch (e) {
			loadError = e instanceof Error ? e.message : 'failed to reach the engine';
			loadState = 'error';
		}
	}

	onMount(loadData);

	// Merge live (newest) + historical, deduped by signal_id.
	const signals = $derived.by(() => {
		const seen = new Set<string>();
		const out: Signal[] = [];
		for (const s of [...store.signals, ...(scanResult?.signals ?? [])]) {
			if (!seen.has(s.signal_id)) {
				seen.add(s.signal_id);
				out.push(s);
			}
		}
		return out;
	});

	// API returns Lightweight-Charts-ready shapes (epoch-second time); cast at the
	// boundary. Empty until the data loads.
	const candles = $derived((bars?.candles ?? []) as unknown as CandlestickData<UTCTimestamp>[]);
	const volume = $derived((bars?.volume ?? []) as unknown as HistogramData<UTCTimestamp>[]);
	const vwap = $derived((bars?.vwap ?? []) as unknown as LineData<UTCTimestamp>[]);
	const markers = $derived(
		(bars?.markers ?? []).map((m) => ({
			time: m.time as UTCTimestamp,
			position: m.position,
			shape: m.shape,
			color: m.color,
			text: m.text
		})) as SeriesMarker<UTCTimestamp>[]
	);
</script>

<section class="monitor">
	<div class="monitor-head">
		<h1>{data.symbol} · {data.timeframe} · reversal scanner</h1>
		<ConnectionStatus state={store.status} source={store.serverStatus?.source} />
	</div>

	{#if loadState === 'loading'}
		<div class="placeholder">
			<p class="spinner" aria-hidden="true"></p>
			<p>Starting the engine &amp; loading {data.symbol}…</p>
			<p class="hint">The first launch can take a few seconds while the engine warms up.</p>
		</div>
	{:else if loadState === 'error'}
		<div class="placeholder error">
			<p>Couldn't reach the engine.</p>
			<p class="hint">{loadError}</p>
			<button onclick={loadData}>Retry</button>
		</div>
	{:else if bars}
		<div class="chart-area">
			<PriceChart {candles} {volume} {vwap} {markers} levels={bars.levels} />
		</div>

		<div class="signals-area">
			<h2>Signals ({signals.length})</h2>
			<div class="signals-scroll">
				<SignalTable {signals} />
			</div>
			{#if signals.length > 0}
				<p class="caveat">{signals[0].attribution.caveat}</p>
			{/if}
		</div>
	{/if}
</section>

<style>
	.monitor {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 1rem 1.25rem;
	}
	.monitor-head {
		flex: 0 0 auto;
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	/* Chart grows to fill most of the window; the signals panel scrolls below it. */
	.chart-area {
		flex: 1 1 58%;
		min-height: 260px;
	}
	.signals-area {
		flex: 1 1 42%;
		min-height: 150px;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.signals-scroll {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		border: 1px solid var(--border);
		border-radius: 8px;
	}
	h2 {
		flex: 0 0 auto;
		font-size: 0.9rem;
		color: var(--muted);
		margin: 0.25rem 0 0;
		font-weight: 600;
	}
	.caveat {
		flex: 0 0 auto;
		color: #6e7681;
		font-size: 0.78rem;
		font-style: italic;
		margin: 0;
	}
	/* Fills the whole content area (centered) while loading / on error. */
	.placeholder {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		border: 1px solid var(--border);
		border-radius: 10px;
		background: var(--panel);
		color: var(--text);
		text-align: center;
	}
	.placeholder.error {
		color: #f85149;
	}
	.placeholder .hint {
		color: var(--muted);
		font-size: 0.82rem;
		margin: 0;
	}
	.placeholder button {
		margin-top: 0.5rem;
		padding: 0.4rem 1rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: transparent;
		color: var(--text);
		cursor: pointer;
	}
	.placeholder button:hover {
		border-color: var(--accent);
	}
	.spinner {
		width: 22px;
		height: 22px;
		margin: 0;
		border: 2px solid var(--border);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation: none;
		}
	}
</style>
