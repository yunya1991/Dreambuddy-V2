"""
单元测试：A9 离场决策 Layer 5 资金压力调整（v2.1 二期接入）

覆盖场景：
  1. 无 capital_advice → Layer 5 不生效，action/confidence 不变
  2. phase2 未启用 → Layer 5 仅记录，不调整
  3. phase2 启用 + HIGH 压力 + RAISE_TP → action→HOLD, confidence×0.8
  4. phase2 启用 + HIGH 压力 + 非 RAISE_TP → action 不变, confidence×0.8
  5. phase2 启用 + LOW 压力 → 不调整
  6. layer5_capital_adjustment 字段结构验证
  7. reason 包含 Layer5 标记

运行方式::

    cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
    python -m pytest 16-调控系统/tests/capital_control/test_a9_layer5.py -v
"""

import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[3]  # dreambuddy-v2
_CORE = _PROJECT / "16-调控系统" / "core"
for _p in (_CORE,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest

from a9_exit_decision import _evaluate_single_position


# ---------------------------------------------------------------------------
# 构造测试数据
# ---------------------------------------------------------------------------

def _make_a1(market_state=None):
    """构造 A1 结果，使其产出 RAISE_TP。"""
    return {
        "research_report": {
            "market_state": market_state or {"atr_pct": 0.02},
        }
    }


def _make_a2_raised():
    """构造 A2 结果：趋势强劲 + 高置信度 + 加速期 → 倾向 RAISE_TP。"""
    return {
        "first_principles_analysis": {
            "synthesis": {
                "path_confidence": 0.8,
                "least_resistance_path": "UP",
            },
            "trend_analysis": {
                "trend_strength": 8,
                "trend_phase": "加速期",
            },
        },
        "market_regime_classification": {
            "regime": "TREND_STRONG",
        },
    }


def _make_a2_hold():
    """构造 A2 结果：中性 → 倾向 HOLD。"""
    return {
        "first_principles_analysis": {
            "synthesis": {
                "path_confidence": 0.5,
                "least_resistance_path": "NEUTRAL",
            },
            "trend_analysis": {
                "trend_strength": 5,
                "trend_phase": "盘整",
            },
        },
        "market_regime_classification": {
            "regime": "RANGE_BOUND",
        },
    }


def _make_a3_long():
    """A3 策略指令偏多。"""
    return {"strategy_directive": {"directive_bias": "LONG"}}


def _make_a3_neutral():
    """A3 策略指令中性。"""
    return {"strategy_directive": {"directive_bias": "HOLD"}}


def _make_position_long(system="v15_martin", upnl=5.0):
    """构造多头持仓。"""
    return {
        "symbol": "BTC",
        "system": system,
        "direction": "LONG",
        "size": 0.5,
        "entry_price": 60000.0,
        "unrealized_pnl": upnl,
    }


def _make_advice(pressure="HIGH", phase2=True, conf_mult=0.8,
                 blocked=("RAISE_TP",), used_pct=85.0, total_eq=260.0):
    """构造资金建议字典。"""
    return {
        "allowed": not (phase2 and pressure == "HIGH" and "RAISE_TP" in (blocked or [])),
        "reason": "ok",
        "max_position_usdt": 52.0,
        "current_avail": 260.0,
        "margin_pressure": pressure,
        "used_pct": used_pct,
        "total_eq": total_eq,
        "phase2_enabled": phase2,
        "confidence_multiplier": conf_mult,
        "blocked_actions": sorted(blocked) if phase2 else [],
    }


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


class TestLayer5NoAdvice:
    """场景 1：无 capital_advice → Layer 5 不生效。"""

    def test_none_advice(self):
        pos = _make_position_long()
        ev = _evaluate_single_position(pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {})
        l5 = ev["layers"]["layer5_capital_adjustment"]
        assert l5["capital_advice_present"] is False
        assert l5["adjusted"] is False
        assert ev["recommended_action"] == "RAISE_TP"
        assert ev["confidence"] == 0.8  # path_confidence 不变

    def test_empty_advice(self):
        pos = _make_position_long()
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, {},
        )
        l5 = ev["layers"]["layer5_capital_adjustment"]
        assert l5["capital_advice_present"] is False
        assert l5["adjusted"] is False

    def test_advice_wrong_system(self):
        """capital_advice 存在但 system 不匹配 → 不生效。"""
        pos = _make_position_long(system="v15_martin")
        advice = {"other_system": _make_advice()}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        l5 = ev["layers"]["layer5_capital_adjustment"]
        assert l5["capital_advice_present"] is False
        assert l5["adjusted"] is False
        assert ev["recommended_action"] == "RAISE_TP"


