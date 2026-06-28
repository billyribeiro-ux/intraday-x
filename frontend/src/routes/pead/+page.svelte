<script lang="ts">
	// Earnings Drift (PEAD) — the one validated edge. Backtest the EPS-surprise
	// long/short portfolio after costs and list currently-open trades.
	import { runPead, type PeadResponse } from '$lib/api/pead';
	import { TrendDownIcon, TrendUpIcon } from '$lib/icons';

	let symbols = $state('AAPL,MSFT,NVDA,TSLA,AMD,META,AMZN,GOOGL,NFLX,JPM,XOM,BAC,DIS,CRM,INTC,CSCO,PFE,KO,NKE,WMT');
	let holdDays = $state(20);
	let years = $state(4);
	let minSue = $state(0);
	let costBps = $state(5);
	let borrowBps = $state(50);

	let loading = $state(false);
	let error = $state<string | null>(null);
	let result = $state<PeadResponse | null>(null);

	async function run() {
		loading = true;
		error = null;
		try {
			result = await runPead(fetch, {
				symbols: symbols.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean),
				hold_days: holdDays,
				years,
				min_sue: minSue,
				cost_bps: costBps,
				borrow_bps: borrowBps
			});
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			result = null;
		} finally {
			loading = false;
		}
	}

	const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
	const pct2 = (x: number) => `${(x * 100 >= 0 ? '+' : '')}${(x * 100).toFixed(2)}%`;
</script>

<section class="pead">
	<header>
		<h1>📈 Earnings Drift <span class="sub">Post-Earnings-Announcement Drift — the validated edge</span></h1>
	</header>

	<div class="controls">
		<label class="wide">Universe (comma-separated)
			<input bind:value={symbols} spellcheck="false" />
		</label>
		<label>Hold (days)<input type="number" bind:value={holdDays} min="1" max="60" /></label>
		<label>Years<input type="number" bind:value={years} min="1" max="10" /></label>
		<label>Min |SUE|<input type="number" step="0.1" bind:value={minSue} min="0" /></label>
		<label>Cost bps/side<input type="number" step="0.5" bind:value={costBps} min="0" /></label>
		<label>Borrow bps/yr<input type="number" step="5" bind:value={borrowBps} min="0" /></label>
		<button onclick={run} disabled={loading}>{loading ? 'Running…' : '▶ Run'}</button>
	</div>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if loading}
		<p class="hint">Fetching deep daily history + earnings surprises across the universe… (a few minutes)</p>
	{/if}

	{#if result}
		{@const edge = result.t_stat > 2}
		<div class="cards">
			<div class="card hero" class:good={result.sharpe > 0.5}>
				<span class="k">Net Sharpe (after costs)</span>
				<span class="v">{result.sharpe.toFixed(2)}</span>
			</div>
			<div class="card"><span class="k">Annualized return</span><span class="v">{pct(result.ann_return)}</span></div>
			<div class="card"><span class="k">Annualized vol</span><span class="v">{pct(result.ann_vol)}</span></div>
			<div class="card"><span class="k">Max drawdown</span><span class="v down">{pct(result.max_drawdown)}</span></div>
			<div class="card"><span class="k">Total return</span><span class="v">{pct(result.total_return)}</span></div>
		</div>

		<div class="edgebar" class:good={edge}>
			Edge: <b>{result.n_events}</b> events · mean <b>{pct2(result.mean_return)}</b>/trade ·
			t-stat <b>{result.t_stat.toFixed(2)}</b> · hit {pct(result.hit_rate)} —
			<b>{edge ? 'edge present (t>2)' : 'not significant on this sample'}</b>
			<span class="meta">{result.symbols.length} names · {result.years}y · hold {result.hold_days}d ·
			{result.cost_bps}bps/side + {result.borrow_bps}bps borrow</span>
		</div>

		<h2>Open trades <span class="sub">announced, still in the drift window</span></h2>
		{#if result.open_trades.length === 0}
			<p class="hint">No open PEAD trades right now.</p>
		{:else}
			<table>
				<thead><tr><th>Symbol</th><th>Announced</th><th>Entry</th><th>Signal</th><th class="num">Surprise $</th><th class="num">SUE</th></tr></thead>
				<tbody>
					{#each result.open_trades as t (t.symbol + t.announce_date)}
						{@const buy = t.side === 'buy'}
						<tr>
							<td class="mono">{t.symbol}</td>
							<td class="mono">{t.announce_date}</td>
							<td class="mono">${t.entry.toFixed(2)}</td>
							<td class="side {buy ? 'buy' : 'sell'}">
								{#if buy}<TrendUpIcon size={15} weight="bold" />{:else}<TrendDownIcon size={15} weight="bold" />{/if}
								{buy ? 'Long' : 'Short'}
							</td>
							<td class="num">{t.surprise >= 0 ? '+' : ''}{t.surprise.toFixed(2)}</td>
							<td class="num">{t.sue.toFixed(2)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	{/if}
</section>

<style>
	.pead { padding: 1rem 1.25rem; overflow: auto; height: 100%; }
	h1 { font-size: 1.1rem; margin: 0 0 0.75rem; }
	.sub { color: var(--muted); font-weight: 400; font-size: 0.8rem; }
	.controls { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: end; margin-bottom: 1rem; }
	label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.72rem; color: var(--muted); }
	label.wide { flex: 1 1 320px; }
	input { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
		padding: 0.4rem 0.5rem; color: var(--text); font-size: 0.85rem; }
	label:not(.wide) input { width: 6rem; }
	button { align-self: end; background: var(--accent); color: #fff; border: none; border-radius: 6px;
		padding: 0.45rem 0.9rem; font-weight: 700; cursor: pointer; }
	button:disabled { opacity: 0.6; cursor: default; }
	.error { color: var(--warn); }
	.hint { color: var(--muted); font-style: italic; }
	.cards { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-bottom: 0.8rem; }
	.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
		padding: 0.6rem 0.9rem; display: flex; flex-direction: column; gap: 0.2rem; min-width: 120px; }
	.card .k { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.03em; }
	.card .v { font-size: 1.35rem; font-weight: 750; font-variant-numeric: tabular-nums; }
	.card.hero { border-color: color-mix(in srgb, var(--accent) 40%, transparent); }
	.card.hero.good .v { color: var(--buy); }
	.v.down { color: var(--sell); }
	.edgebar { background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--muted);
		border-radius: 6px; padding: 0.55rem 0.8rem; font-size: 0.85rem; margin-bottom: 1rem; }
	.edgebar.good { border-left-color: var(--buy); }
	.edgebar .meta { display: block; color: var(--muted); font-size: 0.72rem; margin-top: 0.25rem; }
	h2 { font-size: 0.95rem; margin: 0.5rem 0; }
	table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
	th { text-align: left; color: var(--muted); font-weight: 700; padding: 0.4rem 0.6rem;
		border-bottom: 1px solid var(--border); }
	td { padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
	.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
	.side { display: flex; align-items: center; gap: 0.35rem; font-weight: 650; }
	.side.buy { color: var(--buy); }
	.side.sell { color: var(--sell); }
</style>
