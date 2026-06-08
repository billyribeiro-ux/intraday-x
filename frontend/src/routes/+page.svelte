<script lang="ts">
	import type {
		CandlestickData,
		HistogramData,
		LineData,
		SeriesMarker,
		UTCTimestamp
	} from 'lightweight-charts';

	import type { Signal } from '$lib/api/types';
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

	// Merge live (newest) + historical, deduped by signal_id.
	const signals = $derived.by(() => {
		const seen = new Set<string>();
		const out: Signal[] = [];
		for (const s of [...store.signals, ...data.scan.signals]) {
			if (!seen.has(s.signal_id)) {
				seen.add(s.signal_id);
				out.push(s);
			}
		}
		return out;
	});

	// API returns Lightweight-Charts-ready shapes (epoch-second time); cast at the
	// boundary. Derived so a navigation to another symbol re-renders the chart.
	const candles = $derived(data.bars.candles as unknown as CandlestickData<UTCTimestamp>[]);
	const volume = $derived(data.bars.volume as unknown as HistogramData<UTCTimestamp>[]);
	const vwap = $derived(data.bars.vwap as unknown as LineData<UTCTimestamp>[]);
	const markers = $derived(
		data.bars.markers.map((m) => ({
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

	<PriceChart {candles} {volume} {vwap} {markers} levels={data.bars.levels} />

	<h2>Signals ({signals.length})</h2>
	<SignalTable {signals} />

	{#if signals.length > 0}
		<p class="caveat">{signals[0].attribution.caveat}</p>
	{/if}
</section>

<style>
	.monitor {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.monitor-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	h2 {
		font-size: 0.9rem;
		color: var(--muted);
		margin: 0.25rem 0 0;
		font-weight: 600;
	}
	.caveat {
		color: #6e7681;
		font-size: 0.78rem;
		font-style: italic;
		margin: 0;
	}
</style>
