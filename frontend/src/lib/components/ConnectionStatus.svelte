<script lang="ts">
	import type { ConnState } from '$lib/realtime/signal-store.svelte';
	import { PlugsConnectedIcon, PlugsIcon } from '$lib/icons';

	interface Props {
		state: ConnState;
		source?: string | null;
		configured?: boolean | null;
		detail?: string | null;
	}

	let { state, source = null, configured = null, detail = null }: Props = $props();

	let label = $derived.by(() => {
		if (state === 'open' && configured === false) return 'FMP key needed';
		switch (state) {
			case 'open':
				return source ? `Live · ${source}` : 'Live';
			case 'demo':
				return 'Demo data';
			case 'connecting':
				return 'Connecting…';
			case 'reconnecting':
				return 'Reconnecting…';
			case 'closed':
				return 'Disconnected';
		}
	});

	let connected = $derived((state === 'open' && configured !== false) || state === 'demo');
	let title = $derived(configured === false && detail ? detail : label);
</script>

<span class="status" class:connected class:down={!connected} {title}>
	{#if connected}
		<PlugsConnectedIcon size={15} weight="bold" />
	{:else}
		<PlugsIcon size={15} weight="bold" />
	{/if}
	{label}
</span>

<style>
	.status {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		height: 28px;
		padding: 0 0.6rem;
		border-radius: 6px;
		border: 1px solid var(--border);
		background: var(--surface);
		font-size: 0.76rem;
		font-weight: 650;
		white-space: nowrap;
	}
	.connected {
		color: var(--buy);
	}
	.down {
		color: var(--warn);
	}
</style>
