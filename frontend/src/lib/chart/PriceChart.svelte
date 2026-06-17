<script lang="ts">
	import {
		CandlestickSeries,
		CrosshairMode,
		HistogramSeries,
		LineSeries,
		LineStyle,
		createChart,
		createSeriesMarkers
	} from 'lightweight-charts';
	import type {
		CandlestickData,
		ChartOptions,
		DeepPartial,
		HistogramData,
		IChartApi,
		IPriceLine,
		ISeriesApi,
		ISeriesMarkersPluginApi,
		LineData,
		SeriesMarker,
		Time
	} from 'lightweight-charts';

	import type {
		ChartCandle,
		ChartLine,
		ChartMarker,
		ChartStudy,
		ChartVolume,
		Levels
	} from '$lib/api/types';

	interface Props {
		candles: ChartCandle[];
		volume: ChartVolume[];
		vwap: ChartLine[];
		studies?: ChartStudy[];
		markers?: ChartMarker[];
		levels?: Levels | null;
		symbol?: string;
		timeframe?: string;
		dataCompleteness?: number | null;
	}

	type ChartColors = {
		bg: string;
		panel: string;
		text: string;
		muted: string;
		grid: string;
		accent: string;
		buy: string;
		sell: string;
		warn: string;
		volumeBuy: string;
		volumeSell: string;
	};

	type Legend = {
		time: number;
		open: number;
		high: number;
		low: number;
		close: number;
		volume?: number;
		vwap?: number;
	};

	let {
		candles,
		volume,
		vwap,
		studies = [],
		markers = [],
		levels = null,
		symbol = '',
		timeframe = '',
		dataCompleteness = null
	}: Props = $props();

	let container = $state<HTMLDivElement>();
	let chart: IChartApi | undefined;
	let candleSeries: ISeriesApi<'Candlestick'> | undefined;
	let volumeSeries: ISeriesApi<'Histogram'> | undefined;
	let vwapSeries: ISeriesApi<'Line'> | undefined;
	let studySeries: ISeriesApi<'Line'>[] = [];
	let markerApi: ISeriesMarkersPluginApi<Time> | undefined;
	let levelLines: IPriceLine[] = [];
	let currentStructureKey = '';
	let hovered = $state<Legend | null>(null);

	const latest = $derived.by<Legend | null>(() => {
		const last = candles.at(-1);
		if (!last) return null;
		const lastVolume = volume.at(-1);
		const lastVwap = vwap.at(-1);
		return {
			time: last.time,
			open: last.open,
			high: last.high,
			low: last.low,
			close: last.close,
			volume: lastVolume?.value,
			vwap: lastVwap?.value
		};
	});

	const previousClose = $derived(candles.length > 1 ? candles[candles.length - 2].close : null);
	const legend = $derived(hovered ?? latest);
	const delta = $derived(
		latest && previousClose !== null
			? { value: latest.close - previousClose, pct: ((latest.close - previousClose) / previousClose) * 100 }
			: null
	);
	const deltaClass = $derived(delta && delta.value < 0 ? 'down' : 'up');

	function cssVar(name: string, fallback: string): string {
		const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
		return value || fallback;
	}

	function colors(): ChartColors {
		return {
			bg: cssVar('--bg', '#08090b'),
			panel: cssVar('--panel', '#101318'),
			text: cssVar('--text', '#e6edf3'),
			muted: cssVar('--muted', '#8a94a6'),
			grid: cssVar('--grid', '#242a34'),
			accent: cssVar('--accent', '#7dd3fc'),
			buy: cssVar('--buy', '#2dd4bf'),
			sell: cssVar('--sell', '#fb7185'),
			warn: cssVar('--warn', '#fbbf24'),
			volumeBuy: cssVar('--volume-buy', 'rgba(45, 212, 191, 0.34)'),
			volumeSell: cssVar('--volume-sell', 'rgba(251, 113, 133, 0.34)')
		};
	}

	function pricePrecision(): { precision: number; minMove: number } {
		const price = candles.at(-1)?.close ?? 100;
		if (price < 1) return { precision: 4, minMove: 0.0001 };
		if (price < 10) return { precision: 3, minMove: 0.001 };
		return { precision: 2, minMove: 0.01 };
	}

	function formatPrice(value: number | undefined): string {
		if (value === undefined || Number.isNaN(value)) return '--';
		return value.toLocaleString(undefined, {
			minimumFractionDigits: pricePrecision().precision,
			maximumFractionDigits: pricePrecision().precision
		});
	}

	function formatVolume(value: number | undefined): string {
		if (value === undefined || Number.isNaN(value)) return '--';
		return Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value);
	}

	function formatClock(epochSeconds: number | undefined): string {
		if (!epochSeconds) return '';
		return new Date(epochSeconds * 1000).toLocaleString('en-US', {
			timeZone: 'America/New_York',
			month: 'short',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function completenessLabel(value: number | null): string {
		if (value === null) return '--';
		return `${Math.round(value * 100)}%`;
	}

	function preferredVisibleBars(): number {
		if (candles.length <= 160) return candles.length;
		if (timeframe.endsWith('m')) return 145;
		if (timeframe.endsWith('h')) return 175;
		return 220;
	}

	function candleData(): CandlestickData<Time>[] {
		return candles.map((c) => ({
			time: c.time as Time,
			open: c.open,
			high: c.high,
			low: c.low,
			close: c.close
		}));
	}

	function volumeData(): HistogramData<Time>[] {
		const col = colors();
		return volume.map((v) => ({
			time: v.time as Time,
			value: v.value,
			color: v.color || (candles.find((c) => c.time === v.time && c.close >= c.open) ? col.volumeBuy : col.volumeSell)
		}));
	}

	function vwapData(): LineData<Time>[] {
		return vwap.map((p) => ({ time: p.time as Time, value: p.value }));
	}

	function studyData(study: ChartStudy): LineData<Time>[] {
		return study.points.map((p) => ({ time: p.time as Time, value: p.value }));
	}

	function studyColor(index: number): string {
		const col = colors();
		return [col.accent, '#a78bfa', '#f97316', '#22c55e'][index % 4];
	}

	function markerData(): SeriesMarker<Time>[] {
		return markers.map((m, index) => ({
			id: `${m.time}-${index}`,
			time: m.time as Time,
			position: m.position,
			shape: m.shape,
			color: m.color,
			text: m.text,
			size: 1.18
		}));
	}

	function chartOptions(): DeepPartial<ChartOptions> {
		const col = colors();
		return {
			autoSize: true,
			layout: {
				background: { color: col.panel },
				textColor: col.text,
				fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
			},
			grid: {
				vertLines: { color: col.grid, style: LineStyle.Dotted },
				horzLines: { color: col.grid, style: LineStyle.Dotted }
			},
			crosshair: {
				mode: CrosshairMode.MagnetOHLC,
				vertLine: {
					color: col.muted,
					width: 1,
					style: LineStyle.Dashed,
					labelBackgroundColor: col.panel
				},
				horzLine: {
					color: col.muted,
					width: 1,
					style: LineStyle.Dashed,
					labelBackgroundColor: col.panel
				}
			},
			handleScroll: {
				mouseWheel: true,
				pressedMouseMove: true,
				horzTouchDrag: true,
				vertTouchDrag: false
			},
			handleScale: {
				axisPressedMouseMove: {
					time: true,
					price: true
				},
				mouseWheel: true,
				pinch: true
			},
			rightPriceScale: {
				visible: true,
				borderVisible: false,
				textColor: col.muted,
				scaleMargins: { top: 0.08, bottom: 0.08 }
			},
			leftPriceScale: { visible: false },
			timeScale: {
				rightOffset: 10,
				barSpacing: 8,
				minBarSpacing: 2,
				maxBarSpacing: 26,
				fixLeftEdge: false,
				fixRightEdge: false,
				rightBarStaysOnScroll: true,
				borderVisible: false,
				timeVisible: true,
				secondsVisible: false
			},
			localization: {
				locale: 'en-US',
				timeFormatter: (time: Time) => formatClock(Number(time))
			}
		};
	}

	function applyTheme() {
		if (!chart || !candleSeries || !volumeSeries || !vwapSeries) return;
		const col = colors();
		chart.applyOptions(chartOptions());
		candleSeries.applyOptions({
			upColor: col.buy,
			downColor: col.sell,
			borderUpColor: col.buy,
			borderDownColor: col.sell,
			wickUpColor: col.buy,
			wickDownColor: col.sell
		});
		volumeSeries.applyOptions({ color: col.volumeBuy });
		vwapSeries.applyOptions({ color: col.warn });
		studySeries.forEach((series, index) => {
			series.applyOptions({ color: studyColor(index) });
		});
		renderLevels();
	}

	function syncStudySeries() {
		if (!chart) return;
		while (studySeries.length > studies.length) {
			const series = studySeries.pop();
			if (series) chart.removeSeries(series);
		}
		while (studySeries.length < studies.length) {
			const index = studySeries.length;
			studySeries.push(
				chart.addSeries(LineSeries, {
					color: studyColor(index),
					lineWidth: 1,
					lastValueVisible: false,
					priceLineVisible: false,
					title: studies[index]?.label ?? `Study ${index + 1}`
				})
			);
		}
		studySeries.forEach((series, index) => {
			const study = studies[index];
			series.applyOptions({
				color: studyColor(index),
				title: study?.label ?? `Study ${index + 1}`
			});
			series.setData(study ? studyData(study) : []);
		});
	}

	function renderLevels() {
		if (!candleSeries) return;
		for (const line of levelLines) candleSeries.removePriceLine(line);
		levelLines = [];
		if (!levels) return;
		const col = colors();
		levelLines = [
			candleSeries.createPriceLine({
				price: levels.poc,
				color: col.muted,
				lineWidth: 1,
				lineStyle: LineStyle.Dashed,
				axisLabelVisible: true,
				title: 'POC'
			}),
			candleSeries.createPriceLine({
				price: levels.vah,
				color: col.buy,
				lineWidth: 1,
				lineStyle: LineStyle.Dotted,
				axisLabelVisible: true,
				title: 'VAH'
			}),
			candleSeries.createPriceLine({
				price: levels.val,
				color: col.sell,
				lineWidth: 1,
				lineStyle: LineStyle.Dotted,
				axisLabelVisible: true,
				title: 'VAL'
			})
		];
	}

	function setInitialViewport() {
		if (!chart || candles.length === 0) return;
		const visible = preferredVisibleBars();
		const rightOffset = Math.min(14, Math.max(7, Math.round(visible * 0.07)));
		chart.timeScale().applyOptions({ rightOffset });
		chart.timeScale().setVisibleLogicalRange({
			from: Math.max(0, candles.length - visible),
			to: candles.length + rightOffset
		});
	}

	function updateData() {
		if (!chart || !candleSeries || !volumeSeries || !vwapSeries) return;
		const candlePoints = candleData();
		candleSeries.setData(candlePoints);
		volumeSeries.setData(volumeData());
		vwapSeries.setData(vwapData());
		syncStudySeries();
		markerApi?.setMarkers(markerData());
		renderLevels();

		const nextStructureKey = candles.length
			? `${symbol}:${timeframe}:${candles[0].time}:${candles[candles.length - 1].time}:${candles.length}`
			: `${symbol}:${timeframe}:empty`;
		if (nextStructureKey !== currentStructureKey) {
			currentStructureKey = nextStructureKey;
			setInitialViewport();
		}
	}

	function createSeries() {
		if (!chart) return;
		const col = colors();
		const precision = pricePrecision();
		candleSeries = chart.addSeries(CandlestickSeries, {
			upColor: col.buy,
			downColor: col.sell,
			borderUpColor: col.buy,
			borderDownColor: col.sell,
			wickUpColor: col.buy,
			wickDownColor: col.sell,
			priceFormat: {
				type: 'price',
				precision: precision.precision,
				minMove: precision.minMove
			},
			lastValueVisible: true,
			priceLineVisible: true,
			priceLineWidth: 1,
			title: symbol
		});
		vwapSeries = chart.addSeries(LineSeries, {
			color: col.warn,
			lineWidth: 2,
			lastValueVisible: false,
			priceLineVisible: false,
			title: 'VWAP'
		});

		const volumePane = chart.addPane();
		chart.panes()[0]?.setStretchFactor(0.79);
		volumePane.setStretchFactor(0.21);
		volumeSeries = chart.addSeries(
			HistogramSeries,
			{
				color: col.volumeBuy,
				priceFormat: { type: 'volume' },
				lastValueVisible: false,
				priceLineVisible: false
			},
			1
		);
		chart.priceScale('right', 0).applyOptions({
			borderVisible: false,
			textColor: col.muted,
			scaleMargins: { top: 0.08, bottom: 0.08 }
		});
		chart.priceScale('right', 1).applyOptions({
			borderVisible: false,
			textColor: col.muted,
			scaleMargins: { top: 0.1, bottom: 0.02 }
		});
		markerApi = createSeriesMarkers(candleSeries, [], { autoScale: true });
	}

	$effect(() => {
		if (!container) return;
		chart = createChart(container, chartOptions());
		createSeries();
		updateData();

		const onCrosshairMove: Parameters<IChartApi['subscribeCrosshairMove']>[0] = (param) => {
			if (!candleSeries || !param.time) {
				hovered = null;
				return;
			}
			const candle = param.seriesData.get(candleSeries) as CandlestickData<Time> | undefined;
			if (!candle) {
				hovered = null;
				return;
			}
			const time = Number(candle.time);
			const vol = volume.find((point) => point.time === time);
			const vw = vwap.find((point) => point.time === time);
			hovered = {
				time,
				open: candle.open,
				high: candle.high,
				low: candle.low,
				close: candle.close,
				volume: vol?.value,
				vwap: vw?.value
			};
		};
		chart.subscribeCrosshairMove(onCrosshairMove);

		const themeObserver = new MutationObserver(applyTheme);
		themeObserver.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ['data-theme']
		});

		return () => {
			themeObserver.disconnect();
			chart?.unsubscribeCrosshairMove(onCrosshairMove);
			chart?.remove();
			chart = undefined;
			candleSeries = undefined;
			volumeSeries = undefined;
			vwapSeries = undefined;
			studySeries = [];
			markerApi = undefined;
			levelLines = [];
			currentStructureKey = '';
		};
	});

	$effect(() => {
		updateData();
	});
</script>

<div class="chart-shell">
	<div class="legend" class:positive={deltaClass === 'up'} class:negative={deltaClass === 'down'}>
		<div class="symbol">
			<strong>{symbol || '--'}</strong>
			<span>{timeframe || '--'}</span>
			<span>{formatClock(legend?.time)}</span>
		</div>
		<div class="ohlc">
			<span>O <b>{formatPrice(legend?.open)}</b></span>
			<span>H <b>{formatPrice(legend?.high)}</b></span>
			<span>L <b>{formatPrice(legend?.low)}</b></span>
			<span>C <b>{formatPrice(legend?.close)}</b></span>
			<span>V <b>{formatVolume(legend?.volume)}</b></span>
			<span>VWAP <b>{formatPrice(legend?.vwap)}</b></span>
		</div>
		{#if delta}
			<div class="move">
				{delta.value >= 0 ? '+' : ''}{formatPrice(delta.value)}
				<span>{delta.pct >= 0 ? '+' : ''}{delta.pct.toFixed(2)}%</span>
			</div>
		{/if}
		<div class="quality" title="Feature data completeness">
			Data {completenessLabel(dataCompleteness)}
		</div>
	</div>
	<div class="chart" bind:this={container}></div>
</div>

<style>
	.chart-shell {
		position: relative;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--panel);
	}
	.chart {
		width: 100%;
		height: 100%;
		min-height: 0;
	}
	.legend {
		position: absolute;
		z-index: 2;
		top: 10px;
		left: 12px;
		right: 72px;
		display: flex;
		align-items: center;
		gap: 0.75rem;
		min-height: 30px;
		pointer-events: none;
		color: var(--muted);
		font-size: 0.76rem;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.symbol,
	.ohlc,
	.move,
	.quality {
		display: inline-flex;
		align-items: center;
		gap: 0.45rem;
		min-width: 0;
		padding: 0.34rem 0.5rem;
		border: 1px solid color-mix(in srgb, var(--border) 78%, transparent);
		border-radius: 6px;
		background: color-mix(in srgb, var(--panel) 92%, transparent);
		backdrop-filter: blur(10px);
	}
	.symbol strong {
		color: var(--text);
		font-size: 0.82rem;
	}
	.ohlc {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.ohlc b {
		color: var(--text);
		font-weight: 600;
	}
	.move {
		color: var(--buy);
		font-weight: 700;
	}
	.negative .move {
		color: var(--sell);
	}
	.move span {
		font-weight: 600;
		color: inherit;
	}
	.quality {
		margin-left: auto;
		color: var(--muted);
	}
	@media (max-width: 980px) {
		.legend {
			right: 12px;
			flex-wrap: wrap;
			align-items: flex-start;
			white-space: normal;
		}
		.quality {
			margin-left: 0;
		}
	}
	@media (max-width: 680px) {
		.legend {
			top: 8px;
			left: 8px;
			right: 8px;
			gap: 0.4rem;
			font-size: 0.7rem;
		}
		.symbol,
		.ohlc,
		.move,
		.quality {
			padding: 0.28rem 0.42rem;
		}
	}
</style>
