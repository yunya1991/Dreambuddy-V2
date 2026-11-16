#!/usr/bin/env python3
"""记忆内容漂移检测（P4 再巩固）。

注意与 TB1 的 `drift_detector.py`（PSI/KS 数值分布漂移）区分：那个检测「指标分布是否漂移」，
本模块检测「记忆引用的代码/文档事实是否已失效」。

问题：记忆写下来时引用的是「当时的代码/文档事实」，代码改了、文件删了，记忆就成了
**过时证据**。本模块扫 `memories` 里出现的文件锚点，与仓库现状比对，产出漂移清单；
`--apply` 时把命中项交给既有 `verify(drift_detected=True)` 重置 Beta 先验（走原有链路，
不新建平行状态）。

判定：
  - `anchor_missing`：记忆引用的文件已不存在 → 记忆几乎必然过时；
  - `file_changed_after_memory`：文件 mtime 晚于记忆创建时间 → 可能过时（候选，需人工/verify 复核）。

纪律：默认 dry-run 只读；轨迹来源（rag-bridge/l0.scheduler/l1_router）不参与（已由 TTL 清退）。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from memory_ttl_manager import NO_TRACE_SOURCES, TTL_SCOPE_DEFAULT
except ImportError:  # pragma: no cover - 独立运行兜底
    TTL_SCOPE_DEFAULT = ("rag-bridge", "l0.scheduler", "l1_router")
    NO_TRACE_SOURCES = frozenset(TTL_SCOPE_DEFAULT)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB = _REPO_ROOT / "4-MEMORY" / "data" / "cognitive_memory.db"

# 只认「带目录的文件路径」，避免把普通单词误判成锚点
ANCHOR_RE = re.compile(
    r"(?<![\w./:-])((?:[\w\u4e00-\u9fff][\w\u4e00-\u9fff.\-]*/)+[\w\u4e00-\u9fff.\-]+"
    r"\.(?:tsx|ts|jsx|js|py|md|yaml|yml|json|toml|sql|sh))"
)
_SCAN_QUALITIES = ("S", "A", "B")


def extract_anchors(text: str) -> set[str]:
    """从文本中抽取仓库相对文件路径锚点。"""
    if not text:
        return set()
    return {m.group(1).strip() for m in ANCHOR_RE.finditer(text)}


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _check_anchor(
    repo_root: Path, anchor: str, created_at: datetime | None
) -> dict[str, Any] | None:
    """返回漂移记录；无漂移返回 None。"""
    target = Path(anchor) if Path(anchor).is_absolute() else repo_root / anchor
    if not target.exists():
        return {"anchor": anchor, "reason": "anchor_missing"}
    if created_at is not None:
        try:
            mtime = datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc)
        except OSError:  # pragma: no cover - 文件竞态
            return None
        if mtime > created_at:
            return {
                "anchor": anchor,
                "reason": "file_changed_after_memory",
                "file_mtime": mtime.isoformat(),
            }
    return None


def detect_drift(
    db_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    limit: int = 0,
    dry_run: bool = True,
) -> dict[str, Any]:
    """扫描记忆锚点与仓库现状的漂移。

    Args:
        db_path: 记忆库路径（默认 4-MEMORY/data/cognitive_memory.db）
        repo_root: 仓库根（默认推导）
        limit: >0 时最多返回 N 条漂移（0 = 全量）
        dry_run: True 只报告；False 对命中项调用 verify(drift_detected=True)

    Returns:
        {"ok": True, "scanned", "with_anchors", "drifted", "items", "applied", "dry_run"}
    """
    db = Path(db_path) if db_path else _DEFAULT_DB
    root = Path(repo_root) if repo_root else _REPO_ROOT
    if not db.exists():
        return {"ok": False, "degraded_reason": "db_missing", "db": str(db)}

    marks = ",".join("?" * len(_SCAN_QUALITIES))
    excludes = ",".join("?" * len(TTL_SCOPE_DEFAULT))
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, quality_level, source, created_at, content, tags FROM memories "
            f"WHERE quality_level IN ({marks}) AND COALESCE(source,'') NOT IN ({excludes})",
            [*_SCAN_QUALITIES, *TTL_SCOPE_DEFAULT],
        ).fetchall()
    except sqlite3.Error as exc:
        con.close()
        return {"ok": False, "degraded_reason": "db_query_failed", "error": str(exc)}
    con.close()

    items: list[dict[str, Any]] = []
    with_anchors = 0
    for row in rows:
        anchors = extract_anchors((row["content"] or "") + " " + (row["tags"] or ""))
        if not anchors:
            continue
        with_anchors += 1
        created = _parse_ts(row["created_at"] or "")
        hits = [h for h in (_check_anchor(root, a, created) for a in sorted(anchors)) if h]
        if hits:
            items.append(
                {
                    "id": row["id"],
                    "quality_level": row["quality_level"],
                    "created_at": row["created_at"],
                    "drift": hits,
                }
            )

    drifted_total = len(items)
    if limit and limit > 0:
        items = items[:limit]

    applied = 0
    apply_errors: list[str] = []
    if not dry_run and items:
        from cognitive_loop_entry import CognitiveLoopEntry

        cle = CognitiveLoopEntry(storage_path=str(db))
        for item in items:
            try:
                cle.verify(item["id"], success=False, drift_detected=True)
                applied += 1
            except Exception as exc:  # FAIL-OPEN：单条失败不阻断整批
                apply_errors.append(f"{item['id']}: {exc}")

    return {
        "ok": True,
        "db": str(db),
        "repo_root": str(root),
        "dry_run": dry_run,
        "scanned": len(rows),
        "with_anchors": with_anchors,
        "drifted": drifted_total,
        "returned": len(items),
        "applied": applied,
        "apply_errors": apply_errors,
        "items": items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="记忆漂移检测（P4）")
    parser.add_argument("--db", default=None, help="记忆库路径")
    parser.add_argument("--repo-root", default=None, help="仓库根（默认自动推导）")
    parser.add_argument("--limit", type=int, default=0, help="最多返回 N 条（0=全量）")
    parser.add_argument(
        "--apply", action="store_true", help="对命中项调用 verify(drift_detected=True)"
    )
    args = parser.parse_args(argv)

    out = detect_drift(
        db_path=args.db,
        repo_root=args.repo_root,
        limit=args.limit,
        dry_run=not args.apply,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
