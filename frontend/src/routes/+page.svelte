<script lang="ts">
	import { onMount } from 'svelte';

	import { getBars, scan } from '$lib/api/client';
	import { getSettings } from '$lib/api/settings';
	import type { BarsPayload, CatalystEvent, ScanPayload, Scanner, Signal } from '$lib/api/types';
	import PriceChart from '$lib/chart/PriceChart.svelte';
	import { timeframeToSeconds } from '$lib/chart/time';
	import ConnectionStatus from '$lib/components/ConnectionStatus.svelte';
	import SignalTable from '$lib/components/SignalTable.svelte';
	import { ArrowsClockwiseIcon } from '$lib/icons';
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
		{ label: '7D', days: 7 },
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
		const seen: string[] = [];
		const out: Signal[] = [];
		for (const s of [...signalStore.signals, ...(scanResult?.signals ?? [])]) {
			if (s.symbol === loaded.symbol && !seen.includes(s.signal_id)) {
				seen.push(s.signal_id);
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
	const studies = $derived(bars?.studies ?? []);
	const markers = $derived(bars?.markers ?? []);
	const move = $derived(bars?.move_explanation ?? null);
	const catalysts = $derived(bars?.catalysts ?? []);

	const lastClose = $derived(candles.at(-1)?.close ?? null);
	const completeness = $derived(bars?.data_completeness ?? null);

	function fmtPrice(value: number | null): string {
		if (value === null) return '--';
		const precision = value < 1 ? 4 : value < 10 ? 3 : 2;
		return value.toLocaleString(undefined, {
			minimumFractionDigits: precision,
			maximumFractionDigits: precision
		});
	}

	function fmtPct(value: number | null): string {
		return value === null ? '--' : `${Math.round(value * 100)}%`;
	}

	function fmtCatalystTime(value: string): string {
		const ts = new Date(value);
		if (Number.isNaN(ts.getTime())) return '';
		return ts.toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		});
	}

	function catalystKindLabel(kind: string): string {
		return kind.replaceAll('_', ' ');
	}

	function catalystKey(catalyst: CatalystEvent): string {
		return `${catalyst.kind}-${catalyst.ts}-${catalyst.title}`;
	}

	function fmpLabel(): string {
		switch (fmpStore.status) {
			case 'open':
				return 'FMP live';
			case 'connecting':
				return 'FMP connecting';
			case 'error':
				return fmpStore.error ?? 'FMP offline';
			default:
				return 'FMP idle';
		}
	}
</script>

