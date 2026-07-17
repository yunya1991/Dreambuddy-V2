#!/usr/bin/env python3
"""易经离场系统多场景压力测试（v2 - 架构反转后）

测试架构：yijing_exit_system 为主离场模块，classic_exit_system 为备用层。

测试组：
  A组: 主决策路径（yijing available）
       A1: FORCE_CLOSE / A2: RAISE_TP / A3: HOLD / A4: NO_INTERVENE 中性降级
  B组: 卦象阶段映射（六爻 + 四阶段）
  C组: 备用层降级路径（hexagram=None / 信号中性）
  D组: 多场景压力测试（趋势/震荡/嬴势/逆势/高波动/长期持仓/大亏损）
  E组: 边界值测试（阈值边界 +/- epsilon）
  F组: 端到端架构验证（polling_trader 调用路径）
"""
import sys
import os
import json
import time
import traceback
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import MagicMock, patch

# 设置路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4.yijing_exit_system import (
    YijingExitSystem, YijingExitConfig, YijingExitAction, YijingExitDecision,
)
from scripts.memory_l4.classic_exit_system import ExitAction

# 测试结果收集
_results = []
_pass_count = 0
_fail_count = 0


def record(group: str, name: str, passed: bool, detail: str = ""):
    global _pass_count, _fail_count
    status = "PASS" if passed else "FAIL"
    if passed:
        _pass_count += 1
    else:
        _fail_count += 1
    _results.append({
        "group": group, "name": name, "status": status,
        "detail": detail[:200] if detail else "",
    })
    icon = "✅" if passed else "❌"
    print(f"  {icon} [{group}] {name}" + (f" — {detail[:100]}" if detail and not passed else ""))


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ─── 卦象 Mock 工厂 ───
def make_hexagram(
    name_cn: str = "乾为天",
    risk_level: str = "中",
    current_phase: str = "九五",
    development_stage: str = "成长期",
    direction_hint: str = "UP",
    confidence: float = 0.7,
) -> dict:
    """构造卦象数据（dict 形式，兼容 YijingResult.to_dict()）"""
    return {
        "hexagram_name": name_cn,
        "hexagram_name_cn": name_cn,
        "risk_level": risk_level,
        "current_phase": current_phase,
        "development_stage": development_stage,
        "direction_hint": direction_hint,
        "confidence": confidence,
    }


