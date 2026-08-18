#!/usr/bin/env python3
"""
Phase 2 资金调控接入验证脚本
================================

验证 phase2.enabled=true 时，A9 Layer 5 资金压力调整的实际调控效果。

验证场景：
  A. phase2 启用 + HIGH 压力 + RAISE_TP → HOLD + confidence×0.8
  B. phase2 启用 + LOW 压力 + RAISE_TP → 不调整
  C. phase2 启用 + HIGH 压力 + HOLD → confidence×0.8（action 不变）
  D. 真实 CapitalControlComponent 集成验证（用 mock 持仓）

运行方式::

    cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
    python 16-调控系统/scripts/verify_phase2.py
"""

import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# 设置 sys.path
_PROJECT = Path(__file__).resolve().parents[2]
_CORE = _PROJECT / "16-调控系统" / "core"
_RISK = _PROJECT / "13-通用风控模块"
_RISK_CORE = _RISK / "core"
for _p in (_CORE, _RISK, _RISK_CORE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from capital_control import CapitalControlComponent, CapitalMode
from capital_control.types import (
    AccountType,
    CapitalMode,
    CapitalResult,
    CapitalSnapshot,
    HealthLevel,
    now_iso,
)
from a9_exit_decision import a9_exit_decision_handler, _evaluate_single_position


def _banner(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _make_raised_tp_scenario():
    """构造一个倾向 RAISE_TP 的 A1/A2/A3 输入。"""
    return {
        "a1": {
            "research_report": {
                "market_state": {"atr_pct": 0.02},
            }
        },
        "a2": {
            "first_principles_analysis": {
                "synthesis": {
                    "path_confidence": 0.85,
                    "least_resistance_path": "UP",
                },
                "trend_analysis": {
                    "trend_strength": 9,
                    "trend_phase": "加速期",
                },
            },
            "market_regime_classification": {"regime": "TREND_STRONG"},
        },
        "a3": {"strategy_directive": {"directive_bias": "LONG"}},
    }


def _make_hold_scenario():
    """构造一个倾向 HOLD 的输入。"""
    return {
        "a1": {"research_report": {"market_state": {"atr_pct": 0.02}}},
        "a2": {
            "first_principles_analysis": {
                "synthesis": {"path_confidence": 0.5, "least_resistance_path": "NEUTRAL"},
                "trend_analysis": {"trend_strength": 5, "trend_phase": "盘整"},
            },
            "market_regime_classification": {"regime": "RANGE_BOUND"},
        },
        "a3": {"strategy_directive": {"directive_bias": "HOLD"}},
    }


def _make_position_long(system="v15_martin", upnl=8.0):
    return {
        "symbol": "BTC",
        "system": system,
        "direction": "LONG",
        "size": 0.5,
        "entry_price": 60000.0,
        "unrealized_pnl": upnl,
    }


def _make_capital_result(system, used_pct, total_eq=260.0):
    """构造一个 CapitalResult。"""
    used_margin = total_eq * used_pct / 100.0
    avail = max(0.0, total_eq - used_margin)
    return CapitalResult(
        system=system,
        account_type=AccountType.OKX_LIVE,
        mode=CapitalMode.DYNAMIC,
        total_eq=total_eq,
        avail_balance=avail,
        used_margin=used_margin,
        used_pct=used_pct,
        fallback_used=False,
        timestamp=now_iso(),
    )


def _make_snapshot(by_system):
    """构造 CapitalSnapshot。"""
    total_eq = sum(r.total_eq for r in by_system.values())
    total_used = sum(r.used_margin for r in by_system.values())
    total_avail = sum(r.avail_balance for r in by_system.values())
    overall = (total_used / total_eq * 100) if total_eq > 0 else 0
    return CapitalSnapshot(
        timestamp=now_iso(),
        mode=CapitalMode.DYNAMIC,
        by_system=by_system,
        total_equity=round(total_eq, 2),
        total_avail=round(total_avail, 2),
        total_used=round(total_used, 2),
        overall_used_pct=round(overall, 2),
        health=HealthLevel.CRITICAL if overall >= 80 else (
            HealthLevel.WARNING if overall >= 50 else HealthLevel.HEALTHY
        ),
    )


# =========================================================================
# 场景 A: HIGH 压力 + RAISE_TP → HOLD
# =========================================================================

def scenario_a_high_pressure_raise_tp():
    _banner("场景 A: phase2 启用 + HIGH 压力 + RAISE_TP → HOLD")

    pos = _make_position_long("v15_martin")
    sc = _make_raised_tp_scenario()

    # 构造 HIGH 压力的 advice（通过 mock snapshot）
    component = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
    high_result = _make_capital_result("v15_martin", used_pct=85.0, total_eq=260.0)
    mock_snapshot = _make_snapshot({"v15_martin": high_result})
    component._last_snapshot = mock_snapshot
    component._last_eval_ts = float("inf")  # 避免缓存影响

    advice = component.get_capital_advice("v15_martin", "RAISE_TP")
    print(f"  资金建议: pressure={advice['margin_pressure']}, "
          f"phase2={advice['phase2_enabled']}, "
          f"allowed={advice['allowed']}, "
          f"conf_mult={advice['confidence_multiplier']}")
    print(f"  blocked_actions={advice['blocked_actions']}")

    capital_advice = {"v15_martin": advice}
    ev = _evaluate_single_position(
        pos, sc["a1"], sc["a2"], sc["a3"], {}, capital_advice,
    )

    print(f"\n  原始 action (Layer 4): {ev['layers']['layer4_synthesis']['action']}")
    print(f"  最终 action (Layer 5 后): {ev['recommended_action']}")
    print(f"  原始 confidence: {ev['layers']['layer5_capital_adjustment'].get('original_confidence')}")
    print(f"  最终 confidence: {ev['confidence']}")
    print(f"  Layer 5 adjusted: {ev['layers']['layer5_capital_adjustment']['adjusted']}")
    print(f"  Layer 5 action_adjustment: {ev['layers']['layer5_capital_adjustment'].get('action_adjustment', 'N/A')}")

    # 断言
    assert ev["recommended_action"] == "HOLD", f"期望 HOLD, 实际 {ev['recommended_action']}"
    assert ev["layers"]["layer4_synthesis"]["action"] == "RAISE_TP", "Layer 4 应保留原始 RAISE_TP"
    assert ev["confidence"] == round(0.85 * 0.8, 2), f"置信度衰减错误: {ev['confidence']}"
    assert ev["layers"]["layer5_capital_adjustment"]["adjusted"] is True
    assert ev["parameters"]["new_tp_price"] == 0, "RAISE_TP 转 HOLD 后 new_tp 应为 0"
    assert "Layer5 资金压力调整生效" in ev["reason"]
    print("\n  ✅ 场景 A 验证通过：RAISE_TP→HOLD, confidence 0.85→0.68")


# =========================================================================
# 场景 B: LOW 压力 + RAISE_TP → 不调整
# =========================================================================

def scenario_b_low_pressure_no_adjust():
    _banner("场景 B: phase2 启用 + LOW 压力 + RAISE_TP → 不调整")

    pos = _make_position_long("v15_martin")
    sc = _make_raised_tp_scenario()

    component = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
    low_result = _make_capital_result("v15_martin", used_pct=20.0, total_eq=260.0)
    mock_snapshot = _make_snapshot({"v15_martin": low_result})
    component._last_snapshot = mock_snapshot
    component._last_eval_ts = float("inf")

    advice = component.get_capital_advice("v15_martin", "RAISE_TP")
    print(f"  资金建议: pressure={advice['margin_pressure']}, allowed={advice['allowed']}")

    capital_advice = {"v15_martin": advice}
    ev = _evaluate_single_position(
        pos, sc["a1"], sc["a2"], sc["a3"], {}, capital_advice,
    )

    print(f"  最终 action: {ev['recommended_action']}")
    print(f"  confidence: {ev['confidence']}")
    print(f"  Layer 5 adjusted: {ev['layers']['layer5_capital_adjustment']['adjusted']}")

    assert ev["recommended_action"] == "RAISE_TP", f"期望 RAISE_TP, 实际 {ev['recommended_action']}"
    assert ev["confidence"] == 0.85, f"置信度不应衰减: {ev['confidence']}"
    assert ev["layers"]["layer5_capital_adjustment"]["adjusted"] is False
    assert ev["parameters"]["new_tp_price"] > 0, "RAISE_TP 应保留 new_tp"
    print("\n  ✅ 场景 B 验证通过：LOW 压力不调整，RAISE_TP 保持")


# =========================================================================
# 场景 C: HIGH 压力 + HOLD → confidence×0.8（action 不变）
# =========================================================================

def scenario_c_high_pressure_hold():
    _banner("场景 C: phase2 启用 + HIGH 压力 + HOLD → action 不变, confidence×0.8")

    pos = _make_position_long("v15_martin")
    sc = _make_hold_scenario()

    component = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
    high_result = _make_capital_result("v15_martin", used_pct=90.0, total_eq=260.0)
    mock_snapshot = _make_snapshot({"v15_martin": high_result})
    component._last_snapshot = mock_snapshot
    component._last_eval_ts = float("inf")

    advice = component.get_capital_advice("v15_martin", "HOLD")
    print(f"  资金建议: pressure={advice['margin_pressure']}")

    capital_advice = {"v15_martin": advice}
    ev = _evaluate_single_position(
        pos, sc["a1"], sc["a2"], sc["a3"], {}, capital_advice,
    )

    print(f"  原始 action (Layer 4): {ev['layers']['layer4_synthesis']['action']}")
    print(f"  最终 action: {ev['recommended_action']}")
    print(f"  confidence: {ev['confidence']} (原始 0.5 × 0.8 = {round(0.5*0.8, 2)})")
    print(f"  Layer 5 adjusted: {ev['layers']['layer5_capital_adjustment']['adjusted']}")

    assert ev["recommended_action"] == "HOLD", f"期望 HOLD, 实际 {ev['recommended_action']}"
    assert ev["confidence"] == round(0.5 * 0.8, 2), f"置信度应衰减: {ev['confidence']}"
    assert ev["layers"]["layer5_capital_adjustment"]["adjusted"] is True
    assert "action_adjustment" not in ev["layers"]["layer5_capital_adjustment"], "HOLD 不应有 action_adjustment"
    print("\n  ✅ 场景 C 验证通过：HOLD 保持，confidence 0.5→0.4")


# =========================================================================
# 场景 D: 完整 handler 集成 + decision_layers 验证
# =========================================================================

def scenario_d_full_handler_integration():
    _banner("场景 D: 完整 a9_exit_decision_handler 集成验证")

    pos = _make_position_long("v15_martin")
    sc = _make_raised_tp_scenario()

    component = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
    high_result = _make_capital_result("v15_martin", used_pct=85.0, total_eq=260.0)
    mock_snapshot = _make_snapshot({"v15_martin": high_result})
    component._last_snapshot = mock_snapshot
    component._last_eval_ts = float("inf")

    advice = component.get_capital_advice("v15_martin", "RAISE_TP")

    inputs = {
        "positions": [pos],
        "a1_result": sc["a1"],
        "a2_result": sc["a2"],
        "a3_result": sc["a3"],
        "market": {},
        "capital_advice": {"v15_martin": advice},
    }
    result = a9_exit_decision_handler(inputs, engine=None)

    print(f"  decision_layers keys: {list(result['decision_layers'].keys())}")
    assert "layer5_capital_adjustment" in result["decision_layers"], "缺少 layer5_capital_adjustment"

    ev = result["exit_evaluations"][0]
    print(f"  评估数: {len(result['exit_evaluations'])}")
    print(f"  总体统计: {result['overall_summary']}")
    print(f"  持仓 {ev['position']['symbol']} ({ev['position']['system']}):")
    print(f"    action={ev['recommended_action']}, confidence={ev['confidence']}")
    print(f"    Layer 5: {ev['layers']['layer5_capital_adjustment']}")

    assert ev["recommended_action"] == "HOLD"
    print("\n  ✅ 场景 D 验证通过：完整 handler 链路 Layer 5 生效")


# =========================================================================
# 场景 E: 多系统混合压力验证
# =========================================================================

def scenario_e_multi_system_mixed_pressure():
    _banner("场景 E: 多系统混合压力（v15 HIGH / agent_a LOW）")

    pos_v15 = _make_position_long("v15_martin", upnl=8.0)
    pos_a = _make_position_long("agent_a", upnl=5.0)
    sc = _make_raised_tp_scenario()

    component = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
    v15_high = _make_capital_result("v15_martin", used_pct=85.0, total_eq=260.0)
    agent_a_low = _make_capital_result("agent_a", used_pct=15.0, total_eq=60.0)
    mock_snapshot = _make_snapshot({
        "v15_martin": v15_high,
        "agent_a": agent_a_low,
    })
    component._last_snapshot = mock_snapshot
    component._last_eval_ts = float("inf")

    advice_v15 = component.get_capital_advice("v15_martin", "RAISE_TP")
    advice_a = component.get_capital_advice("agent_a", "RAISE_TP")
    print(f"  v15_martin: pressure={advice_v15['margin_pressure']}, allowed={advice_v15['allowed']}")
    print(f"  agent_a:    pressure={advice_a['margin_pressure']}, allowed={advice_a['allowed']}")

    capital_advice = {"v15_martin": advice_v15, "agent_a": advice_a}
    ev_v15 = _evaluate_single_position(pos_v15, sc["a1"], sc["a2"], sc["a3"], {}, capital_advice)
    ev_a = _evaluate_single_position(pos_a, sc["a1"], sc["a2"], sc["a3"], {}, capital_advice)

    print(f"\n  v15_martin: action={ev_v15['recommended_action']}, conf={ev_v15['confidence']}, adjusted={ev_v15['layers']['layer5_capital_adjustment']['adjusted']}")
    print(f"  agent_a:    action={ev_a['recommended_action']}, conf={ev_a['confidence']}, adjusted={ev_a['layers']['layer5_capital_adjustment']['adjusted']}")

    assert ev_v15["recommended_action"] == "HOLD", "v15 HIGH 应转 HOLD"
    assert ev_a["recommended_action"] == "RAISE_TP", "agent_a LOW 应保持 RAISE_TP"
    assert ev_v15["layers"]["layer5_capital_adjustment"]["adjusted"] is True
    assert ev_a["layers"]["layer5_capital_adjustment"]["adjusted"] is False
    print("\n  ✅ 场景 E 验证通过：v15 HIGH→HOLD, agent_a LOW→RAISE_TP 保持")


# =========================================================================
# 主入口
# =========================================================================

def main():
    _banner("Phase 2 资金调控接入验证（phase2.enabled=true）")

    # 确认配置已启用
    config_path = _PROJECT / "16-调控系统" / "config" / "capital_control.json"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    phase2_on = cfg.get("phase2", {}).get("enabled", False)
    print(f"  配置文件: {config_path}")
    print(f"  phase2.enabled: {phase2_on}")
    assert phase2_on is True, "phase2 必须启用才能验证"
    print(f"  high_pressure_actions_to_block: {cfg['phase2']['high_pressure_actions_to_block']}")
    print(f"  high_pressure_confidence_multiplier: {cfg['phase2']['high_pressure_confidence_multiplier']}")

    # 执行所有场景
    scenario_a_high_pressure_raise_tp()
    scenario_b_low_pressure_no_adjust()
    scenario_c_high_pressure_hold()
    scenario_d_full_handler_integration()
    scenario_e_multi_system_mixed_pressure()

    _banner("🎉 全部 Phase 2 验证场景通过")
    print("  Layer 5 资金压力调整已生效：")
    print("  - HIGH 压力 + RAISE_TP → HOLD（阻断激进止盈上移）")
    print("  - HIGH 压力 → confidence × 0.8（降低信号置信度）")
    print("  - LOW/MEDIUM 压力 → 不调整")
    print("  - layer4_synthesis 保留原始动作，layer5_capital_adjustment 记录调整详情")
    print()


if __name__ == "__main__":
    main()
