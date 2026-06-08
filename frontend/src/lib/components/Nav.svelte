<script lang="ts">
	// Top-level app navigation. Active-route detection uses `page` from
	// `$app/state` (SvelteKit 2.12+, runes-reactive) rather than the legacy
	// `$app/stores` subscription. `$derived` recomputes the active path on every
	// client navigation.
	import { page } from '$app/state';

	import { FlaskIcon, GaugeIcon, GearIcon } from '$lib/icons';

	type NavItem = {
		href: string;
		label: string;
		icon: typeof GaugeIcon;
	};

	const items: NavItem[] = [
		{ href: '/', label: 'Monitor', icon: GaugeIcon },
		{ href: '/backtest', label: 'Backtest', icon: FlaskIcon },
		{ href: '/settings', label: 'Settings', icon: GearIcon }
	];

	const current = $derived(page.url.pathname);

	function isActive(href: string): boolean {
		// Exact match for the Monitor root; prefix match for sub-routes so e.g.
		// /backtest/123 still highlights Backtest.
		return href === '/' ? current === '/' : current === href || current.startsWith(href + '/');
	}
</script>

<nav aria-label="Primary">
	{#each items as item (item.href)}
		{@const active = isActive(item.href)}
		<a href={item.href} class="nav-link" class:active aria-current={active ? 'page' : undefined}>
			<item.icon size={18} weight={active ? 'fill' : 'regular'} />
			<span>{item.label}</span>
		</a>
	{/each}
</nav>

<style>
	nav {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		padding: 0.75rem;
		border-right: 1px solid var(--border);
		background: var(--panel);
		min-width: 168px;
	}
	.nav-link {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.5rem 0.7rem;
		border-radius: 6px;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.875rem;
		font-weight: 500;
		line-height: 1;
		border: 1px solid transparent;
		transition:
			background-color 0.12s ease,
			color 0.12s ease;
	}
	.nav-link:hover {
		color: var(--text);
		background: color-mix(in srgb, var(--accent) 8%, transparent);
	}
	.nav-link.active {
		color: var(--text);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		border-color: color-mix(in srgb, var(--accent) 35%, transparent);
	}
	.nav-link:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
</style>
