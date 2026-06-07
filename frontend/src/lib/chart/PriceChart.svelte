<script lang="ts">
	import {
		CandlestickSeries,
		ColorType,
		createChart,
		createSeriesMarkers,
		HistogramSeries,
		LineSeries,
		LineStyle,
		type CandlestickData,
		type HistogramData,
		type IChartApi,
		type IPriceLine,
		type ISeriesApi,
		type ISeriesMarkersPluginApi,
		type LineData,
		type SeriesMarker,
		type Time,
		type UTCTimestamp
	} from 'lightweight-charts';

	interface Levels {
		poc: number;
		vah: number;
		val: number;
	}

	interface Props {
		candles: CandlestickData<UTCTimestamp>[];
		volume: HistogramData<UTCTimestamp>[];
		vwap: LineData<UTCTimestamp>[];
		markers?: SeriesMarker<UTCTimestamp>[];
		levels?: Levels | null;
		height?: number;
	}

	let { candles, volume, vwap, markers = [], levels = null, height = 420 }: Props = $props();

	// Imperative chart handles — deliberately NOT $state (they're not UI state).
	let container = $state<HTMLDivElement>();
	let chart: IChartApi | undefined;
	let candleSeries: ISeriesApi<'Candlestick'> | undefined;
	let volumeSeries: ISeriesApi<'Histogram'> | undefined;
	let vwapSeries: ISeriesApi<'Line'> | undefined;
	// createSeriesMarkers infers the series' default horizontal scale type (Time);
	// our UTCTimestamp values are valid Time values (covariant), so this is fine.
	let markersApi: ISeriesMarkersPluginApi<Time> | undefined;
	let priceLines: IPriceLine[] = [];

	// 1) create + destroy (runs once; teardown removes the chart).
	$effect(() => {
		if (!container) return;
		const c = createChart(container, {
			autoSize: true,
			layout: {
				background: { type: ColorType.Solid, color: '#0e1117' },
				textColor: '#c9d1d9',
				attributionLogo: true // Apache-2.0 attribution; leave on.
			},
			grid: { vertLines: { color: '#1b2230' }, horzLines: { color: '#1b2230' } },
			timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#30363d' },
			rightPriceScale: { borderColor: '#30363d' }
		});
		candleSeries = c.addSeries(CandlestickSeries, {
			upColor: '#26a69a',
			downColor: '#ef5350',
			borderVisible: false,
			wickUpColor: '#26a69a',
			wickDownColor: '#ef5350'
		});
		volumeSeries = c.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '' }, 1);
		vwapSeries = c.addSeries(LineSeries, { color: '#e3b341', lineWidth: 1 });
		markersApi = createSeriesMarkers(candleSeries, []);
		chart = c;

		return () => {
			c.remove();
			chart = candleSeries = volumeSeries = vwapSeries = markersApi = undefined;
			priceLines = [];
		};
	});

	// 2) push data (re-runs when the data props change — never recreates the chart).
	$effect(() => {
		if (!candleSeries || !volumeSeries || !vwapSeries || !markersApi) return;
		candleSeries.setData(candles);
		volumeSeries.setData(volume);
		vwapSeries.setData(vwap);
		markersApi.setMarkers(markers);

		for (const pl of priceLines) candleSeries.removePriceLine(pl);
		priceLines = [];
		if (levels) {
			priceLines = [
				candleSeries.createPriceLine({ price: levels.poc, color: '#8b949e', lineStyle: LineStyle.Dashed, lineWidth: 1, title: 'POC' }),
				candleSeries.createPriceLine({ price: levels.vah, color: '#3fb950', lineStyle: LineStyle.Dotted, lineWidth: 1, title: 'VAH' }),
				candleSeries.createPriceLine({ price: levels.val, color: '#f85149', lineStyle: LineStyle.Dotted, lineWidth: 1, title: 'VAL' })
			];
		}
		chart?.timeScale().fitContent();
	});
</script>

<!-- Fixed height => no layout shift when data loads. -->
<div class="chart" bind:this={container} style="height: {height}px"></div>

<style>
	.chart {
		width: 100%;
		border: 1px solid #1b2230;
		border-radius: 8px;
		overflow: hidden;
	}
</style>
