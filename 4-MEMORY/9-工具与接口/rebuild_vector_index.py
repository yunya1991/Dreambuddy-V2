#!/usr/bin/env python3
"""重建 sqlite-vec 语义向量索引（fastembed ONNX 模型）。

用途：历史 memories 的 vector 列/vec_memories 表是 256 维哈希向量且覆盖不全
（312k 记忆仅约 5k 有条目）。本脚本用真实 embedding 模型重算全量向量，
同时更新 memories.vector（numpy 回退一致性）与 vec_memories（sqlite-vec 引擎）。

用法：
  python3 rebuild_vector_index.py --db 4-MEMORY/data/cognitive_memory.db \
      --model BAAI/bge-small-zh-v1.5 --batch-size 128
  # 冒烟（只处理 32 条，不替换生产表）：
  python3 rebuild_vector_index.py --limit 32
  # 冒烟并替换（仅用于副本库验证）：
  python3 rebuild_vector_index.py --limit 32 --swap

安全：
  - 默认写入 vec_memories_rebuild 临时表，全量完成后原子换名替换 vec_memories
  - --limit 未指定时才自动替换；--limit 场景需显式 --swap
  - 中途失败不影响线上 vec_memories（旧表保留）
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sqlite_vec  # noqa: E402
from vector_memory_interface import FastEmbedVectorizer  # noqa: E402

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "cognitive_memory.db"
TMP_TABLE = "vec_stage"


def rowid_of(memory_id: str) -> int:
    """与 VectorMemoryInterface._get_rowid 保持一致。"""
    return int(hashlib.md5(memory_id.encode()).hexdigest()[:12], 16)


def to_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 条（冒烟）")
    ap.add_argument("--swap", action="store_true", help="替换生产 vec_memories")
    ap.add_argument(
        "--skip-metadata",
        action="store_true",
        help="不更新 memories.vector（仅建 vec 表）",
    )
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[FATAL] db not found: {db_path}")
        return 2

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)

    total = con.execute("select count(*) from memories").fetchone()[0]
    target = min(total, args.limit) if args.limit else total
    print(f"[INFO] db={db_path} memories={total} target={target} model={args.model}")

    t0 = time.perf_counter()
    vectorizer = FastEmbedVectorizer(args.model)
    dim = vectorizer.dim
    print(f"[INFO] model loaded in {time.perf_counter() - t0:.1f}s dim={dim}")

    con.execute(f"DROP TABLE IF EXISTS {TMP_TABLE}")
    # 普通表暂存：vec0 虚表不支持改名（shadow 表名不同步），故最后用 INSERT..SELECT 落正式表
    con.execute(
        f"CREATE TABLE {TMP_TABLE}("
        "rowid INTEGER PRIMARY KEY, embedding BLOB NOT NULL, "
        "memory_id TEXT NOT NULL, quality TEXT)"
    )

    processed = 0
    written = 0
    started = time.perf_counter()
    cur = con.execute(
        "select id, content, quality_level from memories where content is not null "
        "and length(content) > 0 order by rowid"
    )

    while True:
        fetch_n = args.batch_size
        if args.limit:
            fetch_n = min(fetch_n, target - processed)
            if fetch_n <= 0:
                break
        batch = cur.fetchmany(fetch_n)
        if not batch:
            break
        texts = [row[1] for row in batch]
        vectors = vectorizer.encode_batch(texts)
        for (mem_id, _content, quality), vec in zip(batch, vectors, strict=False):
            blob = to_bytes(vec)
            con.execute(
                f"INSERT OR REPLACE INTO {TMP_TABLE}(rowid, embedding, memory_id, quality) "
                "VALUES (?, ?, ?, ?)",
                (rowid_of(mem_id), blob, mem_id, quality or "C"),
            )
            if not args.skip_metadata:
                con.execute("UPDATE memories SET vector=? WHERE id=?", (blob, mem_id))
            written += 1
        con.commit()
        processed += len(batch)
        elapsed = time.perf_counter() - started
        speed = processed / elapsed if elapsed else 0
        eta = (target - processed) / speed / 60 if speed else 0
        print(
            f"[PROGRESS] {processed}/{target} ({processed / target * 100:.1f}%) "
            f"{speed:.0f}/s eta={eta:.1f}min",
            flush=True,
        )
        if args.limit and processed >= args.limit:
            break

    cur.close()
    con.commit()
    do_swap = args.swap or not args.limit
    if do_swap:
        con.execute("DROP TABLE IF EXISTS vec_memories")
        con.execute(
            "CREATE VIRTUAL TABLE vec_memories USING vec0("
            f"embedding float[{dim}], memory_id text, quality text)"
        )
        con.execute(
            "INSERT INTO vec_memories(rowid, embedding, memory_id, quality) "
            f"SELECT rowid, embedding, memory_id, quality FROM {TMP_TABLE}"
        )
        con.execute(f"DROP TABLE {TMP_TABLE}")
        con.commit()
        print(f"[DONE] swapped vec_memories rows={written} dim={dim}")
    else:
        print(f"[DONE] rebuilt temp table {TMP_TABLE} rows={written} dim={dim} (未替换)")

    print(f"[INFO] elapsed={(time.perf_counter() - started) / 60:.1f}min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
