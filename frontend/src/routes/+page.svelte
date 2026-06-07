<script lang="ts">
	import type { SeriesMarker, UTCTimestamp } from 'lightweight-charts';

	import { uiDirection } from '$lib/api/types';
	import { toChartTime } from '$lib/chart/time';
	import PriceChart from '$lib/chart/PriceChart.svelte';
	import ConnectionStatus from '$lib/components/ConnectionStatus.svelte';
	import SignalTable from '$lib/components/SignalTable.svelte';
	import { SignalStore } from '$lib/realtime/signal-store.svelte';
	import { makeSampleData } from '$lib/sample';

	// Phase 0 demo: seed the store with sample signals. In Phase 5 this becomes
	// store.connect(PUBLIC_WS_URL) and bars/levels come from the REST API.
	const data = makeSampleData();
	const store = new SignalStore(data.signals);

	const markers: SeriesMarker<UTCTimestamp>[] = data.signals
		.map((s): SeriesMarker<UTCTimestamp> => {
			const buy = uiDirection(s.side) === 'buy';
			return {
				time: toChartTime(s.ts),
				position: buy ? 'belowBar' : 'aboveBar',
				shape: buy ? 'arrowUp' : 'arrowDown',
				color: buy ? '#3fb950' : '#f85149',
				text: s.kind.replace('reversal_', '')
			};
		})
		.sort((a, b) => (a.time as number) - (b.time as number));
</script>

<section class="monitor">
	<div class="monitor-head">
		<h1>AAPL · reversal scanner</h1>
		<ConnectionStatus state={store.status} source={store.serverStatus?.source} />
	</div>

	<PriceChart
		candles={data.candles}
		volume={data.volume}
		vwap={data.vwap}
		{markers}
		levels={data.levels}
	/>

	<h2>Signals</h2>
	<SignalTable signals={store.signals} />

	{#if store.signals.length > 0}
		<p class="caveat">{store.signals[0].attribution.caveat}</p>
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
