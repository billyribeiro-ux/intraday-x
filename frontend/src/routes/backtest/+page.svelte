<script lang="ts">
	import {
		formatUsd,
		runBacktest,
		trainBacktestModel,
		type BacktestParams,
		type BacktestResponse,
		type BacktestTrade,
		type LearnResponse
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
	let learning = $state(false);
	let error = $state<string | null>(null);
	let result = $state<BacktestResponse | null>(null);
	let learnResult = $state<LearnResponse | null>(null);
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

	async function handleLearn(params: BacktestParams & { min_samples: number }) {
		learning = true;
		error = null;
		learnResult = null;
		lastParams = params;
		try {
			learnResult = await trainBacktestModel(fetch, {
				symbol: params.symbol,
				timeframe: params.timeframe,
				days: params.days,
				max_hold: params.max_hold,
				scanner: params.scanner,
				min_samples: params.min_samples
			});
		} catch (e) {
			error = e instanceof Error ? e.message : 'Learning failed.';
		} finally {
			learning = false;
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
			'tod_bucket',
			'confidence',
			'quality_score',
			'meta_score',
			'attribution',
			'diagnosis'
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
				t.tod_bucket,
				t.confidence.toFixed(4),
				t.quality_score.toFixed(4),
				t.meta_score == null ? '' : t.meta_score.toFixed(4),
				t.attribution.summary,
				t.diagnosis
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
		const rows: { reason: string; n: number; pnl_cents: number }[] = [];
		for (const t of result.trades) {
			let cur = rows.find((row) => row.reason === t.exit_reason);
			if (!cur) {
				cur = { reason: t.exit_reason, n: 0, pnl_cents: 0 };
				rows.push(cur);
			}
			cur.n += 1;
			cur.pnl_cents += t.pnl_cents;
		}
		return rows.sort((a, b) => b.n - a.n);
	});

	const pnlDelta = $derived(
		result ? result.metrics.total_pnl_cents - result.baseline_metrics.total_pnl_cents : 0
	);

	function fmtPct(value: number | null | undefined): string {
		return value == null ? '—' : `${(value * 100).toFixed(0)}%`;
	}

	function fmtTime(value: string): string {
		return new Date(value).toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		});
	}
</script>

