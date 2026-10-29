#!/usr/bin/env python3
"""检索 CLI 桥接（E1，SPEC §13.5）。

供 Next.js /api/search spawn 调用（stdin JSON → stdout JSON）：
    echo '{"query": "部署", "limit": 20}' | .venv/bin/python scripts/search_cli.py

进程内直调 SearchAPI（豁免凭证，SPEC §5.5）；权限过滤由前端 API Route
按 NextAuth 会话另行执行（本脚本仅返回原始命中）。
"""
import json
import sys
from pathlib import Path

# 项目根加入 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.search_api import SearchAPI  # noqa: E402

FIS_ROOT = "/home/luke/dreambuddy"


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "invalid json"}))
        return 1

    cmd = str(req.get("cmd", "search"))
    limit = int(req.get("limit", 20))

    try:
        api = SearchAPI(root=FIS_ROOT)
        if cmd == "list_files":
            # A1：L1 元数据清单查询（供 SACG DocIndexView 消费）
            result = api.list_files(
                root=req.get("root"),
                type=req.get("type"),
                category=req.get("category"),
                limit=int(req.get("limit", 500)),
            )
            print(json.dumps({"success": True, **result}, ensure_ascii=False))
            return 0

        if cmd == "update":
            # D5（SPEC §13.4）：增量更新触发——记忆落盘后向量化触发器调用
            stats = api.update()
            print(json.dumps({"success": True, **stats}, ensure_ascii=False))
            return 0
        if cmd == "changed":
            # D3（SPEC §13.4）：变更检测统一供给——mtime 比对返回变更文件清单，供 RAG-INFRA 消费
            paths = api.l2._detect_changed_paths()
            print(json.dumps({"success": True, "changed": paths, "count": len(paths)}, ensure_ascii=False))
            return 0
        if cmd == "status":
            # A5（SPEC §13.1）：索引健康度 + reconcile_diff，供记忆管理页新鲜度展示
            result = api.status()
            print(json.dumps({"success": True, **result}, ensure_ascii=False))
            return 0
        if cmd == "recall":
            # A4（SPEC §13.1/§7.6）：BM25 式候选召回，chunk 级，供 case-retriever 精排池补充注入
            query = str(req.get("query", "")).strip()
            if not query:
                print(json.dumps({"success": True, "hits": [], "total": 0}, ensure_ascii=False))
                return 0
            hits = api.recall(query, topK=int(req.get("limit", 50)))
            print(json.dumps({"success": True, "hits": hits, "total": len(hits)}, ensure_ascii=False))
            return 0
        query = str(req.get("query", "")).strip()
        filters = req.get("filters") or None
        if not query:
            print(json.dumps({"success": True, "hits": [], "total": 0, "took_ms": 0}))
            return 0
        # D1（SPEC §5 P5）：CLI search 即混合检索入口——开启 L3 向量通道
        import os
        os.environ["FIS_L3_VECTOR"] = "1"
        result = api.search(query, filters=filters, limit=limit)
        print(json.dumps({"success": True, **result}, ensure_ascii=False))
        return 0
    except Exception as e:  # FAIL-OPEN：桥接失败由调用方降级
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
