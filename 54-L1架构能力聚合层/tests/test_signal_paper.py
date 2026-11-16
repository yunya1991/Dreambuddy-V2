"""T6-4 生产侧记账 runner（signal_paper）契约测试。"""

from __future__ import annotations

import os
import sys

import pytest

_L1_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.join(_L1_DIR, "scripts")
for path in (_L1_DIR, _SCRIPTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import signal_paper as sp  # noqa: E402


def _days(count: int):
    return [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(count)]


def test_build_context_uses_ma_and_percentiles():
    dates = _days(80)
    prices = {day: 100.0 + i for i, day in enumerate(dates)}
    volumes = {day: 1000.0 + i * 10 for i, day in enumerate(dates)}
    context = sp.build_context(prices, volumes, dates, dates[-1])
    assert context["ma_state"] == "up"
    assert 0.0 <= context["vol_pct"] <= 1.0
    assert context["crowd_pct"] > 0.9  # 末日成交额最高


def test_build_context_short_history_returns_empty():
    assert sp.build_context({"2024-01-01": 1.0}, {}, ["2024-01-01"], "2024-01-01") == {}


def test_missing_registry_is_explicit():
    result = sp.run(registry="/tmp/definitely-not-there.db", db_path="/tmp/none.db")
    assert result["ok"] is False
    assert result["reason"] == "registry_missing"
    assert result["recorded"]["inserted"] == 0


def test_run_records_allowed_and_blocked(tmp_path, monkeypatch):
    from l1agg import align
    from l1agg.capabilities import signal_exports

    registry = tmp_path / "reg.db"
    registry.write_bytes(b"")  # 只校验存在性；查询走 monkeypatch
    ledger = tmp_path / "ledger.db"

    dates = _days(80)
    prices = {day: 100.0 + i for i, day in enumerate(dates)}

    monkeypatch.setattr(align, "load_leader", lambda db, symbol, days=1200: dict(prices))
    monkeypatch.setattr(align, "load_daily", lambda *a, **k: {})

    calls = {"n": 0}

    def fake_query(**kwargs):
        calls["n"] += 1
        if not kwargs.get("gate"):
            return {
                "data": {
                    "capabilities": {
                        "D-K03": {
                            "signals": [
                                {
                                    "target": "BTC",
                                    "horizon": 20,
                                    "direction": 1,
                                    "strength": "medium",
                                }
                            ]
                        }
                    }
                }
            }
        return {
            "data": {
                "capabilities": {
                    "D-K03": {
                        "signals": [
                            {
                                "target": "BTC",
                                "horizon": 20,
                                "direction": 1,
                                "strength": "medium",
                                "gating": {"reasons": []},
                            }
                        ],
                        "blocked": [
                            {
                                "target": "BTC",
                                "horizon": 5,
                                "direction": -1,
                                "strength": "weak",
                                "gating": {"reasons": ["ma_against"]},
                            }
                        ],
                    }
                }
            }
        }

    monkeypatch.setattr(signal_exports, "signal_query", fake_query)

    result = sp.run(
        days=5,
        registry=str(registry),
        db_path=str(tmp_path / "core.db"),
        ledger=str(ledger),
    )

    assert result["ok"] is True
    assert result["gate"]["allowed"] == 5
    assert result["gate"]["blocked"] == 5
    assert result["gate"]["by_reason"]["ma_against"] == 5
    assert result["recorded"]["inserted"] == 10
    assert os.path.isfile(ledger)

    # 幂等：同日重跑不重复插入
    again = sp.run(
        days=5, registry=str(registry), db_path=str(tmp_path / "core.db"), ledger=str(ledger)
    )
    assert again["recorded"]["inserted"] == 0
    assert again["recorded"]["duplicates"] == 10


def test_dry_run_does_not_write(tmp_path, monkeypatch):
    from l1agg import align
    from l1agg.capabilities import signal_exports

    registry = tmp_path / "reg.db"
    registry.write_bytes(b"")
    ledger = tmp_path / "ledger.db"
    dates = _days(80)
    prices = {day: 100.0 + i for i, day in enumerate(dates)}

    monkeypatch.setattr(align, "load_leader", lambda db, symbol, days=1200: dict(prices))
    monkeypatch.setattr(align, "load_daily", lambda *a, **k: {})
    monkeypatch.setattr(
        signal_exports,
        "signal_query",
        lambda **kw: {
            "data": {
                "capabilities": {
                    "D-K03": {
                        "signals": [
                            {"target": "BTC", "horizon": 20, "direction": 1, "strength": "medium"}
                        ],
                        "blocked": [],
                    }
                }
            }
        },
    )

    result = sp.run(
        days=2,
        registry=str(registry),
        db_path=str(tmp_path / "core.db"),
        ledger=str(ledger),
        dry_run=True,
    )
    assert result["ok"] is True
    assert result["recorded"]["inserted"] == 0
    assert not os.path.exists(ledger)


@pytest.mark.parametrize("days", [0, 1])
def test_days_are_clamped(days, tmp_path, monkeypatch):
    # days<=0 时仍至少回放 1 天，不产生空 dates
    from l1agg import align
    from l1agg.capabilities import signal_exports

    registry = tmp_path / "reg.db"
    registry.write_bytes(b"")
    dates = _days(80)
    monkeypatch.setattr(
        align,
        "load_leader",
        lambda db, symbol, days=1200: {day: 100.0 + i for i, day in enumerate(dates)},
    )
    monkeypatch.setattr(align, "load_daily", lambda *a, **k: {})
    monkeypatch.setattr(
        signal_exports,
        "signal_query",
        lambda **kw: {
            "data": {"capabilities": {"D-K03": {"signals": [{"target": "BTC"}], "blocked": []}}}
        },
    )
    result = sp.run(
        days=days, registry=str(registry), db_path=str(tmp_path / "core.db"), dry_run=True
    )
    assert result["dates"]["count"] >= 1
