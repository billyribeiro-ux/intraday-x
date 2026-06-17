<script lang="ts">
	import type { ECharts, EChartsCoreOption, graphic, init } from 'echarts/core';
	import type { EquityPoint } from '$lib/api/backtest';

	type EChartsModule = {
		init: typeof init;
		graphic: typeof graphic;
	};

	interface Props {
		/** Cumulative equity in CENTS, from BacktestResponse.equity_curve. */
		curve: EquityPoint[];
		height?: number;
	}

	let { curve, height = 280 }: Props = $props();

	let container = $state<HTMLDivElement>();
	let ddContainer = $state<HTMLDivElement>();
	let echartsModule: EChartsModule | null = null;

	async function loadEcharts(): Promise<EChartsModule> {
		if (echartsModule) return echartsModule;
		const [{ init, use, graphic }, { LineChart }, components, { CanvasRenderer }] =
			await Promise.all([
				import('echarts/core'),
				import('echarts/charts'),
				import('echarts/components'),
				import('echarts/renderers')
			]);
		use([
			LineChart,
			components.GridComponent,
			components.TooltipComponent,
			components.DataZoomInsideComponent,
			CanvasRenderer
		]);
		echartsModule = { init, graphic };
		return echartsModule;
	}

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

	function baseOption(
		data: [number, number][],
		color: string,
		area: boolean,
		ec: EChartsModule
	): EChartsCoreOption {
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
								color: new ec.graphic.LinearGradient(0, 0, 0, 1, [
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
		if (!container || equityData.length === 0) return;
		let disposed = false;
		let observer: ResizeObserver | undefined;
		let c: ECharts | undefined;
		void loadEcharts().then((ec) => {
			if (disposed || !container) return;
			c = ec.init(container, undefined, { renderer: 'canvas' });
			observer = new ResizeObserver(() => c?.resize());
			observer.observe(container);
			const col = colors();
			c.setOption(baseOption(equityData, col.accent, true, ec), true);
		});
		return () => {
			disposed = true;
			observer?.disconnect();
			c?.dispose();
		};
	});

	$effect(() => {
		if (!ddContainer || drawdownData.length === 0) return;
		let disposed = false;
		let observer: ResizeObserver | undefined;
		let c: ECharts | undefined;
		void loadEcharts().then((ec) => {
			if (disposed || !ddContainer) return;
			c = ec.init(ddContainer, undefined, { renderer: 'canvas' });
			observer = new ResizeObserver(() => c?.resize());
			observer.observe(ddContainer);
			const col = colors();
			c.setOption(baseOption(drawdownData, col.sell, false, ec), true);
		});
		return () => {
			disposed = true;
			observer?.disconnect();
			c?.dispose();
		};
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
