# 0002 — Shared SignalEngine + custom event-driven backtester

## Status

Accepted.

## Context

The core requirement of intraday-x is **backtest↔live parity**: a
backtested edge is only trustworthy if the live path runs identical
logic, bar for bar. Any architecture where signal logic lives inside the
backtest runtime (or the live runtime) risks the two forking and drifting
apart — the classic "looks great in backtest, trades differently live"
trap (`AI_LANDMINES.md` #11).

The roadmap originally named `nautilus_trader` for the backtest engine.
Nautilus is a heavy Rust-backed dependency whose real value — realistic
broker execution and a live trading gateway — is not needed for *research*
backtests. The plan explicitly preserved a custom event-driven engine as
the sanctioned fallback "in case Nautilus's data model proves too heavy
for early iteration."

## Decision

Make `SignalEngine.evaluate(FeatureSet)` (`signals/engine.py`) **the single
source of truth** for signals. It is strategy-driven (a `Strategy`
protocol; `ReversalStrategy`/`ScalpingStrategy`) and is called by both the
backtester and the live monitor — only the source of bars differs. Signal
identity is deterministic via `make_signal_id(symbol, ts, kind,
params_version)`, so a re-poll never re-fires and the two paths agree on
identity.

Build a **custom event-driven backtester** (`backtest/runner.py`:
`simulate_trades()` is pure/deterministic; `run_backtest()` scans via the
shared engine then simulates). Fills are on the **next bar** (no same-bar
lookahead), with slippage + commission, single-position, stop/first-target
plus a bar-count time-stop, and P&L in integer cents (ADR 0004). Because
all signal logic lives *outside* the runtime, parity holds regardless of
the executor.

## Consequences

**Positive.** Parity is guaranteed by architecture, not discipline, and
is enforced by `test_parity.py` (incremental/live evaluation equals the
batch/backtest signal set). Iteration is fast and light — no Rust toolchain
or Nautilus data model to fight during research.

**Negative / tradeoffs.** The custom engine models execution more simply
than Nautilus would. At go-live we will add a thin `nautilus_adapter.py`
that wraps the *same* `SignalEngine` as a Nautilus `Strategy` for realistic
execution — meaning two backtest runtimes to maintain, both fed by one
engine.

## Alternatives considered

- **Nautilus now.** Heavy dependency whose execution-realism value isn't
  needed for research; deferred to go-live.
- **vectorbt.** Rejected — its Commons-Clause license forbids *selling*
  the product, a non-starter for a commercial scanner.
- **backtrader.** Rejected — effectively unmaintained.
