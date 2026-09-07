"""阶段匹配策略映射表 — PhaseStrategyMap。

spec 3.8 节落地：`phase × rank → {信号权重偏移, SL/TP 空间建议, 持仓时间建议}`，
Shadow 模式不耦合 BCRM2.0，仅记录策略提示到 JSONL 审计日志。

三阶段闭环（用户 2026-09-01 确认）：
  - P1 预期驱动（CRCL 锚定）：主网上线/升级/合作 → 预期溢价
  - P2 盈收扩张（UNI 锚定）：如 Robinhood 接入带来费用收入大增 → 趋势持仓
  - P3 估值修复（HYPE 锚定）：盈收强+估值稳，大跌后强势修复 → 中长承接

用户最新补充（必须融入）：
  1. 抄新不抄旧：阶段优先级 P1 > P2 > P3（CRCL > UNI > HYPE）
  2. 预期落地后短期炒作风险上升 → 需从 UNI/HYPE 重新评估（on_event_landed_hint）
  3. 持续跟踪优质标的（非一次性判定）

约束：
  - Shadow 纯数据原则：所有字段必须是基本类型（int/float/str/bool/None），不含 callable
  - FAIL-OPEN：未知 phase/rank → 返回 NEUTRAL_STRATEGY_HINT
  - 案例锚定用于 CBR 相似度检索（新标的与案例相似度越高，策略越向案例靠拢）
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from force_vector.coin_fundamental_phase_classifier import (
    P1_EXPECTATION,
    P2_REVENUE_EXPANSION,
    P3_VALUATION_RECOVERY,
)


# ===========================================================================
# 开关（Shadow 模式默认 False，仅记录审计日志）
# ===========================================================================

ENABLE_PHASE_STRATEGY_MAP = False


# ===========================================================================
# 优先级权重（抄新不抄旧）
# ===========================================================================

# 阶段优先级：P1 > P2 > P3
# 用户原话："现阶段 UNI 和 CRCL 机会更大，UNI 和 CRCL 中由于 CRCL 有机会
# 预期机会更大，抄新不抄旧"。
_PHASE_PRIORITY_WEIGHT = {
    P1_EXPECTATION: 3,
    P2_REVENUE_EXPANSION: 2,
    P3_VALUATION_RECOVERY: 1,
}


# ===========================================================================
# 案例锚定
# ===========================================================================

# 每个 phase 的基准案例，用于 CBR 相似度检索
_CASE_ANCHOR = {
    P1_EXPECTATION: "CRCL",
    P2_REVENUE_EXPANSION: "UNI",
    P3_VALUATION_RECOVERY: "HYPE",
}


# ===========================================================================
# 策略映射表
# ===========================================================================

# phase × rank → 策略提示
# 字段：
#   signal_weight_bias    : float  信号权重偏移（+0.1=加权, 0.0=中性, -0.1=减权）
#   sl_space_hint         : str   SL 空间建议（down/normal/up/skip）
#   tp_space_hint         : str   TP 空间建议（down/normal/up/skip）
#   holding_period_hint   : str   持仓时间建议（short/trend/trend_light/mid_long/light/none）
#   case_anchor           : str   案例锚定（CRCL/UNI/HYPE）
#   priority_weight       : int    阶段优先级权重（抄新不抄旧）
#   action_desc           : str   动作描述（人类可读）
PHASE_STRATEGY_MAP: Dict[str, Dict[str, Dict[str, Any]]] = {
    # -------------------------------------------------------------------------
    # P1 预期驱动阶段（CRCL 锚定）
    # -------------------------------------------------------------------------
    P1_EXPECTATION: {
        "S": {
            "signal_weight_bias": 0.1,
            "sl_space_hint": "normal",
            "tp_space_hint": "up",
            "holding_period_hint": "short",
            "case_anchor": "CRCL",
            "priority_weight": 3,
            "action_desc": "TP空间↑(预期溢价)、持仓短(预期落地前撤离)",
        },
        "A": {
            "signal_weight_bias": 0.0,
            "sl_space_hint": "down",
            "tp_space_hint": "normal",
            "holding_period_hint": "short",
            "case_anchor": "CRCL",
            "priority_weight": 3,
            "action_desc": "轻仓试错、SL空间↓(预期波动大)",
        },
        "B": {
            "signal_weight_bias": -0.1,
            "sl_space_hint": "skip",
            "tp_space_hint": "skip",
            "holding_period_hint": "none",
            "case_anchor": "CRCL",
            "priority_weight": 0,  # B级不开仓，priority_weight=0
            "action_desc": "不开",
        },
    },
    # -------------------------------------------------------------------------
    # P2 盈收扩张阶段（UNI 锚定）
    # -------------------------------------------------------------------------
    P2_REVENUE_EXPANSION: {
        "S": {
            "signal_weight_bias": 0.1,
            "sl_space_hint": "normal",
            "tp_space_hint": "up",
            "holding_period_hint": "trend",
            "case_anchor": "UNI",
            "priority_weight": 2,
            "action_desc": "趋势持仓、TP空间↑(盈收扩张持续)、SL常规",
        },
        "A": {
            "signal_weight_bias": 0.0,
            "sl_space_hint": "normal",
            "tp_space_hint": "normal",
            "holding_period_hint": "trend_light",
            "case_anchor": "UNI",
            "priority_weight": 2,
            "action_desc": "跟踪盈收兑现、趋势轻持",
        },
        "B": {
            "signal_weight_bias": -0.1,
            "sl_space_hint": "skip",
            "tp_space_hint": "skip",
            "holding_period_hint": "none",
            "case_anchor": "UNI",
            "priority_weight": 0,
            "action_desc": "观察",
        },
    },
    # -------------------------------------------------------------------------
    # P3 估值修复阶段（HYPE 锚定）
    # -------------------------------------------------------------------------
    P3_VALUATION_RECOVERY: {
        "S": {
            "signal_weight_bias": 0.1,
            "sl_space_hint": "down",
            "tp_space_hint": "normal",
            "holding_period_hint": "mid_long",
            "case_anchor": "HYPE",
            "priority_weight": 1,
            "action_desc": "大跌承接、SL空间↓(修复力强)、持仓中长",
        },
        "A": {
            "signal_weight_bias": 0.0,
            "sl_space_hint": "normal",
            "tp_space_hint": "normal",
            "holding_period_hint": "light",
            "case_anchor": "HYPE",
            "priority_weight": 1,
            "action_desc": "大盘稳定时轻仓",
        },
        "B": {
            "signal_weight_bias": -0.1,
            "sl_space_hint": "skip",
            "tp_space_hint": "skip",
            "holding_period_hint": "none",
            "case_anchor": "HYPE",
            "priority_weight": 0,
            "action_desc": "观察",
        },
    },
}


# ===========================================================================
# 中性策略提示（FAIL-OPEN 兜底）
# ===========================================================================

NEUTRAL_STRATEGY_HINT: Dict[str, Any] = {
    "signal_weight_bias": 0.0,
    "sl_space_hint": "normal",
    "tp_space_hint": "normal",
    "holding_period_hint": "none",
    "case_anchor": "",
    "priority_weight": 0,
    "action_desc": "neutral (fail-open)",
}


# ===========================================================================
# 预期落地切换提示（用户最新补充）
# ===========================================================================

# 用户原话："一旦预期落地，短期风险较高，则会进入到类似 UNI 的增长模式，
# 需要跟踪实际基本盘的盈收是否改善...等估值到达一定阶段，就会出现类似
# HYPE 这类"。
#
# 每个 phase 的"落地后下一阶段"提示：
#   P1 落地 → P2（盈收跟踪，revenue_track_required=True）
#   P2 估值到高位 → P3（估值修复，valuation_high_required=True）
#   P3 终态 → None 或循环回 P1（生命周期再启动）
_EVENT_LANDED_SWITCH_HINT: Dict[str, Dict[str, Any]] = {
    P1_EXPECTATION: {
        "next_phase": P2_REVENUE_EXPANSION,
        "risk_note": "预期落地后短期炒作风险上升，需转入盈收兑现跟踪",
        "revenue_track_required": True,
        "valuation_high_required": False,
    },
    P2_REVENUE_EXPANSION: {
        "next_phase": P3_VALUATION_RECOVERY,
        "risk_note": "估值到高位后盈收扩张放缓，转入估值修复阶段",
        "revenue_track_required": False,
        "valuation_high_required": True,
    },
    P3_VALUATION_RECOVERY: {
        # P3 是终态：要么无下一阶段，要么循环回 P1（新一轮预期启动）
        "next_phase": None,
        "risk_note": "P3 为生命周期终态，等待新一轮预期启动循环回 P1",
        "revenue_track_required": False,
        "valuation_high_required": False,
    },
}

_NEUTRAL_LANDED_HINT: Dict[str, Any] = {
    "next_phase": None,
    "risk_note": "neutral (fail-open)",
    "revenue_track_required": False,
    "valuation_high_required": False,
}


# ===========================================================================
# 查表函数
# ===========================================================================

def get_strategy_hint(phase: Optional[str], rank: Optional[str]) -> Dict[str, Any]:
    """查表返回 phase × rank 的策略提示。

    FAIL-OPEN：未知 phase/rank 或 None → 返回 NEUTRAL_STRATEGY_HINT。

    Shadow 模式：返回纯数据 dict，不含 callable，可直接 JSON 序列化到审计日志。
    """
    if not phase or not rank:
        return dict(NEUTRAL_STRATEGY_HINT)

    rank_map = PHASE_STRATEGY_MAP.get(phase)
    if rank_map is None:
        return dict(NEUTRAL_STRATEGY_HINT)

    hint = rank_map.get(rank)
    if hint is None:
        return dict(NEUTRAL_STRATEGY_HINT)

    # 返回副本，避免外部修改原表
    return dict(hint)


def get_priority_weight(phase: Optional[str]) -> int:
    """返回阶段优先级权重（抄新不抄旧：P1=3 > P2=2 > P3=1）。

    FAIL-OPEN：未知 phase → 返回 0（最低，避免误排序）。
    """
    if not phase:
        return 0
    return _PHASE_PRIORITY_WEIGHT.get(phase, 0)


def get_case_anchor(phase: Optional[str]) -> str:
    """返回阶段对应的案例锚定（CRCL/UNI/HYPE）。

    用于 CBR 相似度检索：新标的与案例相似度越高，策略越向案例靠拢。
    FAIL-OPEN：未知 phase → 返回空字符串。
    """
    if not phase:
        return ""
    return _CASE_ANCHOR.get(phase, "")


def get_event_landed_switch_hint(phase: Optional[str]) -> Dict[str, Any]:
    """返回阶段"落地后切换"提示（用户最新补充）。

    P1 落地 → P2（盈收跟踪）
    P2 估值到高位 → P3（估值修复）
    P3 终态 → None（等待循环回 P1）

    FAIL-OPEN：未知 phase → 返回中性提示（不切换）。
    """
    if not phase:
        return dict(_NEUTRAL_LANDED_HINT)
    hint = _EVENT_LANDED_SWITCH_HINT.get(phase)
    if hint is None:
        return dict(_NEUTRAL_LANDED_HINT)
    return dict(hint)


# ===========================================================================
# Shadow 审计日志辅助（可选：记录策略提示到 JSONL）
# ===========================================================================

def build_shadow_audit_record(
    coin: str,
    phase: str,
    rank: str,
    ts_ms: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造 Shadow 审计记录（用于写入 JSONL 审计日志）。

    Shadow 模式不耦合 BCRM2.0，仅记录策略提示供后续分析。
    """
    hint = get_strategy_hint(phase, rank)
    landed_hint = get_event_landed_switch_hint(phase)
    record: Dict[str, Any] = {
        "coin": coin,
        "phase": phase,
        "rank": rank,
        "ts_ms": ts_ms,
        "strategy_hint": hint,
        "event_landed_next_phase": landed_hint.get("next_phase"),
        "case_anchor": get_case_anchor(phase),
        "priority_weight": get_priority_weight(phase),
    }
    if extra:
        record.update(extra)
    return record
