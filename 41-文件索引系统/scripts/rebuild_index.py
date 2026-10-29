#!/usr/bin/env python3
"""
rebuild_index.py — 全量重建入口
================================
SPEC-41-文件索引系统 v0.6 §3/§5.2
用法: .venv/bin/python scripts/rebuild_index.py [--root PATH]
行为: L1 元数据 + L2 内容索引全量重建（事务内，失败自动回滚）
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# 支持从项目根目录直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.search_api import SearchAPI  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="41-文件索引系统全量重建")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="索引根目录")
    args = parser.parse_args()
    api = SearchAPI(root=args.root)
    stats = api.rebuild()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