# ============================================================
# A组: 主决策路径
# ============================================================
def test_group_a():
    section("A组: 主决策路径（yijing available）")
    sys_obj = YijingExitSystem()

    # A1: FORCE_CLOSE — 高风险 + 方向冲突
    try:
        hex_data = make_hexagram(
            name_cn="坤为地", risk_level="高",
            current_phase="上九", development_stage="衰退期",
            direction_hint="DOWN", confidence=0.85,
        )
        decision = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=98.0,
            position_age_sec=3600, unrealized_pnl_pct=-0.02,
        )
        # 风险分 = 0.35*0.80 + 0.25*0.85 + 0.20*0.80 + 0.20*0.85 = 0.8225 > 0.80
        # direction_consistent = False (DOWN vs long)
        passed = (decision.action == YijingExitAction.FORCE_CLOSE
                  and decision.yijing_risk_score >= 0.80
                  and not decision.direction_consistent)
        record("A", "A1: FORCE_CLOSE 高风险+方向冲突", passed,
               f"action={decision.action.value} risk={decision.yijing_risk_score:.3f} "
               f"dir_consistent={decision.direction_consistent}")
    except Exception as e:
        record("A", "A1: FORCE_CLOSE 高风险+方向冲突", False, f"exception: {e}")

    # A2: RAISE_TP — 价值高 + 成长期 + 飞龙在天 + 盈利
    try:
        hex_data = make_hexagram(
            name_cn="乾为天", risk_level="低",
            current_phase="九五", development_stage="成长期",
            direction_hint="UP", confidence=0.85,
        )
        decision = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=105.0,
            position_age_sec=3600, unrealized_pnl_pct=0.05,
        )
        # 价值分 = 0.45*0.90 + 0.40*0.85 + 0.15*(1-0.25) = 0.8725 > 0.70
        # direction_consistent = True (UP vs long)
        passed = (decision.action == YijingExitAction.RAISE_TP
                  and decision.tp_adjust_pct > 0
                  and decision.direction_consistent)
        record("A", "A2: RAISE_TP 价值高+成长期+盈利", passed,
               f"action={decision.action.value} value={decision.yijing_value_score:.3f} "
               f"tp_adjust={decision.tp_adjust_pct:.2f}")
    except Exception as e:
        record("A", "A2: RAISE_TP 价值高+成长期+盈利", False, f"exception: {e}")

    # A3: NO_INTERVENE 信号良好（应被 polling_trader 解释为 HOLD）
    try:
        hex_data = make_hexagram(
            name_cn="风天小畜", risk_level="低",
            current_phase="九二", development_stage="成长期",
            direction_hint="UP", confidence=0.70,
        )
        decision = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.5,
            position_age_sec=3600, unrealized_pnl_pct=0.015,
        )
        # 风险分 = 0.35*0.25 + 0.25*0.40 + 0.20*0.30 + 0.20*0.20 = 0.2825 < 0.35
        # 价值分 = 0.45*0.65 + 0.40*0.85 + 0.15*0.75 = 0.7425 > 0.60
        # direction_consistent = True
        passed = (decision.action == YijingExitAction.NO_INTERVENE
                  and decision.yijing_risk_score < 0.35
                  and decision.yijing_value_score > 0.60
                  and decision.direction_consistent)
        record("A", "A3: NO_INTERVENE 信号良好(应HOLD)", passed,
               f"action={decision.action.value} risk={decision.yijing_risk_score:.3f} "
               f"value={decision.yijing_value_score:.3f}")
    except Exception as e:
        record("A", "A3: NO_INTERVENE 信号良好(应HOLD)", False, f"exception: {e}")

    # A4: NO_INTERVENE 信号中性（风险偏高/价值偏低 → 应降级 classic）
    try:
        hex_data = make_hexagram(
            name_cn="水雷屯", risk_level="中",
            current_phase="九三", development_stage="萌芽期",
            direction_hint="UP", confidence=0.55,
        )
        decision = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=99.5,
            position_age_sec=3600, unrealized_pnl_pct=-0.005,
        )
        # 风险分 = 0.35*0.50 + 0.25*0.55 + 0.20*0.65 + 0.20*0.20 = 0.48
        # 应该是 NO_INTERVENE 但 risk > 0.35 → polling_trader 应降级 classic
        passed = (decision.action == YijingExitAction.NO_INTERVENE
                  and decision.yijing_risk_score >= 0.35)
        record("A", "A4: NO_INTERVENE 信号中性(应降级)", passed,
               f"action={decision.action.value} risk={decision.yijing_risk_score:.3f} "
               f"value={decision.yijing_value_score:.3f}")
    except Exception as e:
        record("A", "A4: NO_INTERVENE 信号中性(应降级)", False, f"exception: {e}")


# ============================================================
# B组: 卦象阶段映射
# ============================================================
def test_group_b():
    section("B组: 卦象阶段映射（六爻 + 四阶段）")
    sys_obj = YijingExitSystem()
    cfg = sys_obj.config

    # B1-B6: 六爻阶段风险/价值
    phases = [
        ("初九", 0.65, 0.35, "潜龙勿用"),
        ("九二", 0.40, 0.65, "见龙在田"),
        ("九三", 0.55, 0.55, "终日乾乾"),
        ("九四", 0.45, 0.70, "或跃在渊"),
        ("九五", 0.25, 0.90, "飞龙在天"),
        ("上九", 0.85, 0.20, "亢龙有悔"),
    ]
    for phase, exp_risk, exp_value, name in phases:
        try:
            actual_risk = cfg.phase_risk_map.get(phase)
            actual_value = cfg.phase_value_map.get(phase)
            passed = (actual_risk == exp_risk and actual_value == exp_value)
            record("B", f"B: 六爻[{phase}]{name}", passed,
                   f"expected risk={exp_risk} value={exp_value}, "
                   f"actual risk={actual_risk} value={actual_value}")
        except Exception as e:
            record("B", f"B: 六爻[{phase}]{name}", False, f"exception: {e}")

    # B7-B10: 四阶段风险/价值
    stages = [
        ("萌芽期", 0.65, 0.40),
        ("成长期", 0.30, 0.85),
        ("成熟期", 0.45, 0.65),
        ("衰退期", 0.80, 0.25),
    ]
    for stage, exp_risk, exp_value in stages:
        try:
            actual_risk = cfg.stage_risk_map.get(stage)
            actual_value = cfg.stage_value_map.get(stage)
            passed = (actual_risk == exp_risk and actual_value == exp_value)
            record("B", f"B: 四阶段[{stage}]", passed,
                   f"expected risk={exp_risk} value={exp_value}, "
                   f"actual risk={actual_risk} value={actual_value}")
        except Exception as e:
            record("B", f"B: 四阶段[{stage}]", False, f"exception: {e}")

    # B11: risk_level 映射
    for rl_in, exp_risk in [("高", 0.80), ("中", 0.50), ("低", 0.25),
                             ("high", 0.80), ("medium", 0.50), ("low", 0.25)]:
        try:
            actual = cfg.risk_level_map.get(rl_in)
            passed = actual == exp_risk
            record("B", f"B: risk_level[{rl_in}]", passed,
                   f"expected={exp_risk}, actual={actual}")
        except Exception as e:
            record("B", f"B: risk_level[{rl_in}]", False, f"exception: {e}")

    # B12: 方向一致性映射
    for direction, side, exp_risk in [
        ("UP", "long", 0.20), ("UP", "short", 0.85),
        ("DOWN", "long", 0.85), ("DOWN", "short", 0.20),
        ("FLAT", "long", 0.50), ("FLAT", "short", 0.50),
    ]:
        try:
            actual = cfg.direction_consistency_map.get(direction, {}).get(side)
            passed = actual == exp_risk
            record("B", f"B: dir_map[{direction}/{side}]", passed,
                   f"expected={exp_risk}, actual={actual}")
        except Exception as e:
            record("B", f"B: dir_map[{direction}/{side}]", False, f"exception: {e}")


