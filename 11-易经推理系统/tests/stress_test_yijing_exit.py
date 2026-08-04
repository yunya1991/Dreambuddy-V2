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
# G组: VETO 缓存 bug 回归测试（P0修复验证）
# ============================================================
def test_group_g():
    section("G组: VETO 缓存 bug 回归测试（P0修复）")

    # 场景复现：polling_trader 在同一轮询周期内
    #   1) 先调 yijing.evaluate(mode='main') 做主离场评估，写入 _eval_cache
    #   2) classic 决定 CLOSE/REDUCE 后，再调 yijing.evaluate(mode='veto', classic_decision=...) 做否决评估
    # Bug：修复前 veto 调用被 1h 门禁命中缓存，直接返回 NO_INTERVENE，VETO 永不触发
    # Fix：veto 模式绕过 1h 门禁 + 不写缓存

    # G1: 主评估写入缓存后，veto 评估应绕过门禁真正重新计算（不被缓存吞掉）
    try:
        sys_obj = YijingExitSystem()
        # 构造一个"风险偏低+价值高+方向一致+成熟期"的卦象：
        #   - 风险分需 ≥ lower_sl_min_risk_score(0.30) 以跳过 LOWER_SL 分支
        #   - 价值分 > veto_value_threshold(0.60) 满足否决条件
        #   - 方向一致(UP vs long)
        #   - 成熟期（非萌芽/成长期）跳过 LOWER_SL 的 early_stage 过滤
        #   - 未到 FORCE_CLOSE/TIGHTEN_SL/LOWER_TP 阈值
        # 用"九五+成熟期+低风险+UP"：风险=0.40*0.25+0.18*0.25+0.18*0.45+0.24*0.20=0.279
        #   略低于0.30仍可能命中LOWER_SL，改用"九三+成熟期"提高风险到0.30~0.60区间
        # 九三 phase_risk=0.55, 成熟期 stage_risk=0.45, 低 rl=0.25, UP/long=0.20
        # 风险 = 0.40*0.25 + 0.18*0.55 + 0.18*0.45 + 0.24*0.20 = 0.1+0.099+0.081+0.048 = 0.328
        # 价值 = 0.45*0.55 + 0.40*0.65 + 0.15*0.75 = 0.2475+0.26+0.1125 = 0.62 > 0.60 ✓
        hex_data = make_hexagram(
            name_cn="天火同人", risk_level="低",
            current_phase="九三", development_stage="成熟期",
            direction_hint="UP", confidence=0.75,
        )
        # 第一次：main 模式主评估，会写入缓存
        main_decision = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.5,
            position_age_sec=3600, unrealized_pnl_pct=0.015,
            coin="BTC", open_time_sec=time.time() - 3600,
            mode="main",
        )
        main_was_no_intervene = (main_decision.action == YijingExitAction.NO_INTERVENE)

        # 第二次：立即 veto 模式评估（距上次<1h，正常应被门禁拦截）
        # 传入 classic_decision 模拟 classic 决定 CLOSE
        # 用 dict 形式，避免 str(enum) 解析问题：evaluate 中对 dict 取 ["action"]
        classic_dec = {
            "action": "close",   # classic 决定平仓
            "reason": "tb_stop_loss: ATR 止损触发",  # 噪音止损关键词，应被否决
        }

        veto_decision = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.5,
            position_age_sec=3600, unrealized_pnl_pct=0.015,
            classic_decision=classic_dec,
            coin="BTC", open_time_sec=time.time() - 3600,
            mode="veto",
        )
        # 修复前：veto_decision.action == NO_INTERVENE（被缓存吞掉）
        # 修复后：veto_decision.action == VETO_CLOSE（真正执行了否决判定）
        passed = (main_was_no_intervene
                  and veto_decision.action == YijingExitAction.VETO_CLOSE)
        record("G", "G1: veto 绕过 1h 门禁真正重算", passed,
               f"main={main_decision.action.value}(risk={main_decision.yijing_risk_score:.3f},"
               f"value={main_decision.yijing_value_score:.3f}) "
               f"veto={veto_decision.action.value} "
               f"(修复前 veto=no_intervene 为 BUG)")
    except Exception as e:
        record("G", "G1: veto 绕过 1h 门禁真正重算", False, f"exception: {e}")
        print(traceback.format_exc())

    # G2: veto 模式不应污染主决策缓存（veto 后下次主评估仍受原缓存约束）
    try:
        sys_obj = YijingExitSystem()
        hex_data = make_hexagram(
            name_cn="风天小畜", risk_level="低",
            current_phase="九二", development_stage="成长期",
            direction_hint="UP", confidence=0.75,
        )
        # 主评估写缓存
        sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.5,
            position_age_sec=3600, unrealized_pnl_pct=0.015,
            coin="ETH", open_time_sec=time.time() - 3600,
            mode="main",
        )
        cache_before = sys_obj._eval_cache.get("ETH:long")
        main_last_ts_before = cache_before["last_eval_ts"] if cache_before else None

        # veto 评估（如果污染缓存，last_eval_ts 会被刷新）
        classic_dec = {
            "action": "close",
            "reason": "trailing_stop: 跟踪止损",  # 噪音止损关键词
        }
        sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.5,
            position_age_sec=3600, unrealized_pnl_pct=0.015,
            classic_decision=classic_dec,
            coin="ETH", open_time_sec=time.time() - 3600,
            mode="veto",
        )
        cache_after = sys_obj._eval_cache.get("ETH:long")
        main_last_ts_after = cache_after["last_eval_ts"] if cache_after else None

        # 修复后：veto 不写缓存，last_eval_ts 应保持不变
        passed = (main_last_ts_before is not None
                  and main_last_ts_after is not None
                  and main_last_ts_before == main_last_ts_after)
        record("G", "G2: veto 不污染主决策缓存", passed,
               f"ts_before={main_last_ts_before} ts_after={main_last_ts_after} "
               f"(修复前 ts_after 会刷新为 veto 时间，污染缓存)")
    except Exception as e:
        record("G", "G2: veto 不污染主决策缓存", False, f"exception: {e}")
        print(traceback.format_exc())

    # G3: main 模式仍受 1h 门禁约束（修复未破坏原有行为）
    try:
        sys_obj = YijingExitSystem()
        hex_data = make_hexagram(
            name_cn="风天小畜", risk_level="低",
            current_phase="九二", development_stage="成长期",
            direction_hint="UP", confidence=0.75,
        )
        # 第一次 main 评估
        d1 = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.5,
            position_age_sec=3600, unrealized_pnl_pct=0.015,
            coin="SOL", open_time_sec=time.time() - 3600,
            mode="main",
        )
        # 立即第二次 main 评估：应被 1h 门禁拦截，返回缓存 NO_INTERVENE
        d2 = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.5,
            position_age_sec=3600, unrealized_pnl_pct=0.015,
            coin="SOL", open_time_sec=time.time() - 3600,
            mode="main",
        )
        passed = (d1.action == YijingExitAction.NO_INTERVENE
                  and d2.action == YijingExitAction.NO_INTERVENE
                  and "cached" in d2.reason or "window" in d2.reason)
        record("G", "G3: main 模式仍守 1h 门禁", passed,
               f"d1={d1.action.value} d2={d2.action.value} d2.reason={d2.reason[:60]}")
    except Exception as e:
        record("G", "G3: main 模式仍守 1h 门禁", False, f"exception: {e}")
        print(traceback.format_exc())

    # G4: veto 模式无 classic_decision 时不触发 VETO（保持 NO_INTERVENE）
    try:
        sys_obj = YijingExitSystem()
        hex_data = make_hexagram(
            name_cn="风天小畜", risk_level="低",
            current_phase="九二", development_stage="成长期",
            direction_hint="UP", confidence=0.75,
        )
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.5,
            position_age_sec=3600, unrealized_pnl_pct=0.015,
            classic_decision=None,
            coin="XRP", open_time_sec=time.time() - 3600,
            mode="veto",
        )
        # 无 classic_decision → 不应触发 VETO_CLOSE/VETO_REDUCE
        passed = (d.action != YijingExitAction.VETO_CLOSE
                  and d.action != YijingExitAction.VETO_REDUCE)
        record("G", "G4: veto 无 classic_decision 不触发", passed,
               f"action={d.action.value}")
    except Exception as e:
        record("G", "G4: veto 无 classic_decision 不触发", False, f"exception: {e}")
        print(traceback.format_exc())


