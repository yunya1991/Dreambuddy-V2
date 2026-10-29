#!/usr/bin/env python3
"""
reconcile_cron.py — 每小时定时对账入口
=======================================
SPEC-41-文件索引系统 v0.6 §2.3（v0.5 闭环 C4）
用法: .venv/bin/python scripts/reconcile_cron.py [--root PATH]
行为: 全量 mtime+hash 对账，修复惰性校验遗漏（重命名/删除），输出对账差异
部署: crontab 每小时执行（0 * * * *）
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.search_api import SearchAPI  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="41-文件索引系统定时对账")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="索引根目录")
    args = parser.parse_args()
    api = SearchAPI(root=args.root)
    # 对账 = 增量更新（mtime+hash 双重校验，修复重命名/删除遗漏）
    stats = api.update()
    status = api.status()
    report = {
        "reconcile": stats,
        "indexed_files": status["indexed_files"],
        "reconcile_diff": status["reconcile_diff"],
    }
    # B2（41 SPEC §13.2）：0 号文档维度对账联动——41 索引清单 vs 文件系统实际清单
    # 文档变更 → 41 自动重索引（上方 update）→ 0 号 INDEX.md 对账闭环（本维度差异供 0 号消费）
    try:
        doc_root = api.root / "0-系统文档管理"
        fs_docs = sorted(
            str(p.relative_to(api.root))
            for p in doc_root.rglob("*.md")
        ) if doc_root.is_dir() else []
        _files = api.list_files(root="0-系统文档管理", limit=10000)["files"]
        # 对账口径统一：仅对比 .md 文档（41 索引含 .py 等工具脚本，非文档同步范围）
        indexed_docs = sorted(
            (f["path"] if isinstance(f, dict) else str(f))
            for f in _files
            if (f["path"] if isinstance(f, dict) else str(f)).endswith(".md")
        )
        fs_set, idx_set = set(fs_docs), set(indexed_docs)
        report["doc_sync"] = {
            "fs_count": len(fs_docs),
            "indexed_count": len(indexed_docs),
            "missing_in_index": sorted(fs_set - idx_set),
            "stale_in_index": sorted(idx_set - fs_set),
            "in_sync": fs_set == idx_set,
        }
    except Exception as e:
        report["doc_sync"] = {"error": f"{type(e).__name__}: {e}"}
    # C2（41 SPEC §13.3/§7.11）：Wiki lint 对账联动——检测 wiki 页面变更（mtime 快照对比），
    # 变更时输出 lint 重跑提示（wiki 编译层交叉引用校验），供 lint-reports 消费
    try:
        snap_path = "/tmp/fis_wiki_snapshot.json"
        wiki_root = api.root / "2-KNOWLEDGE" / "wiki"
        current = {
            str(p.relative_to(api.root)): int(p.stat().st_mtime)
            for p in wiki_root.rglob("*.md")
        } if wiki_root.is_dir() else {}
        prev = {}
        try:
            prev = json.loads(open(snap_path, encoding="utf-8").read())
        except Exception:
            prev = {}
        changed = sorted(
            k for k, v in current.items() if prev.get(k) != v
        )
        report["wiki_lint_sync"] = {
            "wiki_pages": len(current),
            "changed": changed,
            "lint_rerun_suggested": bool(changed),
        }
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False)
    except Exception as e:
        report["wiki_lint_sync"] = {"error": f"{type(e).__name__}: {e}"}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
