"""ThinkScript export is structurally valid and reflects the params."""

from __future__ import annotations

from intradayx.export.thinkscript import reversal_thinkscript
from intradayx.signals.params import ReversalParams


def test_thinkscript_contains_key_constructs() -> None:
    src = reversal_thinkscript(ReversalParams())
    # Plots buy/sell arrows + VWAP.
    assert "PaintingStrategy.BOOLEAN_ARROW_DOWN" in src
    assert "PaintingStrategy.BOOLEAN_ARROW_UP" in src
    assert "reference VWAP()" in src
    # Mirrors the engine's causal pivot + confluence logic.
    assert "confPivotHigh" in src
    assert "confluenceTop" in src
    # Params are injected.
    p = ReversalParams()
    assert f"threshold  = {p.threshold}" in src
    assert f"pivotK     = {p.pivot_k}" in src
    assert p.version in src
