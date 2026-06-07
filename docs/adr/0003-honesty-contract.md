# 0003 — The honesty contract

## Status

Accepted.

## Context

Most retail scanners overpromise: they name a confident "cause" for every
move and bury the fact that the underlying data was thin or the edge weak.
On free data (yfinance, no internals/options) the measurable edge is
genuinely small — and the only defensible product is one that *surfaces*
that limitation rather than hiding it. A confident wrong reason is worse
than "I don't know," because it pollutes the attribution ranking and
misleads the trader at the moment of decision.

## Decision

Make honesty a structural contract, enforced in the domain types and
across the pipeline:

- **`data_completeness` on every Signal.** Each `Attribution`
  (`domain/signals.py`) carries a `data_completeness` score (0–1) — the
  share of *relevant* capabilities that were actually available — and
  `Signal.confidence` is already scaled down by it.
- **Attribution is correlational, not causal.** SHAP-derived causes carry
  `source = MODEL` and describe *what the model keyed on*, never why the
  market moved; `MODEL_ATTRIBUTION_CAVEAT` (correlation ≠ causation) rides
  with every model attribution. SHAP runs in **`interventional`** mode so
  correlated features aren't mis-credited (`AI_LANDMINES.md` #5).
- **"Cause uncertain" is a first-class output.** When available internals
  don't explain a move, the engine returns `uncertain_attribution(...)` —
  a single `UNEXPLAINED` cause, `uncertain=True` — not a silent gap.
- **Detectors say "insufficient data," never guess.** A detector lacking
  its inputs returns `DetectedEvent.insufficient(...)` (`domain/events.py`),
  counted as dormant. No GEX/squeeze number is fabricated without a real
  `OptionChain` / non-stale short interest (`AI_LANDMINES.md` #14, #15).
- **Validation is leak-free.** Purged + embargoed CV, scalers fit on the
  train fold only, fill-on-next-bar, and the **Deflated Sharpe Ratio**
  to discount multiple-testing overfit.

## Consequences

**Positive.** Output is trustworthy: a losing v1 backtest on free data is
*reported as losing* (CV macro-F1 ≈ 0.51, P(Sharpe>0) surfaced), so the
human trusts the green numbers when they come. No silent overstatement of
what was measured.

**Negative / tradeoffs.** The tool looks "less impressive" than scanners
that confidently invent reasons. "Cause uncertain" and lowered confidence
are common on free data — by design, not as a bug.

## Alternatives considered

- **Hide uncertainty / show confident wrong reasons.** Rejected — it is
  the exact failure mode of the scanners we're displacing, and it destroys
  the only durable moat (trust).
