"""Skill Circulation Stats — SKILL 调用统计，驱动生命周期决策。

借鉴图书馆学流通统计：高频高成功率→采选激活，长期零借阅→剔旧归档。
FAIL-OPEN：文件不可写时不崩溃，返回默认值。

工程约束：HC-1a（独立模块）/ FAIL-OPEN / 零回归
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATS_PATH = Path(__file__).parent / "skill_circulation.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(stats_path: Path) -> dict[str, Any]:
    if not stats_path.exists():
        return {}
    try:
        return json.loads(stats_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(stats: dict[str, Any], stats_path: Path) -> bool:
    try:
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def record_invocation(
    skill_name: str,
    success: bool,
    stats_path: Path | None = None,
) -> dict[str, Any]:
    """记录一次 SKILL 调用。"""
    path = stats_path or DEFAULT_STATS_PATH
    stats = _load(path)
    entry = stats.get(skill_name, {
        "invocation_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "last_invoked_at": None,
    })
    entry["invocation_count"] += 1
    if success:
        entry["success_count"] += 1
    else:
        entry["failure_count"] += 1
    entry["last_invoked_at"] = _now_iso()
    stats[skill_name] = entry
    _save(stats, path)
    return entry


def get_stats(skill_name: str, stats_path: Path | None = None) -> dict[str, Any]:
    """获取单个 SKILL 统计，含 success_rate 计算。"""
    path = stats_path or DEFAULT_STATS_PATH
    stats = _load(path)
    entry = stats.get(skill_name)
    if not entry:
        return {
            "invocation_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "success_rate": 0.0,
            "last_invoked_at": None,
        }
    total = entry["invocation_count"]
    rate = entry["success_count"] / total if total > 0 else 0.0
    return {**entry, "success_rate": rate}


def get_all_stats(stats_path: Path | None = None) -> dict[str, Any]:
    path = stats_path or DEFAULT_STATS_PATH
    return _load(path)


def should_activate(
    skill_name: str,
    stats_path: Path | None = None,
    min_invocations: int = 3,
    min_success_rate: float = 0.6,
) -> bool:
    """invocation≥min_invocations 且 success_rate≥min_success_rate → True。"""
    s = get_stats(skill_name, stats_path)
    return s["invocation_count"] >= min_invocations and s["success_rate"] >= min_success_rate


def should_deprecate(
    skill_name: str,
    stats_path: Path | None = None,
    days: int = 90,
) -> bool:
    """超过 days 天未调用 → True（从未调用也返回 True）。"""
    s = get_stats(skill_name, stats_path)
    if s["last_invoked_at"] is None:
        return True
    try:
        last = datetime.fromisoformat(s["last_invoked_at"])
        return datetime.now(timezone.utc) - last > timedelta(days=days)
    except Exception:
        return False
