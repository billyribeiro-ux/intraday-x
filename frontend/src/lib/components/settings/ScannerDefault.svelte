<script lang="ts">
	// Default-scanner selector → PUT { default_scanner }. The parent owns the
	// canonical value and passes it as a $bindable so a successful save (and the
	// server's echoed value) keep parent and child in sync without a second copy.
	import { putSettings, type ScannerDefault } from '$lib/api/settings';

	let { value = $bindable() }: { value: ScannerDefault } = $props();

	type Option = { value: ScannerDefault; label: string; blurb: string };
	const options: Option[] = [
		{ value: 'reversal', label: 'Reversal', blurb: 'Mean-reversion at extended levels' },
		{ value: 'scalping', label: 'Scalping', blurb: 'Fast momentum entries, tight stops' }
	];

	let saving = $state(false);
	let error = $state<string | null>(null);

	async function select(next: ScannerDefault) {
		if (next === value) return;
		const previous = value;
		value = next; // optimistic
		saving = true;
		error = null;
		try {
			const settings = await putSettings({ default_scanner: next });
			value = settings.default_scanner; // reconcile with server truth
		} catch (e) {
			value = previous;
			error = e instanceof Error ? e.message : 'Failed to save scanner.';
		} finally {
			saving = false;
		}
	}
</script>

<div class="cards" role="group" aria-label="Default scanner">
	{#each options as opt (opt.value)}
		<button
			type="button"
			class="card"
			class:active={value === opt.value}
			aria-pressed={value === opt.value}
			disabled={saving}
			onclick={() => select(opt.value)}
		>
			<span class="label">{opt.label}</span>
			<span class="blurb">{opt.blurb}</span>
		</button>
	{/each}
</div>

{#if error}
	<p class="error" role="alert">{error}</p>
{/if}

<style>
	.cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
		gap: 0.75rem;
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		text-align: left;
		padding: 0.85rem 1rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--bg);
		cursor: pointer;
		transition:
			background-color 0.12s ease,
			border-color 0.12s ease;
	}
	.card:hover:not(:disabled):not(.active) {
		border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
	}
	.card.active {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 12%, transparent);
	}
	.card:disabled {
		opacity: 0.7;
		cursor: progress;
	}
	.card:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.label {
		font-weight: 600;
		color: var(--text);
		font-size: 0.95rem;
	}
	.blurb {
		color: var(--muted);
		font-size: 0.8rem;
	}
	.error {
		margin: 0.5rem 0 0;
		color: #f85149;
		font-size: 0.8rem;
	}
</style>
