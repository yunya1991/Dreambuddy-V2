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

import hashlib
import json
import shutil
import sqlite3
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
C_MEMORY_TTL_DAYS = 30  # C 级记忆 30 天未引用 → 降级 D
D_MEMORY_ARCHIVE_DAYS = 7  # D 级记忆 7 天后 → 归档
RAG_BRIDGE_TTL_DAYS = 7  # RAG-bridge 日志 7 天过期
TAG_MIN_FREQUENCY = 2  # 出现 <2 次的标签视为低频


@dataclass
class TTLReport:
    """TTL 管理报告。"""

    run_at: str
    dry_run: bool
    c_degraded: int = 0  # C→D 降级数
    d_archived: int = 0  # D→归档数
    rag_expired: int = 0  # RAG 日志清理数
    tags_merged: int = 0  # 标签归并数
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


def expire_stale_c_memories(
    memories: list[dict], dry_run: bool = False
) -> tuple[list[dict], int, int]:
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
                _log_audit(
                    "c_to_d_degrade",
                    {
                        "memory_id": m.get("memory_id"),
                        "age_days": age,
                        "reason": f"C级{age}天未验证，降级D",
                    },
                )
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
        _log_audit(
            "d_to_archive",
            {
                "memory_id": memory.get("memory_id"),
                "content_preview": memory.get("content", "")[:100],
            },
        )
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
                    _log_audit(
                        "rag_bridge_expire",
                        {
                            "memory_id": m.get("memory_id"),
                            "age_days": age,
                            "content_preview": m.get("content", "")[:100],
                        },
                    )

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
        _log_audit(
            "tag_merge",
            {
                "merged_count": merged_count,
                "merge_map_size": len(merge_map),
                "samples": dict(list(merge_map.items())[:10]),
            },
        )

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
        candidates = dream_result.get("candidates") or dream_result.get("summary", {}).get(
            "candidates", []
        )
        dup_count = sum(1 for c in candidates if c.get("pattern_type") == "duplicate_error")
        conv_count = sum(
            1
            for c in candidates
            if c.get("pattern_type") in ("convergent_workflow", "converging_workflow")
        )
        conflict_count = sum(
            1 for c in candidates if c.get("pattern_type") in ("contradiction", "conflict")
        )
        report["steps"].append(
            {
                "step": "dreaming_engine",
                "status": "ok",
                "total_scanned": dream_result.get("total_memories_scanned", 0),
                "candidates": len(candidates),
                "duplicates": dup_count,
                "convergent": conv_count,
                "conflicts": conflict_count,
            }
        )
    except Exception as e:
        report["steps"].append({"step": "dreaming_engine", "status": "error", "error": str(e)})

    # Step 3.5: 规则化自动合并（dreaming 检测后执行）
    try:
        from dreaming_engine import auto_merge_duplicates

        merge_result = auto_merge_duplicates(dry_run=dry_run)
        report["steps"].append(
            {
                "step": "auto_merge",
                "status": merge_result.get("status", "error"),
                "merged": merge_result.get("merged", 0),
                "downgraded": merge_result.get("downgraded", 0),
                "created": merge_result.get("created", 0),
                "final_memories": merge_result.get("final_memories", 0),
            }
        )
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
        report["steps"].append(
            {
                "step": "health_audit",
                "status": "ok",
                "health_score": audit_result.get("health_score", 0),
                "duplicates": summary.get("duplicate_groups", 0),
                "stale": summary.get("stale_memories", 0),
                "contradictions": summary.get("contradiction_groups", 0),
                "improvements": summary.get("improvement_opportunities", 0),
            }
        )
    except Exception as e:
        report["steps"].append({"step": "health_audit", "status": "error", "error": str(e)})

    if audit_only:
        report["skipped"] = "P1/P2 清理（audit_only 模式）"
        return report

    # Step 5: P1 — C 级记忆 TTL 淘汰
    try:
        memories, c_deg, d_arch = expire_stale_c_memories(memories, dry_run=dry_run)
        report["steps"].append(
            {
                "step": "c_memory_ttl",
                "status": "ok",
                "c_degraded": c_deg,
                "d_archived": d_arch,
            }
        )
    except Exception as e:
        report["steps"].append({"step": "c_memory_ttl", "status": "error", "error": str(e)})

    # Step 6: P1 — RAG-bridge 日志过期
    try:
        memories, rag_exp = expire_rag_bridge_logs(memories, dry_run=dry_run)
        report["steps"].append(
            {
                "step": "rag_bridge_expire",
                "status": "ok",
                "expired": rag_exp,
            }
        )
    except Exception as e:
        report["steps"].append({"step": "rag_bridge_expire", "status": "error", "error": str(e)})

    # Step 7: P2 — 标签归并
    try:
        memories, tags_merged = merge_similar_tags(memories, dry_run=dry_run)
        report["steps"].append(
            {
                "step": "tag_merge",
                "status": "ok",
                "tags_merged": tags_merged,
            }
        )
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