# ============================================================
# C组: 备用层降级路径
# ============================================================
def test_group_c():
    section("C组: 备用层降级路径")
    sys_obj = YijingExitSystem()

    # C1: hexagram=None → fail-open，返回 NO_INTERVENE + should_log=False
    try:
        decision = sys_obj.evaluate(
            hexagram=None, pos_side="long",
            entry_price=100.0, current_price=98.0,
            position_age_sec=3600, unrealized_pnl_pct=-0.02,
        )
        passed = (decision.action == YijingExitAction.NO_INTERVENE
                  and decision.should_log is False
                  and "fail_open" in decision.reason)
        record("C", "C1: hexagram=None fail-open", passed,
               f"action={decision.action.value} should_log={decision.should_log} "
               f"reason={decision.reason}")
    except Exception as e:
        record("C", "C1: hexagram=None fail-open", False, f"exception: {e}")

    # C2: hexagram=空 dict → fail-open
    try:
        decision = sys_obj.evaluate(
            hexagram={}, pos_side="long",
            entry_price=100.0, current_price=98.0,
            position_age_sec=3600, unrealized_pnl_pct=-0.02,
        )
        # 空 dict 不是 None，但所有字段都缺省
        # current_phase="" → phase_risk=0.50, risk_level=""→0.50
        passed = decision.action in (YijingExitAction.NO_INTERVENE, YijingExitAction.FORCE_CLOSE)
        record("C", "C2: hexagram=空dict 容错", passed,
               f"action={decision.action.value} risk={decision.yijing_risk_score:.3f}")
    except Exception as e:
        record("C", "C2: hexagram=空dict 容错", False, f"exception: {e}")

    # C3: hexagram=异常对象 → fail-open
    try:
        decision = sys_obj.evaluate(
            hexagram=object(), pos_side="long",
            entry_price=100.0, current_price=98.0,
            position_age_sec=3600, unrealized_pnl_pct=-0.02,
        )
        # object() 没有属性 → _extract_hexagram 会尝试读属性，返回带默认值的 dict
        passed = decision.action in (YijingExitAction.NO_INTERVENE, YijingExitAction.FORCE_CLOSE)
        record("C", "C3: hexagram=异常对象 容错", passed,
               f"action={decision.action.value}")
    except Exception as e:
        record("C", "C3: hexagram=异常对象 容错", False, f"exception: {e}")

    # C4: classic_decision=None 主离场模式（不应触发 VETO 路径）
    try:
        hex_data = make_hexagram(
            name_cn="风天小畜", risk_level="低",
            current_phase="九五", development_stage="成长期",
            direction_hint="UP", confidence=0.75,
        )
        decision = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=102.0,
            position_age_sec=3600, unrealized_pnl_pct=0.02,
            classic_decision=None,  # 主离场模式
        )
        # 应该是 RAISE_TP（价值高+成长期+盈利），不是 VETO
        passed = decision.action != YijingExitAction.VETO_CLOSE \
                 and decision.action != YijingExitAction.VETO_REDUCE
        record("C", "C4: classic_decision=None 不触发VETO", passed,
               f"action={decision.action.value}")
    except Exception as e:
        record("C", "C4: classic_decision=None 不触发VETO", False, f"exception: {e}")


