# 0001 — Capability-gated, vendor-agnostic data layer

## Status

Accepted.

## Context

intraday-x must run today on free, zero-setup data (yfinance) and later
light up paid market internals ($TICK/$TRIN/$ADD/$VOLD), options chains,
and short-interest feeds — with **no rewrite** of the features and
detectors that consume them. No single vendor supplies everything:
breadth internals come from a TOS/Schwab-style feed, options greeks from
ORATS/OPRA, short interest from FINRA/Ortex. Worse, the easy failure mode
for a scanner is to *fabricate* a missing input — silently reading "no
$TICK extreme" when in truth there was no $TICK feed at all. That is the
exact "confident wrong answer" the honesty contract (ADR 0003) forbids.

## Decision

Model data sources behind a `DataProvider` ABC (`data/provider.py`).
`capabilities()` and `bars()` are abstract; every optional surface —
`internals`, `options_chain`, `short_interest`, `short_volume`,
`borrow_rate`, `earnings_dates` — defaults to **raising `CapabilityError`**.
A concrete provider overrides only what it genuinely supplies.

Each provider declares a `ProviderCapabilities` (`domain/capabilities.py`):
a `frozenset[Capability]` plus a per-`Timeframe` `max_intraday_lookback`
map. `Capability` is a `StrEnum` catalog (`INTRADAY_BARS_1M`,
`INTERNALS_TICK`, `OPTIONS_GREEKS`, `SHORT_INTEREST`, ...) with family
groupings (`INTERNALS_BREADTH`, `OPTIONS_FULL`, `SHORT_FULL`). Features
and detectors call `caps.supports(...)` / `supports_all(...)` first and
stay **dormant** when the capability is absent — they never call through
and never invent data. `_check_lookback()` raises `LookbackExceededError`
rather than quietly truncating a backtest window.

## Consequences

**Positive.** Adding a vendor is additive, not invasive: a new provider
declaring `INTERNALS_*`/`OPTIONS_*` auto-activates the gated code (Phases
7–9) with zero edits to feature/detector code. Degradation is honest and
measurable — absent capabilities lower a signal's `data_completeness`,
surfaced in the UI/PDF.

**Negative / tradeoffs.** More upfront abstraction than a direct vendor
call, and every consumer pays a small gating-boilerplate tax
(`supports(...)` guards). The capability catalog must be kept in sync as
new data dimensions appear.

## Alternatives considered

- **Hardcode yfinance.** Fastest to ship, but every paid feed later
  becomes a rewrite, and there is no honest place to record "this input
  was unavailable."
- **A thin adapter without capabilities.** Normalizes vendor I/O but
  can't express *what's missing* — consumers would have to infer absence
  from empty returns, which is exactly the silent-misread bug.
