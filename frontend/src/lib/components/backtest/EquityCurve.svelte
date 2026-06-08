<script lang="ts">
	import {
		AreaSeries,
		ColorType,
		createChart,
		LineSeries,
		type AreaData,
		type IChartApi,
		type ISeriesApi,
		type LineData,
		type UTCTimestamp
	} from 'lightweight-charts';

	import type { EquityPoint } from '$lib/api/backtest';

	interface Props {
		/** Cumulative equity in CENTS, from BacktestResponse.equity_curve. */
		curve: EquityPoint[];
		height?: number;
	}

	let { curve, height = 280 }: Props = $props();

	// equity_curve is already cumulative on the backend, so we plot it directly
	// (no trades fallback needed). We divide cents -> dollars at the chart
	// boundary for a readable axis; the raw cents stay intact in the data model.
	const equityArea = $derived<AreaData<UTCTimestamp>[]>(
		curve.map((p) => ({
			time: Math.floor(new Date(p.ts).getTime() / 1000) as UTCTimestamp,
			value: p.equity_cents / 100
		}))
	);

	// Underwater (drawdown) = equity minus its running peak, in dollars (<= 0).
	const underwater = $derived.by<LineData<UTCTimestamp>[]>(() => {
		let peak = -Infinity;
		return curve.map((p) => {
			peak = Math.max(peak, p.equity_cents);
			return {
				time: Math.floor(new Date(p.ts).getTime() / 1000) as UTCTimestamp,
				value: (p.equity_cents - peak) / 100
			};
		});
	});

	let container = $state<HTMLDivElement>();
	let ddContainer = $state<HTMLDivElement>();

	let chart: IChartApi | undefined;
	let equitySeries: ISeriesApi<'Area'> | undefined;
	let ddChart: IChartApi | undefined;
	let ddSeries: ISeriesApi<'Line'> | undefined;

	// Theme-following chart colors read from the CSS vars on the document root, so
	// the chart matches light/dark without hardcoding palette values here.
	function chartColors() {
		const cs = getComputedStyle(document.documentElement);
		return {
			text: cs.getPropertyValue('--muted').trim() || '#8b949e',
			grid: cs.getPropertyValue('--border').trim() || '#1b2230',
			accent: cs.getPropertyValue('--accent').trim() || '#58a6ff'
		};
	}

	// Equity chart: create once + teardown.
	$effect(() => {
		if (!container) return;
		const col = chartColors();
		const c = createChart(container, {
			autoSize: true,
			layout: {
				background: { type: ColorType.Solid, color: 'transparent' },
				textColor: col.text,
				attributionLogo: true
			},
			grid: { vertLines: { color: col.grid }, horzLines: { color: col.grid } },
			timeScale: { timeVisible: true, secondsVisible: false, borderColor: col.grid },
			rightPriceScale: { borderColor: col.grid }
		});
		equitySeries = c.addSeries(AreaSeries, {
			lineColor: col.accent,
			topColor: 'rgba(88,166,255,0.30)',
			bottomColor: 'rgba(88,166,255,0.02)',
			lineWidth: 2,
			priceFormat: { type: 'price', precision: 2, minMove: 0.01 }
		});
		chart = c;
		return () => {
			c.remove();
			chart = equitySeries = undefined;
		};
	});

	// Drawdown chart: create once + teardown.
	$effect(() => {
		if (!ddContainer) return;
		const col = chartColors();
		const c = createChart(ddContainer, {
			autoSize: true,
			layout: {
				background: { type: ColorType.Solid, color: 'transparent' },
				textColor: col.text,
				attributionLogo: false
			},
			grid: { vertLines: { color: col.grid }, horzLines: { color: col.grid } },
			timeScale: { timeVisible: true, secondsVisible: false, borderColor: col.grid },
			rightPriceScale: { borderColor: col.grid }
		});
		ddSeries = c.addSeries(LineSeries, {
			color: '#f85149',
			lineWidth: 1,
			priceFormat: { type: 'price', precision: 2, minMove: 0.01 }
		});
		ddChart = c;
		return () => {
			c.remove();
			ddChart = ddSeries = undefined;
		};
	});

	// Push data (re-runs when the derived arrays change; never recreates a chart).
	$effect(() => {
		if (!equitySeries || !chart) return;
		equitySeries.setData(equityArea);
		chart.timeScale().fitContent();
	});
	$effect(() => {
		if (!ddSeries || !ddChart) return;
		ddSeries.setData(underwater);
		ddChart.timeScale().fitContent();
	});
</script>

{#if curve.length === 0}
	<div class="empty" style="height: {height + 140}px">No equity curve for this run.</div>
{:else}
	<div class="wrap">
		<div class="label">Cumulative equity ($)</div>
		<div class="chart" bind:this={container} style="height: {height}px"></div>
		<div class="label">Underwater drawdown ($)</div>
		<div class="chart" bind:this={ddContainer} style="height: 120px"></div>
	</div>
{/if}

<style>
	.wrap {
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
	.chart {
		width: 100%;
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: hidden;
		background: var(--panel);
	}
	.empty {
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--panel);
		color: var(--muted);
		font-style: italic;
		font-size: 0.85rem;
	}
</style>
