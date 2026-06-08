<script lang="ts">
	import { formatUsd, type BacktestMetrics } from '$lib/api/backtest';

	interface Props {
		metrics: BacktestMetrics;
		nSignals: number;
	}

	let { metrics, nSignals }: Props = $props();

	const pnlClass = $derived(metrics.total_pnl_cents >= 0 ? 'pos' : 'neg');

	// profit_factor === null encodes "infinite" (wins, no losses) — show it
	// honestly as ∞ rather than a fake number.
	const profitFactor = $derived(
		metrics.profit_factor === null ? '∞' : metrics.profit_factor.toFixed(2)
	);

	const winRatePct = $derived((metrics.win_rate * 100).toFixed(1) + '%');

	// Deflated Sharpe P(SR>0): null when < 3 trades (moments undefined) — show "—"
	// rather than a fabricated number.
	const dsrPct = $derived(
		metrics.deflated_sharpe === null ? null : (metrics.deflated_sharpe * 100).toFixed(0) + '%'
	);

	function fmtPct(x: number): string {
		return (x * 100).toFixed(1) + '%';
	}
</script>

<div class="grid">
	<div class="card emphasis">
		<div class="k">Net P&amp;L</div>
		<div class="v {pnlClass}">{formatUsd(metrics.total_pnl_cents)}</div>
	</div>
	<div class="card">
		<div class="k">Trades</div>
		<div class="v">{metrics.n_trades}<span class="sub">/ {nSignals} signals</span></div>
	</div>
	<div class="card">
		<div class="k">Win rate</div>
		<div class="v">{winRatePct}</div>
	</div>
	<div class="card">
		<div class="k">Profit factor</div>
		<div class="v">{profitFactor}</div>
	</div>
	<div class="card">
		<div class="k">Expectancy / trade</div>
		<div class="v">{formatUsd(metrics.expectancy_cents)}</div>
	</div>
	<div class="card">
		<div class="k">Max drawdown</div>
		<div class="v neg">-{formatUsd(metrics.max_drawdown_cents)}</div>
	</div>
</div>

<!--
	Deflated Sharpe P(SR>0) is the headline honesty number (deflated for skew/
	kurtosis + sample size, n_trials from the API). Per-trade Sharpe shown as a
	secondary figure. Both are IN-SAMPLE — the caption says so plainly.
-->
<div class="sharpe">
	<div class="sharpe-head">
		<span class="k">Deflated Sharpe — P(SR &gt; 0)</span>
		<span class="big">{dsrPct ?? '—'}</span>
	</div>
	<div class="sharpe-sub">
		<span class="k">Sharpe (per trade)</span>
		<span class="mid">{metrics.sharpe_per_trade.toFixed(3)}</span>
	</div>
	<p class="caption">
		{#if dsrPct === null}
			Deflated Sharpe needs ≥3 trades; per-trade Sharpe above is in-sample.
		{:else}
			Probability the true Sharpe &gt; 0, <strong>in-sample</strong> — deflated for
			skew/kurtosis and sample size (n_trials = {metrics.n_trials}). Not an
			out-of-sample guarantee; use walk-forward for that.
		{/if}
	</p>
</div>

<div class="tod">
	<div class="label">Per time-of-day</div>
	<div class="table-wrap">
		<table>
			<thead>
				<tr>
					<th>Bucket</th>
					<th class="num">N</th>
					<th class="num">Win rate</th>
					<th class="num">Expectancy</th>
				</tr>
			</thead>
			<tbody>
				{#if metrics.per_tod.length === 0}
					<tr class="empty"><td colspan="4">No per-bucket stats.</td></tr>
				{:else}
					{#each metrics.per_tod as t (t.bucket)}
						<tr>
							<td>{t.bucket}</td>
							<td class="num">{t.n}</td>
							<td class="num">{fmtPct(t.win_rate)}</td>
							<td class="num {t.expectancy_cents >= 0 ? 'pos' : 'neg'}">
								{formatUsd(t.expectancy_cents)}
							</td>
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>
</div>

<style>
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
		gap: 0.6rem;
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		padding: 0.8rem 0.9rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--panel);
	}
	.card.emphasis {
		border-color: var(--accent);
	}
	.k {
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.v {
		font-size: 1.25rem;
		font-weight: 600;
		color: var(--text);
		font-variant-numeric: tabular-nums;
	}
	.v .sub {
		font-size: 0.72rem;
		font-weight: 400;
		color: var(--muted);
		margin-left: 0.4rem;
	}
	.pos {
		color: #3fb950;
	}
	.neg {
		color: #f85149;
	}
	.sharpe {
		margin-top: 0.8rem;
		padding: 0.9rem 1rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--panel);
	}
	.sharpe-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 1rem;
	}
	.sharpe-head .big {
		font-size: 1.6rem;
		font-weight: 700;
		color: var(--accent);
		font-variant-numeric: tabular-nums;
	}
	.sharpe-sub {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 1rem;
		margin-top: 0.5rem;
		padding-top: 0.5rem;
		border-top: 1px solid var(--border);
	}
	.sharpe-sub .mid {
		font-size: 1.05rem;
		font-weight: 600;
		color: var(--text);
		font-variant-numeric: tabular-nums;
	}
	.caption {
		margin: 0.4rem 0 0;
		font-size: 0.76rem;
		color: var(--muted);
		font-style: italic;
		line-height: 1.4;
	}
	.tod {
		margin-top: 0.8rem;
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
	.empty td {
		text-align: center;
		color: var(--muted);
		font-style: italic;
	}
</style>
