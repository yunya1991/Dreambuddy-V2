#!/usr/bin/env python3
"""vector_bridge.py — L3 向量检索桥接（D1，SPEC-41 §5 P5）
==========================================================
以 luke 用户 + venv-trading 执行（chromadb 仅安装于该 venv）。
协议：stdin 收 {"query": ..., "top_k": ...}，stdout 出 JSON 数组
      [{"source_file", "score", "snippet", "heading"}]
FAIL-OPEN：任何异常输出 []（调用方降级为纯 BM25）。
"""
import json
import sys

RAG_INFRA = "/home/luke/dreambuddy/2-KNOWLEDGE/9-RAG-INFRA"


def main() -> None:
    try:
        req = json.loads(sys.stdin.read() or "{}")
        query = str(req.get("query", "")).strip()
        top_k = max(1, min(int(req.get("top_k", 5)), 50))
        if not query:
            print("[]")
            return
        sys.path.insert(0, RAG_INFRA)
        from vector_store.search import search
        results = search(query, top_k=top_k) or []
        out = []
        for r in results:
            out.append({
                "source_file": str(r.get("source_file") or "").strip("/"),
                "score": float(r.get("score") or 0.0),
                "snippet": str(r.get("content") or "")[:200],
                "heading": str(r.get("heading") or ""),
            })
        print(json.dumps(out, ensure_ascii=False))
    except Exception:
        print("[]")


if __name__ == "__main__":
    main()
