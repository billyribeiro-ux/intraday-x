<script lang="ts">
	// Settings screen. Loads the full settings object once on mount, then composes
	// the section components. Loading and error states use fixed-height skeletons
	// so the layout doesn't shift when data arrives (no CLS). After load, the
	// page holds the canonical settings in $state; child sections receive
	// $bindable slices (scanner, symbols) or an onChanged callback (vendors) so
	// their saves keep this page in sync with the server.
	import { onMount } from 'svelte';

	import {
		ArrowClockwiseIcon,
		ChartLineIcon,
		DownloadIcon,
		GearIcon,
		KeyIcon,
		ListBulletsIcon,
		SunIcon
	} from '$lib/icons';
	import { getSettings, type Settings, type Vendor } from '$lib/api/settings';
	import { updater } from '$lib/updates/updater.svelte';
	import ScannerDefault from '$lib/components/settings/ScannerDefault.svelte';
	import ThemeSelector from '$lib/components/settings/ThemeSelector.svelte';
	import VendorKeys from '$lib/components/settings/VendorKeys.svelte';
	import WatchedSymbols from '$lib/components/settings/WatchedSymbols.svelte';

	let settings = $state<Settings | null>(null);
	let error = $state<string | null>(null);

	// App version: only meaningful inside the bundled Tauri app. In the browser
	// (or `tauri dev` without a bundle) we leave it null and show a dash.
	let appVersion = $state<string | null>(null);

	function inTauri(): boolean {
		return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
	}

	// Friendly status line derived from the updater state machine. 'checking'
	// and 'idle' are covered inline below; this maps the resting outcomes.
	const updateStatusLine = $derived.by(() => {
		switch (updater.status) {
			case 'checking':
				return 'Checking for updates…';
			case 'uptodate':
				return "You're on the latest version.";
			case 'available':
				return `Update available — v${updater.version}. See the banner at the top to install.`;
			case 'downloading':
				return 'Downloading update…';
			case 'ready':
				return 'Update installed — restarting…';
			case 'unsupported':
				return 'Updates are only available in the desktop app.';
			case 'unconfigured':
				return "Updates aren't configured for this build.";
			case 'error':
				return updater.error ?? 'Update check failed.';
			default:
				return '';
		}
	});

	onMount(async () => {
		// Load the bundled app version (guarded for non-Tauri). Don't let a
		// version-read failure block the rest of the settings load.
		if (inTauri()) {
			try {
				const { getVersion } = await import('@tauri-apps/api/app');
				appVersion = await getVersion();
			} catch {
				appVersion = null;
			}
		}

		try {
			settings = await getSettings();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load settings.';
		}
	});

	async function reload() {
		error = null;
		settings = null;
		try {
			settings = await getSettings();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load settings.';
		}
	}

	// Replace just the vendors slice when a key is added/removed downstream.
	function onVendorsChanged(vendors: Vendor[]) {
		if (settings) settings.vendors = vendors;
	}
</script>

