"""索引状态总览（cm index）。

默认执行一次增量扫描后汇报；`check=True` 只读校验，不重建索引。
写盘范围仅限 `.cm/index.db`（由 scanner 负责）。
"""

from __future__ import annotations

import datetime
from pathlib import Path

from . import report, scanner

SCHEMA_VERSION = "1.0"


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def index(root, config: dict, conn, check: bool = False) -> dict:
    root = Path(root).expanduser().resolve()
    scan_stats = None
    if not check:
        scan_stats = scanner.scan(root, config, conn, full=False)

    health = report.doctor(root, config, conn)
    docs_row = conn.execute("SELECT COUNT(*) AS n FROM docs WHERE status='active'").fetchone()
    skills_row = conn.execute("SELECT COUNT(*) AS n FROM skills WHERE status='active'").fetchone()

    counts = {
        "docs": docs_row["n"],
        "skills": skills_row["n"],
        "broken_links": health["metrics"]["broken_links"],
        "orphan_files": health["metrics"]["orphan_files"],
        "index_drift": health["metrics"]["index_drift"],
    }
    details = {
        "broken_links": health["details"]["broken_links"],
        "orphan_files": health["details"]["orphan_files"],
        "index_drift": health["details"]["index_drift"],
    }

    notes = []
    if check:
        notes.append("check 模式：只读校验，未重建索引（cm index 可增量重建）")
    else:
        notes.append(
            "已执行增量扫描：新登记 {}，未变化 {}".format(
                scan_stats["scanned"], scan_stats["unchanged"]
            )
        )
    if counts["index_drift"]:
        notes.append("存在索引漂移，执行 cm scan --full 重建")

    return {
        "schema_version": SCHEMA_VERSION,
        "command": "index",
        "workspace": str(root),
        "mode": "check" if check else "incremental",
        "generated_at": _now_iso(),
        "counts": counts,
        "details": details,
        "notes": notes,
    }
