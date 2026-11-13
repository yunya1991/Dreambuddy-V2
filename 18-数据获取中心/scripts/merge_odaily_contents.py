#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""odaily 深度文章增量合并：contents.jsonl → contents_all.jsonl。

每轮爬取完成后调用：将本轮 500 篇按文章 id 去重合并进累积库，
为训练提供持续增长的深度文章语料（不丢失历史轮次）。

用法：python3 scripts/merge_odaily_contents.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("merge_odaily_contents")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "backfill" / "odaily_p0"
SRC = OUT_DIR / "contents.jsonl"
DST = OUT_DIR / "contents_all.jsonl"


def _load(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["id"]] = r
    return rows


def main() -> int:
    if not SRC.exists():
        logger.warning("contents.jsonl 不存在，跳过合并")
        return 0
    existing = _load(DST)
    n_before = len(existing)
    n_new = 0
    for r in _load(SRC).values():
        if r["id"] not in existing:
            existing[r["id"]] = r
            n_new += 1
    tmp = DST.with_name(DST.name + ".tmp")
    tmp.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in existing.values()) + "\n",
        encoding="utf-8",
    )
    tmp.replace(DST)
    logger.info(
        "合并完成：累积库原有 %d，本轮新增 %d，当前累积 %d → %s",
        n_before,
        n_new,
        len(existing),
        DST,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
