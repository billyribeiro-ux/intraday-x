"""Default provider wiring.

Delegates to the config-driven :mod:`~intradayx.data.registry`: the active data
layer is the CompositeProvider assembled from ``Settings.providers`` (priority
order), skipping vendors whose credentials are absent. Add a vendor by
registering it and listing it in ``INTRADAYX_PROVIDERS`` — no code change here.
"""

from __future__ import annotations

from intradayx.data.provider import DataProvider
from intradayx.data.registry import build_provider


def default_provider() -> DataProvider:
    return build_provider()
