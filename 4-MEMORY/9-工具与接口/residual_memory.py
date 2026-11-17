#!/usr/bin/env python3
"""残差记忆器 — SPEC §3.7′ / §4′ 的唯一实现入口。

四件事：
    classify()            子类分型（code/config/runtime/D-tech/D-policy），拿不准归 D-policy
    gate()                写入裁决 S0-S4（敏感 / 分型 / 轨迹 / 冗余 / 残差），verdict → M1/M2/M3
    decode()              M1 指针现场重建（按 source_anchor 定位文件与符号）
    review()              事实源复核 → verify_state(fresh/stale/degraded)
    governance_decision() 治理决策：只降级不删除，D-policy 永不自动处理

设计纪律（硬约束）：
    - D-policy 与未分型（subclass IS NULL）存量：只读，不自动降级/删除
    - code / config / D-tech 不设时间阈值，只按事实源复核
    - runtime 才受时效约束，且 stale 超宽限期才成为淘汰候选
    - 任何解码/复核失败都返回显式 degraded_reason，禁止伪装成「没有」

CLI:
    python3 residual_memory.py backfill --db <path> [--apply] [--limit N]
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

SUBCLASSES = ("code", "config", "runtime", "D-tech", "D-policy")
FORMS = ("M1", "M2", "M3")
VERIFY_STATES = ("fresh", "stale", "degraded")

TRAJECTORY_SOURCES = frozenset({"rag-bridge", "l0.scheduler", "l1_router"})
NO_ANCHOR_SUBCLASSES = frozenset({"runtime", "D-tech", "D-policy"})

RUNTIME_TTL_DAYS = 7
RUNTIME_GRACE_DAYS = 7

_REPO_ROOT = Path(__file__).resolve().parents[2]

# S0：敏感信息（只匹配「键 = 值」形态，避免把 "token 预算" 这类讨论误杀）
_SENSITIVE_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|secret|password|passwd|access[_-]?token|private[_-]?key)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-/+=]{8,}"
    ),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b\d{17}[\dXx]\b"),  # 身份证
    re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),  # 银行卡 16 位（宽松）
)

# 锚点：文件路径 + 可选符号（`file.py:Symbol` / `file.ts:line`）
_ANCHOR_RE = re.compile(
    r"([A-Za-z0-9_./\-\u4e00-\u9fff]+\.(?:py|ts|tsx|js|jsx|go|rs|java|sql|sh|yaml|yml|json|toml|ini))"
    r"(?::([A-Za-z0-9_.\-]+))?"
)

_POLICY_HINTS = ("用户裁定", "约定", "红线", "禁止", "不得", "口径", "规范", "政策")
_TECH_HINTS = ("选型", "决定", "弃用", "改回", "踩坑", "事故", "根因", "复盘", "代价", "回滚")
_RESIDUAL_HINTS = (
    "不要",
    "不用",
    "改用",
    "偏好",
    "习惯",
    "耗时",
    "代价",
    "事故",
    "回滚",
    "损失",
    "根因",
    "维护窗口",
    "属主",
    "有效期",
    "试过",
    "不行",
    "不可行",
    "放弃",
)


@dataclass
class GateVerdict:
    """写入裁决结果。accepted 是策略判定；enforced 表示本次是否真的拦截。"""

    accepted: bool
    reason: str
    stage: str
    subclass: str
    form: str
    source_anchor: str = ""
    verify_state: str = "fresh"
    enforced: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "stage": self.stage,
            "subclass": self.subclass,
            "form": self.form,
            "source_anchor": self.source_anchor,
            "verify_state": self.verify_state,
            "enforced": self.enforced,
            "detail": self.detail,
        }


# ============================================================
# S1 分型
# ============================================================


def extract_anchor(text: str) -> str:
    """从文本中提取 `file[:symbol]` 锚点；无命中返回空串。"""
    if not text:
        return ""
    m = _ANCHOR_RE.search(text)
    if not m:
        return ""
    path, sym = m.group(1), m.group(2) or ""
    return f"{path}:{sym}" if sym else path


def anchor_kind(anchor: str) -> str:
    """锚点类别：code / config / other / empty。"""
    if not anchor:
        return "empty"
    path = anchor.split(":", 1)[0]
    suffix = Path(path).suffix.lower()
    if suffix in {".yaml", ".yml", ".toml", ".ini", ".json", ".env"}:
        return "config"
    if suffix:
        return "code"
    return "other"


def classify(
    content: str,
    *,
    source: str = "",
    tags: Optional[Iterable[str]] = None,
    memory_type: str = "experience",
    source_anchor: str = "",
) -> str:
    """子类分型。保守优先：无法判定时归 D-policy。"""
    tags = list(tags or [])
    blob = " ".join([content or "", " ".join(tags)])

    if source in TRAJECTORY_SOURCES:
        return "runtime"
    if memory_type in {"policy", "decision_policy"}:
        return "D-policy"

    kind = anchor_kind(source_anchor)
    if kind == "code":
        return "code"
    if kind == "config":
        return "config"

    if any(h in blob for h in _POLICY_HINTS):
        return "D-policy"
    if any(h in blob for h in _TECH_HINTS):
        return "D-tech"
    return "D-policy"


def form_for(subclass: str, source_anchor: str = "", *, linked: bool = False) -> str:
    """verdict → 形态：有锚点 M1；有既有条目关联 M2；否则 M3。"""
    if source_anchor and subclass in {"code", "config"}:
        return "M1"
    if linked:
        return "M2"
    if subclass in {"runtime", "D-tech", "D-policy"}:
        return "M2"
    return "M3"


# ============================================================
# A 接入点：gate()
# ============================================================


def _is_sensitive(content: str) -> bool:
    return any(p.search(content or "") for p in _SENSITIVE_PATTERNS)


def _is_trajectory(content: str, source: str) -> bool:
    if source in TRAJECTORY_SOURCES:
        return True
    head = (content or "").lstrip()[:40]
    return head.startswith("[RAG检索]") or head.startswith("[检索]")


def _is_residual(content: str) -> bool:
    blob = content or ""
    return any(h in blob for h in _RESIDUAL_HINTS)


def gate(
    content: str,
    *,
    source: str = "",
    tags: Optional[Iterable[str]] = None,
    memory_type: str = "experience",
    source_anchor: str = "",
    mode: Optional[str] = None,
    redundancy_probe=None,
) -> GateVerdict:
    """写入裁决 S0→S4。

    mode:
        shadow      只判定不拦截（enforced=False）
        enforce_n3  只对 N3 轨迹硬拦（默认，符合 §3.1「N3 为硬零」）
        enforce     全量执行准入判定
    """
    mode = (mode or os.environ.get("COGNITIVE_ADMISSION_MODE") or "enforce_n3").strip()
    anchor = source_anchor or extract_anchor(content)
    subclass = classify(
        content, source=source, tags=tags, memory_type=memory_type, source_anchor=anchor
    )

    def _verdict(accepted: bool, reason: str, stage: str, form: str) -> GateVerdict:
        enforced = mode == "enforce" or (mode == "enforce_n3" and reason == "trajectory")
        return GateVerdict(
            accepted=accepted,
            reason=reason,
            stage=stage,
            subclass=subclass,
            form=form,
            source_anchor=anchor,
            enforced=enforced,
            detail={"mode": mode},
        )

    # S0 敏感：不写，理由显式
    if _is_sensitive(content):
        return _verdict(False, "sensitive", "S0", "M3")

    # S2 N3 轨迹：硬零
    if _is_trajectory(content, source):
        return _verdict(False, "trajectory", "S2", "M3")

    # S3 冗余：有既有条目则转 M2 关联，不新增正文
    if redundancy_probe is not None:
        try:
            existing = redundancy_probe(content)
        except Exception:  # noqa: BLE001 - 探测失败按未命中处理，不阻断写入
            existing = None
        if existing:
            return _verdict(True, "redundant_linked", "S3", "M2")

    # S4 残差测试：M1 必须有锚点；内容型须命中四残差信号
    form = form_for(subclass, anchor)
    if subclass in {"code", "config"} and not anchor:
        # 无锚点的代码/配置类不得进入 M1，也不得当作内容型残差
        return _verdict(False, "pointer_no_anchor", "S4", "M3")
    if form == "M1":
        return _verdict(True, "ok", "S4", "M1")
    if _is_residual(content):
        return _verdict(True, "ok", "S4", "M2")
    return _verdict(False, "non_residual", "S4", "M3")


# ============================================================
# B 接入点：decode()
# ============================================================


def decode(
    source_anchor: str, *, repo_root: Optional[Path] = None, max_lines: int = 24
) -> Dict[str, Any]:
    """按锚点现场重建片段。失败一律返回 ok=False + degraded_reason。"""
    if not source_anchor:
        return {"ok": False, "degraded_reason": "anchor_missing", "next": "按内容返回"}

    path_part, _, symbol = source_anchor.partition(":")
    if not path_part:
        return {"ok": False, "degraded_reason": "anchor_malformed", "next": "按内容返回"}

    root = Path(repo_root or _REPO_ROOT).resolve()
    target = (root / path_part).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return {"ok": False, "degraded_reason": "anchor_outside_repo", "next": "拒绝越界读取"}

    if not target.exists() or not target.is_file():
        return {
            "ok": False,
            "degraded_reason": "anchor_missing",
            "path": str(target.relative_to(root)),
            "next": "回退记忆内容",
        }
    try:
        if target.stat().st_size > 2 * 1024 * 1024:
            return {"ok": False, "degraded_reason": "anchor_file_too_large", "next": "回退记忆内容"}
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {
            "ok": False,
            "degraded_reason": f"anchor_read_failed:{type(exc).__name__}",
            "next": "回退记忆内容",
        }

    start = 0
    if symbol and not symbol.isdigit():
        needle = symbol.split(".")[-1]
        for i, line in enumerate(lines):
            if re.search(
                rf"\b(def|class|function|const|let|var|async)\s+{re.escape(needle)}\b", line
            ) or (needle and needle in line):
                start = i
                break
        else:
            return {
                "ok": False,
                "degraded_reason": "anchor_symbol_missing",
                "path": str(target.relative_to(root)),
                "next": "回退记忆内容",
            }
    elif symbol and symbol.isdigit():
        start = max(0, min(int(symbol) - 1, len(lines) - 1))

    snippet = "\n".join(lines[start : start + max_lines]).strip()
    return {
        "ok": True,
        "path": str(target.relative_to(root)),
        "line": start + 1,
        "symbol": symbol,
        "snippet": snippet[:1200],
    }


# ============================================================
# C 接入点：review() / governance_decision()
# ============================================================


def _age_days(created_at: str, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (now - dt).days)
    except Exception:  # noqa: BLE001 - 时间不可解析按 0 处理，不据此降级
        return 0


def review(
    row: Dict[str, Any],
    *,
    repo_root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> str:
    """事实源复核 → verify_state。D-policy 与未分型一律 fresh（不自动处理）。"""
    subclass = row.get("subclass")
    if subclass in (None, "", "D-policy"):
        return "fresh"

    anchor = row.get("source_anchor") or ""
    if subclass in {"code", "config"}:
        if not anchor:
            return "fresh"
        result = decode(anchor, repo_root=repo_root)
        if result.get("ok"):
            return "fresh"
        # 单轮失配只到 stale；上一轮已 stale 才升 degraded（连续 2 轮）
        return "degraded" if row.get("verify_state") == "stale" else "stale"

    if subclass == "runtime":
        if row.get("verify_state") == "degraded":
            return "degraded"
        return "stale" if _age_days(row.get("created_at", ""), now) >= RUNTIME_TTL_DAYS else "fresh"

    # D-tech：只由 supersedes / 新证据驱动，复核不降级
    return row.get("verify_state") or "fresh"


def governance_decision(row: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, str]:
    """治理决策。返回 action ∈ {keep, degrade, ttl_candidate}。

    只降级不删除；D-policy / 未分型永不进入候选。
    """
    subclass = row.get("subclass")
    state = row.get("verify_state") or "fresh"

    if subclass in (None, ""):
        return {"action": "keep", "reason": "unclassified_hold"}
    if subclass == "D-policy":
        return {"action": "keep", "reason": "policy_hold"}
    if state == "degraded":
        # 移出索引，保留行；物理删除不在本函数职责内
        return {"action": "degrade", "reason": "verify_degraded"}
    if subclass != "runtime":
        return {"action": "keep", "reason": "event_driven_only"}

    age = _age_days(row.get("created_at", ""), now)
    if int(row.get("access_count") or 0) > 0 or row.get("last_used_at"):
        return {"action": "keep", "reason": "recently_used"}
    if state == "stale" and age >= RUNTIME_TTL_DAYS + RUNTIME_GRACE_DAYS:
        return {"action": "ttl_candidate", "reason": "stale_beyond_grace"}
    if age >= RUNTIME_TTL_DAYS:
        return {"action": "ttl_candidate", "reason": "runtime_expired"}
    return {"action": "keep", "reason": "within_ttl"}


# ============================================================
# P1：存量回填
# ============================================================


_RESIDUAL_COLUMNS = (
    ("subclass", "TEXT"),
    ("form", "TEXT"),
    ("source_anchor", "TEXT"),
    ("verify_state", "TEXT DEFAULT 'fresh'"),
)


def ensure_residual_columns(con: sqlite3.Connection) -> Dict[str, Any]:
    """幂等补列（生产库可能尚未初始化 VectorMemoryInterface）。"""
    existing = {str(row[1]) for row in con.execute("PRAGMA table_info(memories)").fetchall()}
    added = []
    for name, ddl in _RESIDUAL_COLUMNS:
        if name not in existing:
            con.execute(f"ALTER TABLE memories ADD COLUMN {name} {ddl}")
            added.append(name)
    if added:
        con.commit()
    return {"added": added, "columns": [name for name, _ in _RESIDUAL_COLUMNS]}


def backfill(
    con: sqlite3.Connection,
    *,
    dry_run: bool = True,
    limit: int = 0,
    batch_size: int = 2000,
) -> Dict[str, Any]:
    """为 subclass 为空的存量记忆回填 subclass / form / source_anchor / verify_state。

    轨迹来源 → runtime；可从内容提取锚点 → code/config；其余保守归 D-policy。
    幂等：只处理 subclass IS NULL 的行。
    有界分批：apply 时按 batch 循环推进；dry-run 只抽样一批（避免全库读入内存）。
    """
    stats: Dict[str, Any] = {
        "scanned": 0,
        "updated": 0,
        "batches": 0,
        "by_subclass": {},
        "by_form": {},
    }
    try:
        con.execute("SELECT subclass FROM memories LIMIT 1")
    except sqlite3.OperationalError:
        stats["degraded_reason"] = "residual_columns_missing"
        stats["next"] = "先执行 ensure_residual_columns（--apply 时自动）"
        return stats
    select_sql = (
        "SELECT id, content, source, tags, memory_type FROM memories "
        "WHERE subclass IS NULL OR subclass = '' LIMIT ?"
    )
    remaining = limit or 0
    while True:
        take = batch_size if not remaining else min(batch_size, remaining)
        rows = con.execute(select_sql, [take]).fetchall()
        if not rows:
            break
        stats["batches"] += 1

        updates = []
        for row in rows:
            rid = row[0] if not hasattr(row, "keys") else row["id"]
            content = row[1] if not hasattr(row, "keys") else row["content"]
            source = (row[2] if not hasattr(row, "keys") else row["source"]) or ""
            tags_raw = row[3] if not hasattr(row, "keys") else row["tags"]
            memory_type = row[4] if not hasattr(row, "keys") else row["memory_type"]
            try:
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else list(tags_raw or [])
            except (ValueError, TypeError):
                tags = []
            anchor = extract_anchor(content or "")
            subclass = classify(
                content or "",
                source=source,
                tags=tags,
                memory_type=memory_type or "experience",
                source_anchor=anchor,
            )
            form = form_for(subclass, anchor)
            updates.append((subclass, form, anchor, "fresh", rid))
            stats["by_subclass"][subclass] = stats["by_subclass"].get(subclass, 0) + 1
            stats["by_form"][form] = stats["by_form"].get(form, 0) + 1

        stats["scanned"] += len(rows)
        if dry_run:
            break
        try:
            con.executemany(
                "UPDATE memories SET subclass=?, form=?, source_anchor=?, verify_state=? WHERE id=?",
                updates,
            )
            con.commit()
            stats["updated"] += len(updates)
        except sqlite3.Error as exc:
            con.rollback()
            stats["error"] = str(exc)
            break

        if remaining:
            remaining -= len(rows)
            if remaining <= 0:
                break
    stats["dry_run"] = dry_run
    return stats


def reclassify_invalid_anchors(
    con: sqlite3.Connection,
    *,
    repo_root: Optional[Path] = None,
    dry_run: bool = True,
    limit: int = 0,
) -> Dict[str, Any]:
    """把「锚点在仓库中解析不到」的 code/config 降为内容型子类。

    存量回填从正文正则抽出的裸文件名（如 `pool.js`）大多不是仓库路径；
    若保留 code/config，复核会把它误标 stale。锚点不可解析时按无锚点重分型，
    保守落到 D-tech / D-policy，form 改 M2。
    """
    stats: Dict[str, Any] = {"checked": 0, "kept": 0, "reclassified": 0, "by_subclass": {}}
    sql = (
        "SELECT id, content, source, tags, memory_type, subclass, source_anchor "
        "FROM memories WHERE subclass IN ('code','config')"
    )
    params: list = []
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    updates = []
    for row in con.execute(sql, params).fetchall():
        rid = row[0] if not hasattr(row, "keys") else row["id"]
        content = (row[1] if not hasattr(row, "keys") else row["content"]) or ""
        source = (row[2] if not hasattr(row, "keys") else row["source"]) or ""
        tags_raw = row[3] if not hasattr(row, "keys") else row["tags"]
        memory_type = row[4] if not hasattr(row, "keys") else row["memory_type"]
        anchor = (row[6] if not hasattr(row, "keys") else row["source_anchor"]) or ""
        stats["checked"] += 1
        if anchor and decode(anchor, repo_root=repo_root).get("ok"):
            stats["kept"] += 1
            continue
        try:
            tags = json.loads(tags_raw) if isinstance(tags_raw, str) else list(tags_raw or [])
        except (ValueError, TypeError):
            tags = []
        new_subclass = classify(
            content, source=source, tags=tags, memory_type=memory_type or "experience"
        )
        updates.append((new_subclass, form_for(new_subclass, ""), "", "fresh", rid))
        stats["by_subclass"][new_subclass] = stats["by_subclass"].get(new_subclass, 0) + 1
    stats["reclassified"] = len(updates)
    if dry_run or not updates:
        stats["dry_run"] = dry_run
        return stats
    try:
        con.executemany(
            "UPDATE memories SET subclass=?, form=?, source_anchor=?, verify_state=? WHERE id=?",
            updates,
        )
        con.commit()
    except sqlite3.Error as exc:
        con.rollback()
        stats["error"] = str(exc)
    stats["dry_run"] = dry_run
    return stats


def verify_deletion_set(
    path: str | Path, *, min_precision: float = 0.95, min_recall: float = 0.95
) -> Dict[str, Any]:
    """用标注好的删除测试集评测治理决策（SPEC §3.3 删除测试 / §4′ P5 门禁）。

    只统计 label ∈ {delete, keep}；ambiguous 留给人工，不参与打分。
    「预测删除」的唯一定义是 governance_decision == ttl_candidate（物理删除候选）。
    """
    p = Path(path)
    cases = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))

    tp = fp = tn = fn = 0
    false_deletes: list[str] = []
    missed: list[str] = []
    for c in cases:
        label = c.get("label")
        if label not in ("delete", "keep"):
            continue
        decision = governance_decision(c)
        pred_delete = decision["action"] == "ttl_candidate"
        if label == "delete":
            if pred_delete:
                tp += 1
            else:
                fn += 1
                missed.append(c.get("id", ""))
        elif pred_delete:
            fp += 1
            false_deletes.append(c.get("id", ""))
        else:
            tn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    passed = precision >= min_precision and recall >= min_recall and tp > 0
    return {
        "file": str(p),
        "cases": len(cases),
        "scored": tp + fp + tn + fn,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "false_deletes": false_deletes[:20],
        "missed": missed[:20],
        "thresholds": {"precision": min_precision, "recall": min_recall},
        "passed": passed,
    }


def export_blind_sample(
    con: sqlite3.Connection,
    out_dir: str | Path,
    *,
    base: int = 400,
    ratio: float = 0.2,
    seed: int = 42,
) -> Dict[str, Any]:
    """导出 20% 人工盲评样本（SPEC §4′ P1 验收）。

    产出两个文件：
      blind_sheet_*.csv    人工填写用（不含预测子类）
      blind_answers_*.jsonl 预测答案（评分时用，评审期间不要打开）
    """
    import csv
    import math
    import random

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    per_class = max(1, math.ceil(base / len(SUBCLASSES)))
    picked: list[Dict[str, Any]] = []
    for sc in SUBCLASSES:
        rows = con.execute(
            "SELECT id, content, source, memory_type, subclass, form, source_anchor, verify_state "
            "FROM memories WHERE subclass=? AND length(content)>0 "
            "ORDER BY random() LIMIT ?",
            [sc, per_class],
        ).fetchall()
        for r in rows:
            picked.append(
                dict(r)
                if hasattr(r, "keys")
                else {
                    "id": r[0],
                    "content": r[1],
                    "source": r[2],
                    "memory_type": r[3],
                    "subclass": r[4],
                    "form": r[5],
                    "source_anchor": r[6],
                    "verify_state": r[7],
                }
            )
    random.Random(seed).shuffle(picked)
    picked = picked[:base]
    blind_n = max(1, int(len(picked) * ratio))
    blind_ids = {r["id"] for r in picked[:blind_n]}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    sheet = out / f"blind_sheet_{stamp}.csv"
    answers = out / f"blind_answers_{stamp}.jsonl"
    with sheet.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "sample", "source", "memory_type", "content", "human_subclass"])
        for r in picked:
            w.writerow(
                [
                    r["id"],
                    1 if r["id"] in blind_ids else 0,
                    r["source"] or "",
                    r["memory_type"] or "",
                    (r["content"] or "")[:200].replace("\n", " "),
                    "",
                ]
            )
    with answers.open("w", encoding="utf-8") as f:
        for r in picked:
            f.write(
                json.dumps(
                    {
                        "id": r["id"],
                        "subclass": r["subclass"],
                        "form": r["form"],
                        "source_anchor": r["source_anchor"] or "",
                        "verify_state": r["verify_state"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return {
        "dir": str(out),
        "sheet": str(sheet),
        "answers": str(answers),
        "sampled": len(picked),
        "blind": blind_n,
        "by_subclass": {sc: sum(1 for r in picked if r["subclass"] == sc) for sc in SUBCLASSES},
    }


def score_blind_sample(sheet_path: str | Path, answers_path: str | Path) -> Dict[str, Any]:
    """按人工填写结果计算一致率与 Cohen's κ（只看 sample=1 且已填写的行）。"""
    import csv

    preds = {}
    for line in Path(answers_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            preds[row["id"]] = row["subclass"]

    pairs = []
    skipped = 0
    with Path(sheet_path).open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if str(row.get("sample", "0")) != "1":
                continue
            human = (row.get("human_subclass") or "").strip()
            if human not in SUBCLASSES:
                skipped += 1
                continue
            pairs.append((preds.get(row["id"]), human))

    if not pairs:
        return {
            "scored": 0,
            "agreement": 0.0,
            "kappa": 0.0,
            "passed": False,
            "degraded_reason": "no_filled_rows",
            "skipped": skipped,
        }

    correct = sum(1 for p, h in pairs if p == h)
    po = correct / len(pairs)
    pred_counts = dict.fromkeys(SUBCLASSES, 0)
    human_counts = dict.fromkeys(SUBCLASSES, 0)
    for p, h in pairs:
        pred_counts[p] = pred_counts.get(p, 0) + 1
        human_counts[h] += 1
    pe = sum(pred_counts[sc] / len(pairs) * human_counts[sc] / len(pairs) for sc in SUBCLASSES)
    kappa = (po - pe) / (1 - pe) if pe < 1 else 0.0
    return {
        "scored": len(pairs),
        "skipped": skipped,
        "agreement": round(po, 4),
        "kappa": round(kappa, 4),
        "passed": po >= 0.90 and kappa >= 0.60,
    }


# ============================================================
# CLI
# ============================================================


def _default_db() -> Path:
    return _REPO_ROOT / "4-MEMORY" / "data" / "cognitive_memory.db"


def main(argv: Optional[list] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="残差记忆器（SPEC §3.7′/§4′）")
    parser.add_argument("--backfill", action="store_true", help="回填存量 subclass/form/anchor")
    parser.add_argument(
        "--reclassify", action="store_true", help="锚点不可解析的 code/config 降为内容型"
    )
    parser.add_argument("--repo-root", default="", help="锚点解析根目录（默认自动推断）")
    parser.add_argument("--verify-deletion", default="", help="删除测试集 JSONL 路径")
    parser.add_argument("--write-report", default="", help="删除评测报告落盘路径")
    parser.add_argument("--export-blind", default="", help="导出盲评样本目录")
    parser.add_argument("--score-blind", default="", help="盲评 sheet CSV 路径")
    parser.add_argument("--answers", default="", help="盲评答案 JSONL 路径")
    parser.add_argument("--db", default=str(_default_db()), help="cognitive_memory.db 路径")
    parser.add_argument("--apply", action="store_true", help="实际写入（缺省 dry-run）")
    parser.add_argument("--limit", type=int, default=0, help="单轮最多处理条数（0=不限）")
    args = parser.parse_args(argv)

    if args.score_blind:
        if not args.answers:
            print("缺少 --answers")
            return 1
        report = score_blind_sample(args.score_blind, args.answers)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("passed") else 2

    if not any(
        [args.backfill, args.reclassify, args.verify_deletion, args.export_blind, args.score_blind]
    ):
        parser.print_help()
        return 1

    con = sqlite3.connect(f"file:{args.db}?mode=ro" if not args.apply else args.db, uri=True)
    con.row_factory = sqlite3.Row

    if args.export_blind:
        try:
            report = export_blind_sample(con, args.export_blind)
        finally:
            con.close()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    try:
        if args.apply:
            ensure_residual_columns(con)
        if args.verify_deletion:
            report = verify_deletion_set(args.verify_deletion)
            if args.write_report:
                Path(args.write_report).parent.mkdir(parents=True, exist_ok=True)
                Path(args.write_report).write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["passed"] else 2
        if args.reclassify:
            report = reclassify_invalid_anchors(
                con,
                repo_root=Path(args.repo_root) if args.repo_root else None,
                dry_run=not args.apply,
                limit=args.limit,
            )
        else:
            report = backfill(con, dry_run=not args.apply, limit=args.limit)
    finally:
        con.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
