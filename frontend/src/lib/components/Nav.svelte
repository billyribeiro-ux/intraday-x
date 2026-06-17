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
		gap: 0.35rem;
		padding: 0.7rem 0.55rem;
		border-right: 1px solid var(--border);
		background: var(--panel);
		width: 148px;
		flex: 0 0 148px;
	}
	.nav-link {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		min-height: 34px;
		padding: 0 0.65rem;
		border-radius: 6px;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.82rem;
		font-weight: 650;
		line-height: 1;
		border: 1px solid transparent;
		transition:
			background-color 0.12s ease,
			color 0.12s ease;
	}
	.nav-link:hover {
		color: var(--text);
		background: var(--surface);
	}
	.nav-link.active {
		color: var(--text);
		background: color-mix(in srgb, var(--accent) 12%, var(--surface));
		border-color: color-mix(in srgb, var(--accent) 35%, transparent);
	}
	.nav-link:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	@media (max-width: 720px) {
		nav {
			flex-direction: row;
			width: 100%;
			flex: 0 0 auto;
			overflow-x: hidden;
			border-right: none;
			border-bottom: 1px solid var(--border);
		}
		.nav-link {
			flex: 1 1 0;
			justify-content: center;
			min-width: 0;
		}
		.nav-link span {
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}
	}
</style>
