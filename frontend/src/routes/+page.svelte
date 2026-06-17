<script lang="ts">
	import { onMount } from 'svelte';

	import { getBars, scan } from '$lib/api/client';
	import { getSettings } from '$lib/api/settings';
	import type { BarsPayload, ScanPayload, Scanner, Signal } from '$lib/api/types';
	import PriceChart from '$lib/chart/PriceChart.svelte';
	import { timeframeToSeconds } from '$lib/chart/time';
	import ConnectionStatus from '$lib/components/ConnectionStatus.svelte';
	import SignalTable from '$lib/components/SignalTable.svelte';
	import { FmpLiveStore, type FmpAssetClass } from '$lib/realtime/fmp-live.svelte';
	import { SignalStore } from '$lib/realtime/signal-store.svelte';

	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	// svelte-ignore state_referenced_locally
	const initialSymbol = data.symbol ?? 'AAPL';
	// svelte-ignore state_referenced_locally
	const initialTimeframe = data.timeframe ?? '5m';
	// svelte-ignore state_referenced_locally
	const initialDays = data.days ?? 7;

	const timeframes = [
		'1m',
		'2m',
		'3m',
		'4m',
		'5m',
		'10m',
		'15m',
		'30m',
		'1h',
		'2h',
		'4h',
		'1d',
		'1w',
		'1mo',
		'3mo',
		'1y'
	];

	const ranges: { label: string; days: number }[] = [
		{ label: '1D', days: 1 },
		{ label: '5D', days: 5 },
		{ label: '1M', days: 30 },
		{ label: '3M', days: 90 },
		{ label: '6M', days: 180 },
		{ label: '1Y', days: 365 },
		{ label: '2Y', days: 730 },
		{ label: '3Y', days: 1095 },
		{ label: '5Y', days: 1825 },
		{ label: 'MAX', days: 36500 }
	];

	const scanners: { value: Scanner; label: string }[] = [
		{ value: 'reversal', label: 'Reversal' },
		{ value: 'scalping', label: 'Scalping' }
	];

	const assetClasses: { label: string; value: FmpAssetClass }[] = [
		{ label: 'Stock', value: 'stock' },
		{ label: 'Crypto', value: 'crypto' },
		{ label: 'Forex', value: 'forex' }
	];

	// Form state seeded from the loader.
	let symbol = $state(initialSymbol);
	let timeframe = $state(initialTimeframe);
	let range = $state(initialDays);
	let scanner = $state<Scanner>('reversal');
	let assetClass = $state<FmpAssetClass>('stock');
	// What the currently-shown data is actually FOR (set after a successful load).
	let loaded = $state({ symbol: initialSymbol, timeframe: initialTimeframe });

	const signalStore = new SignalStore();
	$effect(() => {
		signalStore.connect();
		return () => signalStore.destroy();
	});

	const fmpStore = new FmpLiveStore();
	$effect(() => {
		if (loaded.symbol && loaded.timeframe) {
			void fmpStore.connect(loaded.symbol, assetClass);
		}
		return () => fmpStore.disconnect();
	});

	type LoadState = 'loading' | 'ready' | 'error';
	let loadState = $state<LoadState>('loading');
	let loadError = $state<string | null>(null);
	let bars = $state<BarsPayload | null>(null);
	let scanResult = $state<ScanPayload | null>(null);

	async function initFromSettings() {
		try {
			const settings = await getSettings();
			if (settings.default_scanner === 'reversal' || settings.default_scanner === 'scalping') {
				scanner = settings.default_scanner;
			}
		} catch {
			// ignore; default reversal is fine
		}
	}

	async function loadData() {
		const sym = symbol.trim().toUpperCase();
		if (!/^[A-Za-z.\-/]{1,12}$/.test(sym)) {
			loadError = 'Enter a valid ticker (e.g. SPY).';
			loadState = 'error';
			return;
		}
		symbol = sym;
		loadState = 'loading';
		loadError = null;
		try {
			const [b, s] = await Promise.all([
				getBars(fetch, sym, timeframe, range),
				scan(fetch, sym, timeframe, range, scanner)
			]);
			bars = b;
			scanResult = s;
			loaded = { symbol: sym, timeframe };
			loadState = 'ready';
		} catch (e) {
			loadError = e instanceof Error ? e.message : 'failed to reach the engine';
			loadState = 'error';
		}
	}

	function onSubmit(e: SubmitEvent) {
		e.preventDefault();
		void loadData();
	}

	onMount(() => {
		void initFromSettings();
		void loadData();
	});

	// Merge live (newest) + historical for the LOADED symbol, deduped by id.
	const signals = $derived.by(() => {
		const seen = new Set<string>();
		const out: Signal[] = [];
		for (const s of [...signalStore.signals, ...(scanResult?.signals ?? [])]) {
			if (s.symbol === loaded.symbol && !seen.has(s.signal_id)) {
				seen.add(s.signal_id);
				out.push(s);
			}
		}
		return out;
	});

	// Live candles: apply the latest FMP tick to the current bar only.
	// We do not synthesize new bars because we have no live volume/VWAP for them.
	const liveCandles = $derived.by(() => {
		const base = bars?.candles ?? [];
		if (!base.length || !fmpStore.lastTick) return base;
		const tickTsSeconds = Math.floor(fmpStore.lastTick.ts / 1000);
		const interval = timeframeToSeconds(loaded.timeframe);
		const currentBarStart = Math.floor(base[base.length - 1].time / interval) * interval;
		const tickBarStart = Math.floor(tickTsSeconds / interval) * interval;
		if (tickBarStart !== currentBarStart) return base;
		const copy = base.slice();
		const last = { ...copy[copy.length - 1] };
		last.close = fmpStore.lastTick.price;
		last.high = Math.max(last.high, fmpStore.lastTick.price);
		last.low = Math.min(last.low, fmpStore.lastTick.price);
		copy[copy.length - 1] = last;
		return copy;
	});

	const candles = $derived(liveCandles);
	const volume = $derived(bars?.volume ?? []);
	const vwap = $derived(bars?.vwap ?? []);
	const markers = $derived(bars?.markers ?? []);
