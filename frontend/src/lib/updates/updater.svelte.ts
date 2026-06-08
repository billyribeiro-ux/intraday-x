// In-app auto-update service for the Tauri desktop shell.
//
// A single reactive singleton (`updater`) drives both the full-width
// `UpdateBanner` and the Settings "Software update" section. All Tauri APIs
// are lazy-imported so the plain browser build (and SSR) never pull them in;
// outside Tauri the machine parks in 'unsupported' and renders nothing.
//
// The plugin throws when the app has no `plugins.updater` block (no signing
// pubkey / no endpoints) — that's the expected state for dev and unsigned
// builds, so we map it to 'unconfigured' rather than surfacing a scary error.
// Genuine failures (network, signature mismatch) DO surface in 'error' with a
// message — no silent catch.

import type { DownloadEvent, Update } from '@tauri-apps/plugin-updater';

export type UpdateStatus =
	| 'idle'
	| 'checking'
	| 'uptodate'
	| 'available'
	| 'downloading'
	| 'ready'
	| 'error'
	| 'unsupported' // not running inside Tauri (browser / SSR)
	| 'unconfigured'; // Tauri, but no updater endpoints/pubkey configured

/** True only inside the bundled Tauri webview. */
function inTauri(): boolean {
	return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

/**
 * The plugin surfaces "no updater config" as a thrown error rather than a
 * distinct status. Sniff its message so dev/unsigned builds degrade to
 * 'unconfigured' instead of 'error'. Matches the strings the Rust core emits
 * when the config block or endpoints are missing.
 */
function isUnconfiguredError(message: string): boolean {
	const m = message.toLowerCase();
	return (
		m.includes('updater') &&
		(m.includes('not configured') ||
			m.includes('no configuration') ||
			m.includes('missing') ||
			m.includes('no endpoint') ||
			m.includes('endpoints') ||
			m.includes('pubkey') ||
			m.includes('public key'))
	);
}

class Updater {
	status = $state<UpdateStatus>('idle');
	/** Available version (set once an update is found). */
	version = $state<string | null>(null);
	/** Release notes / changelog body, when the manifest provides one. */
	notes = $state<string | null>(null);
	/** Download progress in 0..1, or null while indeterminate. */
	progress = $state<number | null>(null);
	/** Human-readable error message when status === 'error'. */
	error = $state<string | null>(null);

	// Held between check() and downloadAndInstall() so we install the exact
	// Update we found. Not reactive — it's an opaque resource handle.
	#pending: Update | null = null;

	/**
	 * Check the configured endpoint for a newer release.
	 * - Not in Tauri              → 'unsupported'
	 * - No updater config/pubkey  → 'unconfigured'
	 * - Newer release available   → 'available' (+version/+notes)
	 * - Already current           → 'uptodate'
	 * - Anything else (network…)  → 'error' (+message)
	 */
	check = async (): Promise<void> => {
		if (!inTauri()) {
			this.status = 'unsupported';
			return;
		}

		this.status = 'checking';
		this.error = null;

		try {
			const { check } = await import('@tauri-apps/plugin-updater');
			const update = await check();

			if (update) {
				this.#pending = update;
				this.version = update.version;
				this.notes = update.body ?? null;
				this.status = 'available';
			} else {
				this.#pending = null;
				this.version = null;
				this.notes = null;
				this.status = 'uptodate';
			}
		} catch (e) {
			const message = e instanceof Error ? e.message : String(e);
			if (isUnconfiguredError(message)) {
				this.status = 'unconfigured';
			} else {
				this.error = message;
				this.status = 'error';
			}
		}
	};

	/**
	 * Download + install the pending update, reporting progress, then relaunch.
	 * Must be called only when status === 'available'. Errors surface in
	 * 'error' — never swallowed.
	 */
	downloadAndInstall = async (): Promise<void> => {
		if (!inTauri()) {
			this.status = 'unsupported';
			return;
		}
		const update = this.#pending;
		if (!update) {
			// Nothing staged — make the caller re-check rather than guess.
			this.error = 'No update has been found yet. Check for updates first.';
			this.status = 'error';
			return;
		}

		this.status = 'downloading';
		this.progress = 0;
		this.error = null;

		let downloaded = 0;
		let contentLength = 0;

		try {
			await update.downloadAndInstall((event: DownloadEvent) => {
				switch (event.event) {
					case 'Started':
						contentLength = event.data.contentLength ?? 0;
						this.progress = 0;
						break;
					case 'Progress':
						downloaded += event.data.chunkLength;
						// Indeterminate (null) if the server didn't send a length.
						this.progress = contentLength > 0 ? downloaded / contentLength : null;
						break;
					case 'Finished':
						this.progress = 1;
						break;
				}
			});

			this.status = 'ready';

			const { relaunch } = await import('@tauri-apps/plugin-process');
			await relaunch();
		} catch (e) {
			const message = e instanceof Error ? e.message : String(e);
			this.error = message;
			this.status = 'error';
		}
	};

	/** Dismiss a non-blocking 'available' banner without installing. */
	dismiss = (): void => {
		if (this.status === 'available') {
			this.status = 'idle';
		}
	};
}

/** App-wide singleton. Import and use directly in components. */
export const updater = new Updater();
