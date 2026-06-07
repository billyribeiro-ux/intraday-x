"""Fill model — realistic, no same-bar lookahead.

Entries fill on the NEXT bar's open (the signal bar's close isn't tradable at
decision time — see docs/AI_LANDMINES.md), with slippage applied against the
trade direction. Commission is per-share. Money is tracked in integer cents.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FillModel:
    slippage_bps: float = 1.0  # adverse slippage, basis points of price
    commission_per_share_cents: float = 0.5  # e.g. half a cent / share each side

    def entry_price(self, ref_price: float, *, is_long: bool) -> float:
        """Apply adverse slippage to a reference (next-open) price."""
        slip = ref_price * self.slippage_bps / 10_000.0
        return ref_price + slip if is_long else ref_price - slip

    def commission_cents(self, shares: int) -> int:
        """Per-share commission for one side, in integer cents (rounded up-ish)."""
        return round(self.commission_per_share_cents * shares)
