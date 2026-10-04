#!/usr/bin/env python3
"""记忆数据保障管理器 — TTL 淘汰 + RAG 日志过期 + 标签归并 + 定期审计。

集成 dreaming_engine 和 memory_health_audit，提供一站式记忆维护入口。

功能模块：
    P0: run_maintenance_cycle()  — 定期运行 dreaming + audit，输出报告
    P1: expire_stale_c_memories() — C 级记忆 TTL 淘汰（30天未引用→D级→7天后归档）
    P1: expire_rag_bridge_logs()  — RAG-bridge 检索日志 7 天过期清理
    P2: merge_similar_tags()     — 单次标签同义归并

设计原则：
    - FAIL-OPEN：所有操作异常不中断主流程
    - 安全第一：修改前自动备份，原子写入
    - 软删除：D 级记忆移到归档文件，不直接删除
    - 审计日志：所有变更记录到 JSONL

使用方式：
    # 完整维护周期（cron 每日运行）
    python memory_ttl_manager.py --cycle

    # 仅干运行（不修改数据）
    python memory_ttl_manager.py --dry-run

    # 仅运行 P0 审计
    python memory_ttl_manager.py --audit-only

    # 仅运行 P1 清理
    python memory_ttl_manager.py --cleanup
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 路径常量
_MEMORY_DIR = Path(__file__).resolve().parent.parent
_BAYESIAN_FILE = _MEMORY_DIR / "2-交易记忆单元" / "bayesian_memories.json"
_ARCHIVE_DIR = _MEMORY_DIR / "data" / "archive"
_AUDIT_LOG = _MEMORY_DIR / "9-工具与接口" / "data" / "ttl_audit_log.jsonl"

# TTL 配置
C_MEMORY_TTL_DAYS = 30       # C 级记忆 30 天未引用 → 降级 D
D_MEMORY_ARCHIVE_DAYS = 7    # D 级记忆 7 天后 → 归档
RAG_BRIDGE_TTL_DAYS = 7      # RAG-bridge 日志 7 天过期
TAG_MIN_FREQUENCY = 2        # 出现 <2 次的标签视为低频


@dataclass
class TTLReport:
    """TTL 管理报告。"""
    run_at: str
    dry_run: bool
    c_degraded: int = 0       # C→D 降级数
    d_archived: int = 0       # D→归档数
    rag_expired: int = 0      # RAG 日志清理数
    tags_merged: int = 0      # 标签归并数
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_at": self.run_at,
            "dry_run": self.dry_run,
            "c_degraded": self.c_degraded,
            "d_archived": self.d_archived,
            "rag_expired": self.rag_expired,
            "tags_merged": self.tags_merged,
            "errors": self.errors,
        }


def _load_memories() -> tuple[list[dict], dict[str, Any]]:
    """加载 bayesian_memories.json。FAIL-OPEN。"""
    try:
        with open(_BAYESIAN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("memories", []), data
    except Exception as e:
        print(f"[ERROR] 加载记忆库失败: {e}", file=sys.stderr)
        return [], {}


def _backup_memories() -> Path | None:
    """备份当前记忆库。"""
    try:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = _BAYESIAN_FILE.parent / f"bayesian_memories_backup_{ts}.json"
        shutil.copy2(_BAYESIAN_FILE, backup)
        # 保留最近 5 个备份
        backups = sorted(_BAYESIAN_FILE.parent.glob("bayesian_memories_backup_*.json"))
        for old in backups[:-5]:
            old.unlink(missing_ok=True)
        return backup
    except Exception as e:
        print(f"[WARN] 备份失败: {e}", file=sys.stderr)
        return None


def _save_memories(memories: list[dict], schema: dict[str, Any]) -> bool:
    """原子写入记忆库。"""
    try:
        schema["memories"] = memories
        schema["last_updated"] = datetime.now(timezone.utc).isoformat()
        tmp = _BAYESIAN_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        tmp.replace(_BAYESIAN_FILE)
        return True
    except Exception as e:
        print(f"[ERROR] 保存记忆库失败: {e}", file=sys.stderr)
        return False


def _log_audit(action: str, details: dict[str, Any]) -> None:
    """记录审计日志到 JSONL。FAIL-OPEN。"""
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            **details,
        }
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _parse_age(created_at: str) -> int:
    """解析记忆年龄（天数）。失败返回 0。"""
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 0


# ── P1: C 级记忆 TTL 淘汰 ──────────────────────────────────────

def expire_stale_c_memories(memories: list[dict], dry_run: bool = False) -> tuple[list[dict], int, int]:
    """C 级记忆 TTL 淘汰：30 天未引用 → D 级，D 级 7 天后 → 归档。

    Args:
        memories: 记忆列表（会被修改）
        dry_run: 仅模拟不修改

    Returns:
        (更新后的记忆列表, C→D 降级数, D→归档数)
    """
    c_degraded = 0
    d_archived = 0
    archived_ids: list[str] = []

    for m in memories:
        quality = m.get("quality_level", "")
        age = _parse_age(m.get("created_at", ""))

        # C 级 + 超过 TTL + 从未验证 → 降级 D
        if quality == "C" and age >= C_MEMORY_TTL_DAYS and m.get("verify_count", 0) == 0:
            if not dry_run:
                m["quality_level"] = "D"
                m["last_updated"] = datetime.now(timezone.utc).isoformat()
                _log_audit("c_to_d_degrade", {
                    "memory_id": m.get("memory_id"),
                    "age_days": age,
                    "reason": f"C级{age}天未验证，降级D",
                })
            c_degraded += 1

        # D 级 + 超过归档 TTL → 归档（从列表移除）
        elif quality == "D" and age >= D_MEMORY_ARCHIVE_DAYS:
            archived_ids.append(m.get("memory_id", ""))
            if not dry_run:
                _archive_memory(m)
            d_archived += 1

    # 从列表中移除已归档的记忆
    if archived_ids and not dry_run:
        memories = [m for m in memories if m.get("memory_id") not in set(archived_ids)]

    return memories, c_degraded, d_archived


def _archive_memory(memory: dict) -> None:
    """将记忆移到归档文件。FAIL-OPEN。"""
    try:
        _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_file = _ARCHIVE_DIR / "archived_memories.jsonl"
        with open(archive_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(memory, ensure_ascii=False) + "\n")
        _log_audit("d_to_archive", {
            "memory_id": memory.get("memory_id"),
            "content_preview": memory.get("content", "")[:100],
        })
    except Exception as e:
        _log_audit("archive_error", {"memory_id": memory.get("memory_id"), "error": str(e)})


# ── P1: RAG-bridge 日志过期 ─────────────────────────────────────

def expire_rag_bridge_logs(memories: list[dict], dry_run: bool = False) -> tuple[list[dict], int]:
    """RAG-bridge 检索日志 7 天过期清理。

    筛选条件：source 包含 'rag-bridge' 且创建时间 > 7 天。

    Args:
        memories: 记忆列表
        dry_run: 仅模拟

    Returns:
        (更新后的记忆列表, 清理数)
    """
    expired = 0
    to_remove: set[str] = set()

    for m in memories:
        source = m.get("source", "")
        if "rag-bridge" in source:
            age = _parse_age(m.get("created_at", ""))
            if age >= RAG_BRIDGE_TTL_DAYS:
                to_remove.add(m.get("memory_id", ""))
                expired += 1
                if not dry_run:
                    _archive_memory(m)
                    _log_audit("rag_bridge_expire", {
                        "memory_id": m.get("memory_id"),
                        "age_days": age,
                        "content_preview": m.get("content", "")[:100],
                    })

    if to_remove and not dry_run:
        memories = [m for m in memories if m.get("memory_id") not in to_remove]

    return memories, expired


# ── P2: 标签归并 ───────────────────────────────────────────────

def merge_similar_tags(memories: list[dict], dry_run: bool = False) -> tuple[list[dict], int]:
    """低频标签同义归并。

    策略：
    1. 统计所有标签频率
    2. 出现 <2 次的标签，用编辑距离找最近的高频标签（距离 <=2）归并
    3. 只做简单字符串近似，不做语义分析

    Args:
        memories: 记忆列表
        dry_run: 仅模拟

    Returns:
        (更新后的记忆列表, 归并数)
    """
    # 统计标签频率
    tag_freq: Counter = Counter()
    for m in memories:
        tags = m.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        tag_freq.update(tags)

    # 找低频标签
    low_freq = {t for t, c in tag_freq.items() if c < TAG_MIN_FREQUENCY and len(t) > 1}
    if not low_freq:
        return memories, 0

    # 为每个低频标签找最近的高频标签
    high_freq = {t: c for t, c in tag_freq.items() if c >= TAG_MIN_FREQUENCY}
    merge_map: dict[str, str] = {}
    for low_tag in low_freq:
        best_match = None
        best_dist = 3  # 最大编辑距离
        for high_tag in high_freq:
            if abs(len(low_tag) - len(high_tag)) > 3:
                continue
            dist = _levenshtein(low_tag, high_tag)
            if dist < best_dist:
                best_dist = dist
                best_match = high_tag
        if best_match:
            merge_map[low_tag] = best_match

    if not merge_map:
        return memories, 0

    # 应用归并
    merged_count = 0
    for m in memories:
        tags = m.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        new_tags = []
        changed = False
        for t in tags:
            if t in merge_map:
                new_tags.append(merge_map[t])
                changed = True
            else:
                new_tags.append(t)
        if changed:
            # 去重保序
            new_tags = list(dict.fromkeys(new_tags))
            if not dry_run:
                m["tags"] = new_tags
            merged_count += 1

    if merge_map and not dry_run:
        _log_audit("tag_merge", {
            "merged_count": merged_count,
            "merge_map_size": len(merge_map),
            "samples": dict(list(merge_map.items())[:10]),
        })

    return memories, merged_count


def _levenshtein(a: str, b: str) -> int:
    """计算两个字符串的编辑距离。"""
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


# ── P0: 定期维护周期 ───────────────────────────────────────────

def run_maintenance_cycle(dry_run: bool = False, audit_only: bool = False) -> dict[str, Any]:
    """一站式记忆维护周期。

    流程：
    1. 备份记忆库
    2. 运行 dreaming_engine 检测模式
    3. 运行 memory_health_audit 审计
    4. P1: C 级记忆 TTL 淘汰
    5. P1: RAG-bridge 日志过期
    6. P2: 标签归并
    7. 保存并记录审计日志

    Args:
        dry_run: 仅模拟，不修改数据
        audit_only: 仅运行审计（P0），不执行清理（P1/P2）

    Returns:
        完整维护报告
    """
    report: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "audit_only": audit_only,
        "steps": [],
    }

    # Step 1: 加载
    memories, schema = _load_memories()
    if not memories:
        report["error"] = "加载记忆库失败"
        return report
    report["total_memories"] = len(memories)

    # Step 2: 备份
    if not dry_run and not audit_only:
        backup = _backup_memories()
        report["backup"] = str(backup) if backup else "failed"

    # Step 3: P0 — Dreaming Engine 模式检测
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from dreaming_engine import run_dreaming_cycle
        dream_result = run_dreaming_cycle()
        candidates = dream_result.get("candidates") or dream_result.get("summary", {}).get("candidates", [])
        dup_count = sum(1 for c in candidates if c.get("pattern_type") == "duplicate_error")
        conv_count = sum(1 for c in candidates if c.get("pattern_type") in ("convergent_workflow", "converging_workflow"))
        conflict_count = sum(1 for c in candidates if c.get("pattern_type") in ("contradiction", "conflict"))
        report["steps"].append({
            "step": "dreaming_engine",
            "status": "ok",
            "total_scanned": dream_result.get("total_memories_scanned", 0),
            "candidates": len(candidates),
            "duplicates": dup_count,
            "convergent": conv_count,
            "conflicts": conflict_count,
        })
    except Exception as e:
        report["steps"].append({"step": "dreaming_engine", "status": "error", "error": str(e)})

    # Step 3.5: 规则化自动合并（dreaming 检测后执行）
    try:
        from dreaming_engine import auto_merge_duplicates
        merge_result = auto_merge_duplicates(dry_run=dry_run)
        report["steps"].append({
            "step": "auto_merge",
            "status": merge_result.get("status", "error"),
            "merged": merge_result.get("merged", 0),
            "downgraded": merge_result.get("downgraded", 0),
            "created": merge_result.get("created", 0),
            "final_memories": merge_result.get("final_memories", 0),
        })
        # 自动合并后重新加载记忆列表（因为记忆库已变更）
        if not dry_run and merge_result.get("merged", 0) > 0:
            memories, schema = _load_memories()
    except Exception as e:
        report["steps"].append({"step": "auto_merge", "status": "error", "error": str(e)})

    # Step 4: P0 — Memory Health Audit
    try:
        from memory_health_audit import run_health_audit
        audit_result = run_health_audit()
        summary = audit_result.get("summary", {})
        report["steps"].append({
            "step": "health_audit",
            "status": "ok",
            "health_score": audit_result.get("health_score", 0),
            "duplicates": summary.get("duplicate_groups", 0),
            "stale": summary.get("stale_memories", 0),
            "contradictions": summary.get("contradiction_groups", 0),
            "improvements": summary.get("improvement_opportunities", 0),
        })
    except Exception as e:
        report["steps"].append({"step": "health_audit", "status": "error", "error": str(e)})

    if audit_only:
        report["skipped"] = "P1/P2 清理（audit_only 模式）"
        return report

    # Step 5: P1 — C 级记忆 TTL 淘汰
    try:
        memories, c_deg, d_arch = expire_stale_c_memories(memories, dry_run=dry_run)
        report["steps"].append({
            "step": "c_memory_ttl",
            "status": "ok",
            "c_degraded": c_deg,
            "d_archived": d_arch,
        })
    except Exception as e:
        report["steps"].append({"step": "c_memory_ttl", "status": "error", "error": str(e)})

    # Step 6: P1 — RAG-bridge 日志过期
    try:
        memories, rag_exp = expire_rag_bridge_logs(memories, dry_run=dry_run)
        report["steps"].append({
            "step": "rag_bridge_expire",
            "status": "ok",
            "expired": rag_exp,
        })
    except Exception as e:
        report["steps"].append({"step": "rag_bridge_expire", "status": "error", "error": str(e)})

    # Step 7: P2 — 标签归并
    try:
        memories, tags_merged = merge_similar_tags(memories, dry_run=dry_run)
        report["steps"].append({
            "step": "tag_merge",
            "status": "ok",
            "tags_merged": tags_merged,
        })
    except Exception as e:
        report["steps"].append({"step": "tag_merge", "status": "error", "error": str(e)})

    # Step 8: 保存
    if not dry_run:
        saved = _save_memories(memories, schema)
        report["saved"] = saved
        report["final_memories"] = len(memories)
    else:
        report["final_memories"] = len(memories)

    # 审计日志
    _log_audit("maintenance_cycle", report)

    return report


# ── CLI 入口 ───────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="记忆数据保障管理器")
    parser.add_argument("--cycle", action="store_true", help="运行完整维护周期")
    parser.add_argument("--dry-run", action="store_true", help="仅模拟，不修改数据")
    parser.add_argument("--audit-only", action="store_true", help="仅运行审计")
    parser.add_argument("--cleanup", action="store_true", help="仅运行 P1+P2 清理")
    args = parser.parse_args(argv)

    if not any([args.cycle, args.dry_run, args.audit_only, args.cleanup]):
        parser.print_help()
        return 1

    if args.dry_run or args.audit_only:
        report = run_maintenance_cycle(dry_run=args.dry_run, audit_only=args.audit_only)
    elif args.cleanup:
        # 仅运行清理部分
        memories, schema = _load_memories()
        if not memories:
            print("加载记忆库失败")
            return 1
        _backup_memories()
        memories, c_deg, d_arch = expire_stale_c_memories(memories)
        memories, rag_exp = expire_rag_bridge_logs(memories)
        memories, tags_merged = merge_similar_tags(memories)
        _save_memories(memories, schema)
        report = {
            "c_degraded": c_deg, "d_archived": d_arch,
            "rag_expired": rag_exp, "tags_merged": tags_merged,
            "final_memories": len(memories),
        }
    else:
        report = run_maintenance_cycle()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
