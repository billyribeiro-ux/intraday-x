<script lang="ts">
	import type { BacktestParams, Timeframe } from '$lib/api/backtest';
	import type { Scanner } from '$lib/api/types';
	import { PlayIcon, SpinnerIcon } from '$lib/icons';

	interface Props {
		/** Callback prop (runes idiom — NO createEventDispatcher). */
		onRun: (params: BacktestParams) => void;
		loading?: boolean;
	}

	let { onRun, loading = false }: Props = $props();

	const uid = $props.id();

	const timeframes: Timeframe[] = ['1m', '5m', '15m', '30m', '1h', '1d'];
	const scanners: { value: Scanner; label: string }[] = [
		{ value: 'reversal', label: 'Reversal' },
		{ value: 'scalping', label: 'Scalping' }
	];

	// Form state.
	let symbol = $state('AAPL');
	let timeframe = $state<Timeframe>('5m');
	let days = $state(60);
	let maxHold = $state(24);
	let scanner = $state<Scanner>('reversal');

	// A simple, honest client-side validity check (fail loud, no silent fallbacks).
	const symbolValid = $derived(/^[A-Za-z.\-]{1,8}$/.test(symbol.trim()));
	const daysValid = $derived(Number.isInteger(days) && days >= 1 && days <= 730);
	const maxHoldValid = $derived(Number.isInteger(maxHold) && maxHold >= 1 && maxHold <= 500);
	const canRun = $derived(symbolValid && daysValid && maxHoldValid && !loading);

	function submit(e: SubmitEvent) {
		e.preventDefault();
		if (!canRun) return;
		onRun({
			symbol: symbol.trim().toUpperCase(),
			timeframe,
			days,
			max_hold: maxHold,
			scanner
		});
	}
</script>

<form class="form" onsubmit={submit}>
	<div class="field">
		<label for="{uid}-symbol">Ticker</label>
		<input
			id="{uid}-symbol"
			class="mono"
			class:invalid={symbol.length > 0 && !symbolValid}
			type="text"
			autocomplete="off"
			spellcheck="false"
			maxlength="8"
			bind:value={symbol}
			placeholder="AAPL"
		/>
	</div>

	<div class="field">
		<label for="{uid}-timeframe">Timeframe</label>
		<select id="{uid}-timeframe" bind:value={timeframe}>
			{#each timeframes as tf (tf)}
				<option value={tf}>{tf}</option>
			{/each}
		</select>
	</div>

	<div class="field">
		<label for="{uid}-days">Lookback (days)</label>
		<input
			id="{uid}-days"
			class="num"
			class:invalid={!daysValid}
			type="number"
			min="1"
			max="730"
			step="1"
			bind:value={days}
		/>
	</div>

	<div class="field">
		<label for="{uid}-maxhold">Max hold (bars)</label>
		<input
			id="{uid}-maxhold"
			class="num"
			class:invalid={!maxHoldValid}
			type="number"
			min="1"
			max="500"
			step="1"
			bind:value={maxHold}
		/>
	</div>

	<div class="field">
		<label for="{uid}-scanner">Scanner</label>
		<select id="{uid}-scanner" bind:value={scanner}>
			{#each scanners as s (s.value)}
				<option value={s.value}>{s.label}</option>
			{/each}
		</select>
	</div>

	<button class="run" type="submit" disabled={!canRun}>
		{#if loading}
			<SpinnerIcon size={16} weight="bold" class="spin" />
			Running…
		{:else}
			<PlayIcon size={16} weight="fill" />
			Run backtest
		{/if}
	</button>
</form>

<style>
	.form {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: 0.75rem;
		padding: 1rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--panel);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	label {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	input,
	select {
		height: 36px;
		padding: 0 0.6rem;
		background: var(--bg);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 0.875rem;
		font-family: inherit;
	}
	input:focus,
	select:focus {
		outline: none;
		border-color: var(--accent);
	}
	input.invalid {
		border-color: #f85149;
	}
	input.mono {
		width: 7rem;
		text-transform: uppercase;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	}
	input.num {
		width: 8.5rem;
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	select {
		min-width: 7rem;
	}
	.run {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		height: 36px;
		padding: 0 1rem;
		margin-left: auto;
		background: var(--accent);
		color: #fff;
		border: none;
		border-radius: 6px;
		font-size: 0.875rem;
		font-weight: 600;
		cursor: pointer;
	}
	.run:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}
	.run :global(.spin) {
		animation: spin 0.8s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
