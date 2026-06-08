"""intradayx — self-learning intraday day-trading scanner & backtester.

The package is organized so that one ``SignalEngine.evaluate()`` is the single
source of truth shared by the backtester and the live monitor, and a
capability-gated data layer lets every feature/detector degrade *honestly*
(reporting ``data_completeness`` and "cause uncertain") rather than fabricating
a signal it cannot support.
"""

__version__ = "0.0.1"
