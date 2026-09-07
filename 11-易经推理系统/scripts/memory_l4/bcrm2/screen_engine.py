"""BCRM2 特征集成双保险三层防护：L1 审计标签 / L2 同向抑制 / L3 反向熔断。

项目记忆硬约束：模块化独立关断开关架构。
  - L1（强制）：写审计标签，纯记录，不可关断。
  - L2（默认开）：战略层防守档 + 仓位过重 + 特征重叠高时，抑制仓位放大。
  - L3（默认关）：防守档下连续高仓位亏损累计达到阈值，暂停交易若干小时。
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import pandas as pd


# ============================================================================
# FEATURE_INTEGRATION_GUARD 默认配置（10 子开关 + 参数，严格对齐全局 fixture）
# ============================================================================

FEATURE_INTEGRATION_GUARD: dict = {
    # L1 强制开启（总开关；但 L1 本身 attach_l1_audit 永远生效，不受此开关控制语义，
    # 仅作为顶层“存在性”声明对外暴露；即便 switch=False，attach_l1_audit 仍执行 —— 满足项目“强制”定义）
    "enable_l1_audit_tag": True,
    # L2 同向抑制（默认开）
    "enable_l2_same_direction_suppression": True,
    # L3 反向熔断（默认关）
    "enable_l3_conflict_circuit_breaker": False,
    # L2 参数：触发时的 war_state 阈值（≥ 此档才认为是防守档）；ALL 档顺序 ALLOW < COOLDOWN < FREEZE
    "l2_war_state_threshold": "COOLDOWN",
    # L2 参数：仓位超过此比例 → 认为“放大风险”
    "l2_position_cap_before": 0.50,
    # L2 参数：抑制后 cap 到此比例
    "l2_position_cap_after": 0.40,
    # L2 参数：特征来源重叠率超过此值 → 认为同向共振风险
    "l2_overlap_pct_threshold": 0.40,
    # L3 参数：满足“防守档 + 高仓位 + 亏损”的连续交易笔数阈值
    "l3_consecutive_losses": 3,
    # L3 参数：触发后暂停小时数
    "l3_pause_duration_hours": 4,
}

# war_state 严重程度等级（用于阈值比较）
_WAR_STATE_RANK = {"ALLOW": 0, "COOLDOWN": 1, "FREEZE": 2}


def get_feature_integration_guard() -> dict:
    """返回 guard 配置的深拷贝（避免调用方篡改全局默认）。"""
    return copy.deepcopy(FEATURE_INTEGRATION_GUARD)


# ============================================================================
# L1 审计标签（强制开启，纯记录）
# ============================================================================

def attach_l1_audit(trade_dict: dict, war_state: str, overlap_pct: float) -> dict:
    """把战略层 war_state 和特征重叠率注入到 trade 记录（纯记录，不改变决策）。

    写入两个字段：strategic_war_state / feature_overlap_pct。
    项目记忆要求：L1 强制。
    """
    out = dict(trade_dict) if isinstance(trade_dict, dict) else {}
    out["strategic_war_state"] = war_state
    out["feature_overlap_pct"] = float(overlap_pct)
    return out


def compute_source_overlap_pct(lstar_sources: Iterable, strategic_sources: Iterable) -> float:
    """计算 BCRM2 L* 视角与战略层视角的“数据来源列名”重叠率。

    overlap = |L* ∩ S| / min(|L*|, |S|)    —— 按较小一方归一（更保守评估重叠程度）。
    若任一方为空集 → 返回 0.0。
    """
    L = set(lstar_sources)
    S = set(strategic_sources)
    if not L or not S:
        return 0.0
    inter = len(L & S)
    return inter / min(len(L), len(S))


# ============================================================================
# L2 同向抑制（默认开）
# ============================================================================

def _war_state_ge(war_state: str, threshold: str) -> bool:
    """war_state 严重程度 ≥ 阈值？未知档按 ALLOW 处理（FAIL-OPEN：不触发抑制）。"""
    return _WAR_STATE_RANK.get(war_state, 0) >= _WAR_STATE_RANK.get(threshold, 0)


def apply_l2_if_needed(position_pct: float, war_state: str, overlap_pct: float,
                       guard_cfg: dict, trade_id: str = "") -> tuple:
    """L2 同向抑制：防守档 + 高仓位 + 高重叠 → 把仓位 cap 到指定上限。

    Returns:
        (new_position_pct: float, log_line: str)
        未触发时 log_line 为空串；触发时 log_line 含 [L2-SUPPRESS] 前缀。
    """
    cfg = guard_cfg or FEATURE_INTEGRATION_GUARD
    # 开关关断 → 直接原仓位 bypass
    if not cfg.get("enable_l2_same_direction_suppression", True):
        return float(position_pct), ""

    threshold_ws = cfg.get("l2_war_state_threshold", "COOLDOWN")
    cap_before = float(cfg.get("l2_position_cap_before", 0.50))
    cap_after = float(cfg.get("l2_position_cap_after", 0.40))
    overlap_thr = float(cfg.get("l2_overlap_pct_threshold", 0.40))

    trigger = (
        _war_state_ge(war_state, threshold_ws)
        and float(position_pct) > cap_before
        and float(overlap_pct) > overlap_thr
    )
    if not trigger:
        return float(position_pct), ""

    new_pos = min(float(position_pct), cap_after)
    tid = f"trade={trade_id} " if trade_id else ""
    # 统一用两位小数（匹配测试 fixture 的典型断言：0.62→0.40 / FREEZE 等）
    pp_str = f"{position_pct:.2f}" if abs(position_pct - round(position_pct, 2)) < 1e-9 else f"{position_pct}"
    np_str = f"{new_pos:.2f}" if abs(new_pos - round(new_pos, 2)) < 1e-9 else f"{new_pos}"
    overlap_str = f"{overlap_pct:.3f}"
    log_line = (
        f"[L2-SUPPRESS] {tid}war={war_state} overlap={overlap_str} "
        f"pos={pp_str}→{np_str} (cap_before={cap_before:.2f} cap_after={cap_after:.2f})"
    )
    return new_pos, log_line


# ============================================================================
# L3 反向熔断（默认关）
# ============================================================================

def _is_defensive_war_state(ws: str) -> bool:
    """防守档：COOLDOWN 或 FREEZE（ALLOW 不算）。"""
    return _WAR_STATE_RANK.get(ws, 0) >= _WAR_STATE_RANK["COOLDOWN"]


def check_l3_and_maybe_pause(recent_trades: list, guard_cfg: dict,
                             now: Any = None) -> tuple:
    """L3 反向熔断：防守档 + 连续 N 笔≥30% 仓位亏损 → 暂停 P 小时。

    Args:
        recent_trades: [{"position_pct": float, "pnl": float, "war_state": str, ...}]，
            语义按“最近的交易”顺序；streak 从头开始扫描，遇到不符合（非防守档/仓位<30%/盈利）
            的条目就清零连续计数，符合则 +1，达到阈值即触发。
        guard_cfg: 配置 dict
        now: pd.Timestamp（推荐）/ datetime/ None；None 时用 pd.Timestamp.now(tz="UTC")

    Returns:
        (paused: bool, until_ts: Optional[pd.Timestamp], log_line: str)
        未触发：(False, None, "")
    """
    cfg = guard_cfg or FEATURE_INTEGRATION_GUARD
    if not cfg.get("enable_l3_conflict_circuit_breaker", False):
        return False, None, ""

    need = int(cfg.get("l3_consecutive_losses", 3))
    pause_h = int(cfg.get("l3_pause_duration_hours", 4))
    min_pos = 0.30  # ≥30% 仓位才算高仓位（项目记忆语义，阈值硬编码）

    streak = 0
    for t in recent_trades:
        ws = t.get("war_state", "ALLOW") if isinstance(t, dict) else "ALLOW"
        pos = float(t.get("position_pct", 0.0)) if isinstance(t, dict) else 0.0
        pnl = float(t.get("pnl", 0.0)) if isinstance(t, dict) else 0.0
        qualifies = _is_defensive_war_state(ws) and pos >= min_pos and pnl < 0.0
        if qualifies:
            streak += 1
            if streak >= need:
                break
        else:
            streak = 0  # 不满足 → 连续计数清零

    if streak < need:
        return False, None, ""

    if now is None:
        now_ts = pd.Timestamp.now(tz="UTC")
    elif isinstance(now, pd.Timestamp):
        now_ts = now.tz_localize("UTC") if now.tzinfo is None else now
    elif isinstance(now, datetime):
        now_ts = pd.Timestamp(now)
        if now_ts.tzinfo is None:
            now_ts = now_ts.tz_localize("UTC")
    else:
        now_ts = pd.Timestamp(str(now), tz="UTC")

    until_ts = now_ts + pd.Timedelta(hours=pause_h)
    log_line = (
        f"[L3-CIRCUIT] defensive_war_streak_stopped streak={streak} "
        f"pause={pause_h}h until={until_ts.isoformat()}"
    )
    return True, until_ts, log_line
