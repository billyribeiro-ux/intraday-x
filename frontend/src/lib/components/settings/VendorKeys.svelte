<script lang="ts">
	// API-key management for FREE, NON-BROKER market-data vendors (Twelve Data,
	// Polygon, yfinance). Keys are WRITE-ONLY: the server never returns a value,
	// so this component only ever shows a configured/not-set badge — it never
	// renders a key. After a successful set/clear we re-fetch settings so the
	// badge reflects server truth, then notify the parent via `onChanged`.
	import {
		CheckCircleIcon,
		CircleIcon,
		EyeIcon,
		EyeSlashIcon,
		KeyIcon,
		TrashIcon
	} from '$lib/icons';
	import { clearVendorKey, getSettings, setVendorKey, type Vendor } from '$lib/api/settings';

	let { vendors, onChanged }: { vendors: Vendor[]; onChanged: (vendors: Vendor[]) => void } =
		$props();

	// A vendor whose key the backend reads from no env var needs no key at all.
	function needsKey(v: Vendor): boolean {
		return v.env_var !== null;
	}

	// Per-vendor draft input + reveal toggle, keyed by vendor name. Kept in a
	// plain object of $state so each row's input is independent.
	let drafts = $state<Record<string, string>>({});
	let revealed = $state<Record<string, boolean>>({});
	let busy = $state<string | null>(null);
	let notice = $state<{ vendor: string; kind: 'ok' | 'error'; text: string } | null>(null);

	async function refresh() {
		const settings = await getSettings();
		onChanged(settings.vendors);
	}

	async function save(vendor: string) {
		const key = (drafts[vendor] ?? '').trim();
		if (!key) {
			notice = { vendor, kind: 'error', text: 'Enter a key first.' };
			return;
		}
		busy = vendor;
		notice = null;
		try {
			await setVendorKey(vendor, key);
			drafts[vendor] = '';
			revealed[vendor] = false;
			await refresh();
			notice = { vendor, kind: 'ok', text: 'Key saved.' };
		} catch (e) {
			notice = {
				vendor,
				kind: 'error',
				text: e instanceof Error ? e.message : 'Failed to save key.'
			};
		} finally {
			busy = null;
		}
	}

	async function clear(vendor: string) {
		busy = vendor;
		notice = null;
		try {
			await clearVendorKey(vendor);
			drafts[vendor] = '';
			await refresh();
			notice = { vendor, kind: 'ok', text: 'Key removed.' };
		} catch (e) {
			notice = {
				vendor,
				kind: 'error',
				text: e instanceof Error ? e.message : 'Failed to remove key.'
			};
		} finally {
			busy = null;
		}
	}
</script>

<p class="lede">
	Free, non-broker market-data vendors. Add an API key to enable a vendor; keys are stored on the
	backend and never shown again.
</p>

<ul class="vendors">
	{#each vendors as vendor (vendor.name)}
		{@const name = vendor.name}
		<li class="vendor">
			<div class="row">
				<div class="ident">
					<span class="name">{vendor.name}</span>
					{#if !needsKey(vendor)}
						<span class="badge neutral">no key needed</span>
					{:else if vendor.configured}
						<span class="badge ok">
							<CheckCircleIcon size={14} weight="fill" />
							configured
						</span>
					{:else}
						<span class="badge off">
							<CircleIcon size={14} />
							not set
						</span>
					{/if}
				</div>
				{#if vendor.env_var}
					<code class="env">{vendor.env_var}</code>
				{/if}
			</div>

			{#if needsKey(vendor)}
				<div class="controls">
					<div class="field">
						<KeyIcon size={15} class="field-icon" />
						<input
							type={revealed[name] ? 'text' : 'password'}
							placeholder={vendor.configured ? 'Replace key…' : 'Paste API key…'}
							autocomplete="off"
							spellcheck="false"
							disabled={busy === name}
							bind:value={drafts[name]}
							onkeydown={(e) => {
								if (e.key === 'Enter') save(name);
							}}
						/>
						<button
							type="button"
							class="reveal"
							aria-label={revealed[name] ? 'Hide key' : 'Show key'}
							onclick={() => (revealed[name] = !revealed[name])}
						>
							{#if revealed[name]}
								<EyeSlashIcon size={16} />
							{:else}
								<EyeIcon size={16} />
							{/if}
						</button>
					</div>
					<button
						type="button"
						class="btn primary"
						disabled={busy === name}
						onclick={() => save(name)}
					>
						{vendor.configured ? 'Replace' : 'Save'}
					</button>
					{#if vendor.configured}
						<button
							type="button"
							class="btn ghost"
							disabled={busy === name}
							aria-label="Clear {name} key"
							onclick={() => clear(name)}
						>
							<TrashIcon size={16} />
						</button>
					{/if}
				</div>
			{/if}

			{#if notice && notice.vendor === name}
				<p class="msg" class:error={notice.kind === 'error'} role="status">{notice.text}</p>
			{/if}
		</li>
	{/each}
</ul>

<style>
	.lede {
		margin: 0 0 1rem;
		color: var(--muted);
		font-size: 0.85rem;
		line-height: 1.4;
	}
	.vendors {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.vendor {
		padding: 0.85rem 1rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--bg);
	}
	.row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}
	.ident {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.name {
		font-weight: 600;
		color: var(--text);
		font-size: 0.95rem;
	}
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		padding: 0.15rem 0.5rem;
		border-radius: 999px;
		font-size: 0.72rem;
		font-weight: 600;
		border: 1px solid var(--border);
	}
	.badge.ok {
		color: #3fb950;
		border-color: color-mix(in srgb, #3fb950 40%, var(--border));
		background: color-mix(in srgb, #3fb950 12%, transparent);
	}
	.badge.off {
		color: var(--muted);
	}
	.badge.neutral {
		color: var(--accent);
		border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	.env {
		font-size: 0.72rem;
		color: var(--muted);
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	}
	.controls {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-top: 0.75rem;
	}
	.field {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		flex: 1;
		padding: 0 0.6rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--panel);
	}
	.field:focus-within {
		border-color: color-mix(in srgb, var(--accent) 55%, var(--border));
	}
	.field :global(.field-icon) {
		color: var(--muted);
		flex-shrink: 0;
	}
	.field input {
		flex: 1;
		border: none;
		background: transparent;
		color: var(--text);
		font-size: 0.85rem;
		padding: 0.5rem 0;
		outline: none;
		min-width: 0;
	}
	.field input::placeholder {
		color: var(--muted);
	}
	.reveal {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: none;
		background: transparent;
		color: var(--muted);
		cursor: pointer;
		padding: 0.2rem;
	}
	.reveal:hover {
		color: var(--text);
	}
	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.35rem;
		padding: 0.5rem 0.85rem;
		border-radius: 6px;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		border: 1px solid var(--border);
		transition:
			background-color 0.12s ease,
			border-color 0.12s ease,
			color 0.12s ease;
	}
	.btn:disabled {
		opacity: 0.6;
		cursor: progress;
	}
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: #fff;
	}
	.btn.primary:hover:not(:disabled) {
		background: color-mix(in srgb, var(--accent) 85%, #000);
	}
	.btn.ghost {
		background: transparent;
		color: var(--muted);
	}
	.btn.ghost:hover:not(:disabled) {
		color: #f85149;
		border-color: color-mix(in srgb, #f85149 45%, var(--border));
	}
	.btn:focus-visible,
	.reveal:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.msg {
		margin: 0.6rem 0 0;
		font-size: 0.8rem;
		color: #3fb950;
	}
	.msg.error {
		color: #f85149;
	}
</style>