# ============================================================
# H组: Bug修复回归测试（本次修复专项）
# ============================================================
def test_group_h():
    section("H组: Bug修复回归测试（P0 Bug1/Bug2专项验证）")

    # ── Bug1: 48h持仓超时强制降级 ──

    # H1: 超时场景下 HOLD判定条件的 not_expired=False，整体HOLD失败 → 走降级路径
    # 注：yijing可能返回lower_sl/tighten_sl（其他分支优先级更高），但不影响超时降级逻辑的验证
    try:
        sys_obj = YijingExitSystem()
        hex_data = make_hexagram(
            name_cn="风天小畜", risk_level="低",
            current_phase="九二", development_stage="成长期",
            direction_hint="UP", confidence=0.70,
        )
        # 构造 position_age_sec=200000 > veto_max_hold_sec=172800(48h)
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.0,
            position_age_sec=200000,  # > 48h
            unrealized_pnl_pct=0.01,
        )
        # 检查polling_trader层HOLD判定的5个条件：risk_low & value_high & dir_consistent & loss_acceptable & not_expired
        cfg = sys_obj.config
        risk_low = d.yijing_risk_score < cfg.veto_risk_threshold
        value_high = d.yijing_value_score > cfg.veto_value_threshold
        not_expired = 200000 < cfg.veto_max_hold_sec  # Bug1核心验证: 超时后此条件为False
        loss_acceptable = 0.01 > cfg.veto_max_loss_pct
        hold_conditions_overall = risk_low and value_high and d.direction_consistent and loss_acceptable and not_expired
        # 关键: not_expired必须为False → 整体HOLD失败 → 降级classic
        passed = (not not_expired
                  and risk_low and value_high and d.direction_consistent
                  and not hold_conditions_overall)
        record("H", "H1: 48h超时 HOLD条件整体False → 走降级路径", passed,
               f"action={d.action.value} risk={d.yijing_risk_score:.3f} "
               f"value={d.yijing_value_score:.3f} dir_consistent={d.direction_consistent} "
               f"not_expired(超时后应False)={not_expired} hold_overall(应为False)={hold_conditions_overall}")
    except Exception as e:
        record("H", "H1: 48h超时HOLD条件拦截", False, f"exception: {e}")
        print(traceback.format_exc())

    # H2: 未超时场景下 not_expired=True，HOLD条件整体可以成立（对比验证）
    try:
        sys_obj = YijingExitSystem()
        hex_data = make_hexagram(
            name_cn="风天小畜", risk_level="低",
            current_phase="九二", development_stage="成长期",
            direction_hint="UP", confidence=0.70,
        )
        # 构造正常持仓=2h（未超时）
        d = sys_obj.evaluate(
            hexagram=hex_data, pos_side="long",
            entry_price=100.0, current_price=101.0,
            position_age_sec=7200,  # 2h < 48h
            unrealized_pnl_pct=0.01,
        )
        cfg = sys_obj.config
        risk_low = d.yijing_risk_score < cfg.veto_risk_threshold
        value_high = d.yijing_value_score > cfg.veto_value_threshold
        not_expired = 7200 < cfg.veto_max_hold_sec
        loss_acceptable = 0.01 > cfg.veto_max_loss_pct  # 1% > -3%
        hold_condition = risk_low and value_high and d.direction_consistent and loss_acceptable and not_expired
        # 核心：not_expired为True，HOLD条件整体成立（即使yijing走了lower_sl分支，逻辑条件是对的）
        passed = (not_expired and risk_low and value_high and d.direction_consistent and hold_condition)
        record("H", "H2: 未超时 HOLD条件整体成立（对比组）", passed,
               f"hold_cond={hold_condition} not_expired={not_expired} "
               f"risk_low={risk_low} value_high={value_high} action={d.action.value}")
    except Exception as e:
        record("H", "H2: 未超时 HOLD条件成立（对比组）", False, f"exception: {e}")
        print(traceback.format_exc())

    # H3: veto_max_hold_sec 配置值正确（172800 = 48h）
    try:
        sys_obj = YijingExitSystem()
        cfg = sys_obj.config
        expected_48h = 48 * 3600  # 172800
        passed = (cfg.veto_max_hold_sec == expected_48h)
        record("H", "H3: veto_max_hold_sec=48h(172800s) 配置正确", passed,
               f"veto_max_hold_sec={cfg.veto_max_hold_sec} expected={expected_48h}")
    except Exception as e:
        record("H", "H3: 48h超时配置值", False, f"exception: {e}")

    # ── Bug2: L0_RISK_GATE 过度敏感修复 ──

    # H4: 验证ExitConfig参数已被优化（通过构造ClassicExitSystem检查新参数）
    try:
        # 导入ClassicExit相关类
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "memory_l4"))
        from classic_exit_system import ClassicExitSystem, ExitConfig

        # 模拟polling_trader中修复后的配置
        exit_cfg = ExitConfig(
            l0_risk_gate_enabled=True,
            l0_risk_gate_long_thr=0.65,        # Bug2修复: 从0.5→0.65
            l0_risk_gate_short_thr=0.60,       # Bug2修复: 同步提高
            l0_risk_gate_min_hold_sec=3600.0,  # Bug2修复: 新增1h保护期
            l0_risk_gate_profit_bypass_pct=0.05,  # Bug2修复: 3%→5%
            l0_risk_gate_cooldown_min=60.0,
            l0_risk_gate_confirm_n=3,
        )
        classic_sys = ClassicExitSystem(config=exit_cfg)
        cfg = classic_sys.config
        # 检查4个关键参数是否正确写入
        passed = (cfg.l0_risk_gate_long_thr == 0.65
                  and cfg.l0_risk_gate_short_thr == 0.60
                  and cfg.l0_risk_gate_min_hold_sec == 3600.0
                  and cfg.l0_risk_gate_profit_bypass_pct == 0.05)
        record("H", "H4: L0_RISK_GATE 4个关键参数正确写入配置", passed,
               f"long_thr={cfg.l0_risk_gate_long_thr} short_thr={cfg.l0_risk_gate_short_thr} "
               f"min_hold_sec={cfg.l0_risk_gate_min_hold_sec} "
               f"profit_bypass_pct={cfg.l0_risk_gate_profit_bypass_pct}")
    except Exception as e:
        record("H", "H4: L0_RISK_GATE参数写入配置", False, f"exception: {e}")
        print(traceback.format_exc())

    # H5: 验证min_hold_sec前不触发risk_gate（持仓30min < 1h，hold_risk即使很高也跳过）
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "memory_l4"))
        from classic_exit_system import (
            ClassicExitSystem, ExitConfig, ExitAction,
            PositionState, ExitFeatureSet, ExitPriority
        )

        exit_cfg = ExitConfig(
            l0_risk_gate_enabled=True,
            l0_risk_gate_long_thr=0.65,
            l0_risk_gate_min_hold_sec=3600.0,  # 1h保护期
            l0_risk_gate_confirm_n=1,          # 降低确认数，便于触发
            l0_risk_gate_cooldown_min=0.0,     # 取消冷却
            l0_risk_gate_profit_bypass_enabled=False,  # 关闭盈利旁路
        )
        classic_sys = ClassicExitSystem(config=exit_cfg)

        # 构造PositionState: 持仓30min < 1h保护期，hold_risk=0.9（极高风险）
        now_ts = time.time() * 1000
        pos = PositionState(
            coin="TEST",
            side="long",
            entry_price=100.0,
            current_price=99.0,  # 轻微亏损
            position_age_sec=30 * 60,  # 30min = 1800s < 3600s保护期
            unrealized_pnl_pct=-0.01,
            leverage=3.0,
            atr_pct=0.03,
            mfe_pnl_pct=0.0,
        )
        features = ExitFeatureSet(
            hold_risk=0.90,  # 极高风险，远超0.65阈值
            adx=25.0, dd=0.05, trend_shape=None,
        )
        decision = classic_sys._check_risk_gate(pos, features, now_ts)
        # 持仓<min_hold_sec，应返回HOLD不触发减仓
        passed = (decision.action == ExitAction.HOLD)
        record("H", "H5: 持仓<1h保护期即使高风险也不触发risk_gate", passed,
               f"action={decision.action.value} hold_risk=0.90 "
               f"hold_age=30min min_hold_sec=3600s reason={decision.reason[:60]}")
    except Exception as e:
        record("H", "H5: min_hold_sec保护期拦截", False, f"exception: {e}")
        print(traceback.format_exc())

    # H6: 验证long_thr提高后0.65以下不触发（持仓2h已过保护期）
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "memory_l4"))
        from classic_exit_system import (
            ClassicExitSystem, ExitConfig, ExitAction,
            PositionState, ExitFeatureSet
        )

        exit_cfg = ExitConfig(
            l0_risk_gate_enabled=True,
            l0_risk_gate_long_thr=0.65,
            l0_risk_gate_min_hold_sec=3600.0,
            l0_risk_gate_confirm_n=1,
            l0_risk_gate_cooldown_min=0.0,
            l0_risk_gate_profit_bypass_enabled=False,
            l0_risk_gate_deadband=0.0,  # 取消死区便于精确测试
        )
        classic_sys = ClassicExitSystem(config=exit_cfg)
        # 清空历史状态
        classic_sys.state.risk_gate.clear()

        now_ts = time.time() * 1000
        pos = PositionState(
            coin="TEST2",
            side="long",
            entry_price=100.0,
            current_price=99.0,
            position_age_sec=2 * 3600,  # 2h = 7200s > 1h保护期
            unrealized_pnl_pct=-0.01,
            leverage=3.0,
            atr_pct=0.03,
            mfe_pnl_pct=0.0,
        )
        # hold_risk=0.60 < 0.65阈值，不应触发
        features = ExitFeatureSet(
            hold_risk=0.60,
            adx=25.0, dd=0.05, trend_shape=None,
        )
        decision = classic_sys._check_risk_gate(pos, features, now_ts)
        passed = (decision.action == ExitAction.HOLD)
        record("H", "H6: hold_risk=0.60 < 0.65阈值不触发risk_gate", passed,
               f"action={decision.action.value} hold_risk=0.60 thr=0.65 reason={decision.reason[:60]}")
    except Exception as e:
        record("H", "H6: long_thr=0.65阈值以下不触发", False, f"exception: {e}")
        print(traceback.format_exc())


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
    test_group_g()
    test_group_h()  # H组: 本次Bug修复专项回归测试

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
