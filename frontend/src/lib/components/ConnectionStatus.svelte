<script lang="ts">
	import type { ConnState } from '$lib/realtime/signal-store.svelte';
	import { PlugsConnectedIcon, PlugsIcon } from '$lib/icons';

	interface Props {
		state: ConnState;
		source?: string | null;
	}

	let { state, source = null }: Props = $props();

	let label = $derived.by(() => {
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

	let connected = $derived(state === 'open' || state === 'demo');
</script>

<span class="status" class:connected class:down={!connected}>
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
		font-size: 0.8rem;
		padding: 0.25rem 0.6rem;
		border-radius: 999px;
		border: 1px solid #1b2230;
	}
	.connected {
		color: #3fb950;
	}
	.down {
		color: #d29922;
	}
</style>