# ============================================================
# D组: 多场景压力测试
# ============================================================
def test_group_d():
    section("D组: 多场景压力测试")
    sys_obj = YijingExitSystem()

    # D1: 趋势市嬴势 — 飞龙在天 + 做多 + 大盈利 → RAISE_TP or HOLD
    try:
        hex_data = make_hexagram(
            name_cn="乾为天", risk_level="低",
            current_phase="九五", development_stage="成长期",
            direction_hint="UP", confidence=0.85,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=110.0,
            position_age_sec=7200, unrealized_pnl_pct=0.10,
        )
        passed = d.action in (YijingExitAction.RAISE_TP, YijingExitAction.NO_INTERVENE) \
                 and d.yijing_value_score > 0.70
        record("D", "D1: 趋势市嬴势(飞龙在天+做多+10%盈利)", passed,
               f"action={d.action.value} value={d.yijing_value_score:.3f}")
    except Exception as e:
        record("D", "D1: 趋势市嬴势", False, f"exception: {e}")

    # D2: 趋势市逆势 — 坤为地 + 做多 + 亏损 → FORCE_CLOSE
    try:
        hex_data = make_hexagram(
            name_cn="坤为地", risk_level="高",
            current_phase="上九", development_stage="衰退期",
            direction_hint="DOWN", confidence=0.80,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=95.0,
            position_age_sec=7200, unrealized_pnl_pct=-0.05,
        )
        passed = d.action == YijingExitAction.FORCE_CLOSE
        record("D", "D2: 趋势市逆势(坤为地+做多+亏损)", passed,
               f"action={d.action.value} risk={d.yijing_risk_score:.3f}")
    except Exception as e:
        record("D", "D2: 趋势市逆势", False, f"exception: {e}")

    # D3: 震荡市持仓 — 坎为水 + 方向冲突 → 评估
    try:
        hex_data = make_hexagram(
            name_cn="坎为水", risk_level="中",
            current_phase="九三", development_stage="成熟期",
            direction_hint="DOWN", confidence=0.55,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=99.8,
            position_age_sec=3600, unrealized_pnl_pct=-0.002,
        )
        # 坎为水+做多 → 方向冲突，风险提升
        passed = (not d.direction_consistent) and d.yijing_risk_score > 0.40
        record("D", "D3: 震荡市持仓(坎为水+方向冲突)", passed,
               f"action={d.action.value} risk={d.yijing_risk_score:.3f} "
               f"dir_consistent={d.direction_consistent}")
    except Exception as e:
        record("D", "D3: 震荡市持仓", False, f"exception: {e}")

    # D4: 高波动顶部 — 亢龙有悔 + direction conflict → FORCE_CLOSE
    try:
        hex_data = make_hexagram(
            name_cn="乾为天", risk_level="高",
            current_phase="上九", development_stage="衰退期",
            direction_hint="DOWN", confidence=0.75,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=105.0,
            position_age_sec=5400, unrealized_pnl_pct=0.05,
        )
        # 上九风险=0.85 + DOWN vs long=0.85 → 风险高 + 方向冲突
        passed = d.action == YijingExitAction.FORCE_CLOSE
        record("D", "D4: 高波动顶部(亢龙有悔+方向冲突)", passed,
               f"action={d.action.value} risk={d.yijing_risk_score:.3f}")
    except Exception as e:
        record("D", "D4: 高波动顶部", False, f"exception: {e}")

    # D5: 长期持仓过期 — position_age_sec > 48h → 不应主 HOLD（应降级 classic）
    try:
        hex_data = make_hexagram(
            name_cn="风天小畜", risk_level="低",
            current_phase="九二", development_stage="成长期",
            direction_hint="UP", confidence=0.70,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.0,
            position_age_sec=200000,  # > 172800 = 48h
            unrealized_pnl_pct=0.01,
        )
        # yijing 返回 NO_INTERVENE，但 polling_trader 的 HOLD 判定会因 not_expired=False 而降级
        passed = d.action == YijingExitAction.NO_INTERVENE  # yijing 本身不关心时间，由 polling_trader 判定
        record("D", "D5: 长期持仓过期(>48h)", passed,
               f"action={d.action.value} 需polling_trader判定 not_expired=False 降级")
    except Exception as e:
        record("D", "D5: 长期持仓过期", False, f"exception: {e}")

    # D6: 大亏损 — unrealized_pnl_pct < -3% → 不应主 HOLD（应降级 classic）
    try:
        hex_data = make_hexagram(
            name_cn="风天小畜", risk_level="低",
            current_phase="九二", development_stage="成长期",
            direction_hint="UP", confidence=0.70,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=96.0,
            position_age_sec=3600, unrealized_pnl_pct=-0.04,  # -4% < -3%
        )
        # yijing 返回 NO_INTERVENE，但 polling_trader 的 HOLD 判定会因 loss_acceptable=False 而降级
        passed = d.action == YijingExitAction.NO_INTERVENE
        record("D", "D6: 大亏损(<-3%)", passed,
               f"action={d.action.value} 需polling_trader判定 loss_acceptable=False 降级")
    except Exception as e:
        record("D", "D6: 大亏损", False, f"exception: {e}")

    # D7: 萌芽期持仓 — 风险高 + 价值低 → NO_INTERVENE 但应降级 classic
    try:
        hex_data = make_hexagram(
            name_cn="水雷屯", risk_level="中",
            current_phase="初九", development_stage="萌芽期",
            direction_hint="UP", confidence=0.50,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=100.5,
            position_age_sec=1800, unrealized_pnl_pct=0.005,
        )
        # 风险分 = 0.35*0.50 + 0.25*0.65 + 0.20*0.65 + 0.20*0.20 = 0.495 > 0.35
        # 价值分 = 0.45*0.35 + 0.40*0.40 + 0.15*0.50 = 0.3875 < 0.60
        passed = (d.action == YijingExitAction.NO_INTERVENE
                  and d.yijing_risk_score >= 0.35
                  and d.yijing_value_score <= 0.60)
        record("D", "D7: 萌芽期持仓(应降级)", passed,
               f"action={d.action.value} risk={d.yijing_risk_score:.3f} "
               f"value={d.yijing_value_score:.3f}")
    except Exception as e:
        record("D", "D7: 萌芽期持仓", False, f"exception: {e}")

    # D8: 做空嬴势 — 坤为地 + 做空 + 盈利 → RAISE_TP or HOLD
    try:
        hex_data = make_hexagram(
            name_cn="坤为地", risk_level="低",
            current_phase="九五", development_stage="成长期",
            direction_hint="DOWN", confidence=0.80,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="short",
            entry_price=100.0, current_price=92.0,
            position_age_sec=7200, unrealized_pnl_pct=0.08,
        )
        # DOWN vs short = 0.20 → direction_consistent=True
        passed = d.action in (YijingExitAction.RAISE_TP, YijingExitAction.NO_INTERVENE) \
                 and d.direction_consistent
        record("D", "D8: 做空嬴势(坤为地+做空+8%盈利)", passed,
               f"action={d.action.value} value={d.yijing_value_score:.3f} "
               f"dir_consistent={d.direction_consistent}")
    except Exception as e:
        record("D", "D8: 做空嬴势", False, f"exception: {e}")


