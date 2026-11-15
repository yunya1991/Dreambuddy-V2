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
import re
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
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--threads", type=int, default=8, help="fastembed ONNX 线程数")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 条（冒烟）")
    ap.add_argument("--swap", action="store_true", help="替换生产 vec_memories")
    ap.add_argument(
        "--skip-metadata",
        action="store_true",
        help="不更新 memories.vector（仅建 vec 表）",
    )
    ap.add_argument(
        "--source",
        action="append",
        default=[],
        help="只重建指定 source 的记忆（可重复传入，与 --ids/--where 互斥）",
    )
    ap.add_argument(
        "--ids",
        default="",
        help="只重建指定 id（逗号分隔，与 --source/--where 互斥）",
    )
    ap.add_argument(
        "--where",
        default="",
        help="原始 SQL 条件（谨慎使用，与 --source/--ids 互斥）",
    )
    args = ap.parse_args()

    # 选择器互斥：同时给多个筛选条件语义不清（AND/OR 混用会误伤全表）
    selector_count = sum(
        1 for flag in (bool(args.source), bool(args.ids.strip()), bool(args.where.strip())) if flag
    )
    if selector_count > 1:
        print("[FATAL] --source / --ids / --where 三者互斥，只能选其一")
        return 2

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

    # 定向重建（--source / --ids / --where）：只处理子集，避免 3GB 库全量重算
    filters: list[str] = []
    filter_params: list = []
    if args.source:
        filters.append(f"source IN ({', '.join('?' * len(args.source))})")
        filter_params.extend(args.source)
    id_list = [i.strip() for i in args.ids.split(",") if i.strip()]
    if id_list:
        filters.append(f"id IN ({', '.join('?' * len(id_list))})")
        filter_params.extend(id_list)
    if args.where.strip():
        filters.append(f"({args.where.strip()})")
    where_sql = (" AND " + " AND ".join(filters)) if filters else ""
    filtered = bool(filters)

    scoped_total = total
    if filtered:
        scoped_total = con.execute(
            f"select count(*) from memories where 1=1{where_sql}", filter_params
        ).fetchone()[0]
        print(f"[INFO] 定向重建：条件={filters} 命中 {scoped_total}/{total} 条")
    target = min(scoped_total, args.limit) if args.limit else scoped_total
    print(f"[INFO] db={db_path} memories={total} target={target} model={args.model}")
    if target == 0:
        # 零匹配时直接退出：绝不允许用空 stage 表覆盖 vec_memories（会 recall 全盲）
        print("[INFO] 无匹配记忆，跳过重建")
        con.close()
        return 0

    t0 = time.perf_counter()
    vectorizer = FastEmbedVectorizer(args.model, threads=args.threads)
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
    # rowid 键集分页：若用长游标持续读取再穿插写入，读快照会被并发写入方（如云端
    # data_center_scheduler）失效，触发 SQLITE_BUSY_SNAPSHOT（表现为 database is locked，
    # busy_timeout 不重试）。每批独立 SELECT 可让读事务及时结束。
    last_rowid = 0

    while True:
        fetch_n = args.batch_size
        if args.limit:
            fetch_n = min(fetch_n, target - processed)
            if fetch_n <= 0:
                break
        rows = con.execute(
            "select rowid, id, content, quality_level from memories "
            "where rowid > ?" + where_sql + " order by rowid limit ?",
            [last_rowid, *filter_params, fetch_n],
        ).fetchall()
        if not rows:
            break
        last_rowid = rows[-1][0]
        batch = [row for row in rows if row[2]]
        if not batch:
            continue
        texts = [row[2] for row in batch]
        vectors = vectorizer.encode_batch(texts)
        for (_rowid, mem_id, _content, quality), vec in zip(batch, vectors, strict=False):
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
        processed += len(rows)
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

    con.commit()
    do_swap = args.swap or not args.limit
    if do_swap:
        # 切换段必须原子：DROP 成功但 INSERT 失败会导致 recall 全盲，故整体包在
        # BEGIN IMMEDIATE ... COMMIT 内，任何异常一律 ROLLBACK 保留旧索引。
        try:
            if con.in_transaction:
                con.commit()
            con.execute("BEGIN IMMEDIATE")
            if filtered:
                # 定向重建：只替换本次重建到的 id，禁止 DROP 整表（否则清空未覆盖的记忆）
                existing = con.execute(
                    "select sql from sqlite_master where name='vec_memories'"
                ).fetchone()
                if existing is None:
                    con.execute(
                        "CREATE VIRTUAL TABLE vec_memories USING vec0("
                        f"embedding float[{dim}], memory_id text, quality text)"
                    )
                else:
                    m = re.search(r"float\[(\d+)\]", str(existing[0] or ""))
                    if m and int(m.group(1)) != dim:
                        raise RuntimeError(
                            f"现有索引维度 {m.group(1)} 与本次模型维度 {dim} 不一致，"
                            "禁止定向替换（请先全量重建）"
                        )
                    con.execute(
                        f"DELETE FROM vec_memories WHERE rowid IN "
                        f"(SELECT rowid FROM {TMP_TABLE})"
                    )
                con.execute(
                    "INSERT INTO vec_memories(rowid, embedding, memory_id, quality) "
                    f"SELECT rowid, embedding, memory_id, quality FROM {TMP_TABLE}"
                )
            else:
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
            if not filtered:
                # 索引自描述：写 embed_model，使所有进程无需各自配置环境变量即可用同一模型
                con.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
                con.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES('embed_model', ?)", [args.model]
                )
                con.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES('embed_dim', ?)", [str(dim)]
                )
            con.commit()
        except Exception as exc:
            con.rollback()
            print(f"[FATAL] 索引切换失败，已回滚（vec_memories 保持原状）：{exc}")
            return 1
        print(f"[DONE] swapped vec_memories rows={written} dim={dim}")
    else:
        print(f"[DONE] rebuilt temp table {TMP_TABLE} rows={written} dim={dim} (未替换)")

    print(f"[INFO] elapsed={(time.perf_counter() - started) / 60:.1f}min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
