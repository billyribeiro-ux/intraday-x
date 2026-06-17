<script lang="ts">
	import * as echarts from 'echarts';
	import type { ChartCandle, ChartVolume, ChartLine, ChartMarker, Levels } from '$lib/api/types';

	interface Props {
		candles: ChartCandle[];
		volume: ChartVolume[];
		vwap: ChartLine[];
		markers?: ChartMarker[];
		levels?: Levels | null;
	}

	let { candles, volume, vwap, markers = [], levels = null }: Props = $props();

	let container = $state<HTMLDivElement>();
	let chart: echarts.ECharts | undefined;

	function themeColors() {
		const cs = getComputedStyle(document.documentElement);
		return {
			bg: cs.getPropertyValue('--panel').trim() || '#0e1117',
			text: cs.getPropertyValue('--text').trim() || '#c9d1d9',
			grid: cs.getPropertyValue('--border').trim() || '#1b2230',
			muted: cs.getPropertyValue('--muted').trim() || '#8b949e'
		};
	}

	function chartOptions(): echarts.EChartsCoreOption {
		const col = themeColors();
		const upColor = '#26a69a';
		const downColor = '#ef5350';

		const candleData = candles.map((c) => [c.time * 1000, c.open, c.close, c.low, c.high]);
		const volumeData = volume.map((v) => ({
			value: [v.time * 1000, v.value],
			itemStyle: { color: v.color }
		}));
		const vwapData = vwap.map((p) => [p.time * 1000, p.value]);

		const markLines = levels
			? [
					{
						yAxis: levels.poc,
						name: 'POC',
						lineStyle: { color: col.muted, type: 'dashed', width: 1 },
						label: { formatter: 'POC', color: col.muted }
					},
					{
						yAxis: levels.vah,
						name: 'VAH',
						lineStyle: { color: '#3fb950', type: 'dotted', width: 1 },
						label: { formatter: 'VAH', color: '#3fb950' }
					},
					{
						yAxis: levels.val,
						name: 'VAL',
						lineStyle: { color: '#f85149', type: 'dotted', width: 1 },
						label: { formatter: 'VAL', color: '#f85149' }
					}
			  ]
			: [];

		const symbolMap: Record<string, string> = {
			arrowUp: 'triangle',
			arrowDown: 'triangle',
			circle: 'circle',
			square: 'rect'
		};
		const markerData = markers.map((m) => {
			const candle = candles.find((c) => c.time === m.time);
			let price = candle ? candle.close : 0;
			if (m.position === 'aboveBar') price = candle ? candle.high : price;
			if (m.position === 'belowBar') price = candle ? candle.low : price;
			return {
				coord: [m.time * 1000, price],
				symbol: symbolMap[m.shape] || 'circle',
				symbolRotate: m.shape === 'arrowDown' ? 180 : 0,
				itemStyle: { color: m.color },
				label: m.text
					? { show: true, formatter: m.text, position: 'top', color: m.color }
					: undefined
			};
		});

		return {
			backgroundColor: col.bg,
			textStyle: { color: col.text },
			animation: false,
			grid: [
				{ left: 56, right: 16, top: 16, bottom: '32%' },
				{ left: 56, right: 16, top: '68%', bottom: 40 }
			],
			xAxis: [
				{
					type: 'time',
					gridIndex: 0,
					axisLine: { lineStyle: { color: col.grid } },
					splitLine: { show: true, lineStyle: { color: col.grid } },
					axisLabel: { color: col.text },
					axisPointer: { label: { show: false } }
				},
				{
					type: 'time',
					gridIndex: 1,
					axisLine: { lineStyle: { color: col.grid } },
					splitLine: { show: true, lineStyle: { color: col.grid } },
					axisLabel: { color: col.text }
				}
			],
			yAxis: [
				{
					scale: true,
					gridIndex: 0,
					axisLine: { lineStyle: { color: col.grid } },
					splitLine: { show: true, lineStyle: { color: col.grid } },
					axisLabel: { color: col.text }
				},
				{
					scale: true,
					gridIndex: 1,
					axisLine: { lineStyle: { color: col.grid } },
					splitLine: { show: true, lineStyle: { color: col.grid } },
					axisLabel: { color: col.text },
					splitNumber: 2
				}
			],
			dataZoom: [
				{ type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
				{ type: 'slider', xAxisIndex: [0, 1], bottom: 4, height: 16, show: false }
			],
			tooltip: {
				trigger: 'axis',
				axisPointer: { type: 'cross' },
				backgroundColor: col.bg,
				borderColor: col.grid,
				textStyle: { color: col.text }
			},
			series: [
				{
					name: 'Price',
					type: 'candlestick',
					xAxisIndex: 0,
					yAxisIndex: 0,
					data: candleData,
					itemStyle: {
						color: upColor,
						color0: downColor,
						borderColor: upColor,
						borderColor0: downColor
					},
					markLine: { data: markLines, symbol: 'none', animation: false },
					markPoint: {
						data: markerData,
						symbolSize: 12,
						animation: false
					}
				},
				{
					name: 'VWAP',
					type: 'line',
					xAxisIndex: 0,
					yAxisIndex: 0,
					data: vwapData,
					showSymbol: false,
					lineStyle: { color: '#e3b341', width: 1 },
					animation: false
				},
				{
					name: 'Volume',
					type: 'bar',
					xAxisIndex: 1,
					yAxisIndex: 1,
					data: volumeData,
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
		if (!chart) return;
		// Merge-in updates instead of rebuilding; keeps live updates smooth.
		chart.setOption(chartOptions(), false, true);
	});
</script>

<div class="chart" bind:this={container}></div>

<style>
	.chart {
		width: 100%;
		height: 100%;
		min-height: 0;
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: hidden;
	}
</style>
