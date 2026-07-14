#!/usr/bin/env python3
"""
建议反馈与风险控制模块 — 16-调控系统 Phase 3

功能：
  1. 建议反馈机制 — 记录各系统对统一离场建议的采纳/拒绝情况
  2. 风险控制权限管理 — 按系统/紧急度分级的建议执行权限
  3. 执行审计日志 — 完整的建议→执行→结果链路追踪
  4. 效果统计 — 采纳建议 vs 不采纳建议的绩效对比

权限等级体系（从低到高）：
  NOTIFY     - 仅通知，不执行
  ADVISE     - 建议执行，人工确认
  AUTO_REDUCE - 自动减仓（≤50%）
  AUTO_CLOSE - 自动平仓（仅限 P0 安全硬退出）
  FULL_AUTO  - 全自动（所有建议自动执行）

各系统默认权限：
  - agent_a/b/c: ADVISE（建议制）
  - v15_martin: NOTIFY（马丁系统自主离场为主）
  - yijing_bcrm: ADVISE（易经系统人工干预）
  - screen_trend: NOTIFY（三屏系统技术离场为主）
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum


BASE_DIR = Path(__file__).parent.parent.parent
FEEDBACK_DIR = BASE_DIR / "16-调控系统" / "artifacts" / "feedback"
PERMISSION_CONFIG_PATH = BASE_DIR / "16-调控系统" / "config" / "permission_config.json"


class PermissionLevel(str, Enum):
    """权限等级"""
    NOTIFY = "NOTIFY"
    ADVISE = "ADVISE"
    AUTO_REDUCE = "AUTO_REDUCE"
    AUTO_CLOSE = "AUTO_CLOSE"
    FULL_AUTO = "FULL_AUTO"


PERMISSION_RANK = {
    "NOTIFY": 0,
    "ADVISE": 1,
    "AUTO_REDUCE": 2,
    "AUTO_CLOSE": 3,
    "FULL_AUTO": 4,
}

URGENCY_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

DEFAULT_SYSTEM_PERMISSIONS = {
    "agent_a": {
        "permission_level": "ADVISE",
        "auto_execute_urgency": "CRITICAL",
        "max_auto_reduce_pct": 0.3,
        "notes": "默认建议制，CRITICAL 级别可自动减仓30%",
    },
    "agent_b": {
        "permission_level": "ADVISE",
        "auto_execute_urgency": "CRITICAL",
        "max_auto_reduce_pct": 0.3,
        "notes": "默认建议制，CRITICAL 级别可自动减仓30%",
    },
    "agent_c": {
        "permission_level": "ADVISE",
        "auto_execute_urgency": "CRITICAL",
        "max_auto_reduce_pct": 0.3,
        "notes": "默认建议制，CRITICAL 级别可自动减仓30%",
    },
    "v15_martin": {
        "permission_level": "NOTIFY",
        "auto_execute_urgency": "CRITICAL",
        "max_auto_reduce_pct": 0.0,
        "notes": "马丁系统以自主离场为主，仅通知",
    },
    "yijing_bcrm": {
        "permission_level": "ADVISE",
        "auto_execute_urgency": "HIGH",
        "max_auto_reduce_pct": 0.5,
        "notes": "易经系统建议制，HIGH 以上可减仓50%",
    },
    "screen_trend": {
        "permission_level": "NOTIFY",
        "auto_execute_urgency": "CRITICAL",
        "max_auto_reduce_pct": 0.0,
        "notes": "三屏趋势以技术离场为主，仅通知",
    },
}


def load_permission_config() -> Dict[str, Any]:
    """加载权限配置"""
    if PERMISSION_CONFIG_PATH.exists():
        try:
            with open(PERMISSION_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"systems": DEFAULT_SYSTEM_PERMISSIONS, "version": "1.0.0-default"}


def save_permission_config(config: Dict[str, Any]):
    """保存权限配置"""
    PERMISSION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PERMISSION_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_system_permission(system_name: str) -> Dict[str, Any]:
    """获取指定系统的权限配置"""
    config = load_permission_config()
    systems = config.get("systems", {})
    if system_name in systems:
        return systems[system_name]
    return {
        "permission_level": "NOTIFY",
        "auto_execute_urgency": "CRITICAL",
        "max_auto_reduce_pct": 0.0,
        "notes": "未配置系统，默认仅通知",
    }


def can_auto_execute(system_name: str, action: str, urgency: str) -> Dict[str, Any]:
    """
    判断是否可以自动执行建议

    Args:
        system_name: 系统名称
        action: 建议动作（CLOSE/REDUCE/HOLD/RAISE_TP）
        urgency: 紧急度（LOW/MEDIUM/HIGH/CRITICAL）

    Returns:
        {
            "can_execute": bool,
            "reason": str,
            "max_reduce_pct": float,  # 仅 REDUCE 时有意义
            "permission_level": str,
        }
    """
    perm = get_system_permission(system_name)
    level = perm.get("permission_level", "NOTIFY")
    level_rank = PERMISSION_RANK.get(level, 0)
    urgency_rank = URGENCY_LEVELS.index(urgency) if urgency in URGENCY_LEVELS else 0
    auto_urgency = perm.get("auto_execute_urgency", "CRITICAL")
    auto_urgency_rank = URGENCY_LEVELS.index(auto_urgency) if auto_urgency in URGENCY_LEVELS else 3

    if action == "HOLD" or action == "RAISE_TP":
        return {
            "can_execute": False,
            "reason": f"{action} 类建议无需自动执行",
            "permission_level": level,
            "max_reduce_pct": 0.0,
        }

    if level_rank >= PERMISSION_RANK["FULL_AUTO"]:
        return {
            "can_execute": True,
            "reason": "全自动模式，所有建议自动执行",
            "permission_level": level,
            "max_reduce_pct": 1.0 if action == "REDUCE" else 0.0,
        }

    if urgency_rank < auto_urgency_rank:
        return {
            "can_execute": False,
            "reason": f"紧急度({urgency})低于自动执行阈值({auto_urgency})",
            "permission_level": level,
            "max_reduce_pct": 0.0,
        }

    if action == "CLOSE":
        if level_rank >= PERMISSION_RANK["AUTO_CLOSE"]:
            return {
                "can_execute": True,
                "reason": f"权限等级({level})允许自动平仓，紧急度({urgency})达标",
                "permission_level": level,
                "max_reduce_pct": 1.0,
            }
        else:
            return {
                "can_execute": False,
                "reason": f"权限等级({level})不允许自动平仓，需要人工确认",
                "permission_level": level,
                "max_reduce_pct": 0.0,
            }

    if action == "REDUCE":
        if level_rank >= PERMISSION_RANK["AUTO_REDUCE"]:
            max_pct = perm.get("max_auto_reduce_pct", 0.3)
            return {
                "can_execute": True,
                "reason": f"权限等级({level})允许自动减仓，最大比例 {max_pct:.0%}",
                "permission_level": level,
                "max_reduce_pct": max_pct,
            }
        else:
            return {
                "can_execute": False,
                "reason": f"权限等级({level})不允许自动减仓",
                "permission_level": level,
                "max_reduce_pct": 0.0,
            }

    return {
        "can_execute": False,
        "reason": "未知动作类型",
        "permission_level": level,
        "max_reduce_pct": 0.0,
    }


@dataclass
class FeedbackRecord:
    """建议反馈记录"""
    evaluation_id: str
    system_name: str
    symbol: str
    position_direction: str
    recommended_action: str
    recommendation_urgency: str
    recommendation_confidence: float
    feedback_action: str  # ACCEPTED / REJECTED / PARTIAL / PENDING
    executed_action: str = ""
    executed_pct: float = 0.0
    feedback_note: str = ""
    actual_outcome: str = ""
    actual_pnl_change: float = 0.0
    timestamp: str = ""


def _get_feedback_file(evaluation_id: str) -> Path:
    """获取反馈文件路径"""
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    return FEEDBACK_DIR / f"feedback_{evaluation_id}.json"


def record_feedback(
    evaluation_id: str,
    system_name: str,
    symbol: str,
    position_direction: str,
    recommended_action: str,
    recommendation_urgency: str,
    recommendation_confidence: float,
    feedback_action: str,
    executed_action: str = "",
    executed_pct: float = 0.0,
    note: str = "",
) -> Dict[str, Any]:
    """
    记录建议反馈

    Args:
        evaluation_id: 评估 ID
        system_name: 系统名称
        symbol: 币种
        position_direction: 持仓方向
        recommended_action: 建议动作
        recommendation_urgency: 建议紧急度
        recommendation_confidence: 建议置信度
        feedback_action: 反馈动作 ACCEPTED/REJECTED/PARTIAL/PENDING
        executed_action: 实际执行动作
        executed_pct: 执行比例（0-1）
        note: 备注

    Returns:
        反馈记录
    """
    record = FeedbackRecord(
        evaluation_id=evaluation_id,
        system_name=system_name,
        symbol=symbol,
        position_direction=position_direction,
        recommended_action=recommended_action,
        recommendation_urgency=recommendation_urgency,
        recommendation_confidence=recommendation_confidence,
        feedback_action=feedback_action,
        executed_action=executed_action,
        executed_pct=executed_pct,
        feedback_note=note,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    feedback_file = _get_feedback_file(evaluation_id)
    feedback_data = {"evaluation_id": evaluation_id, "records": []}

    if feedback_file.exists():
        try:
            with open(feedback_file, "r", encoding="utf-8") as f:
                feedback_data = json.load(f)
                if "records" not in feedback_data:
                    feedback_data["records"] = []
        except (json.JSONDecodeError, IOError):
            pass

    record_dict = {
        "system_name": record.system_name,
        "symbol": record.symbol,
        "position_direction": record.position_direction,
        "recommended_action": record.recommended_action,
        "recommendation_urgency": record.recommendation_urgency,
        "recommendation_confidence": record.recommendation_confidence,
        "feedback_action": record.feedback_action,
        "executed_action": record.executed_action,
        "executed_pct": record.executed_pct,
        "feedback_note": record.feedback_note,
        "actual_outcome": record.actual_outcome,
        "actual_pnl_change": record.actual_pnl_change,
        "timestamp": record.timestamp,
    }

    found = False
    for i, r in enumerate(feedback_data["records"]):
        if r.get("system_name") == system_name and r.get("symbol") == symbol:
            feedback_data["records"][i] = record_dict
            found = True
            break
    if not found:
        feedback_data["records"].append(record_dict)

    feedback_data["last_updated"] = datetime.now(timezone.utc).isoformat()
    feedback_data["total_records"] = len(feedback_data["records"])

    with open(feedback_file, "w", encoding="utf-8") as f:
        json.dump(feedback_data, f, ensure_ascii=False, indent=2)

    return record_dict


def get_feedback_stats(max_evaluations: int = 20) -> Dict[str, Any]:
    """
    获取反馈统计数据

    Args:
        max_evaluations: 最多统计多少次评估

    Returns:
        统计数据
    """
    if not FEEDBACK_DIR.exists():
        return {"total_evaluations": 0, "total_records": 0}

    feedback_files = sorted(
        FEEDBACK_DIR.glob("feedback_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:max_evaluations]

    all_records = []
    for fp in feedback_files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
                for r in data.get("records", []):
                    r["_source_file"] = fp.name
                    all_records.append(r)
        except (json.JSONDecodeError, IOError):
            pass

    if not all_records:
        return {"total_evaluations": len(feedback_files), "total_records": 0}

    accepted = sum(1 for r in all_records if r.get("feedback_action") == "ACCEPTED")
    rejected = sum(1 for r in all_records if r.get("feedback_action") == "REJECTED")
    partial = sum(1 for r in all_records if r.get("feedback_action") == "PARTIAL")
    pending = sum(1 for r in all_records if r.get("feedback_action") == "PENDING")

    by_system = {}
    for r in all_records:
        sys = r.get("system_name", "unknown")
        if sys not in by_system:
            by_system[sys] = {"total": 0, "accepted": 0, "rejected": 0, "partial": 0}
        by_system[sys]["total"] += 1
        fb = r.get("feedback_action", "")
        if fb == "ACCEPTED":
            by_system[sys]["accepted"] += 1
        elif fb == "REJECTED":
            by_system[sys]["rejected"] += 1
        elif fb == "PARTIAL":
            by_system[sys]["partial"] += 1

    return {
        "total_evaluations": len(feedback_files),
        "total_records": len(all_records),
        "accepted_count": accepted,
        "rejected_count": rejected,
        "partial_count": partial,
        "pending_count": pending,
        "acceptance_rate": round(accepted / len(all_records), 2) if all_records else 0,
        "by_system": by_system,
    }


def set_system_permission(system_name: str, permission_level: str,
                          auto_execute_urgency: str = "CRITICAL",
                          max_auto_reduce_pct: float = 0.3,
                          notes: str = "") -> Dict[str, Any]:
    """
    设置系统权限等级

    Args:
        system_name: 系统名称
        permission_level: 权限等级
        auto_execute_urgency: 自动执行的紧急度阈值
        max_auto_reduce_pct: 最大自动减仓比例
        notes: 备注

    Returns:
        更新后的权限配置
    """
    if permission_level not in PERMISSION_RANK:
        raise ValueError(f"无效的权限等级: {permission_level}")

    config = load_permission_config()
    if "systems" not in config:
        config["systems"] = {}

    config["systems"][system_name] = {
        "permission_level": permission_level,
        "auto_execute_urgency": auto_execute_urgency,
        "max_auto_reduce_pct": max_auto_reduce_pct,
        "notes": notes,
    }
    config["last_updated"] = datetime.now(timezone.utc).isoformat()

    save_permission_config(config)
    return config["systems"][system_name]


if __name__ == "__main__":
    print("=== 权限配置 ===")
    config = load_permission_config()
    for sys_name, perm in config.get("systems", {}).items():
        print(f"  {sys_name}: {perm['permission_level']} (auto >= {perm['auto_execute_urgency']})")

    print("\n=== 自动执行测试 ===")
    test_cases = [
        ("agent_a", "CLOSE", "CRITICAL"),
        ("agent_a", "REDUCE", "HIGH"),
        ("agent_a", "CLOSE", "MEDIUM"),
        ("v15_martin", "CLOSE", "CRITICAL"),
    ]
    for sys_name, action, urgency in test_cases:
        result = can_auto_execute(sys_name, action, urgency)
        print(f"  {sys_name} {action} ({urgency}): "
              f"{'✓ 可执行' if result['can_execute'] else '✗ 不可执行'} - {result['reason']}")

    print("\n=== 反馈统计 ===")
    stats = get_feedback_stats()
    print(f"  总评估数: {stats['total_evaluations']}")
    print(f"  总记录数: {stats['total_records']}")
    if stats['total_records'] > 0:
        print(f"  采纳率: {stats['acceptance_rate']:.0%}")
        print(f"  采纳: {stats['accepted_count']}, 拒绝: {stats['rejected_count']}, 部分: {stats['partial_count']}")
