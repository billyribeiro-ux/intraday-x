<script lang="ts">
	import { uiDirection, type Signal } from '$lib/api/types';
	import { TrendDownIcon, TrendUpIcon } from '$lib/icons';

	interface Props {
		signals: Signal[];
	}

	let { signals }: Props = $props();

	// Market date (ET) — US equities trade on America/New_York.
	function fmtDate(iso: string): string {
		return new Date(iso).toLocaleDateString('en-US', {
			timeZone: 'America/New_York',
			month: 'short',
			day: '2-digit'
		});
	}

	// EXACT clock time of the signal, in market time (ET) — not a coarse bucket.
	function fmtTime(iso: string): string {
		return new Date(iso).toLocaleTimeString('en-US', {
			timeZone: 'America/New_York',
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit',
			hour12: true
		});
	}

	function score(n: number | undefined | null): string {
		return n == null ? '—' : n.toFixed(2);
	}
</script>

<div class="table-wrap">
	<table>
		<thead>
			<tr>
				<th>Date</th>
				<th>Ticker</th>
				<th>Kind</th>
				<th>Side</th>
				<th class="num">Conf</th>
				<th class="num">Quality</th>
				<th class="num">ML</th>
				<th>Time (ET)</th>
				<th>Why</th>
			</tr>
		</thead>
		<tbody>
			{#if signals.length === 0}
				<tr class="empty"><td colspan="9">No signals yet.</td></tr>
			{:else}
				{#each signals as s (s.signal_id)}
					{@const dir = uiDirection(s.side)}
					<tr>
						<td class="mono">{fmtDate(s.ts)}</td>
						<td class="mono">{s.symbol}</td>
						<td>{s.kind.replace('reversal_', '').replace('scalp_', '')}</td>
						<td class="side {dir}">
							{#if dir === 'buy'}
								<TrendUpIcon size={15} weight="bold" />
							{:else}
								<TrendDownIcon size={15} weight="bold" />
							{/if}
							{s.side}
						</td>
						<td class="num">{s.confidence.toFixed(2)}</td>
						<td class="num">{score(s.quality_score)}</td>
						<td class="num">{score(s.meta_score)}</td>
						<td class="mono">{fmtTime(s.ts)}</td>
						<td class="why">{s.attribution.summary}</td>
					</tr>
				{/each}
			{/if}
		</tbody>
	</table>
</div>

<style>
	.table-wrap {
		contain: layout paint;
		height: 100%;
		overflow: auto;
	}
	table {
		width: 100%;
		min-width: 760px;
		border-collapse: collapse;
		font-size: 0.78rem;
	}
	thead th {
		position: sticky;
		top: 0;
		background: var(--panel);
		color: var(--muted);
		text-align: left;
		font-weight: 700;
		padding: 0.5rem 0.65rem;
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
		z-index: 1;
	}
	tbody td {
		height: 36px;
		padding: 0 0.65rem;
		border-bottom: 1px solid var(--border);
		color: var(--text);
		white-space: nowrap;
	}
	tbody tr:hover td {
		background: color-mix(in srgb, var(--accent) 6%, transparent);
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.mono {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	}
	.side {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		text-transform: capitalize;
	}
	.side.buy {
		color: var(--buy);
	}
	.side.sell {
		color: var(--sell);
	}
	.why {
		color: var(--muted);
		max-width: 18rem;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.empty td {
		text-align: center;
		color: var(--muted);
		font-style: italic;
	}
</style>
