<script lang="ts">
	import { uiDirection, type Signal } from '$lib/api/types';
	import { TrendDownIcon, TrendUpIcon } from '$lib/icons';

	interface Props {
		signals: Signal[];
	}

	let { signals }: Props = $props();

	function fmtTime(iso: string): string {
		return new Date(iso).toLocaleString(undefined, {
			month: 'short',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		});
	}
</script>

<div class="table-wrap">
	<table>
		<thead>
			<tr>
				<th>Time</th>
				<th>Ticker</th>
				<th>Kind</th>
				<th>Side</th>
				<th class="num">Conf</th>
				<th>Time-of-day</th>
				<th>Why</th>
			</tr>
		</thead>
		<tbody>
			{#if signals.length === 0}
				<tr class="empty"><td colspan="7">No signals yet.</td></tr>
			{:else}
				{#each signals as s (s.signal_id)}
					{@const dir = uiDirection(s.side)}
					<tr>
						<td class="mono">{fmtTime(s.ts)}</td>
						<td class="mono">{s.symbol}</td>
						<td>{s.kind.replace('reversal_', '')}</td>
						<td class="side {dir}">
							{#if dir === 'buy'}
								<TrendUpIcon size={15} weight="bold" />
							{:else}
								<TrendDownIcon size={15} weight="bold" />
							{/if}
							{s.side}
						</td>
						<td class="num">{s.confidence.toFixed(2)}</td>
						<td>{s.time_of_day_bucket}</td>
						<td class="why">{s.attribution.summary}</td>
					</tr>
				{/each}
			{/if}
		</tbody>
	</table>
</div>

<style>
	.table-wrap {
		/* contain layout so appending rows can't reflow neighbouring panes */
		contain: layout paint;
		border: 1px solid #1b2230;
		border-radius: 8px;
		overflow: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
	}
	thead th {
		position: sticky;
		top: 0;
		background: #11161f;
		color: #8b949e;
		text-align: left;
		font-weight: 600;
		padding: 0.5rem 0.75rem;
		border-bottom: 1px solid #1b2230;
		white-space: nowrap;
	}
	tbody td {
		height: 40px; /* fixed row height => zero CLS on append */
		padding: 0 0.75rem;
		border-bottom: 1px solid #161c27;
		color: #c9d1d9;
		white-space: nowrap;
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
		color: #3fb950;
	}
	.side.sell {
		color: #f85149;
	}
	.why {
		color: #8b949e;
		max-width: 22rem;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.empty td {
		text-align: center;
		color: #6e7681;
		font-style: italic;
	}
</style>