<section class="monitor">
	<div class="monitor-head">
		<div class="instrument">
			<span class="kicker">Monitor</span>
			<div class="instrument-row">
				<h1>{loaded.symbol}</h1>
				<span class="price">{fmtPrice(lastClose)}</span>
				<span class="chip">{loaded.timeframe}</span>
				<span class="chip">Data {fmtPct(completeness)}</span>
			</div>
		</div>
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
			<select
				class="asset-class"
				bind:value={assetClass}
				aria-label="Asset class"
				title="FMP live feed asset class"
			>
				{#each assetClasses as ac (ac.value)}
					<option value={ac.value}>{ac.label}</option>
				{/each}
			</select>
			<button type="submit" disabled={loadState === 'loading'}>
				<ArrowsClockwiseIcon size={15} weight="bold" />
				Load
			</button>
		</form>
		<div class="status-group">
			{#if fmpStore.status === 'connecting'}
				<span class="live-dot connecting" title={fmpLabel()}></span>
			{:else if fmpStore.status === 'open'}
				<span class="live-dot" title={fmpLabel()}></span>
			{:else if fmpStore.status === 'error'}
				<span class="live-dot error" title={fmpLabel()}></span>
			{/if}
			<ConnectionStatus
				state={signalStore.status}
				source={signalStore.serverStatus?.source}
				configured={signalStore.serverStatus?.configured}
				detail={signalStore.serverStatus?.detail}
			/>
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
		<div class="workbench">
			<div class="chart-area">
				<PriceChart
					{candles}
					{volume}
					{vwap}
					{studies}
					{markers}
					levels={bars.levels}
					symbol={loaded.symbol}
					timeframe={loaded.timeframe}
					dataCompleteness={bars.data_completeness}
				/>
			</div>

			<aside class="signals-area">
				<div class="signals-head">
					<div>
						<h2>{scanner} signals</h2>
						<p>{signals.length} live + historical matches</p>
					</div>
					<span class="count">{signals.length}</span>
				</div>
				{#if move}
					<div class="state-panel">
						<div class="state-row">
							<span class="state-kicker">Market state</span>
							<span class="state-confidence">{fmtPct(move.confidence)}</span>
						</div>
						<div class="state-title">
							<span class="state-direction {move.direction}">{move.direction}</span>
							<span>{move.regime}</span>
						</div>
						<p>{move.summary}</p>
						<div class="drivers">
							{#each move.drivers.slice(0, 3) as driver (driver.kind)}
								<span title={driver.label}>{driver.label} · {fmtPct(driver.score)}</span>
							{/each}
						</div>
						{#if catalysts.length > 0}
							<div class="catalysts">
								<div class="state-row">
									<span class="state-kicker">FMP catalysts</span>
								</div>
								{#each catalysts.slice(0, 3) as catalyst (catalystKey(catalyst))}
									{@const meta = `${catalystKindLabel(catalyst.kind)} · ${fmtPct(catalyst.score)} · ${fmtCatalystTime(catalyst.ts)}`}
									{#if catalyst.url}
										<a class="catalyst-row" href={catalyst.url} target="_blank" rel="noreferrer">
											<span>{meta}</span>
											<strong>{catalyst.title}</strong>
										</a>
									{:else}
										<div class="catalyst-row">
											<span>{meta}</span>
											<strong>{catalyst.title}</strong>
										</div>
									{/if}
								{/each}
							</div>
						{/if}
					</div>
				{/if}
				<div class="signals-scroll">
					<SignalTable {signals} />
				</div>
				{#if signals.length > 0}
					<p class="caveat">{signals[0].attribution.caveat}</p>
				{/if}
			</aside>
		</div>
	{/if}
</section>

<style>
	.monitor {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		gap: 0.75rem;
		padding: 0.85rem;
	}
	.monitor-head {
		display: grid;
		grid-template-columns: minmax(230px, auto) minmax(0, 1fr) auto;
		align-items: center;
		gap: 0.75rem;
		padding: 0.7rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--panel);
	}
	.instrument {
		min-width: 0;
	}
	.kicker {
		display: block;
		margin-bottom: 0.2rem;
		color: var(--muted);
		font-size: 0.68rem;
		font-weight: 700;
		text-transform: uppercase;
	}
	.instrument-row {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		min-width: 0;
	}
	h1 {
		font-size: 1.35rem;
		font-weight: 760;
		line-height: 1;
	}
	.price {
		color: var(--text);
		font-size: 1rem;
		font-weight: 650;
		font-variant-numeric: tabular-nums;
	}
	.chip,
	.count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 24px;
		padding: 0 0.5rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface);
		color: var(--muted);
		font-size: 0.72rem;
		font-weight: 650;
		white-space: nowrap;
	}
	.picker {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.45rem;
		min-width: 0;
		flex-wrap: wrap;
	}
	.picker input,
	.picker select {
		height: 34px;
		padding: 0 0.55rem;
		background: var(--surface);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 0.82rem;
		font-family: inherit;
	}
	.picker input:hover,
	.picker select:hover {
		border-color: var(--border-strong);
	}
	.picker input:focus,
	.picker select:focus {
		outline: none;
		border-color: var(--accent);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent);
	}
	.picker .ticker {
		width: 6.5rem;
		text-transform: uppercase;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-weight: 700;
	}
	.picker button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.35rem;
		height: 34px;
		padding: 0 0.8rem;
		background: var(--accent);
		color: var(--accent-contrast);
		border: none;
		border-radius: 6px;
		font-size: 0.82rem;
		font-weight: 750;
		cursor: pointer;
	}
	.picker button:hover:not(:disabled) {
		filter: brightness(1.07);
	}
	.picker button:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}
	.status-group {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 0.55rem;
		min-width: max-content;
	}
	.live-dot {
		width: 9px;
		height: 9px;
		border-radius: 50%;
		background: var(--buy);
		box-shadow: 0 0 8px color-mix(in srgb, var(--buy) 75%, transparent);
	}
	.live-dot.connecting {
		background: var(--warn);
		box-shadow: 0 0 8px color-mix(in srgb, var(--warn) 75%, transparent);
		animation: pulse 1s ease-in-out infinite;
	}
	.live-dot.error {
		background: var(--sell);
		box-shadow: 0 0 8px color-mix(in srgb, var(--sell) 75%, transparent);
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
	.workbench {
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(330px, 28vw);
		gap: 0.75rem;
	}
	.chart-area {
		min-width: 0;
		min-height: 0;
	}
	.signals-area {
		min-width: 0;
		min-height: 0;
		display: grid;
		grid-template-rows: auto auto minmax(0, 1fr) auto;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--panel);
		overflow: hidden;
	}
	.signals-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		padding: 0.8rem 0.9rem;
		border-bottom: 1px solid var(--border);
	}
	h2 {
		font-size: 0.9rem;
		color: var(--text);
		margin: 0;
		font-weight: 700;
		text-transform: capitalize;
	}
	.signals-head p {
		margin: 0.18rem 0 0;
		color: var(--muted);
		font-size: 0.75rem;
	}
	.count {
		min-width: 34px;
		color: var(--text);
		font-variant-numeric: tabular-nums;
	}
	.state-panel {
		padding: 0.75rem 0.85rem;
		border-bottom: 1px solid var(--border);
		background: color-mix(in srgb, var(--surface) 42%, transparent);
	}
	.state-row,
	.state-title,
	.drivers {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		min-width: 0;
	}
	.state-row {
		justify-content: space-between;
	}
	.state-kicker,
	.state-confidence {
		color: var(--muted);
		font-size: 0.68rem;
		font-weight: 700;
		text-transform: uppercase;
	}
	.state-title {
		margin-top: 0.35rem;
		font-size: 0.92rem;
		font-weight: 760;
		text-transform: capitalize;
	}
	.state-direction {
		color: var(--muted);
	}
	.state-direction.up {
		color: var(--buy);
	}
	.state-direction.down {
		color: var(--sell);
	}
	.state-panel p {
		margin: 0.35rem 0 0;
		color: var(--muted);
		font-size: 0.75rem;
		line-height: 1.35;
	}
	.drivers {
		flex-wrap: wrap;
		margin-top: 0.55rem;
	}
	.drivers span {
		max-width: 100%;
		padding: 0.2rem 0.4rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface);
		color: var(--text);
		font-size: 0.68rem;
		font-weight: 650;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.catalysts {
		display: grid;
		gap: 0.45rem;
		margin-top: 0.7rem;
		padding-top: 0.65rem;
		border-top: 1px solid var(--border);
	}
	.catalyst-row {
		display: grid;
		gap: 0.18rem;
		min-width: 0;
		color: inherit;
		text-decoration: none;
	}
	.catalyst-row:hover strong {
		color: var(--accent);
	}
	.catalyst-row span {
		color: var(--muted);
		font-size: 0.65rem;
		font-weight: 700;
		text-transform: capitalize;
	}
	.catalyst-row strong {
		color: var(--text);
		font-size: 0.73rem;
		font-weight: 650;
		line-height: 1.3;
		overflow: hidden;
		display: -webkit-box;
		line-clamp: 2;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
	}
	.signals-scroll {
		min-height: 0;
		overflow: auto;
	}
	.caveat {
		padding: 0.65rem 0.85rem;
		border-top: 1px solid var(--border);
		color: var(--muted);
		font-size: 0.75rem;
		line-height: 1.35;
		margin: 0;
	}
	.placeholder {
		min-height: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--panel);
		color: var(--text);
		text-align: center;
	}
	.placeholder.error {
		color: var(--sell);
	}
	.placeholder .hint {
		align-self: center;
		color: var(--muted);
		font-size: 0.82rem;
		line-height: 1.4;
		margin: 0;
		max-width: 100%;
		min-width: 0;
		overflow-wrap: anywhere;
		white-space: normal;
		width: min(78ch, calc(100vw - 3rem));
		word-break: break-word;
	}
	.placeholder button {
		margin-top: 0.5rem;
		padding: 0.45rem 1rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface);
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
	@media (max-width: 1180px) {
		.monitor-head {
			grid-template-columns: 1fr;
			align-items: stretch;
		}
		.picker {
			justify-content: flex-start;
		}
		.status-group {
			justify-content: flex-start;
		}
	}
	@media (max-width: 980px) {
		.monitor {
			overflow: auto;
		}
		.workbench {
			grid-template-columns: 1fr;
			grid-template-rows: minmax(520px, 68vh) minmax(320px, 44vh);
		}
	}
	@media (max-width: 640px) {
		.monitor {
			padding: 0.6rem;
		}
		.monitor-head {
			padding: 0.6rem;
		}
		.instrument-row {
			flex-wrap: wrap;
		}
		.picker {
			display: grid;
			grid-template-columns: repeat(2, minmax(0, 1fr));
			gap: 0.45rem;
		}
		.picker .ticker,
		.picker input,
		.picker select,
		.picker button {
			min-width: 0;
			width: 100%;
		}
		.picker button {
			grid-column: 1 / -1;
			padding: 0 0.45rem;
		}
		.picker .asset-class {
			grid-column: 1 / -1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.spinner,
		.live-dot.connecting {
			animation: none;
		}
	}
</style>
