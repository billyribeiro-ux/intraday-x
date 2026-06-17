<script lang="ts">
	// Watched-symbols editor → PUT { watched_symbols }. The text input accepts a
	// comma/space-separated list; on save we normalize to an upper-cased,
	// de-duplicated array. The parent owns the canonical list ($bindable) and is
	// reconciled with the server's echoed value after a successful save.
	import { ListBulletsIcon } from '$lib/icons';
	import { putSettings } from '$lib/api/settings';

	let { symbols = $bindable() }: { symbols: string[] } = $props();

	// Draft text seeded from the current list. We intentionally do NOT bind this
	// to `symbols` reactively — the user edits freely and commits on Save.
	let draft = $state(symbols.join(', '));
	let saving = $state(false);
	let notice = $state<{ kind: 'ok' | 'error'; text: string } | null>(null);

	function parse(input: string): string[] {
		const seen = new Set<string>();
		const out: string[] = [];
		for (const raw of input.split(/[\s,]+/)) {
			const sym = raw.trim().toUpperCase();
			if (sym && !seen.has(sym)) {
				seen.add(sym);
				out.push(sym);
			}
		}
		return out;
	}

	const parsed = $derived(parse(draft));

	async function save() {
		saving = true;
		notice = null;
		try {
			const settings = await putSettings({ watched_symbols: parsed });
			symbols = settings.watched_symbols;
			draft = symbols.join(', ');
			notice = { kind: 'ok', text: `Saved ${symbols.length} symbol${symbols.length === 1 ? '' : 's'}.` };
		} catch (e) {
			notice = { kind: 'error', text: e instanceof Error ? e.message : 'Failed to save symbols.' };
		} finally {
			saving = false;
		}
	}
</script>

<div class="editor">
	<div class="field">
		<ListBulletsIcon size={15} class="field-icon" />
		<input
			type="text"
			placeholder="AAPL, MSFT, NVDA…"
			autocomplete="off"
			spellcheck="false"
			disabled={saving}
			bind:value={draft}
			onkeydown={(e) => {
				if (e.key === 'Enter') save();
			}}
		/>
	</div>
	<button type="button" class="btn primary" disabled={saving} onclick={save}>Save</button>
</div>

{#if parsed.length}
	<div class="chips" aria-label="Parsed symbols">
		{#each parsed as sym (sym)}
			<span class="chip">{sym}</span>
		{/each}
	</div>
{:else}
	<p class="empty">No symbols — the scanner will have nothing to watch.</p>
{/if}

{#if notice}
	<p class="msg" class:error={notice.kind === 'error'} role="status">{notice.text}</p>
{/if}

<style>
	.editor {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.field {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		flex: 1;
		padding: 0 0.6rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--bg);
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
		padding: 0.55rem 0;
		outline: none;
		min-width: 0;
		text-transform: uppercase;
	}
	.field input::placeholder {
		color: var(--muted);
		text-transform: none;
	}
	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0.55rem 0.85rem;
		border-radius: 6px;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		border: 1px solid var(--accent);
		background: var(--accent);
		color: var(--accent-contrast);
		transition: background-color 0.12s ease;
	}
	.btn:hover:not(:disabled) {
		background: color-mix(in srgb, var(--accent) 85%, #000);
	}
	.btn:disabled {
		opacity: 0.6;
		cursor: progress;
	}
	.btn:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin-top: 0.75rem;
	}
	.chip {
		padding: 0.2rem 0.55rem;
		border-radius: 6px;
		border: 1px solid var(--border);
		background: var(--bg);
		color: var(--text);
		font-size: 0.78rem;
		font-weight: 600;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	}
	.empty {
		margin: 0.75rem 0 0;
		color: var(--muted);
		font-size: 0.8rem;
	}
	.msg {
		margin: 0.6rem 0 0;
		font-size: 0.8rem;
		color: var(--buy);
	}
	.msg.error {
		color: var(--sell);
	}
</style>