# ── DB 级分级 TTL（SPEC §3.7：C=7d / B=14d / A=存量上限 / S=不淘汰）──
#
# 与上面的 JSON 记忆库路径并存：上面治理 bayesian_memories.json（纵向经验的应用记忆），
# 这里治理 cognitive_memory.db 的 memories 表（315K 条、含 RAG 日志）。
#
# 两阶段淘汰（禁止单阶段删行）：
#   阶段一：memories 行保留，移出检索索引（删 vec 行）→ memory_ttl_pending
#   宽限 7 天
#   阶段二：降为记忆树叶节点痕迹（memory_traces）→ 物理删除 memories 行（经
#           VectorMemoryInterface.delete，保证 vec 表级联）
#
# 生效范围白名单：初始仅 {rag-bridge, l0.scheduler, l1_router}，其余记忆不动。

_DB_DEFAULT = _MEMORY_DIR / "data" / "cognitive_memory.db"
TTL_DAYS = {"C": 7, "B": 14}
A_CAP = 500  # A+S 存量上限（S 永不淘汰）
TTL_GRACE_DAYS = 7  # 阶段一 → 阶段二宽限期
TRACE_PER_LEAF = 20  # 每叶节点痕迹上限
TRACE_GLOBAL = 5000  # 全局痕迹上限
TTL_SCOPE_DEFAULT = ("rag-bridge", "l0.scheduler", "l1_router")
# 轨迹类来源不留痕（SPEC §3.7 第 6 条 / G11「rag-bridge 零痕迹」）：
# 它们本不该入库，删除属脏数据修复，不是「遗忘」。
NO_TRACE_SOURCES = frozenset(TTL_SCOPE_DEFAULT)
# SPEC §3.7′：这些子类只降级、永不自动删除（D-policy 连降级也不做）
PROTECTED_SUBCLASSES = frozenset({"code", "config", "D-tech", "D-policy"})
ORPHAN_NODE = "_orphan"  # 无法归属项目时的兜底树节点


def _open_db(db_path: str | Path = _DB_DEFAULT):
    """打开 DB 并尽力加载 sqlite-vec（加载失败不影响纯 SQL 逻辑）。"""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    try:
        import sqlite_vec

        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
    except Exception:  # noqa: BLE001 - 向量扩展缺失时降级为纯 SQL
        pass
    return con


def _has_table(con, name: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", [name]
        ).fetchone()
        is not None
    )


