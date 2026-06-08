# 0004 — Money and P&L in integer cents

## Status

Accepted.

## Context

Backtests accumulate per-trade P&L into an equity curve and roll it up
into expectancy, profit factor, and Sharpe. Two classic numeric bugs
threaten that math:

1. **Float drift.** Representing dollars as `float` lets tiny binary
   rounding errors accumulate across thousands of trades, so the equity
   curve and metrics no longer reconcile to the sum of individual trades.
2. **i32 overflow.** A 32-bit integer cents value caps at ~$21.5M. That's
   fine per-trade but **overflows on rollups** — cumulative P&L, equity-
   curve sums, and any future MRR/LTV aggregate (`AI_LANDMINES.md` #12).

Stripe-style financial wire formats are `int64` everywhere, so integer
cents is also the natural interchange type.

## Decision

Track **all money and P&L as integer cents**, never floats-as-dollars and
never `i32`. In this Python codebase that means a plain `int` (arbitrary
precision, so no overflow); the rule is conceptually i64 / `BIGINT` for any
typed layer (Rust struct field, DB column). The backtester carries this
end-to-end: `Trade.pnl_cents: int`, `BacktestResult.equity_curve:
list[tuple[datetime, int]]`, and the `DEFAULT_NOTIONAL_CENTS = 10_000_00`
constant (`backtest/runner.py`); commission and gross are computed in cents
and summed in cents. Conversion to dollars happens **only at display/IO**
(e.g. the CSV export emits P&L in both cents and dollars).

## Consequences

**Positive.** P&L is exact and reconcilable — the equity curve always
equals the sum of trade `pnl_cents`. No overflow on any aggregate, and the
representation matches financial wire formats for free.

**Negative / tradeoffs.** Every display, export, and chart must remember
to divide by 100 at the boundary; a missed conversion shows cents where
dollars were meant. The discipline must be held at every IO edge, not just
in the core.

## Alternatives considered

- **Float dollars.** Rejected — accumulation drift breaks metric
  reconciliation.
- **i32 cents.** Rejected — the ~$21.5M cap overflows on cumulative
  rollups even when every individual trade is small.
