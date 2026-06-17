"""Fill model — realistic, no same-bar lookahead.

Entries fill on the NEXT bar's open (the signal bar's close isn't tradable at
decision time — see docs/AI_LANDMINES.md), with slippage applied against the
trade direction. Commission is per-share. Money is tracked in integer cents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FillModel:
    slippage_bps: float = 1.0  # adverse slippage, basis points of price
    commission_per_share_cents: float = 0.5  # e.g. half a cent / share each side
    max_dollar_volume_pct: float = 1.0  # cap position at this share of bar $ volume

    def entry_price(self, ref_price: float, *, is_long: bool) -> float:
        """Apply adverse slippage to a reference (next-open) price."""
        slip = ref_price * self.slippage_bps / 10_000.0
        return ref_price + slip if is_long else ref_price - slip

    def commission_cents(self, shares: int) -> int:
        """Per-share commission for one side, in integer cents (rounded UP).

        ``round`` (banker's) would undercharge — waiving commission entirely on a
        1-share trade (round(0.5)=0). Ceil never under-charges the realism knob.
        """
        return math.ceil(self.commission_per_share_cents * shares)

    def max_shares_for_liquidity(self, price: float, volume: int) -> int:
        """Limit shares so the trade does not exceed its share of bar dollar volume."""
        if price <= 0 or volume <= 0 or self.max_dollar_volume_pct <= 0:
            return 0
        if self.max_dollar_volume_pct >= 1.0:
            return 2_147_483_647  # no effective cap
        max_dollars = price * volume * self.max_dollar_volume_pct
        return int(max_dollars / price)
