# Architecture Decision Records

This directory holds the **Architecture Decision Records (ADRs)** for
intraday-x. An ADR captures a single significant design choice: the
context that forced it, the decision taken, the consequences (good *and*
bad), and the alternatives that were weighed and rejected. ADRs are
immutable once accepted — when a decision changes, a new ADR supersedes
the old one rather than editing history. They exist so that six months
from now nobody has to re-derive *why* the data layer raises instead of
returning empty, or why the backtester isn't Nautilus.

These records are grounded in the codebase as built — see
`docs/ARCHITECTURE.md` and `docs/ROADMAP.md` for the broader narrative
and `docs/AI_LANDMINES.md` for the runtime traps each decision avoids.

## Index

| # | Title | One-line summary |
|---|---|---|
| [0001](0001-capability-gated-vendor-agnostic-data-layer.md) | Capability-gated, vendor-agnostic data layer | A `DataProvider` ABC + `Capability` enum + `ProviderCapabilities`; features gate on capabilities and stay dormant rather than fabricate. |
| [0002](0002-shared-signal-engine-custom-backtester.md) | Shared SignalEngine + custom backtester | One `SignalEngine.evaluate(FeatureSet)` drives both backtest and live; a custom event-driven backtester instead of `nautilus_trader` for now. |
| [0003](0003-honesty-contract.md) | The honesty contract | Every signal carries `data_completeness`; attribution is correlational with a mandatory caveat; "cause uncertain" is a first-class output. |
| [0004](0004-money-in-integer-cents.md) | Money in integer cents | All money/P&L is integer cents (i64 / BIGINT), never floats-as-dollars or i32. |
| [0005](0005-config-driven-provider-registry.md) | Config-driven provider registry | The active data layer is assembled from a typed config priority list via a provider registry; unconfigured vendors are skipped. |
