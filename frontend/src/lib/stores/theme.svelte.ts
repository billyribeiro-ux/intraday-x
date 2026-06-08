// Theme store — Svelte 5 runes. Owns the user's theme *preference*
// ('dark' | 'light' | 'system') and the *resolved* theme actually applied to
// the DOM ('dark' | 'light'). The preference persists to localStorage; the
// 'system' preference resolves via matchMedia and reacts to OS changes.
//
// This is a module-level singleton that lives OUTSIDE the component tree, so it
// can't rely on $effect for the matchMedia subscription — it wires the listener
// imperatively in init() and applies the theme by mutating
// document.documentElement.dataset.theme. All browser APIs are guarded with
// `typeof window` so importing this module is safe during SSR / non-browser.

export type ThemeMode = 'dark' | 'light' | 'system';
export type ResolvedTheme = 'dark' | 'light';

const STORAGE_KEY = 'intraday-x:theme';
// Dark-first app: when we can't read a preference (SSR, no storage), default to
// dark so there's no light flash before hydration.
const DEFAULT_MODE: ThemeMode = 'dark';

function isBrowser(): boolean {
	return typeof window !== 'undefined';
}

function readStoredMode(): ThemeMode {
	if (!isBrowser()) return DEFAULT_MODE;
	try {
		const raw = window.localStorage.getItem(STORAGE_KEY);
		if (raw === 'dark' || raw === 'light' || raw === 'system') return raw;
	} catch {
		// localStorage can throw (private mode, disabled storage). Fail to the
		// default rather than crashing the app shell.
	}
	return DEFAULT_MODE;
}

function systemPrefersDark(): boolean {
	if (!isBrowser() || typeof window.matchMedia !== 'function') return true;
	return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

class ThemeStore {
	/** The user's chosen preference. */
	mode = $state<ThemeMode>(DEFAULT_MODE);
	/** The theme actually applied to <html> — 'system' collapsed to dark/light. */
	resolved = $state<ResolvedTheme>('dark');

	#mql: MediaQueryList | null = null;
	#onSystemChange = () => {
		// Only the 'system' preference cares about OS changes.
		if (this.mode === 'system') this.#apply();
	};

	/**
	 * Read the stored preference, apply it to the DOM, and subscribe to OS
	 * theme changes. Safe to call from a component's top level or layout; a
	 * no-op (beyond reading the default) outside the browser. Idempotent.
	 */
	init() {
		this.mode = readStoredMode();
		if (!isBrowser()) {
			this.resolved = 'dark';
			return;
		}
		if (!this.#mql && typeof window.matchMedia === 'function') {
			this.#mql = window.matchMedia('(prefers-color-scheme: dark)');
			this.#mql.addEventListener('change', this.#onSystemChange);
		}
		this.#apply();
	}

	/** Set an explicit preference, persist it, and apply it. */
	setTheme(mode: ThemeMode) {
		this.mode = mode;
		if (isBrowser()) {
			try {
				window.localStorage.setItem(STORAGE_KEY, mode);
			} catch {
				// Persisting is best-effort; the in-memory choice still applies.
			}
		}
		this.#apply();
	}

	/** Cycle dark -> light -> system -> dark. Used by the topbar toggle. */
	cycle() {
		const next: ThemeMode =
			this.mode === 'dark' ? 'light' : this.mode === 'light' ? 'system' : 'dark';
		this.setTheme(next);
	}

	/** Resolve the current preference and write it to <html data-theme>. */
	#apply() {
		const resolved: ResolvedTheme =
			this.mode === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : this.mode;
		this.resolved = resolved;
		if (isBrowser()) {
			document.documentElement.dataset.theme = resolved;
		}
	}
}

export const theme = new ThemeStore();