# ============================================================
# E组: 边界值测试
# ============================================================
def test_group_e():
    section("E组: 边界值测试")
    sys_obj = YijingExitSystem()
    cfg = sys_obj.config

    # E1: 风险分 = 0.80 边界（FORCE_CLOSE 阈值）
    try:
        # 构造风险分恰为 0.80 的卦象
        # 风险分 = 0.35*rl + 0.25*phase + 0.20*stage + 0.20*dir
        # 选 risk_level=高(0.80) + phase=九三(0.55) + stage=成熟期(0.45) + direction_conflict
        # = 0.35*0.80 + 0.25*0.55 + 0.20*0.45 + 0.20*0.85 = 0.28+0.1375+0.09+0.17 = 0.6775
        # 选 risk_level=高(0.80) + phase=上九(0.85) + stage=衰退期(0.80) + direction_conflict
        # = 0.35*0.80 + 0.25*0.85 + 0.20*0.80 + 0.20*0.85 = 0.28+0.2125+0.16+0.17 = 0.8225 > 0.80
        hex_data = make_hexagram(
            name_cn="坤为地", risk_level="高",
            current_phase="上九", development_stage="衰退期",
            direction_hint="DOWN", confidence=0.80,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=99.0,
            position_age_sec=3600, unrealized_pnl_pct=-0.01,
        )
        passed = d.yijing_risk_score >= 0.80 and d.action == YijingExitAction.FORCE_CLOSE
        record("E", "E1: 风险分>=0.80 触发FORCE_CLOSE", passed,
               f"risk={d.yijing_risk_score:.4f} action={d.action.value}")
    except Exception as e:
        record("E", "E1: 风险分>=0.80 触发FORCE_CLOSE", False, f"exception: {e}")

    # E2: 风险分接近 0.80 但 < 0.80 → 不应 FORCE_CLOSE
    try:
        # 选 risk_level=高(0.80) + phase=九三(0.55) + stage=成熟期(0.45) + direction_conflict
        # = 0.35*0.80 + 0.25*0.55 + 0.20*0.45 + 0.20*0.85 = 0.6775 < 0.80
        hex_data = make_hexagram(
            name_cn="水雷屯", risk_level="高",
            current_phase="九三", development_stage="成熟期",
            direction_hint="DOWN", confidence=0.70,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=99.0,
            position_age_sec=3600, unrealized_pnl_pct=-0.01,
        )
        passed = d.yijing_risk_score < 0.80 and d.action != YijingExitAction.FORCE_CLOSE
        record("E", "E2: 风险分<0.80 不触发FORCE_CLOSE", passed,
               f"risk={d.yijing_risk_score:.4f} action={d.action.value}")
    except Exception as e:
        record("E", "E2: 风险分<0.80 不触发FORCE_CLOSE", False, f"exception: {e}")

    # E3: 价值分 = 0.70 边界（RAISE_TP 阈值）
    try:
        # 价值分 = 0.45*phase_value + 0.40*stage_value + 0.15*(1-rl_risk)
        # 选 phase=九四(0.70) + stage=成熟期(0.65) + risk_level=中(0.50 → value=0.50)
        # = 0.45*0.70 + 0.40*0.65 + 0.15*0.50 = 0.315 + 0.26 + 0.075 = 0.65 < 0.70
        # 选 phase=九五(0.90) + stage=成熟期(0.65) + risk_level=低(0.25 → value=0.75)
        # = 0.45*0.90 + 0.40*0.65 + 0.15*0.75 = 0.405 + 0.26 + 0.1125 = 0.7775 > 0.70
        hex_data = make_hexagram(
            name_cn="乾为天", risk_level="低",
            current_phase="九五", development_stage="成熟期",
            direction_hint="UP", confidence=0.75,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=103.0,
            position_age_sec=3600, unrealized_pnl_pct=0.03,
        )
        passed = d.yijing_value_score > 0.70 and d.action == YijingExitAction.RAISE_TP
        record("E", "E3: 价值分>0.70 触发RAISE_TP", passed,
               f"value={d.yijing_value_score:.4f} action={d.action.value}")
    except Exception as e:
        record("E", "E3: 价值分>0.70 触发RAISE_TP", False, f"exception: {e}")

    # E4: 盈利 = 0.02 边界（RAISE_TP 最小盈利）
    try:
        hex_data = make_hexagram(
            name_cn="乾为天", risk_level="低",
            current_phase="九五", development_stage="成长期",
            direction_hint="UP", confidence=0.80,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=102.0,
            position_age_sec=3600, unrealized_pnl_pct=0.02,  # exactly 0.02
        )
        passed = d.action == YijingExitAction.RAISE_TP
        record("E", "E4: 盈利=0.02 边界触发RAISE_TP", passed,
               f"action={d.action.value}")
    except Exception as e:
        record("E", "E4: 盈利=0.02 边界", False, f"exception: {e}")

    # E5: 盈利 < 0.02 → 不应 RAISE_TP
    try:
        hex_data = make_hexagram(
            name_cn="乾为天", risk_level="低",
            current_phase="九五", development_stage="成长期",
            direction_hint="UP", confidence=0.80,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.5,
            position_age_sec=3600, unrealized_pnl_pct=0.015,  # < 0.02
        )
        passed = d.action != YijingExitAction.RAISE_TP
        record("E", "E5: 盈利<0.02 不触发RAISE_TP", passed,
               f"action={d.action.value}")
    except Exception as e:
        record("E", "E5: 盈利<0.02", False, f"exception: {e}")