class TestLayer5Phase2Disabled:
    """场景 2：phase2 未启用 → 仅记录不调整。"""

    def test_high_pressure_no_phase2(self):
        pos = _make_position_long()
        advice = {"v15_martin": _make_advice(pressure="HIGH", phase2=False)}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        l5 = ev["layers"]["layer5_capital_adjustment"]
        assert l5["capital_advice_present"] is True
        assert l5["margin_pressure"] == "HIGH"
        assert l5["phase2_enabled"] is False
        assert l5["adjusted"] is False
        # action 不变
        assert ev["recommended_action"] == "RAISE_TP"
        # confidence 不变
        assert ev["confidence"] == 0.8
        # reason 不含 Layer5 标记
        assert "Layer5" not in ev["reason"]


class TestLayer5HighPressureRaiseTP:
    """场景 3：phase2 + HIGH + RAISE_TP → HOLD, confidence×0.8。"""

    def test_raise_tp_to_hold(self):
        pos = _make_position_long()
        advice = {"v15_martin": _make_advice(pressure="HIGH", phase2=True, conf_mult=0.8)}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        # action 转为 HOLD
        assert ev["recommended_action"] == "HOLD"
        # confidence 衰减
        assert ev["confidence"] == round(0.8 * 0.8, 2)  # 0.64
        # new_tp 参数应为 0（不再 RAISE_TP）
        assert ev["parameters"]["new_tp_price"] == 0
        assert ev["parameters"]["new_tp_pct"] == 0

    def test_layer5_detail_fields(self):
        pos = _make_position_long()
        advice = {"v15_martin": _make_advice(pressure="HIGH", phase2=True)}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        l5 = ev["layers"]["layer5_capital_adjustment"]
        assert l5["capital_advice_present"] is True
        assert l5["margin_pressure"] == "HIGH"
        assert l5["phase2_enabled"] is True
        assert l5["adjusted"] is True
        assert l5["action_adjustment"] == "RAISE_TP→HOLD"
        assert l5["confidence_multiplier"] == 0.8
        assert l5["original_confidence"] == 0.8
        assert l5["final_confidence"] == round(0.8 * 0.8, 3)

    def test_layer4_records_original_action(self):
        """layer4_synthesis.action 应保留原始 RAISE_TP。"""
        pos = _make_position_long()
        advice = {"v15_martin": _make_advice(pressure="HIGH", phase2=True)}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        l4 = ev["layers"]["layer4_synthesis"]
        assert l4["action"] == "RAISE_TP"  # 原始动作

    def test_reason_contains_layer5_marker(self):
        pos = _make_position_long()
        advice = {"v15_martin": _make_advice(pressure="HIGH", phase2=True)}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        assert "Layer5 资金压力调整生效" in ev["reason"]

    def test_custom_confidence_multiplier(self):
        """自定义置信度乘数（如 0.5）。"""
        pos = _make_position_long()
        advice = {"v15_martin": _make_advice(pressure="HIGH", phase2=True, conf_mult=0.5)}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        assert ev["confidence"] == round(0.8 * 0.5, 2)  # 0.4

    def test_raise_tp_not_in_blocked(self):
        """RAISE_TP 不在 blocked_actions 中时不转换（仅 confidence 衰减）。"""
        pos = _make_position_long()
        advice = {"v15_martin": _make_advice(
            pressure="HIGH", phase2=True, blocked=(),
        )}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        # action 保持 RAISE_TP
        assert ev["recommended_action"] == "RAISE_TP"
        # 但 confidence 衰减
        assert ev["confidence"] == round(0.8 * 0.8, 2)
        l5 = ev["layers"]["layer5_capital_adjustment"]
        assert l5["adjusted"] is True
        assert "action_adjustment" not in l5