</script>

<section class="monitor">
	<div class="monitor-head">
		<form class="picker" onsubmit={onSubmit}>
			<input
				class="ticker"
				type="text"
				autocomplete="off"
				spellcheck="false"
				maxlength="12"
				bind:value={symbol}
				placeholder="Ticker"
				aria-label="Ticker"
			/>
			<select bind:value={timeframe} aria-label="Timeframe">
				{#each timeframes as tf (tf)}
					<option value={tf}>{tf}</option>
				{/each}
			</select>
			<select bind:value={range} aria-label="Range">
				{#each ranges as r (r.days)}
					<option value={r.days}>{r.label}</option>
				{/each}
			</select>
			<select bind:value={scanner} aria-label="Scanner">
				{#each scanners as s (s.value)}
					<option value={s.value}>{s.label}</option>
				{/each}
			</select>
			<select bind:value={assetClass} aria-label="Asset class" title="FMP live feed asset class">
				{#each assetClasses as ac (ac.value)}
					<option value={ac.value}>{ac.label}</option>
				{/each}
			</select>
			<button type="submit" disabled={loadState === 'loading'}>Load</button>
		</form>
		<div class="status-group">
			{#if fmpStore.status === 'connecting'}
				<span class="live-dot connecting" title="FMP live feed connecting…"></span>
			{:else if fmpStore.status === 'open'}
				<span class="live-dot" title="FMP live feed connected"></span>
			{:else if fmpStore.status === 'error'}
				<span class="live-dot error" title="FMP live feed: {fmpStore.error ?? 'disconnected'}"></span>
			{/if}
			<ConnectionStatus state={signalStore.status} source={signalStore.serverStatus?.source} />
		</div>
	</div>

	{#if loadState === 'loading'}
		<div class="placeholder">
			<p class="spinner" aria-hidden="true"></p>
			<p>Loading {symbol} · {timeframe}…</p>
			<p class="hint">The first launch can take a few seconds while the engine warms up.</p>
		</div>
	{:else if loadState === 'error'}
		<div class="placeholder error">
			<p>Couldn't load {symbol}.</p>
			<p class="hint">{loadError}</p>
			<button onclick={() => loadData()}>Retry</button>
		</div>
	{:else if bars}
		<div class="chart-area">
			<PriceChart {candles} {volume} {vwap} {markers} levels={bars.levels} />
		</div>

		<div class="signals-area">
			<h2>{loaded.symbol} · {loaded.timeframe} · {scanner} signals ({signals.length})</h2>
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
		gap: 1rem;
	}
	.picker {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.picker input,
	.picker select {
		height: 32px;
		padding: 0 0.55rem;
		background: var(--bg);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 0.875rem;
		font-family: inherit;
	}
	.picker input:focus,
	.picker select:focus {
		outline: none;
		border-color: var(--accent);
	}
	.picker .ticker {
		width: 6.5rem;
		text-transform: uppercase;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	}
	.picker button {
		height: 32px;
		padding: 0 0.9rem;
		background: var(--accent);
		color: #fff;
		border: none;
		border-radius: 6px;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
	}
	.picker button:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}
	.status-group {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.live-dot {
		width: 9px;
		height: 9px;
		border-radius: 50%;
		background: #3fb950;
		box-shadow: 0 0 6px #3fb950;
	}
	.live-dot.connecting {
		background: #e3b341;
		box-shadow: 0 0 6px #e3b341;
		animation: pulse 1s ease-in-out infinite;
	}
	.live-dot.error {
		background: #f85149;
		box-shadow: 0 0 6px #f85149;
	}
	@keyframes pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.4;
		}
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
