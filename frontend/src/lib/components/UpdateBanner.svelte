<script lang="ts">
	// Non-blocking, full-width auto-update banner. Sits above `.app` in the
	// layout. Renders nothing in the resting states (idle / uptodate /
	// unsupported / unconfigured / checking) and only intrudes when there is an
	// actionable update or an in-flight install.
	import { ArrowClockwiseIcon, DownloadIcon, XIcon } from '$lib/icons';
	import { updater } from '$lib/updates/updater.svelte';

	// Whole-number percent for the progress bar / label. Indeterminate
	// (progress === null) renders an animated stripe instead of a fill.
	const pct = $derived(
		updater.progress === null ? null : Math.round(updater.progress * 100)
	);
</script>

{#if updater.status === 'available'}
	<div class="banner" role="status">
		<DownloadIcon size={18} weight="fill" />
		<span class="msg">Update available — v{updater.version}</span>
		<div class="actions">
			<button type="button" class="primary" onclick={() => updater.downloadAndInstall()}>
				<ArrowClockwiseIcon size={15} weight="bold" />
				Update &amp; Restart
			</button>
			<button
				type="button"
				class="dismiss"
				aria-label="Dismiss update notification"
				onclick={() => updater.dismiss()}
			>
				<XIcon size={15} weight="bold" />
			</button>
		</div>
	</div>
{:else if updater.status === 'downloading'}
	<div class="banner" role="status" aria-live="polite">
		<DownloadIcon size={18} weight="fill" />
		<span class="msg">
			Downloading update{pct === null ? '…' : ` — ${pct}%`}
		</span>
		<div
			class="progress"
			class:indeterminate={pct === null}
			role="progressbar"
			aria-valuemin={0}
			aria-valuemax={100}
			aria-valuenow={pct ?? undefined}
		>
			<div class="bar" style:width={pct === null ? undefined : `${pct}%`}></div>
		</div>
	</div>
{:else if updater.status === 'ready'}
	<div class="banner" role="status" aria-live="polite">
		<ArrowClockwiseIcon size={18} weight="fill" />
		<span class="msg">Restarting…</span>
	</div>
{/if}

<style>
	.banner {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		width: 100%;
		padding: 0.6rem 1.25rem;
		border-bottom: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border));
		background: color-mix(in srgb, var(--accent) 12%, var(--panel));
		color: var(--text);
		font-size: 0.875rem;
	}
	.msg {
		font-weight: 600;
	}
	.actions {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-left: auto;
	}
	.primary {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.4rem 0.8rem;
		border-radius: 6px;
		border: 1px solid var(--accent);
		background: var(--accent);
		color: var(--bg);
		font-size: 0.825rem;
		font-weight: 600;
		cursor: pointer;
		transition:
			filter 0.12s ease,
			background-color 0.12s ease;
	}
	.primary:hover {
		filter: brightness(1.08);
	}
	.primary:focus-visible {
		outline: 2px solid var(--text);
		outline-offset: 2px;
	}
	.dismiss {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border-radius: 6px;
		border: 1px solid var(--border);
		background: transparent;
		color: var(--muted);
		cursor: pointer;
		transition:
			color 0.12s ease,
			border-color 0.12s ease;
	}
	.dismiss:hover {
		color: var(--text);
		border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
	}
	.dismiss:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.progress {
		margin-left: auto;
		flex: 0 0 200px;
		height: 6px;
		border-radius: 999px;
		background: color-mix(in srgb, var(--accent) 18%, var(--panel));
		overflow: hidden;
	}
	.bar {
		height: 100%;
		border-radius: 999px;
		background: var(--accent);
		transition: width 0.15s ease;
	}
	.progress.indeterminate .bar {
		width: 40%;
		animation: slide 1.1s ease-in-out infinite;
	}
	@keyframes slide {
		0% {
			margin-left: -40%;
		}
		100% {
			margin-left: 100%;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.progress.indeterminate .bar {
			animation: none;
			width: 100%;
			opacity: 0.6;
		}
	}
</style>
