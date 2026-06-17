// TypeScript mirror of the backend domain + websocket protocol.
// Kept in sync with backend/src/intradayx/domain/signals.py and the Phase-5
// websocket contract. JSON numbers are fine for prices; money/P&L in cents
// would be `number` (JS is exact to 2^53).

export type Side = 'buy' | 'sell' | 'short' | 'cover' | 'exit';
export type SignalKind = 'reversal_top' | 'reversal_bottom' | 'scalp_long' | 'scalp_short';
export type Scanner = 'reversal' | 'scalping';
export type TodBucket =
	| 'premarket'
	| 'open_drive'
	| 'morning'
	| 'lunch'
	| 'afternoon'
	| 'power_hour'
	| 'afterhours';

export interface Cause {
	kind: string;
	score: number; // 0..1 contribution share
	source: 'rule' | 'model';
	label: string;
}

export interface Attribution {
	ranked_causes: Cause[];
	data_completeness: number; // 0..1
	uncertain: boolean;
	caveat: string;
	summary: string;
}

export interface Signal {
	signal_id: string;
	symbol: string;
	ts: string; // ISO-8601 UTC (bar close that produced it)
	kind: SignalKind;
	side: Side;
	confidence: number; // 0..1, already scaled by data_completeness
	entry: number;
	stop: number;
	targets: number[];
	time_of_day_bucket: TodBucket;
	attribution: Attribution;
	quality_score?: number;
	meta_score?: number | null;
}

// --- websocket protocol (Phase 5) ---

export interface WsEnvelope<T> {
	v: number;
	type: string;
	ts: number; // server send time, epoch ms
	data: T;
}

export interface StatusData {
	source: string; // honest provenance, e.g. "yfinance"
	mode: 'poll' | 'stream';
	poll_interval_s?: number;
	market_session: 'pre' | 'rth' | 'post' | 'closed';
	watched: string[];
	engine_version: string;
}

export type WsMessage =
	| WsEnvelope<StatusData> // type: "status"
	| WsEnvelope<{ next_poll_in_s: number }> // type: "heartbeat"
	| WsEnvelope<Signal> // type: "signal"
	| WsEnvelope<{ signal_id: string; reason: string }> // type: "signal_revoke"
	| WsEnvelope<{ code: string; retry_in_s: number }>; // type: "error"

export function uiDirection(side: Side): 'buy' | 'sell' {
	return side === 'buy' || side === 'cover' ? 'buy' : 'sell';
}

// --- REST payloads (mirror backend api/schemas.py) ---

export interface ChartCandle {
	time: number;
	open: number;
	high: number;
	low: number;
	close: number;
}
export interface ChartVolume {
	time: number;
	value: number;
	color: string;
}
export interface ChartLine {
	time: number;
	value: number;
}
export interface ChartMarker {
	time: number;
	position: 'aboveBar' | 'belowBar' | 'inBar';
	shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
	color: string;
	text: string;
}
export interface Levels {
	poc: number;
	vah: number;
	val: number;
}
export interface ChartStudy {
	key: string;
	label: string;
	pane: 'price' | string;
	points: ChartLine[];
}
export interface BarsPayload {
	symbol: string;
	timeframe: string;
	candles: ChartCandle[];
	volume: ChartVolume[];
	vwap: ChartLine[];
	studies: ChartStudy[];
	markers: ChartMarker[];
	levels: Levels | null;
	data_completeness: number;
}
export interface ScanPayload {
	symbol: string;
	timeframe: string;
	n_bars: number;
	data_completeness: number;
	signals: Signal[];
}
