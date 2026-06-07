"""Walk-forward runs end-to-end and reports the right structure."""

from __future__ import annotations

from intradayx.backtest.metrics import BacktestMetrics
from intradayx.backtest.walkforward import WalkForwardResult, walk_forward
from intradayx.data.providers.yfinance_provider import YFinanceProvider
from intradayx.domain.bars import Timeframe
from tests.fixtures.synthetic import make_bars


def test_walk_forward_structure() -> None:
    bars = make_bars(closes=[100.0 + (i % 7) for i in range(240)], timeframe=Timeframe.M5)
    caps = YFinanceProvider().capabilities()
    res = walk_forward(bars, caps, scanner="reversal", n_windows=4, thresholds=(0.3, 0.4, 0.5))

    assert isinstance(res, WalkForwardResult)
    assert res.n_trials_per_window == 3
    assert res.scanner == "reversal"
    assert isinstance(res.oos_metrics, BacktestMetrics)
    assert 0.0 <= res.deflated_sharpe <= 1.0
    assert len(res.windows) <= 4
