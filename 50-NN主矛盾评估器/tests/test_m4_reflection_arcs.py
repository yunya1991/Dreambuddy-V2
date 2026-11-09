"""M4-2/M4-4 测试：龙头监控门 + salience 门（SPEC-M3）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_42_PATH = str(_REPO_ROOT / "42-神经网络交易协调层")
if _42_PATH not in sys.path:
    sys.path.insert(0, _42_PATH)

import core.reflection_arcs as ra  # noqa: E402
from core.macro_force import MacroForce  # noqa: E402
from task_dispatcher import TaskDispatcher  # noqa: E402


@pytest.fixture
def temp_dispatcher(tmp_path, monkeypatch):
    """用临时路径的 dispatcher 替换 reflection_arcs 的全局 dispatcher。"""
    path = str(tmp_path / "dispatch_tasks.jsonl")
    d = TaskDispatcher(dispatch_path=path)
    monkeypatch.setattr(ra, "_get_dispatcher", lambda: d)
    return d


def _macro_btc(d1: float) -> dict[str, MacroForce]:
    return {
        "BTC": MacroForce(
            symbol="BTC",
            layer="L1_anchor",
            d1_trend=d1,
            d2_fund=0.0,
            d4_sentiment=0.0,
            washout=0.0,
            f_cycle=d1,
            corr0=1.0,
            layer_gate=1.0,
            t_arrive_days=None,
            degraded=[],
        )
    }


class TestMacroLedGate:
    def test_below_threshold_not_triggered(self, temp_dispatcher):
        result = ra.check_macro_led_gate(_macro_btc(0.3))
        assert result["triggered"] is False
        assert result["task_id"] is None

    def test_above_threshold_triggers_p0(self, temp_dispatcher):
        result = ra.check_macro_led_gate(_macro_btc(0.5))
        assert result["triggered"] is True
        assert result["task_id"] is not None
        queued = temp_dispatcher.list_queued()
        assert len(queued) == 1
        assert queued[0].priority == "P0"
        assert queued[0].trigger == "macro_led"

    def test_negative_above_threshold_triggers(self, temp_dispatcher):
        result = ra.check_macro_led_gate(_macro_btc(-0.6))
        assert result["triggered"] is True

    def test_no_btc_not_triggered(self, temp_dispatcher):
        result = ra.check_macro_led_gate({})
        assert result["triggered"] is False

    def test_exact_threshold_not_triggered(self, temp_dispatcher):
        # |0.4| is not >= 0.4? threshold is >=, so 0.4 should trigger
        result = ra.check_macro_led_gate(_macro_btc(0.4))
        assert result["triggered"] is True


class TestSalienceGate:
    def test_below_threshold_not_triggered(self, temp_dispatcher):
        evs = [{"source": "11-bcrm", "confidence": 0.5, "symbol": "BTC/USDT"}]
        result = ra.check_salience_gate(evs)
        assert result["triggered"] == []

    def test_above_threshold_triggers_p1(self, temp_dispatcher):
        evs = [{"source": "11-bcrm", "confidence": 0.8, "symbol": "BTC/USDT"}]
        result = ra.check_salience_gate(evs)
        assert len(result["triggered"]) == 1
        assert result["triggered"][0]["source"] == "11-bcrm"
        queued = temp_dispatcher.list_queued()
        assert queued[0].priority == "P1"
        assert queued[0].trigger == "micro_led"

    def test_same_source_only_once(self, temp_dispatcher):
        evs = [
            {"source": "11-bcrm", "confidence": 0.8, "symbol": "BTC/USDT"},
            {"source": "11-bcrm", "confidence": 0.9, "symbol": "BTC/USDT"},
        ]
        result = ra.check_salience_gate(evs)
        assert len(result["triggered"]) == 1

    def test_salience_quota_blocks_third(self, temp_dispatcher):
        ra.check_salience_gate([{"source": "11-bcrm", "confidence": 0.8, "symbol": "A"}])
        ra.check_salience_gate([{"source": "11-bcrm", "confidence": 0.8, "symbol": "B"}])
        # 第 3 次同源应被配额拦截
        result = ra.check_salience_gate([{"source": "11-bcrm", "confidence": 0.8, "symbol": "C"}])
        assert result["triggered"] == []

    def test_no_dispatcher_fail_open(self, monkeypatch):
        monkeypatch.setattr(ra, "_get_dispatcher", lambda: None)
        result = ra.check_salience_gate([{"source": "11-bcrm", "confidence": 0.9}])
        assert result["triggered"] == []
        macro_result = ra.check_macro_led_gate(_macro_btc(0.9))
        assert macro_result["triggered"] is False
