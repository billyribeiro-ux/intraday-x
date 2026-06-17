<script lang="ts">
	import {
		formatUsd,
		runBacktest,
		type BacktestParams,
		type BacktestResponse,
		type BacktestTrade
	} from '$lib/api/backtest';
	import BacktestForm from '$lib/components/backtest/BacktestForm.svelte';
	import EquityCurve from '$lib/components/backtest/EquityCurve.svelte';
	import MetricsPanel from '$lib/components/backtest/MetricsPanel.svelte';
	import {
		DownloadSimpleIcon,
		FilePdfIcon,
		FlaskIcon,
		WarningIcon,
		XCircleIcon
	} from '$lib/icons';

	let loading = $state(false);
	let error = $state<string | null>(null);
	let result = $state<BacktestResponse | null>(null);
	// Remembered for filenames + the results header (survives a failed re-run).
	let lastParams = $state<BacktestParams | null>(null);

	async function handleRun(params: BacktestParams) {
		loading = true;
		error = null;
		lastParams = params;
		try {
			result = await runBacktest(fetch, params);
		} catch (e) {
			// Surface, never swallow.
			error = e instanceof Error ? e.message : 'Backtest failed.';
			result = null;
		} finally {
			loading = false;
		}
	}

	// --- Exports ---------------------------------------------------------------
	// CSV: built client-side from the trades (below). PDF: the native print dialog
	// (window.print → "Save as PDF") — no backend/reportlab dependency, works in
	// the bundled webview.

	function csvCell(v: string | number): string {
		const s = String(v);
		return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
	}

	function tradesToCsv(trades: BacktestTrade[]): string {
		const header = [
			'signal_id',
			'kind',
			'side',
			'entry_ts',
			'exit_ts',
			'entry',
			'exit',
			'shares',
			'pnl_usd',
			'exit_reason',
			'tod_bucket'
		];
		const rows = trades.map((t) =>
			[
				t.signal_id,
				t.kind,
				t.is_long ? 'long' : 'short',
				t.entry_ts,
				t.exit_ts,
				t.entry,
				t.exit,
				t.shares,
				(t.pnl_cents / 100).toFixed(2),
				t.exit_reason,
				t.tod_bucket
			]
				.map(csvCell)
				.join(',')
		);
		return [header.join(','), ...rows].join('\n');
	}

	function exportCsv() {
		if (!result) return;
		const csv = tradesToCsv(result.trades);
		const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `backtest_${result.symbol}_${result.timeframe}_trades.csv`;
		document.body.appendChild(a);
		a.click();
		a.remove();
		URL.revokeObjectURL(url);
	}

	// Attribution summary derived from the trades (exit-reason breakdown).
	const exitBreakdown = $derived.by(() => {
		if (!result) return [] as { reason: string; n: number; pnl_cents: number }[];
		const map = new Map<string, { reason: string; n: number; pnl_cents: number }>();
		for (const t of result.trades) {
			const cur = map.get(t.exit_reason) ?? { reason: t.exit_reason, n: 0, pnl_cents: 0 };
			cur.n += 1;
			cur.pnl_cents += t.pnl_cents;
			map.set(t.exit_reason, cur);
		}
		return [...map.values()].sort((a, b) => b.n - a.n);
	});
</script>

