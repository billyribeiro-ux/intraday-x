"""CSV export for signals and backtest trades.

One row per signal (flattened, including the ranked 'why' and data_completeness)
and one row per trade. P&L is emitted both in cents (exact) and dollars.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

from intradayx.domain.signals import Signal

if TYPE_CHECKING:
    from intradayx.backtest.runner import BacktestResult

SIGNAL_FIELDS = [
    "signal_id",
    "symbol",
    "ts",
    "kind",
    "side",
    "confidence",
    "entry",
    "stop",
    "targets",
    "time_of_day_bucket",
    "primary_cause",
    "ranked_causes",
    "data_completeness",
    "uncertain",
]

TRADE_FIELDS = [
    "signal_id",
    "kind",
    "side",
    "entry_ts",
    "exit_ts",
    "entry",
    "exit",
    "shares",
    "pnl_cents",
    "pnl_usd",
    "exit_reason",
    "tod_bucket",
]


def _signal_row(s: Signal) -> dict[str, object]:
    a = s.attribution
    return {
        "signal_id": s.signal_id,
        "symbol": s.symbol,
        "ts": s.ts.isoformat(),
        "kind": s.kind.value,
        "side": s.side.value,
        "confidence": f"{s.confidence:.4f}",
        "entry": f"{s.entry:.4f}",
        "stop": f"{s.stop:.4f}",
        "targets": "|".join(f"{t:.4f}" for t in s.targets),
        "time_of_day_bucket": s.time_of_day_bucket,
        "primary_cause": a.primary_cause.kind.value if a.primary_cause else "",
        "ranked_causes": "; ".join(f"{c.kind.value}:{c.score:.2f}" for c in a.ranked_causes),
        "data_completeness": f"{a.data_completeness:.2f}",
        "uncertain": a.uncertain,
    }


def signals_to_csv(signals: list[Signal], path: Path | str) -> int:
    path = Path(path)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SIGNAL_FIELDS)
        w.writeheader()
        for s in signals:
            w.writerow(_signal_row(s))
    return len(signals)


def trades_to_csv(result: BacktestResult, path: Path | str) -> int:
    path = Path(path)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        w.writeheader()
        for t in result.trades:
            w.writerow(
                {
                    "signal_id": t.signal_id,
                    "kind": t.kind,
                    "side": "long" if t.is_long else "short",
                    "entry_ts": t.entry_ts.isoformat(),
                    "exit_ts": t.exit_ts.isoformat(),
                    "entry": f"{t.entry:.4f}",
                    "exit": f"{t.exit:.4f}",
                    "shares": t.shares,
                    "pnl_cents": t.pnl_cents,
                    "pnl_usd": f"{t.pnl_cents / 100:.2f}",
                    "exit_reason": t.exit_reason.value,
                    "tod_bucket": t.tod_bucket,
                }
            )
    return len(result.trades)
