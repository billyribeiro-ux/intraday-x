<script lang="ts">
	// Theme segmented control. Drives the global theme store for an INSTANT
	// visual change (theme.setTheme mutates <html data-theme> synchronously) and
	// persists the choice to the backend (PUT { theme }). The store is the source
	// of truth for what's applied; the backend is durable cross-session storage.
	import { DesktopIcon, MoonIcon, SunIcon } from '$lib/icons';
	import { putSettings, type Theme } from '$lib/api/settings';
	import { theme } from '$lib/stores/theme.svelte';

	type Option = { value: Theme; label: string };
	const options: Option[] = [
		{ value: 'dark', label: 'Dark' },
		{ value: 'light', label: 'Light' },
		{ value: 'system', label: 'System' }
	];

	// Reflect the live store preference so the control stays in sync with the
	// topbar toggle without holding a second copy of the state.
	let saving = $state(false);
	let error = $state<string | null>(null);

	async function select(value: Theme) {
		if (value === theme.mode) return;
		// Apply instantly via the store; revert on a failed persist.
		const previous = theme.mode;
		theme.setTheme(value);
		saving = true;
		error = null;
		try {
			await putSettings({ theme: value });
		} catch (e) {
			theme.setTheme(previous);
			error = e instanceof Error ? e.message : 'Failed to save theme.';
		} finally {
			saving = false;
		}
	}
</script>

<div class="segmented" role="group" aria-label="Theme">
	{#each options as opt (opt.value)}
		<button
			type="button"
			class="seg"
			class:active={theme.mode === opt.value}
			aria-pressed={theme.mode === opt.value}
			disabled={saving}
			onclick={() => select(opt.value)}
		>
			{#if opt.value === 'dark'}
				<MoonIcon size={16} weight="fill" />
			{:else if opt.value === 'light'}
				<SunIcon size={16} weight="fill" />
			{:else}
				<DesktopIcon size={16} />
			{/if}
			<span>{opt.label}</span>
		</button>
	{/each}
</div>

{#if error}
	<p class="error" role="alert">{error}</p>
{/if}

<style>
	.segmented {
		display: inline-flex;
		gap: 0.25rem;
		padding: 0.25rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--bg);
	}
	.seg {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.4rem 0.8rem;
		border: 1px solid transparent;
		border-radius: 6px;
		background: transparent;
		color: var(--muted);
		font-size: 0.85rem;
		font-weight: 500;
		cursor: pointer;
		transition:
			background-color 0.12s ease,
			color 0.12s ease,
			border-color 0.12s ease;
	}
	.seg:hover:not(:disabled):not(.active) {
		color: var(--text);
		background: color-mix(in srgb, var(--accent) 8%, transparent);
	}
	.seg.active {
		color: var(--text);
		background: color-mix(in srgb, var(--accent) 15%, transparent);
		border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
	}
	.seg:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.seg:disabled {
		cursor: progress;
		opacity: 0.7;
	}
	.error {
		margin: 0.5rem 0 0;
		color: #f85149;
		font-size: 0.8rem;
	}
</style>