def ensure_ttl_tables(con) -> None:
    """幂等建表：待淘汰队列 + 树梢痕迹池。"""
    con.execute(
        "CREATE TABLE IF NOT EXISTS memory_ttl_pending("
        "id TEXT PRIMARY KEY, quality_level TEXT, source TEXT, created_at TEXT, "
        "stage1_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_ttl_pending_stage1 ON memory_ttl_pending(stage1_at)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS memory_traces("
        "id TEXT PRIMARY KEY, project TEXT NOT NULL, node_path TEXT NOT NULL, "
        "source TEXT, keywords TEXT, snippet_200 TEXT, expired_at INTEGER NOT NULL)"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_traces_node ON memory_traces(node_path)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_traces_expired ON memory_traces(expired_at)")
    con.commit()


def _cutoff(now: datetime, days: int) -> str:
    """与库内 created_at 同格式（UTC +00:00）的阈值，保证字符串比较有效。"""
    return (now - timedelta(days=days)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _pending_exclusion(con) -> str:
    """限批推进前提：已进入宽限队列的行不再重复选中（否则每天只处理同一批）。

    宽限期内主表行仍在，必须显式排除 pending，否则 `--limit` 永远停在最旧 N 条。
    """
    if not _has_table(con, "memory_ttl_pending"):
        return ""
    return " AND id NOT IN (SELECT id FROM memory_ttl_pending)"


def _has_column(con, table: str, column: str) -> bool:
    """列存在性检查：旧库尚未迁移残差字段时，治理按最保守口径处理。"""
    try:
        return any(
            str(row[1]) == column for row in con.execute(f"PRAGMA table_info({table})").fetchall()
        )
    except sqlite3.Error:
        return False


def _iter_expired(con, scope: tuple[str, ...], now: datetime) -> list[dict[str, Any]]:
    """按 quality_level 分级取候选：C=7 天、B=14 天，且从未被使用过。

    SPEC §3.7′：只有 `runtime`（或未分型的轨迹存量）受时效约束；
    code / config / D-tech / D-policy 及未分型非轨迹存量一律不进入候选。
    """
    marks = ",".join("?" * len(scope))
    exclude = _pending_exclusion(con)
    traj = tuple(TTL_SCOPE_DEFAULT)
    traj_marks = ",".join("?" * len(traj))
    # 未分型（NULL）仅允许轨迹来源按脏数据清退，其余按 D-policy 冻结；
    # 注意：这里的来源必须是轨迹常量，不能用调用方 scope（scope 可包含非轨迹来源）。
    residual_sql = (
        " AND (subclass='runtime' OR (subclass IS NULL AND source IN (" + traj_marks + ")))"
        " AND COALESCE(verify_state,'fresh') <> 'degraded'"
    )
    out: list[dict[str, Any]] = []
    for level, days in TTL_DAYS.items():
        base_sql = (
            "SELECT id, quality_level, source, created_at, substr(content,1,400) AS snippet, tags "
            "FROM memories WHERE quality_level=? AND source IN (" + marks + ") "
            "AND COALESCE(access_count,0)=0 AND last_used_at IS NULL AND created_at < ?"
        )
        base_params = [level, *scope, _cutoff(now, days)]
        try:
            rows = con.execute(
                base_sql + residual_sql + exclude + " ORDER BY created_at ASC",
                [*base_params, *traj],
            ).fetchall()
        except sqlite3.OperationalError:
            # 旧库尚无 subclass / verify_state 列：回退到 scope 口径（默认仅轨迹来源）
            rows = con.execute(
                base_sql + exclude + " ORDER BY created_at ASC", base_params
            ).fetchall()
        out.extend(dict(r) for r in rows)
    return out


def _iter_a_overflow(con, scope: tuple[str, ...], now: datetime) -> list[dict[str, Any]]:
    """A 级按存量上限控制：量满删最旧 / 最低频（S 永不淘汰）。

    生效范围同样受白名单约束，避免 TTL 未验证前误删真实教训。
    SPEC §3.7′：仅 `runtime` 参与存量上限；未分型/其余子类一律冻结。
    旧库无 subclass 列时保持原有 scope 口径（默认 scope 仅轨迹来源）。
    """
    marks = ",".join("?" * len(scope))
    residual = " AND subclass='runtime'"
    exclude = _pending_exclusion(con)
    count_sql = (
        "SELECT count(*) FROM memories WHERE quality_level IN ('A','S') AND source IN ("
        + marks
        + ")"
    )
    try:
        total = con.execute(count_sql + residual, list(scope)).fetchone()[0]
    except sqlite3.OperationalError:
        total = con.execute(count_sql, list(scope)).fetchone()[0]
    excess = int(total) - A_CAP
    if excess <= 0:
        return []
    base_sql = (
        "SELECT id, quality_level, source, created_at, substr(content,1,400) AS snippet, tags "
        "FROM memories WHERE quality_level='A' AND source IN (" + marks + ")"
    )
    try:
        rows = con.execute(
            base_sql + residual + exclude + " "
            "ORDER BY COALESCE(last_used_at,0) ASC, created_at ASC LIMIT ?",
            [*scope, excess],
        ).fetchall()
    except sqlite3.OperationalError:
        rows = con.execute(
            base_sql + exclude + " "
            "ORDER BY COALESCE(last_used_at,0) ASC, created_at ASC LIMIT ?",
            [*scope, excess],
        ).fetchall()
    return [dict(r) for r in rows]


def inspect_index(con) -> dict[str, Any]:
    """向量索引一致性巡检（SPEC G0 / P0）。

    检查三件事：meta.embed_dim 与 vector 长度直方图是否一致、混维条数、
    memories 与 vec_memories 的条数差。任一异常都必须显式暴露（degraded）。
    """
    report: dict[str, Any] = {"degraded": False, "reasons": []}
    expected_dim = None
    if _has_table(con, "meta"):
        row = con.execute("SELECT value FROM meta WHERE key='embed_dim'").fetchone()
        if row and str(row[0]).isdigit():
            expected_dim = int(row[0])
    report["expected_dim"] = expected_dim

    hist: dict[str, int] = {}
    for row in con.execute(
        "SELECT length(vector)/4 AS dim, count(*) AS c FROM memories "
        "WHERE vector IS NOT NULL GROUP BY dim ORDER BY c DESC"
    ).fetchall():
        hist[str(row[0])] = int(row[1])
    report["vector_dim_histogram"] = hist

    total = con.execute("SELECT count(*) FROM memories").fetchone()[0]
    report["memories_total"] = int(total)
    vec_total = (
        con.execute("SELECT count(*) FROM vec_memories").fetchone()[0]
        if _has_table(con, "vec_memories")
        else 0
    )
    report["vec_total"] = int(vec_total)
    report["count_gap_raw"] = int(total) - int(vec_total)
    # TTL 阶段一合法地移出索引（行保留在 pending 宽限期），不计入异常缺口
    pending = 0
    if _has_table(con, "memory_ttl_pending"):
        pending = con.execute(
            "SELECT count(*) FROM memory_ttl_pending p JOIN memories m ON m.id=p.id"
        ).fetchone()[0]
    report["pending_in_memories"] = int(pending)
    report["count_gap"] = int(report["count_gap_raw"]) - int(pending)

    mixed = 0
    if expected_dim is not None:
        mixed = sum(c for dim, c in hist.items() if dim.isdigit() and int(dim) != expected_dim)
        if mixed and _has_column(con, "memories", "source"):
            report["mixed_by_source"] = {
                str(r[0] or ""): int(r[1])
                for r in con.execute(
                    "SELECT source, count(*) AS c FROM memories "
                    "WHERE vector IS NOT NULL AND length(vector)/4 != ? GROUP BY source",
                    [expected_dim],
                ).fetchall()
            }
    report["mixed_dim"] = int(mixed)
    if expected_dim is not None and mixed == 0 and report["count_gap"] == 0:
        report["note"] = "维度与条数均一致"
    if expected_dim is None:
        report["degraded"] = True
        report["reasons"].append("meta_embed_dim_missing")
    if mixed > 0:
        report["degraded"] = True
        report["reasons"].append("mixed_dim")
    if report["count_gap"] != 0:
        report["degraded"] = True
        report["reasons"].append("count_gap")
    return report


def review_verify_states(
    con,
    *,
    dry_run: bool = True,
    limit: int = 0,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """事实源复核 → 更新 verify_state（SPEC §3.7′ C 接入点）。

    只复核带锚点的 code / config；D-tech 由 supersedes 驱动，
    runtime 的时效由治理决策按 created_at 计算，D-policy 与未分型一律跳过。
    degraded 只移出向量索引，不物理删除。
    """
    stats: dict[str, Any] = {
        "dry_run": dry_run,
        "checked": 0,
        "changed": 0,
        "degraded": 0,
        "stale": 0,
        "fresh": 0,
        "index_removed": 0,
        "errors": 0,
    }
    if not _has_column(con, "memories", "subclass"):
        stats["degraded_reason"] = "subclass_column_missing"
        return stats

    sql = (
        "SELECT id, content, source, tags, created_at, subclass, source_anchor, "
        "verify_state, access_count, last_used_at FROM memories "
        "WHERE subclass IN ('code','config') AND source_anchor IS NOT NULL "
        "AND source_anchor <> ''"
    )
    params: list = []
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    rows = con.execute(sql, params).fetchall()

    from residual_memory import review as _review

    now_iso = datetime.now(timezone.utc).isoformat()
    has_vec = _has_table(con, "vec_memories")
    updates: list[tuple[str, str, str]] = []
    remove_index: list[str] = []
    for raw in rows:
        row = dict(raw)
        try:
            new_state = _review(row, repo_root=Path(repo_root) if repo_root else None)
        except Exception as exc:  # noqa: BLE001 - 单条复核失败不阻断整批
            stats["errors"] += 1
            stats["last_error"] = f"{row.get('id')}: {type(exc).__name__}: {exc}"
            continue
        stats["checked"] += 1
        old_state = row.get("verify_state") or "fresh"
        if new_state == old_state:
            continue
        stats["changed"] += 1
        stats[new_state] = stats.get(new_state, 0) + 1
        updates.append((new_state, now_iso, row["id"]))
        if new_state == "degraded":
            remove_index.append(row["id"])

    if dry_run or not updates:
        return stats

    con.executemany("UPDATE memories SET verify_state=?, updated_at=? WHERE id=?", updates)
    if has_vec:
        for mid in remove_index:
            rowid = int(hashlib.md5(mid.encode()).hexdigest()[:12], 16)
            for column, value in (("rowid", rowid), ("memory_id", mid)):
                try:
                    con.execute(f"DELETE FROM vec_memories WHERE {column}=?", [value])
                    stats["index_removed"] += 1
                except sqlite3.Error:
                    pass  # vec0 未加载时跳过：行仍在 memories
    con.commit()
    return stats


def _resolve_trace_node(tree, text: str) -> tuple[str, str]:
    """把记忆归位到树梢：命中 → 下钻到最深子节点；未命中 → 项目 `_orphan`。

    痕迹只挂已存在节点，禁止无归属堆放成全局大池（SPEC G11）。
    """
    if tree is None or not getattr(tree, "nodes", None):
        return ORPHAN_NODE, ORPHAN_NODE
    try:
        hits = tree.query(text, top_k=1, min_score=2.0)
    except Exception:  # noqa: BLE001 - 树不可用时降级为 orphan，不阻断淘汰
        hits = []
    if not hits:
        return ORPHAN_NODE, ORPHAN_NODE
    path = hits[0]["path"]
    leaf = path
    for _ in range(3):
        kids = tree.children(leaf)
        if not kids:
            break
        leaf = kids[0]
    return path.split("/")[0], leaf


def _trim_traces(con, node_path: str) -> None:
    """痕迹容量门：每叶 ≤20、全局 ≤5000，超出删最旧。"""
    leaf_count = con.execute(
        "SELECT count(*) FROM memory_traces WHERE node_path=?", [node_path]
    ).fetchone()[0]
    if leaf_count >= TRACE_PER_LEAF:
        con.execute(
            "DELETE FROM memory_traces WHERE id IN ("
            "SELECT id FROM memory_traces WHERE node_path=? ORDER BY expired_at ASC LIMIT ?)",
            [node_path, leaf_count - TRACE_PER_LEAF + 1],
        )
    total = con.execute("SELECT count(*) FROM memory_traces").fetchone()[0]
    if total >= TRACE_GLOBAL:
        con.execute(
            "DELETE FROM memory_traces WHERE id IN ("
            "SELECT id FROM memory_traces ORDER BY expired_at ASC LIMIT ?)",
            [total - TRACE_GLOBAL + 1],
        )


def _stage1(con, candidates: list[dict[str, Any]], now: datetime, dry_run: bool) -> dict[str, Any]:
    """阶段一：移出检索索引（保留 memories 行，可逆）。"""
    stats: dict[str, Any] = {"candidates": len(candidates), "promoted": 0, "vec_removed": 0}
    if not candidates:
        return stats
    if dry_run:
        return stats
    has_vec = _has_table(con, "vec_memories")
    ts = int(now.timestamp())
    expires = ts + TTL_GRACE_DAYS * 86400
    for mem in candidates:
        con.execute(
            "INSERT OR REPLACE INTO memory_ttl_pending"
            "(id, quality_level, source, created_at, stage1_at, expires_at) VALUES (?,?,?,?,?,?)",
            [mem["id"], mem["quality_level"], mem["source"], mem["created_at"], ts, expires],
        )
        stats["promoted"] += 1
        if has_vec:
            # 与 VectorMemoryInterface._get_rowid 保持一致
            rowid = int(hashlib.md5(mem["id"].encode()).hexdigest()[:12], 16)
            try:
                con.execute("DELETE FROM vec_memories WHERE rowid=?", [rowid])
                stats["vec_removed"] += 1
            except sqlite3.Error as exc:  # vec0 未加载时跳过，行仍在 memories
                stats.setdefault("vec_errors", 0)
                stats["vec_errors"] += 1
                stats["last_vec_error"] = str(exc)
    con.commit()
    return stats


def _stage2(
    con, tree, now: datetime, dry_run: bool, db_path: str | Path = _DB_DEFAULT
) -> dict[str, Any]:
    """阶段二：降为树梢痕迹 + 物理删除主表行（经 VectorMemoryInterface.delete）。"""
    stats: dict[str, Any] = {
        "eligible": 0,
        "traces": 0,
        "trace_skipped_trajectory": 0,
        "skipped_protected": 0,
        "purged": 0,
        "errors": 0,
    }
    if not _has_table(con, "memory_ttl_pending"):
        return stats
    select_base = "SELECT p.id, p.source, p.quality_level, m.content, m.tags, m.created_at"
    select_where = " FROM memory_ttl_pending p JOIN memories m ON m.id=p.id WHERE p.stage1_at <= ?"
    since = [int(now.timestamp()) - TTL_GRACE_DAYS * 86400]
    try:
        rows = con.execute(select_base + ", m.subclass" + select_where, since).fetchall()
        has_sub = True
    except sqlite3.OperationalError:
        rows = con.execute(select_base + ", NULL AS subclass" + select_where, since).fetchall()
        has_sub = False

    # SPEC §3.7′：code / config / D-tech / D-policy 永不自动删除（防御性兜底）
    if has_sub:
        protected = [r["id"] for r in rows if r["subclass"] in PROTECTED_SUBCLASSES]
        rows = [r for r in rows if r["subclass"] not in PROTECTED_SUBCLASSES]
        if protected and not dry_run:
            con.executemany("DELETE FROM memory_ttl_pending WHERE id=?", [(i,) for i in protected])
            con.commit()
        stats["skipped_protected"] = len(protected)

    stats["eligible"] = len(rows)
    if dry_run or not rows:
        return stats

    from memory_tree import tokenize  # 延迟导入：避免记忆树缺失时阻断 TTL

    ts = int(now.timestamp())
    # Phase A：先写痕迹并提交，释放写锁（否则 VectorMemoryInterface 的独立连接会被锁住）
    for row in rows:
        content = row["content"] or ""
        if row["source"] in NO_TRACE_SOURCES:
            stats["trace_skipped_trajectory"] += 1
            continue
        keywords = ",".join(tokenize(content[:200] + " " + (row["tags"] or ""))[:12])
        project, node_path = _resolve_trace_node(tree, content[:200] + " " + (row["tags"] or ""))
        try:
            _trim_traces(con, node_path)
            con.execute(
                "INSERT OR REPLACE INTO memory_traces"
                "(id, project, node_path, source, keywords, snippet_200, expired_at) "
                "VALUES (?,?,?,?,?,?,?)",
                [row["id"], project, node_path, row["source"], keywords, content[:200], ts],
            )
            stats["traces"] += 1
        except sqlite3.Error as exc:  # 痕迹失败也不能阻断淘汰
            stats["errors"] += 1
            stats["last_error"] = str(exc)
    con.commit()

    # Phase B：统一经 VectorMemoryInterface.delete 物理删除（含 vec 表级联）
    purged: list[str] = []
    vm = None
    try:
        from vector_memory_interface import VectorMemoryInterface

        vm = VectorMemoryInterface(storage_path=str(db_path), allow_degraded=True)
        for row in rows:
            try:
                vm.delete(row["id"])
                purged.append(row["id"])
                stats["purged"] += 1
            except Exception as exc:  # noqa: BLE001 - 单条失败保留 pending 供下轮重试
                stats["errors"] += 1
                stats["last_error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - 引擎不可用时整批保留 pending
        stats["errors"] += 1
        stats["last_error"] = f"vm_init: {exc}"
    finally:
        if vm is not None:
            vm.close()

    # Phase C：只清已成功删除的 pending，失败的留待下轮
    if purged:
        con.executemany("DELETE FROM memory_ttl_pending WHERE id=?", [(i,) for i in purged])
        con.commit()
    return stats


def run_db_ttl_cycle(
    db_path: str | Path = _DB_DEFAULT,
    dry_run: bool = True,
    scope: tuple[str, ...] | None = None,
    now: datetime | None = None,
    tree=None,
    stage: str = "both",
    limit: int = 0,
) -> dict[str, Any]:
    """DB 级分级 TTL 周期。默认 dry-run；写操作须显式 dry_run=False。

    stage: "1" 仅移出索引 / "2" 仅宽限期后清退 / "both" 两阶段顺序执行。
    limit: 单轮阶段一最多处理条数（0=不限）。云端定时任务建议限批，避免长时间持锁。
    """
    now = now or datetime.now(timezone.utc)
    scope = tuple(scope or TTL_SCOPE_DEFAULT)
    report: dict[str, Any] = {
        "run_at": now.isoformat(),
        "dry_run": dry_run,
        "scope": list(scope),
        "stage": stage,
        "ttl_days": dict(TTL_DAYS),
        "a_cap": A_CAP,
        "grace_days": TTL_GRACE_DAYS,
    }
    con = _open_db(db_path)
    try:
        if not dry_run:
            ensure_ttl_tables(con)
        candidates = _iter_expired(con, scope, now) + _iter_a_overflow(con, scope, now)
        report["candidates_total"] = len(candidates)
        if limit and limit > 0:
            candidates = candidates[:limit]
        report["candidates_batch"] = len(candidates)
        if stage in ("1", "both"):
            report["stage1"] = _stage1(con, candidates, now, dry_run)
        if stage in ("2", "both"):
            report["stage2"] = _stage2(con, tree, now, dry_run, db_path)
        report["trace_total"] = (
            con.execute("SELECT count(*) FROM memory_traces").fetchone()[0]
            if _has_table(con, "memory_traces")
            else 0
        )
        report["pending_total"] = (
            con.execute("SELECT count(*) FROM memory_ttl_pending").fetchone()[0]
            if _has_table(con, "memory_ttl_pending")
            else 0
        )
    finally:
        con.close()
    return report


# ── CLI 入口 ───────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="记忆数据保障管理器")
    parser.add_argument("--cycle", action="store_true", help="运行完整维护周期")
    parser.add_argument("--dry-run", action="store_true", help="仅模拟，不修改数据")
    parser.add_argument("--audit-only", action="store_true", help="仅运行审计")
    parser.add_argument("--cleanup", action="store_true", help="仅运行 P1+P2 清理")
    parser.add_argument("--db-cycle", action="store_true", help="DB 级分级 TTL（默认 dry-run）")
    parser.add_argument(
        "--inspect-index",
        action="store_true",
        help="向量索引一致性巡检（混维 / count 差，SPEC G0）",
    )
    parser.add_argument(
        "--review-residual",
        action="store_true",
        help="事实源复核 verify_state（SPEC §3.7′，默认 dry-run）",
    )
    parser.add_argument("--repo-root", default="", help="复核锚点的仓库根目录（默认自动推断）")
    parser.add_argument("--db", default=str(_DB_DEFAULT), help="cognitive_memory.db 路径")
    parser.add_argument("--scope", default="", help="source 白名单，逗号分隔")
    parser.add_argument("--stage", choices=["1", "2", "both"], default="both")
    parser.add_argument("--apply", action="store_true", help="实际执行（缺省仅 dry-run）")
    parser.add_argument("--with-tree", action="store_true", help="痕迹按记忆树归位到树梢")
    parser.add_argument("--limit", type=int, default=0, help="单轮阶段一最多处理条数（0=不限）")
    args = parser.parse_args(argv)

    if args.inspect_index:
        con = _open_db(args.db)
        try:
            report = inspect_index(con)
        finally:
            con.close()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.review_residual:
        con = _open_db(args.db)
        try:
            report = review_verify_states(
                con,
                dry_run=not args.apply,
                limit=args.limit,
                repo_root=args.repo_root or None,
            )
        finally:
            con.close()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.db_cycle:
        scope = tuple(s.strip() for s in args.scope.split(",") if s.strip()) or None
        tree = None
        if args.with_tree:
            from memory_tree import MemoryTree

            tree = MemoryTree.load()
        report = run_db_ttl_cycle(
            db_path=args.db,
            dry_run=not args.apply,
            scope=scope,
            tree=tree,
            stage=args.stage,
            limit=args.limit,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

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
            "c_degraded": c_deg,
            "d_archived": d_arch,
            "rag_expired": rag_exp,
            "tags_merged": tags_merged,
            "final_memories": len(memories),
        }
    else:
        report = run_maintenance_cycle()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
