"""T9-4 信号反馈：非重叠口径与分母一致性测试（不依赖真实库）。"""

from __future__ import annotations

import importlib.util
import os
import sys

_L1_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_L1_DIR)
_FRONTEND_SCRIPTS = os.path.join(_REPO, "3.1-FRONTEND", "scripts")
for path in (_L1_DIR, _FRONTEND_SCRIPTS):
    if path not in sys.path:
        sys.path.insert(0, path)

_spec = importlib.util.spec_from_file_location(
    "signal_feedback", os.path.join(_FRONTEND_SCRIPTS, "signal_feedback.py")
)
sf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sf)


def _days(count: int):
    return [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(count)]


def _row(as_of: str, direction: int = 1, horizon: int = 20, strength: str = "medium"):
    return {
        "as_of": as_of,
        "target": "BTC",
        "horizon": horizon,
        "direction": direction,
        "strength": strength,
        "decision": "allowed",
    }


def test_non_overlapping_selection_and_rates(monkeypatch):
    dates = _days(120)
    prices = {day: 100.0 * (1.01**i) for i, day in enumerate(dates)}  # 单调上涨

    monkeypatch.setattr(sf, "_price_map", lambda symbol, days: dict(prices))
    rows = [
        _row(dates[0]),
        _row(dates[5]),  # 与上一条间隔 5 < 20 → 被非重叠规则剔除
        _row(dates[25]),
        _row(dates[50]),
    ]
    from l1agg import signal_ledger

    monkeypatch.setattr(
        signal_ledger,
        "read_journal",
        lambda decision=None, limit=2000: [dict(item) for item in rows],
    )

    payload = sf.build(horizons=(20,), limit=100)
    block = payload["horizons"][0]
    totals = block["totals"]

    assert totals["n_raw"] == 4
    assert totals["n_eff"] == 3  # dates[0] / dates[25] / dates[50]
    assert totals["hits"] == 3  # 全为多头 + 单调上涨
    assert totals["hit_rate"] == 1.0
    assert block["buckets"][0]["n_eff"] == 3
    # 分母与展示样本一致：n_eff 就是分档与逐标的表里的样本数
    assert block["targets"][0]["n_eff"] == totals["n_eff"]


def test_short_forward_window_is_skipped(monkeypatch):
    dates = _days(30)
    prices = {day: 100.0 + i for i, day in enumerate(dates)}
    monkeypatch.setattr(sf, "_price_map", lambda symbol, days: dict(prices))
    from l1agg import signal_ledger

    # 末条信号之后不足 horizon 天 → 不参与命中率
    monkeypatch.setattr(
        signal_ledger,
        "read_journal",
        lambda decision=None, limit=2000: [_row(dates[29])],
    )
    payload = sf.build(horizons=(20,), limit=10)
    assert payload["horizons"][0]["totals"]["n_eff"] == 0
    assert payload["quality"]["status"] == "empty"


def test_empty_journal_returns_empty_quality(monkeypatch):
    from l1agg import signal_ledger

    monkeypatch.setattr(signal_ledger, "read_journal", lambda decision=None, limit=2000: [])
    payload = sf.build(horizons=(5, 20), limit=10)
    assert payload["ok"] is True
    assert payload["horizons"] == []
    assert payload["quality"]["degraded_reason"] == "empty_journal"
