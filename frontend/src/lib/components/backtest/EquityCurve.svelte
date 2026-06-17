<script lang="ts">
	import * as echarts from 'echarts';
	import type { EquityPoint } from '$lib/api/backtest';

	interface Props {
		/** Cumulative equity in CENTS, from BacktestResponse.equity_curve. */
		curve: EquityPoint[];
		height?: number;
	}

	let { curve, height = 280 }: Props = $props();

	let container = $state<HTMLDivElement>();
	let ddContainer = $state<HTMLDivElement>();
	let chart: echarts.ECharts | undefined;
	let ddChart: echarts.ECharts | undefined;

	function colors() {
		const cs = getComputedStyle(document.documentElement);
		return {
			panel: cs.getPropertyValue('--panel').trim() || '#101318',
			text: cs.getPropertyValue('--muted').trim() || '#8b949e',
			grid: cs.getPropertyValue('--border').trim() || '#1b2230',
			accent: cs.getPropertyValue('--accent').trim() || '#58a6ff',
			sell: cs.getPropertyValue('--sell').trim() || '#fb7185'
		};
	}

	const equityData = $derived<[number, number][]>(
		curve.map((p) => [new Date(p.ts).getTime(), p.equity_cents / 100])
	);

	const drawdownData = $derived.by<[number, number][]>(() => {
		let peak = -Infinity;
		return curve.map((p) => {
			peak = Math.max(peak, p.equity_cents);
			return [new Date(p.ts).getTime(), (p.equity_cents - peak) / 100];
		});
	});

	function baseOption(data: [number, number][], color: string, area: boolean): echarts.EChartsCoreOption {
		const col = colors();
		return {
			animation: false,
			grid: { left: 56, right: 16, top: 16, bottom: 40 },
			xAxis: {
				type: 'time',
				axisLine: { lineStyle: { color: col.grid } },
				splitLine: { show: true, lineStyle: { color: col.grid } },
				axisLabel: { color: col.text }
			},
			yAxis: {
				type: 'value',
				axisLine: { lineStyle: { color: col.grid } },
				splitLine: { show: true, lineStyle: { color: col.grid } },
				axisLabel: { color: col.text }
			},
			dataZoom: [{ type: 'inside' }],
			tooltip: {
				trigger: 'axis',
				backgroundColor: col.panel,
				borderColor: col.grid,
				textStyle: { color: col.text }
			},
			series: [
				{
					type: 'line',
					data,
					showSymbol: false,
					lineStyle: { color, width: 2 },
					areaStyle: area
						? {
								color: new (echarts as any).graphic.LinearGradient(0, 0, 0, 1, [
									{ offset: 0, color },
									{ offset: 1, color: 'rgba(0,0,0,0)' }
								])
					  }
					: undefined,
					animation: false
				}
			]
		};
	}

	$effect(() => {
		if (!container) return;
		const c = echarts.init(container, undefined, { renderer: 'canvas' });
		chart = c;
		const observer = new ResizeObserver(() => c.resize());
		observer.observe(container);
		return () => {
			observer.disconnect();
			c.dispose();
			chart = undefined;
		};
	});

	$effect(() => {
		if (!ddContainer) return;
		const c = echarts.init(ddContainer, undefined, { renderer: 'canvas' });
		ddChart = c;
		const observer = new ResizeObserver(() => c.resize());
		observer.observe(ddContainer);
		return () => {
			observer.disconnect();
			c.dispose();
			ddChart = undefined;
		};
	});

	$effect(() => {
		if (!chart || equityData.length === 0) return;
		const col = colors();
		chart.setOption(baseOption(equityData, col.accent, true), true);
	});

	$effect(() => {
		if (!ddChart || drawdownData.length === 0) return;
		const col = colors();
		ddChart.setOption(baseOption(drawdownData, col.sell, false), true);
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