<section class="studio">
	<div class="head">
		<FlaskIcon size={20} weight="fill" />
		<h1>Backtest Studio</h1>
	</div>

	<BacktestForm onRun={handleRun} onLearn={handleLearn} {loading} {learning} />

	{#if error}
		<div class="banner" role="alert">
			<XCircleIcon size={18} weight="fill" />
			<span>{error}</span>
			<button class="dismiss" type="button" onclick={() => (error = null)} aria-label="Dismiss">
				×
			</button>
		</div>
	{/if}

	{#if learnResult}
		<div class="learn-banner" class:warn={learnResult.insufficient}>
			<div>
				<strong>{learnResult.saved ? 'Model trained and saved' : 'Model not saved'}</strong>
				<span>
					{learnResult.insufficient
						? learnResult.reason
						: `${learnResult.n_samples} samples · ROC-AUC ${learnResult.cv_roc_auc.toFixed(3)} · precision ${fmtPct(learnResult.cv_precision)}`}
				</span>
			</div>
			{#if learnResult.feature_importance.length > 0}
				<div class="features">
					{#each learnResult.feature_importance.slice(0, 4) as [feature, value] (feature)}
						<span>{feature} · {value.toFixed(3)}</span>
					{/each}
				</div>
			{/if}
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

			<div class="learning-panel">
				<div>
					<div class="label">Learning layer</div>
					<p>{result.learning.summary}</p>
				</div>
				<div class="learning-stats">
					<span>Model {result.learning.model_loaded ? 'loaded' : 'missing'}</span>
					<span>Selected {result.learning.selected_signals}/{result.n_raw_signals}</span>
					<span>Avg ML {fmtPct(result.learning.avg_meta_score)}</span>
					<span class={pnlDelta >= 0 ? 'pos' : 'neg'}>Δ {formatUsd(pnlDelta)}</span>
				</div>
			</div>

			<div class="comparison">
				<div>
					<span class="label">Raw scanner</span>
					<strong>{formatUsd(result.baseline_metrics.total_pnl_cents)}</strong>
					<small>
						{result.baseline_metrics.n_trades} trades · {fmtPct(result.baseline_metrics.win_rate)} win
					</small>
				</div>
				<div>
					<span class="label">Active run</span>
					<strong class={result.metrics.total_pnl_cents >= 0 ? 'pos' : 'neg'}>
						{formatUsd(result.metrics.total_pnl_cents)}
					</strong>
					<small>{result.metrics.n_trades} trades · {fmtPct(result.metrics.win_rate)} win</small>
				</div>
				<div>
					<span class="label">Data</span>
					<strong>{fmtPct(result.data_completeness)}</strong>
					<small>{result.catalysts.length} FMP catalysts attached</small>
				</div>
			</div>

			<EquityCurve curve={result.equity_curve} />

			<div class="ledger">
				<div class="label">Evidence ledger</div>
				{#if result.trades.length === 0}
					<div class="empty-ledger">No executed trades. Train over more history or lower the ML threshold.</div>
				{:else}
					<div class="ledger-list">
						{#each result.trades as trade (trade.signal_id)}
							<details class="trade-card" open={result.trades.length <= 4}>
								<summary>
									<span class="side" class:long={trade.is_long} class:short={!trade.is_long}>
										{trade.is_long ? 'Long' : 'Short'}
									</span>
									<strong>{trade.kind.replaceAll('_', ' ')}</strong>
									<span>{fmtTime(trade.entry_ts)}</span>
									<span class={trade.pnl_cents >= 0 ? 'pos' : 'neg'}>{formatUsd(trade.pnl_cents)}</span>
									<span>{trade.exit_reason}</span>
								</summary>
								<div class="trade-body">
									<div>
										<div class="label">Signal thesis</div>
										<p>{trade.attribution.summary}</p>
										<div class="chips">
											<span>Conf {fmtPct(trade.confidence)}</span>
											<span>Quality {fmtPct(trade.quality_score)}</span>
											<span>ML {fmtPct(trade.meta_score)}</span>
										</div>
									</div>
									<div>
										<div class="label">Move evidence</div>
										<p>{trade.entry_explanation?.summary ?? 'No entry-state explanation available.'}</p>
										<p>{trade.exit_explanation?.summary ?? 'No exit-state explanation available.'}</p>
									</div>
									<div>
										<div class="label">FMP catalysts</div>
										{#if trade.catalysts.length === 0}
											<p>No nearby FMP catalyst found for this signal window.</p>
										{:else}
											<div class="catalyst-list">
												{#each trade.catalysts as catalyst (`${trade.signal_id}-${catalyst.kind}-${catalyst.ts}-${catalyst.title}`)}
													<span>
														{catalyst.kind.replaceAll('_', ' ')} · {fmtPct(catalyst.score)} · {catalyst.title}
													</span>
												{/each}
											</div>
										{/if}
									</div>
									<div class="diagnosis">
										<div class="label">Diagnosis</div>
										<p>{trade.diagnosis}</p>
									</div>
								</div>
							</details>
						{/each}
					</div>
				{/if}
			</div>

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

	.learn-banner,
	.learning-panel,
	.comparison,
	.trade-card,
	.empty-ledger {
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--panel);
	}
	.learn-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.9rem;
		padding: 0.8rem 0.9rem;
	}
	.learn-banner.warn {
		border-color: color-mix(in srgb, var(--warn) 55%, var(--border));
	}
	.learn-banner strong {
		display: block;
		color: var(--text);
		font-size: 0.9rem;
	}
	.learn-banner span,
	.learning-panel p,
	.trade-body p {
		color: var(--muted);
		font-size: 0.78rem;
		line-height: 1.4;
		margin: 0.2rem 0 0;
	}
	.features,
	.learning-stats,
	.chips,
	.catalyst-list {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.features span,
	.learning-stats span,
	.chips span,
	.catalyst-list span {
		max-width: 100%;
		padding: 0.2rem 0.42rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface);
		color: var(--text);
		font-size: 0.68rem;
		font-weight: 650;
	}
	.learning-panel {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 0.8rem;
		align-items: center;
		padding: 0.85rem 0.95rem;
	}
	.learning-stats {
		justify-content: flex-end;
	}
	.comparison {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		overflow: hidden;
	}
	.comparison > div {
		display: grid;
		gap: 0.25rem;
		padding: 0.8rem 0.95rem;
		border-right: 1px solid var(--border);
	}
	.comparison > div:last-child {
		border-right: 0;
	}
	.comparison strong {
		font-size: 1.2rem;
		color: var(--text);
		font-variant-numeric: tabular-nums;
	}
	.comparison small {
		color: var(--muted);
		font-size: 0.74rem;
	}
	.ledger {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.empty-ledger {
		padding: 1rem;
		color: var(--muted);
		font-size: 0.85rem;
	}
	.ledger-list {
		display: grid;
		gap: 0.55rem;
	}
	.trade-card {
		overflow: hidden;
	}
	.trade-card summary {
		display: grid;
		grid-template-columns: auto minmax(130px, 1fr) auto auto auto;
		align-items: center;
		gap: 0.65rem;
		min-height: 42px;
		padding: 0 0.8rem;
		cursor: pointer;
		color: var(--muted);
		font-size: 0.78rem;
	}
	.trade-card summary strong {
		color: var(--text);
		text-transform: capitalize;
	}
	.side {
		padding: 0.18rem 0.42rem;
		border-radius: 6px;
		font-size: 0.68rem;
		font-weight: 760;
	}
	.side.long {
		background: color-mix(in srgb, var(--buy) 14%, transparent);
		color: var(--buy);
	}
	.side.short {
		background: color-mix(in srgb, var(--sell) 14%, transparent);
		color: var(--sell);
	}
	.trade-body {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.8rem;
		padding: 0.8rem;
		border-top: 1px solid var(--border);
	}
	.diagnosis {
		grid-column: 1 / -1;
		padding-top: 0.6rem;
		border-top: 1px solid var(--border);
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
	@media (max-width: 860px) {
		.learning-panel,
		.comparison,
		.trade-body {
			grid-template-columns: 1fr;
		}
		.learning-stats {
			justify-content: flex-start;
		}
		.comparison > div {
			border-right: 0;
			border-bottom: 1px solid var(--border);
		}
		.trade-card summary {
			grid-template-columns: auto minmax(0, 1fr) auto;
		}
		.trade-card summary span:nth-last-child(-n + 2) {
			display: none;
		}
	}
</style>
