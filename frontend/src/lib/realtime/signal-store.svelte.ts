// Runes-based realtime signal store. In Phase 0 it simply holds seed (demo)
// signals. When `connect(url)` is called (Phase 5) it opens a websocket with
// exponential backoff + a heartbeat watchdog and prepends incoming signals.
// We export a class instance (you cannot export reassigned $state directly).

import { browser } from '$app/environment';

import type { Signal, StatusData, WsMessage } from '$lib/api/types';

const MAX_SIGNALS = 500;
const HEARTBEAT_TIMEOUT_MS = 25_000;
const BACKOFF_START_MS = 500;
const BACKOFF_MAX_MS = 15_000;

export type ConnState = 'demo' | 'connecting' | 'open' | 'reconnecting' | 'closed';

export class SignalStore {
	status = $state<ConnState>('demo');
	serverStatus = $state<StatusData | null>(null);
	error = $state<string | null>(null);
	// Immutable records — reassign the array on change rather than deep-proxy it.
	signals = $state.raw<Signal[]>([]);

	#ws: WebSocket | null = null;
	#url: string | null = null;
	#backoff = BACKOFF_START_MS;
	#lastHeartbeat = 0;
	#watchdog: ReturnType<typeof setInterval> | null = null;
	#reconnect: ReturnType<typeof setTimeout> | null = null;

	constructor(seed: Signal[] = []) {
		this.signals = seed;
	}

	connect(url: string): void {
		if (!browser) return;
		this.#url = url;
		this.#open();
	}

	#open(): void {
		if (!this.#url) return;
		this.status = this.#ws ? 'reconnecting' : 'connecting';
		const ws = new WebSocket(this.#url);
		this.#ws = ws;

		ws.onopen = () => {
			this.status = 'open';
			this.error = null;
			this.#backoff = BACKOFF_START_MS;
			this.#lastHeartbeat = Date.now();
			this.#startWatchdog();
		};
		ws.onmessage = (ev) => this.#onMessage(ev);
		ws.onclose = () => this.#scheduleReconnect();
		ws.onerror = () => {
			this.error = 'websocket error';
			ws.close();
		};
	}

	#onMessage(ev: MessageEvent): void {
		let msg: WsMessage;
		try {
			msg = JSON.parse(ev.data) as WsMessage;
		} catch {
			return;
		}
		this.#lastHeartbeat = Date.now();
		switch (msg.type) {
			case 'status':
				this.serverStatus = msg.data as StatusData;
				break;
			case 'signal':
				this.signals = [msg.data as Signal, ...this.signals].slice(0, MAX_SIGNALS);
				break;
			case 'signal_revoke': {
				const { signal_id } = msg.data as { signal_id: string };
				this.signals = this.signals.filter((s) => s.signal_id !== signal_id);
				break;
			}
			case 'error':
				this.error = (msg.data as { code: string }).code;
				break;
		}
	}

	#startWatchdog(): void {
		this.#stopWatchdog();
		this.#watchdog = setInterval(() => {
			if (Date.now() - this.#lastHeartbeat > HEARTBEAT_TIMEOUT_MS) {
				this.#ws?.close(); // triggers reconnect via onclose
			}
		}, 5_000);
	}

	#stopWatchdog(): void {
		if (this.#watchdog) clearInterval(this.#watchdog);
		this.#watchdog = null;
	}

	#scheduleReconnect(): void {
		this.#stopWatchdog();
		this.status = 'reconnecting';
		const jitter = this.#backoff * 0.2 * (Math.random() - 0.5);
		const delay = Math.min(this.#backoff + jitter, BACKOFF_MAX_MS);
		this.#backoff = Math.min(this.#backoff * 2, BACKOFF_MAX_MS);
		this.#reconnect = setTimeout(() => this.#open(), delay);
	}

	destroy(): void {
		this.#stopWatchdog();
		if (this.#reconnect) clearTimeout(this.#reconnect);
		this.#reconnect = null;
		if (this.#ws) {
			this.#ws.onclose = null;
			this.#ws.close();
		}
		this.#ws = null;
		this.status = 'closed';
	}
}
