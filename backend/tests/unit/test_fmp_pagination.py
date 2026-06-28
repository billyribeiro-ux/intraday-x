"""FMP intraday backward-pagination: deep [start, end] from ~6-day pages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from intradayx.data.providers.fmp_provider import FMPProvider
from intradayx.domain.bars import Timeframe


def test_intraday_pages_backward_to_cover_deep_range(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Simulate FMP: each call returns ~6 trading days (newest-first) ending at
    # `to`, down to a data floor; older `to` serves older windows.
    floor = datetime(2026, 5, 1, tzinfo=UTC)
    calls: list[str] = []

    def fake_request(path: str, params: dict[str, str]) -> Any:
        assert path == "historical-chart/5min"
        to = datetime.strptime(params["to"], "%Y-%m-%d").replace(tzinfo=UTC)
        calls.append(params["to"])
        rows = []
        for i in range(6):  # 6 daily 16:00 bars walking back from `to`
            day = to - timedelta(days=i)
            if day < floor:
                break
            rows.append({"date": day.strftime("%Y-%m-%d") + " 16:00:00",
                         "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1})
        return rows  # newest-first

    p = FMPProvider(api_key="test")
    monkeypatch.setattr(p, "_request", fake_request)
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 6, 26, tzinfo=UTC)
    bars = p.bars("AAPL", start, end, Timeframe.M5)

    # Multiple pages were needed (one call could never reach back ~8 weeks).
    assert len(calls) > 1
    # Deep coverage: spans roughly start..end, far more than a single 6-day page.
    assert len(bars) > 20
    assert bars.start is not None and bars.start.date() <= datetime(2026, 5, 6).date()
    assert bars.end is not None and bars.end.date() >= datetime(2026, 6, 20).date()
