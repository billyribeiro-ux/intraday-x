# 0005 — Config-driven provider registry

## Status

Accepted.

## Context

ADR 0001 made each vendor a capability-declaring `DataProvider`. But the
requirement is stronger than "support multiple vendors" — it's that
choosing "a different provider, or several composed together" must be a
**config** change, not a code change, and must hold up to principal-grade
rigor (no subtly-wrong adapter slipping in). A hardcoded factory that
news up a fixed provider list defeats that: every deployment with a
different data subscription would need an edit and a redeploy.

## Decision

Assemble the active data layer from **typed config** via a **provider
registry**:

- `config.py` is `pydantic-settings` (`env_prefix="INTRADAYX_"`); the
  `providers: list[str]` field (default `["polygon", "alpaca",
  "yfinance"]`, overridable via `INTRADAYX_PROVIDERS`) is the **priority
  list** — order is preference.
- `data/registry.py` exposes `register_provider(name, factory)` and
  `build_provider(settings)`. Vendors self-register by name (yfinance,
  alpaca, polygon today). `build_provider` walks the config list, skips
  any name not in the registry, and skips any provider whose
  `is_configured()` is `False` (no credentials) — so a missing API key
  silently drops that vendor instead of erroring on every request.
  **yfinance is the floor**: if nothing is configured, it falls back to
  yfinance. The result is wrapped in a `CompositeProvider` carrying the
  per-vendor priorities.
- Adding a vendor is two lines: `register_provider("x", XProvider)` plus
  listing `"x"` in `INTRADAYX_PROVIDERS` — no call-site edits.
- A **contract test** runs every registered provider through the
  `DataProvider` interface invariants, so a subtly-wrong adapter fails CI
  rather than production.

## Consequences

**Positive.** Add, swap, or compose vendors by one env var plus a two-line
registration. Credential-gated vendors degrade gracefully (skipped, not
fatal). The contract test prevents adapters that violate the interface
from shipping.

**Negative / tradeoffs.** A bit more indirection — the active stack is
resolved at runtime from config rather than being visible as a literal in
code, so debugging "which provider answered" goes through the log line
`build_provider` emits and the `source` column on the merged `BarSet`.

## Alternatives considered

- **A hardcoded factory** (what this replaced). Simple, but every change
  of data subscription is a code edit + redeploy, and there's no single
  seam for the contract test to enforce interface invariants.
