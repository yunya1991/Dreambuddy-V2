#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IndexQueryService 适配器 — 供 TypeScript 子进程调用。

用法:
  python3 index_query_adapter.py query "查询文本" --top-k 5
  python3 index_query_adapter.py count

输出 JSON 到 stdout，失败输出 {"degraded": true, "results": []}
"""
import sys
import json
from pathlib import Path

# 确保能找到 index_query_service
_RAG_DIR = Path(__file__).resolve().parent.parent / "2-KNOWLEDGE" / "9-RAG-INFRA"
sys.path.insert(0, str(_RAG_DIR))

try:
    from index_query_service import IndexQueryService
    _svc = IndexQueryService()
    _available = True
except Exception as e:
    _available = False
    _error = str(e)


def main():
    if not _available:
        print(json.dumps({"degraded": True, "error": _error, "results": []}))
        return

    if len(sys.argv) < 2:
        print(json.dumps({"degraded": True, "error": "no command", "results": []}))
        return

    cmd = sys.argv[1]

    if cmd == "query":
        if len(sys.argv) < 3:
            print(json.dumps({"degraded": True, "error": "no query text", "results": []}))
            return
        query_text = sys.argv[2]
        top_k = 5
        threshold = 0.3
        category = None

        # 解析可选参数
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--top-k" and i + 1 < len(sys.argv):
                top_k = int(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == "--threshold" and i + 1 < len(sys.argv):
                threshold = float(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == "--category" and i + 1 < len(sys.argv):
                category = sys.argv[i + 1].split(",")
                i += 2
            else:
                i += 1

        results = _svc.query(query_text, top_k=top_k, score_threshold=threshold,
                             category_filter=category)
        print(json.dumps({"degraded": False, "results": results}, ensure_ascii=False))

    elif cmd == "count":
        n = _svc.count()
        print(json.dumps({"degraded": False, "count": n}))

    else:
        print(json.dumps({"degraded": True, "error": f"unknown cmd: {cmd}", "results": []}))


if __name__ == "__main__":
    main()