<section class="page">
	<header class="page-head">
		<GearIcon size={22} weight="fill" />
		<div>
			<h1>Settings</h1>
			<p class="sub">Appearance, data vendors, and scanner defaults.</p>
		</div>
	</header>

	{#if error}
		<div class="state error" role="alert">
			<p>{error}</p>
			<button type="button" class="retry" onclick={reload}>Retry</button>
		</div>
	{:else if !settings}
		<!-- Fixed-height skeletons matching the loaded layout — no CLS on arrival. -->
		<div class="skeletons" aria-hidden="true">
			<div class="sk-card"></div>
			<div class="sk-card tall"></div>
			<div class="sk-card"></div>
			<div class="sk-card"></div>
		</div>
	{:else}
		<div class="sections">
			<section class="card">
				<div class="card-head">
					<SunIcon size={18} weight="fill" />
					<div>
						<h2>Appearance</h2>
						<p class="desc">Theme applies instantly and is saved for next time.</p>
					</div>
				</div>
				<ThemeSelector />
			</section>

			<section class="card">
				<div class="card-head">
					<KeyIcon size={18} weight="fill" />
					<div>
						<h2>Data vendors</h2>
						<p class="desc">Free, non-broker market-data sources.</p>
					</div>
				</div>
				<VendorKeys vendors={settings.vendors} onChanged={onVendorsChanged} />
			</section>

			<section class="card">
				<div class="card-head">
					<ChartLineIcon size={18} weight="fill" />
					<div>
						<h2>Default scanner</h2>
						<p class="desc">Which strategy new scans start with.</p>
					</div>
				</div>
				<ScannerDefault bind:value={settings.default_scanner} />
			</section>

			<section class="card">
				<div class="card-head">
					<ListBulletsIcon size={18} weight="fill" />
					<div>
						<h2>Watched symbols</h2>
						<p class="desc">Comma or space separated; saved upper-cased.</p>
					</div>
				</div>
				<WatchedSymbols bind:symbols={settings.watched_symbols} />
			</section>

			<section class="card">
				<div class="card-head">
					<DownloadIcon size={18} weight="fill" />
					<div>
						<h2>Software update</h2>
						<p class="desc">Check for and install new desktop releases.</p>
					</div>
				</div>
				<div class="update">
					<dl class="version">
						<dt>Current version</dt>
						<dd>{appVersion ?? '—'}</dd>
					</dl>
					<div class="update-action">
						<button
							type="button"
							class="check"
							disabled={updater.status === 'checking' ||
								updater.status === 'downloading'}
							onclick={() => updater.check()}
						>
							<ArrowClockwiseIcon
								size={15}
								weight="bold"
								class={updater.status === 'checking' ? 'spin' : ''}
							/>
							Check for updates
						</button>
						{#if updateStatusLine}
							<p
								class="update-status"
								class:is-error={updater.status === 'error'}
								role={updater.status === 'error' ? 'alert' : 'status'}
							>
								{updateStatusLine}
							</p>
						{/if}
					</div>
				</div>
			</section>
		</div>
	{/if}
</section>

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}
	.page-head {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		color: var(--accent);
	}
	.page-head h1 {
		color: var(--text);
	}
	.sub {
		margin: 0.15rem 0 0;
		color: var(--muted);
		font-size: 0.85rem;
	}
	.sections {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}
	.card {
		padding: 1.25rem;
		border: 1px solid var(--border);
		border-radius: 10px;
		background: var(--panel);
	}
	.card-head {
		display: flex;
		align-items: flex-start;
		gap: 0.6rem;
		margin-bottom: 1rem;
		color: var(--accent);
	}
	.card-head h2 {
		margin: 0;
		font-size: 0.95rem;
		font-weight: 600;
		color: var(--text);
	}
	.desc {
		margin: 0.15rem 0 0;
		color: var(--muted);
		font-size: 0.8rem;
	}
	/* Skeletons mirror the real card stack so first paint == loaded layout. */
	.skeletons {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}
	.sk-card {
		height: 132px;
		border: 1px solid var(--border);
		border-radius: 10px;
		background: linear-gradient(
			90deg,
			var(--panel) 0%,
			color-mix(in srgb, var(--accent) 6%, var(--panel)) 50%,
			var(--panel) 100%
		);
		background-size: 200% 100%;
		animation: shimmer 1.4s ease-in-out infinite;
	}
	.sk-card.tall {
		height: 280px;
	}
	@keyframes shimmer {
		0% {
			background-position: 200% 0;
		}
		100% {
			background-position: -200% 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.sk-card {
			animation: none;
		}
	}
	.update {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
	}
	.version {
		margin: 0;
	}
	.version dt {
		color: var(--muted);
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.version dd {
		margin: 0.15rem 0 0;
		color: var(--text);
		font-size: 1rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.update-action {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 0.4rem;
	}
	.check {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.45rem 0.9rem;
		border-radius: 6px;
		border: 1px solid var(--border);
		background: var(--bg);
		color: var(--text);
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		transition: border-color 0.12s ease;
	}
	.check:hover:not(:disabled) {
		border-color: var(--accent);
	}
	.check:disabled {
		opacity: 0.7;
		cursor: progress;
	}
	.check:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.check :global(.spin) {
		animation: spin 0.9s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.check :global(.spin) {
			animation: none;
		}
	}
	.update-status {
		margin: 0;
		color: var(--muted);
		font-size: 0.8rem;
		text-align: right;
	}
	.update-status.is-error {
		color: #f85149;
	}
	.state.error {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 1rem 1.25rem;
		border: 1px solid color-mix(in srgb, #f85149 45%, var(--border));
		border-radius: 10px;
		background: color-mix(in srgb, #f85149 10%, var(--panel));
	}
	.state.error p {
		margin: 0;
		color: #f85149;
		font-size: 0.85rem;
	}
	.retry {
		padding: 0.45rem 0.9rem;
		border-radius: 6px;
		border: 1px solid var(--border);
		background: var(--bg);
		color: var(--text);
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
	}
	.retry:hover {
		border-color: var(--accent);
	}
	.retry:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
</style>
