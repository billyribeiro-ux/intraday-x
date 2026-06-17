// Live tick stream from Financial Modeling Prep's WebSocket feeds.
// FMP provides three endpoints: US stocks, crypto, and forex. After login with
// the user's API key we subscribe to a ticker/pair and surface the last trade
// tick so the chart can update in real time.

import { browser } from '$app/environment';
import { getVendorKey } from '$lib/api/settings';

export type FmpAssetClass = 'stock' | 'crypto' | 'forex';

export interface FmpTick {
	ts: number; // epoch milliseconds
	price: number;
	size: number;
	type: 'T' | 'Q' | 'B';
}

const ENDPOINTS: Record<FmpAssetClass, string> = {
	stock: 'wss://websockets.financialmodelingprep.com',
	crypto: 'wss://crypto.financialmodelingprep.com',
	forex: 'wss://forex.financialmodelingprep.com'
};

export class FmpLiveStore {
	status = $state<'idle' | 'connecting' | 'open' | 'error'>('idle');
	error = $state<string | null>(null);
	lastTick = $state<FmpTick | null>(null);

	#ws: WebSocket | null = null;
	#symbol = '';
	#assetClass: FmpAssetClass = 'stock';
	#apiKey = '';
	#generation = 0;

	async connect(symbol: string, assetClass: FmpAssetClass): Promise<void> {
		if (!browser) return;
		this.disconnect();
		const generation = ++this.#generation;
		this.#symbol = symbol;
		this.#assetClass = assetClass;
		this.status = 'connecting';
		this.error = null;
		this.lastTick = null;

		try {
			this.#apiKey = await getVendorKey('fmp');
		} catch (err) {
			if (generation !== this.#generation) return;
			this.status = 'error';
			this.error = err instanceof Error ? err.message : 'no FMP API key';
			return;
		}

		if (generation !== this.#generation) return;
		this.#open(generation);
	}

	#formatSymbol(symbol: string): string {
		const cleaned = symbol.replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
		if (this.#assetClass === 'forex') {
			// FMP forex pairs are six-letter codes, e.g. eurusd.
			return cleaned.slice(0, 6);
		}
		if (this.#assetClass === 'crypto') {
			// FMP crypto pairs are e.g. btcusd.
			return cleaned;
		}
		return cleaned;
	}

	#open(generation: number): void {
		if (generation !== this.#generation) return;
		const ws = new WebSocket(ENDPOINTS[this.#assetClass]);
		this.#ws = ws;

		ws.onopen = () => {
			ws.send(JSON.stringify({ event: 'login', data: { apiKey: this.#apiKey } }));
		};
		ws.onmessage = (ev) => this.#onMessage(ev, generation, ws);
		ws.onerror = () => {
			this.error = 'FMP websocket error';
			ws.close();
		};
		ws.onclose = () => {
			if (generation !== this.#generation) return;
			if (this.status === 'open') {
				this.status = 'error';
				this.error = this.error ?? 'FMP connection closed';
			} else if (!this.error) {
				this.status = 'error';
				this.error = 'FMP connection failed';
			}
		};
	}

	#onMessage(ev: MessageEvent, generation: number, ws: WebSocket): void {
		if (generation !== this.#generation) return;
		let msg: Record<string, unknown>;
		try {
			msg = JSON.parse(ev.data as string);
		} catch {
			return;
		}

		if (msg.event === 'login') {
			if (msg.status === 200) {
				this.status = 'open';
				ws.send(
					JSON.stringify({
						event: 'subscribe',
						data: { ticker: [this.#formatSymbol(this.#symbol)] }
					})
				);
			} else {
				this.status = 'error';
				this.error = typeof msg.message === 'string' ? msg.message : 'FMP login failed';
				ws.close();
			}
			return;
		}

		// Trade ('T') and quote ('Q') messages carry price fields.
		const price =
			typeof msg.lp === 'number'
				? msg.lp
				: typeof msg.ap === 'number'
					? msg.ap
					: typeof msg.bp === 'number'
						? msg.bp
						: undefined;
		if (price == null) return;

		let ts = typeof msg.t === 'number' ? msg.t : Date.now();
		// FMP timestamps can be seconds or milliseconds; normalize to ms.
		if (ts < 1_000_000_000_000) ts *= 1000;

		this.lastTick = {
			ts,
			price,
			size: typeof msg.ls === 'number' ? msg.ls : 0,
			type: (msg.type as 'T' | 'Q' | 'B') || 'T'
		};
	}

	disconnect(): void {
		this.#generation++;
		this.status = 'idle';
		this.error = null;
		this.lastTick = null;
		if (this.#ws) {
			this.#ws.onclose = null;
			this.#ws.close();
			this.#ws = null;
		}
	}
}
