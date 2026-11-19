#!/usr/bin/env python3
"""生成删除测试集（SPEC §3.3 / §4′ P5 门禁）。

用例按治理规则逐条覆盖，含反例（D-policy/近期使用/未分型/降级态）：
  - label=delete：到期 runtime 轨迹，应进入 ttl_candidate
  - label=keep：任何不应物理删除的记忆（含只降级不删除的 degraded）

日期用「距今 N 天」动态生成，避免测试集随时间失效。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent / "deletion_set.jsonl"

# (id, subclass, age_days, access_count, last_used_days, verify_state, label)
CASES = [
    ("del-runtime-8d", "runtime", 8, 0, None, "fresh", "delete"),
    ("del-runtime-30d", "runtime", 30, 0, None, "fresh", "delete"),
    ("del-runtime-400d", "runtime", 400, 0, None, "fresh", "delete"),
    ("del-runtime-stale-14d", "runtime", 14, 0, None, "stale", "delete"),
    ("del-runtime-stale-15d", "runtime", 15, 0, None, "stale", "delete"),
    ("del-runtime-stale-60d", "runtime", 60, 0, None, "stale", "delete"),
    ("del-runtime-stale-20d", "runtime", 20, 0, None, "stale", "delete"),
    ("del-runtime-9d", "runtime", 9, 0, None, "fresh", "delete"),
    ("keep-runtime-1d", "runtime", 1, 0, None, "fresh", "keep"),
    ("keep-runtime-6d", "runtime", 6, 0, None, "fresh", "keep"),
    ("keep-runtime-today", "runtime", 0, 0, None, "fresh", "keep"),
    ("keep-runtime-stale-2d", "runtime", 2, 0, None, "stale", "keep"),
    ("keep-runtime-30d-accessed", "runtime", 30, 3, None, "fresh", "keep"),
    ("keep-runtime-100d-used", "runtime", 100, 0, 0, "fresh", "keep"),
    ("keep-runtime-stale-30d-accessed", "runtime", 30, 1, None, "stale", "keep"),
    ("keep-policy-400d", "D-policy", 400, 0, None, "fresh", "keep"),
    ("keep-policy-0d", "D-policy", 0, 0, None, "fresh", "keep"),
    ("keep-tech-400d", "D-tech", 400, 0, None, "fresh", "keep"),
    ("keep-code-400d", "code", 400, 0, None, "fresh", "keep"),
    ("keep-config-400d", "config", 400, 0, None, "fresh", "keep"),
    ("keep-unclassified-400d", None, 400, 0, None, "fresh", "keep"),
    ("keep-empty-subclass-400d", "", 400, 0, None, "fresh", "keep"),
    ("keep-runtime-degraded-30d", "runtime", 30, 0, None, "degraded", "keep"),
    ("keep-runtime-degraded-100d", "runtime", 100, 0, None, "degraded", "keep"),
]


def main() -> None:
    now = datetime.now(timezone.utc)
    lines = []
    for cid, subclass, age, access, last_used, state, label in CASES:
        created = (now - timedelta(days=age)).isoformat()
        row = {
            "id": cid,
            "content": f"删除测试用例 {cid}",
            "subclass": subclass,
            "memory_type": "experience",
            "source": "rag-bridge" if subclass == "runtime" else "mcp",
            "created_at": created,
            "access_count": access,
            "last_used_at": (
                (now - timedelta(days=last_used)).isoformat() if last_used is not None else None
            ),
            "verify_state": state,
            "label": label,
        }
        lines.append(json.dumps(row, ensure_ascii=False))
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    deletes = sum(1 for c in CASES if c[6] == "delete")
    print(f"wrote {OUT} cases={len(CASES)} delete={deletes} keep={len(CASES) - deletes}")


if __name__ == "__main__":
    main()