<section class="studio">
	<div class="head">
		<FlaskIcon size={20} weight="fill" />
		<h1>Backtest Studio</h1>
	</div>

	<BacktestForm onRun={handleRun} {loading} />

	{#if error}
		<div class="banner" role="alert">
			<XCircleIcon size={18} weight="fill" />
			<span>{error}</span>
			<button class="dismiss" type="button" onclick={() => (error = null)} aria-label="Dismiss">
				×
			</button>
		</div>
	{/if}

	{#if loading}
		<!-- Fixed-height skeleton => no layout shift when results land. -->
		<div class="skeleton" aria-busy="true" aria-label="Running backtest">
			<div class="sk-cards">
				{#each Array(6) as _, i (i)}
					<div class="sk-card"></div>
				{/each}
			</div>
			<div class="sk-chart"></div>
			<div class="sk-table"></div>
		</div>
	{:else if result}
		<div class="results">
			<div class="results-head">
				<h2>
					{result.symbol} · {result.timeframe}
					{#if lastParams}· {lastParams.days}d · max hold {lastParams.max_hold}{/if}
				</h2>
				<div class="actions">
					<button class="ghost" type="button" onclick={exportCsv} disabled={result.trades.length === 0}>
						<DownloadSimpleIcon size={15} weight="bold" />
						Export CSV
					</button>
					<button
						class="ghost"
						type="button"
						onclick={() => window.print()}
						title="Open the print dialog → Save as PDF"
					>
						<FilePdfIcon size={15} weight="bold" />
						Export PDF
					</button>
				</div>
			</div>

			<MetricsPanel metrics={result.metrics} nSignals={result.n_signals} />

			<EquityCurve curve={result.equity_curve} />

			<div class="attr">
				<div class="label">Exit attribution</div>
				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>Exit reason</th>
								<th class="num">Trades</th>
								<th class="num">Total P&amp;L</th>
							</tr>
						</thead>
						<tbody>
							{#if exitBreakdown.length === 0}
								<tr class="empty"><td colspan="3">No trades in this run.</td></tr>
							{:else}
								{#each exitBreakdown as r (r.reason)}
									<tr>
										<td>{r.reason}</td>
										<td class="num">{r.n}</td>
										<td class="num {r.pnl_cents >= 0 ? 'pos' : 'neg'}">{formatUsd(r.pnl_cents)}</td>
									</tr>
								{/each}
							{/if}
						</tbody>
					</table>
				</div>
			</div>
		</div>
	{:else}
		<div class="placeholder">
			<WarningIcon size={16} weight="fill" />
			<span>Configure a run and press <strong>Run backtest</strong> to see results.</span>
		</div>
	{/if}
</section>

<style>
	.studio {
		display: flex;
		flex-direction: column;
		gap: 0.9rem;
		width: min(100%, 1280px);
		margin: 0 auto;
		padding: 1rem;
	}
	.head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		color: var(--accent);
	}
	.head h1 {
		color: var(--text);
	}
	.banner {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.7rem 0.9rem;
		border: 1px solid color-mix(in srgb, var(--sell) 58%, var(--border));
		border-radius: 8px;
		background: color-mix(in srgb, var(--sell) 10%, var(--panel));
		color: var(--sell);
		font-size: 0.85rem;
	}
	.banner .dismiss {
		margin-left: auto;
		background: none;
		border: none;
		color: var(--sell);
		font-size: 1.1rem;
		line-height: 1;
		cursor: pointer;
	}
	.results,
	.skeleton {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.results-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		flex-wrap: wrap;
	}
	h2 {
		font-size: 0.9rem;
		color: var(--muted);
		font-weight: 600;
		margin: 0;
	}
	.actions {
		display: flex;
		gap: 0.5rem;
	}
	.ghost {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		height: 32px;
		padding: 0 0.7rem;
		background: var(--surface);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 0.8rem;
		font-weight: 600;
		cursor: pointer;
	}
	.ghost:hover:not(:disabled) {
		border-color: var(--accent);
	}
	.ghost:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.placeholder {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 1.25rem;
		border: 1px dashed var(--border);
		border-radius: 8px;
		background: var(--panel);
		color: var(--muted);
		font-size: 0.875rem;
	}

	/* Skeleton sized to match the real results so first paint doesn't shift. */
	.sk-cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
		gap: 0.6rem;
	}
	.sk-card {
		height: 72px;
		border-radius: 8px;
		background: var(--panel);
		border: 1px solid var(--border);
	}
	.sk-chart {
		height: 280px;
		border-radius: 8px;
		background: var(--panel);
		border: 1px solid var(--border);
	}
	.sk-table {
		height: 200px;
		border-radius: 8px;
		background: var(--panel);
		border: 1px solid var(--border);
	}
	.sk-card,
	.sk-chart,
	.sk-table {
		animation: pulse 1.4s ease-in-out infinite;
	}
	@keyframes pulse {
		50% {
			opacity: 0.5;
		}
	}

	.attr {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.label {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.table-wrap {
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
	}
	thead th {
		background: var(--panel);
		color: var(--muted);
		text-align: left;
		font-weight: 600;
		padding: 0.5rem 0.75rem;
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}
	tbody td {
		height: 38px;
		padding: 0 0.75rem;
		border-bottom: 1px solid var(--border);
		color: var(--text);
		white-space: nowrap;
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.pos {
		color: var(--buy);
	}
	.neg {
		color: var(--sell);
	}
	.empty td {
		text-align: center;
		color: var(--muted);
		font-style: italic;
	}
</style>