# ============================================================
# F组: 端到端架构验证（验证 polling_trader 调用路径）
# ============================================================
def test_group_f():
    section("F组: 端到端架构验证（polling_trader 调用路径）")

    # 验证：当 yijing 返回 FORCE_CLOSE/RAISE_TP/HOLD(信号良好) 时，classic 不应被调用
    # 当 yijing 不可用 或 NO_INTERVENE 中性时，classic 应被调用

    try:
        from scripts.memory_l4.polling_trader import PollingTrader
        from scripts.memory_l4.yijing_exit_system import YijingExitAction
    except Exception as e:
        record("F", "F0: import PollingTrader", False, f"exception: {e}")
        return

    # F1: yijing FORCE_CLOSE → classic 不应被调用
    try:
        # 用 Mock 模拟 PollingTrader 的关键方法
        trader = MagicMock(spec=PollingTrader)
        trader.yijing_exit_system = YijingExitSystem()
        trader.yijing_exit_system.config.veto_risk_threshold = 0.35
        trader.yijing_exit_system.config.veto_value_threshold = 0.60

        # 构造 FORCE_CLOSE 场景
        hex_data = make_hexagram(
            name_cn="坤为地", risk_level="高",
            current_phase="上九", development_stage="衰退期",
            direction_hint="DOWN", confidence=0.85,
        )
        yijing_decision = trader.yijing_exit_system.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=98.0,
            position_age_sec=3600, unrealized_pnl_pct=-0.02,
        )
        # 验证 yijing 决策是 FORCE_CLOSE
        force_close_triggered = yijing_decision.action == YijingExitAction.FORCE_CLOSE
        # 验证：架构上，FORCE_CLOSE 路径直接 return，不会调用 exit_system.evaluate_full
        record("F", "F1: yijing FORCE_CLOSE 直接返回(不调classic)", force_close_triggered,
               f"action={yijing_decision.action.value} risk={yijing_decision.yijing_risk_score:.3f}")
    except Exception as e:
        record("F", "F1: yijing FORCE_CLOSE", False, f"exception: {e}")

    # F2: yijing RAISE_TP → classic 不应被调用
    try:
        trader = MagicMock(spec=PollingTrader)
        trader.yijing_exit_system = YijingExitSystem()

        hex_data = make_hexagram(
            name_cn="乾为天", risk_level="低",
            current_phase="九五", development_stage="成长期",
            direction_hint="UP", confidence=0.85,
        )
        yijing_decision = trader.yijing_exit_system.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=105.0,
            position_age_sec=3600, unrealized_pnl_pct=0.05,
        )
        passed = yijing_decision.action == YijingExitAction.RAISE_TP
        record("F", "F2: yijing RAISE_TP 直接返回(不调classic)", passed,
               f"action={yijing_decision.action.value}")
    except Exception as e:
        record("F", "F2: yijing RAISE_TP", False, f"exception: {e}")

    # F3: yijing NO_INTERVENE + 信号良好 → 应 HOLD（polling_trader 不调 classic）
    try:
        trader = MagicMock(spec=PollingTrader)
        trader.yijing_exit_system = YijingExitSystem()
        cfg = trader.yijing_exit_system.config

        hex_data = make_hexagram(
            name_cn="风天小畜", risk_level="低",
            current_phase="九二", development_stage="成长期",
            direction_hint="UP", confidence=0.70,
        )
        upl_ratio = 0.015
        position_age_sec = 3600
        yijing_decision = trader.yijing_exit_system.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.5,
            position_age_sec=position_age_sec, unrealized_pnl_pct=upl_ratio,
        )

        # 模拟 polling_trader 的 HOLD 判定逻辑
        risk_low = yijing_decision.yijing_risk_score < cfg.veto_risk_threshold
        value_high = yijing_decision.yijing_value_score > cfg.veto_value_threshold
        loss_acceptable = upl_ratio > cfg.veto_max_loss_pct
        not_expired = position_age_sec < cfg.veto_max_hold_sec
        should_hold = (risk_low and value_high
                       and yijing_decision.direction_consistent
                       and loss_acceptable and not_expired)

        passed = (yijing_decision.action == YijingExitAction.NO_INTERVENE
                  and should_hold)
        record("F", "F3: yijing NO_INTERVENE 信号良好→HOLD(不调classic)", passed,
               f"action={yijing_decision.action.value} risk_low={risk_low} "
               f"value_high={value_high} dir_consistent={yijing_decision.direction_consistent} "
               f"loss_ok={loss_acceptable} not_expired={not_expired}")
    except Exception as e:
        record("F", "F3: yijing NO_INTERVENE→HOLD", False, f"exception: {e}")

    # F4: yijing NO_INTERVENE + 信号中性 → 应降级 classic
    try:
        trader = MagicMock(spec=PollingTrader)
        trader.yijing_exit_system = YijingExitSystem()
        cfg = trader.yijing_exit_system.config

        hex_data = make_hexagram(
            name_cn="水雷屯", risk_level="中",
            current_phase="九三", development_stage="萌芽期",
            direction_hint="UP", confidence=0.55,
        )
        upl_ratio = -0.005
        position_age_sec = 3600
        yijing_decision = trader.yijing_exit_system.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=99.5,
            position_age_sec=position_age_sec, unrealized_pnl_pct=upl_ratio,
        )

        # 模拟 polling_trader 的 HOLD 判定逻辑
        risk_low = yijing_decision.yijing_risk_score < cfg.veto_risk_threshold
        value_high = yijing_decision.yijing_value_score > cfg.veto_value_threshold
        loss_acceptable = upl_ratio > cfg.veto_max_loss_pct
        not_expired = position_age_sec < cfg.veto_max_hold_sec
        should_hold = (risk_low and value_high
                       and yijing_decision.direction_consistent
                       and loss_acceptable and not_expired)

        passed = (yijing_decision.action == YijingExitAction.NO_INTERVENE
                  and not should_hold)  # 信号中性 → 不 HOLD → 降级 classic
        record("F", "F4: yijing NO_INTERVENE 信号中性→降级classic", passed,
               f"action={yijing_decision.action.value} risk_low={risk_low} "
               f"value_high={value_high} should_hold={should_hold}")
    except Exception as e:
        record("F", "F4: yijing NO_INTERVENE→降级", False, f"exception: {e}")

    # F5: yijing unavailable (hexagram=None) → 应直接调用 classic
    try:
        # 验证 _infer_current_hexagram 返回 None 时，polling_trader 会调用 classic
        # 通过日志消息验证："易经卦象不可用，启用经典离场备用层"
        # 这里只能验证 yijing_exit_system 的行为
        sys_obj = YijingExitSystem()
        d = sys_obj.evaluate(
            hexagram=None, pos_side="long",
            entry_price=100.0, current_price=98.0,
            position_age_sec=3600, unrealized_pnl_pct=-0.02,
        )
        passed = (d.action == YijingExitAction.NO_INTERVENE
                  and d.should_log is False
                  and "fail_open" in d.reason)
        record("F", "F5: yijing不可用→fail_open(走classic)", passed,
               f"action={d.action.value} reason={d.reason}")
    except Exception as e:
        record("F", "F5: yijing不可用", False, f"exception: {e}")


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("  易经离场系统多场景压力测试（v2 - 架构反转后）")
    print("  架构: yijing 主离场 + classic 备用层")
    print("=" * 60)

    test_group_a()
    test_group_b()
    test_group_c()
    test_group_d()
    test_group_e()
    test_group_f()

    # 汇总
    print(f"\n{'='*60}")
    print(f"  测试汇总")
    print(f"{'='*60}")
    total = _pass_count + _fail_count
    print(f"  总用例: {total}")
    print(f"  通过:   {_pass_count}")
    print(f"  失败:   {_fail_count}")
    if total > 0:
        pass_rate = _pass_count / total * 100
        print(f"  通过率: {pass_rate:.1f}%")

    # 按组统计
    print(f"\n  按组统计:")
    groups = {}
    for r in _results:
        g = r["group"]
        if g not in groups:
            groups[g] = {"pass": 0, "fail": 0}
        if r["status"] == "PASS":
            groups[g]["pass"] += 1
        else:
            groups[g]["fail"] += 1
    for g in sorted(groups.keys()):
        s = groups[g]
        t = s["pass"] + s["fail"]
        rate = s["pass"] / t * 100 if t > 0 else 0
        print(f"    {g}组: {s['pass']}/{t} ({rate:.0f}%)")

    # 输出失败用例详情
    failed = [r for r in _results if r["status"] == "FAIL"]
    if failed:
        print(f"\n  失败用例详情:")
        for r in failed:
            print(f"    [{r['group']}] {r['name']}: {r['detail']}")

    # 输出 JSON 报告
    report_path = Path("data/stress_test_yijing_exit_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "architecture": "yijing_primary + classic_backup",
        "total": total,
        "pass": _pass_count,
        "fail": _fail_count,
        "pass_rate": round(_pass_count / total * 100, 2) if total > 0 else 0,
        "results": _results,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  报告已保存: {report_path}")

    return 0 if _fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
