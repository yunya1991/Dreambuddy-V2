#!/usr/bin/env python3
"""Gold Set 自动标注脚本 — 从记忆库分层采样构建 gold set。

策略：
- S/A/D 档：全量纳入（数量少）
- B 档：采样 100 条
- C 档：采样 100 条（优先高 confidence）
- 使用现有 quality_level 作为初始 gold_quality
- 可后续人工修正

用法:
  python3 seed_gold_set.py              # 采样并写入 gold set
  python3 seed_gold_set.py --stats      # 仅查看 gold set 统计
  python3 seed_gold_set.py --kappa      # 计算 Cohen's kappa（需双人标注）
"""
from __future__ import annotations

import argparse
import os
import random
import sqlite3
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from verification_observer import GoldSetManager

DB_PATH = _SCRIPT_DIR.parent / "data" / "cognitive_memory.db"
GOLD_STORAGE = str(_SCRIPT_DIR.parent / "data" / "verification_observer")

# 各档位采样数
SAMPLE_SIZES = {
    "S": None,   # None = 全量
    "A": None,
    "B": 100,
    "C": 100,
    "D": None,
}


def fetch_memories_by_quality(db_path: str, quality: str, limit: int | None = None) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if limit:
        cur.execute(
            "SELECT id, content, quality_level, confidence, tags FROM memories "
            "WHERE quality_level = ? ORDER BY confidence DESC LIMIT ?",
            (quality, limit),
        )
    else:
        cur.execute(
            "SELECT id, content, quality_level, confidence, tags FROM memories "
            "WHERE quality_level = ? ORDER BY confidence DESC",
            (quality,),
        )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def seed_gold_set(db_path: str, storage: str) -> dict:
    gsm = GoldSetManager(storage_path=storage)
    seeded = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}

    for quality, limit in SAMPLE_SIZES.items():
        memories = fetch_memories_by_quality(db_path, quality, limit)
        for mem in memories:
            tags = []
            if mem.get("tags"):
                try:
                    import json
                    tags = json.loads(mem["tags"]) if isinstance(mem["tags"], str) else list(mem["tags"])
                except Exception:
                    tags = []
            gsm.add(
                memory_id=mem["id"],
                content=mem["content"][:500],  # 截断避免过长
                gold_quality=mem["quality_level"],
                gold_confidence=float(mem["confidence"] or 0.0),
                tags=tags,
            )
            seeded[quality] += 1

    return seeded


def show_stats(storage: str) -> None:
    gsm = GoldSetManager(storage_path=storage)
    print(f"Gold Set 总数: {gsm.count()}")
    # 按 gold_quality 统计
    from collections import Counter
    quality_dist = Counter()
    for mid in gsm.list_ids():
        entry = gsm.get(mid)
        if entry:
            quality_dist[entry.gold_quality] += 1
    for q in ["S", "A", "B", "C", "D"]:
        if q in quality_dist:
            print(f"  {q}: {quality_dist[q]}")
    kappa = gsm.cohen_kappa()
    print(f"Cohen's kappa: {kappa:.4f} (需双人标注才有意义)")


def main():
    parser = argparse.ArgumentParser(description="Gold Set 自动标注")
    parser.add_argument("--stats", action="store_true", help="仅查看统计")
    parser.add_argument("--kappa", action="store_true", help="计算 Cohen's kappa")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"❌ 数据库不存在: {DB_PATH}")
        sys.exit(1)

    if args.stats or args.kappa:
        show_stats(GOLD_STORAGE)
        return

    print("=" * 60)
    print("🔬 Gold Set 自动标注 — 从记忆库分层采样")
    print("=" * 60)

    seeded = seed_gold_set(str(DB_PATH), GOLD_STORAGE)
    total = sum(seeded.values())
    print(f"\n✅ Gold Set 构建完成，共 {total} 条:")
    for q, n in seeded.items():
        print(f"  {q}: {n}")

    print("\n📊 统计:")
    show_stats(GOLD_STORAGE)


if __name__ == "__main__":
    main()