class TestLayer5HighPressureNonRaiseTP:
    """场景 4：phase2 + HIGH + 非 RAISE_TP → action 不变, confidence×0.8。"""

    def test_hold_with_high_pressure(self):
        """HOLD 动作 + HIGH 压力 → 仍 HOLD，confidence 衰减。"""
        pos = _make_position_long()
        # 使用中性 A2/A3 使 action=HOLD
        advice = {"v15_martin": _make_advice(pressure="HIGH", phase2=True)}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_hold(), _make_a3_neutral(), {}, advice,
        )
        assert ev["recommended_action"] == "HOLD"
        # confidence 衰减
        assert ev["confidence"] == round(0.5 * 0.8, 2)  # 0.4
        l5 = ev["layers"]["layer5_capital_adjustment"]
        assert l5["adjusted"] is True
        assert "action_adjustment" not in l5


class TestLayer5LowPressure:
    """场景 5：phase2 + LOW 压力 → 不调整。"""

    def test_low_pressure_no_adjust(self):
        pos = _make_position_long()
        advice = {"v15_martin": _make_advice(pressure="LOW", phase2=True)}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        assert ev["recommended_action"] == "RAISE_TP"
        assert ev["confidence"] == 0.8  # 不衰减
        l5 = ev["layers"]["layer5_capital_adjustment"]
        assert l5["adjusted"] is False
        assert "Layer5" not in ev["reason"]

    def test_medium_pressure_no_adjust(self):
        pos = _make_position_long()
        advice = {"v15_martin": _make_advice(pressure="MEDIUM", phase2=True)}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        assert ev["recommended_action"] == "RAISE_TP"
        assert ev["confidence"] == 0.8
        l5 = ev["layers"]["layer5_capital_adjustment"]
        assert l5["adjusted"] is False


class TestLayer5Structure:
    """场景 6：layer5_capital_adjustment 字段结构验证。"""

    def test_all_expected_fields_present_when_adjusted(self):
        pos = _make_position_long()
        advice = {"v15_martin": _make_advice(pressure="HIGH", phase2=True)}
        ev = _evaluate_single_position(
            pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {}, advice,
        )
        l5 = ev["layers"]["layer5_capital_adjustment"]
        for key in (
            "capital_advice_present", "margin_pressure", "phase2_enabled",
            "used_pct", "total_eq", "adjusted", "final_confidence",
            "confidence_multiplier", "original_confidence", "action_adjustment",
        ):
            assert key in l5, f"missing key: {key}"

    def test_minimal_fields_when_no_advice(self):
        pos = _make_position_long()
        ev = _evaluate_single_position(pos, _make_a1(), _make_a2_raised(), _make_a3_long(), {})
        l5 = ev["layers"]["layer5_capital_adjustment"]
        assert "capital_advice_present" in l5
        assert "adjusted" in l5
        assert "final_confidence" in l5


class TestDecisionLayers:
    """验证 handler 级 decision_layers 包含 layer5。"""

    def test_decision_layers_has_layer5(self):
        from a9_exit_decision import a9_exit_decision_handler

        inputs = {
            "positions": [_make_position_long()],
            "a1_result": _make_a1(),
            "a2_result": _make_a2_raised(),
            "a3_result": _make_a3_long(),
            "market": {},
            "capital_advice": {"v15_martin": _make_advice(pressure="HIGH", phase2=True)},
        }
        result = a9_exit_decision_handler(inputs, engine=None)
        dl = result["decision_layers"]
        assert "layer5_capital_adjustment" in dl
        assert "capital pressure" in dl["layer5_capital_adjustment"]
