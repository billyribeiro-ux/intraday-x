<script lang="ts">
	import { onMount } from 'svelte';

	import favicon from '$lib/assets/favicon.svg';

	import Nav from '$lib/components/Nav.svelte';
	import UpdateBanner from '$lib/components/UpdateBanner.svelte';
	import { DesktopIcon, MoonIcon, SunIcon } from '$lib/icons';
	import { theme } from '$lib/stores/theme.svelte';

	import '../app.css';

	let { children } = $props();

	// Apply the persisted theme and subscribe to OS changes once, on mount.
	// One-time browser setup — onMount, not $effect (no state to synchronize).
	// The matchMedia listener lives for the app-wide singleton's lifetime.
	onMount(() => {
		theme.init();
	});

	const toggleLabel = $derived(
		theme.mode === 'dark'
			? 'Theme: dark (click for light)'
			: theme.mode === 'light'
				? 'Theme: light (click for system)'
				: 'Theme: system (click for dark)'
	);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<UpdateBanner />

<div class="app">
	<header class="topbar">
		<span class="brand">intraday-<span class="x">x</span></span>
		<span class="tag">self-learning intraday scanner</span>
		<button
			type="button"
			class="theme-toggle"
			onclick={() => theme.cycle()}
			title={toggleLabel}
			aria-label={toggleLabel}
		>
			{#if theme.mode === 'system'}
				<DesktopIcon size={18} />
			{:else if theme.resolved === 'dark'}
				<MoonIcon size={18} weight="fill" />
			{:else}
				<SunIcon size={18} weight="fill" />
			{/if}
		</button>
	</header>
	<div class="body">
		<Nav />
		<main>
			{@render children()}
		</main>
	</div>
</div>

<style>
	.app {
		display: flex;
		flex-direction: column;
		height: 100vh;
	}
	.topbar {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		min-height: 52px;
		padding: 0.6rem 0.85rem 0.6rem 1rem;
		border-bottom: 1px solid var(--border);
		background: var(--panel);
		box-shadow: 0 1px 0 color-mix(in srgb, #fff 4%, transparent) inset;
	}
	.brand {
		font-weight: 700;
		font-size: 1.05rem;
		letter-spacing: 0;
		align-self: baseline;
	}
	.brand .x {
		color: var(--accent);
	}
	.tag {
		color: var(--muted);
		font-size: 0.8rem;
		align-self: baseline;
	}
	.theme-toggle {
		margin-left: auto;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 34px;
		height: 34px;
		border-radius: 6px;
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--text);
		cursor: pointer;
		transition:
			background-color 0.12s ease,
			border-color 0.12s ease;
	}
	.theme-toggle:hover {
		border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
		background: color-mix(in srgb, var(--accent) 8%, transparent);
	}
	.theme-toggle:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.body {
		display: flex;
		flex: 1;
		min-height: 0;
		background: var(--bg);
	}
	main {
		flex: 1;
		min-width: 0;
		min-height: 0;
		display: flex;
		flex-direction: column;
		overflow-y: auto;
		background: var(--bg);
	}
	@media (max-width: 720px) {
		.topbar {
			padding-left: 0.75rem;
		}
		.tag {
			display: none;
		}
		.body {
			flex-direction: column;
		}
	}
</style>
