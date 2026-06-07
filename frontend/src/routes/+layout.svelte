<script lang="ts">
	import favicon from '$lib/assets/favicon.svg';

	import '../app.css';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<div class="app">
	<header class="topbar">
		<span class="brand">intraday-<span class="x">x</span></span>
		<span class="tag">self-learning intraday scanner</span>
	</header>
	<main>
		{@render children()}
	</main>
</div>

<style>
	.topbar {
		display: flex;
		align-items: baseline;
		gap: 0.75rem;
		padding: 0.75rem 1.25rem;
		border-bottom: 1px solid var(--border);
		background: var(--panel);
	}
	.brand {
		font-weight: 700;
		font-size: 1.05rem;
		letter-spacing: -0.01em;
	}
	.brand .x {
		color: var(--accent);
	}
	.tag {
		color: var(--muted);
		font-size: 0.8rem;
	}
	main {
		padding: 1.25rem;
		max-width: 1100px;
		margin: 0 auto;
	}
</style>
