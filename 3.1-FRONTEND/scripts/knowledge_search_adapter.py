#!/usr/bin/env python3
"""
知识库检索 HTTP Adapter — 单次请求模式调用 9-RAG-INFRA 的只读检索接口。

用法:
  python3 knowledge_search_adapter.py search '{"query":"BTC 资金费率", "top_k":5, "method":"hybrid"}'

method:
  - fts:     BM25 全文检索 (Whoosh)
  - vector:  语义向量检索 (ChromaDB)
  - hybrid:  三路混合检索 (vector + graph + keyword) ← 默认

stdout: 单行 JSON {"ok":true,"data":{"results":[...],"method":"hybrid","degraded":false}}
       或 {"ok":false,"error":"...","degraded":true}
stderr: import 噪音 + 错误日志

设计:
  - 复刻 skill_index_adapter.py stdout→stderr 重定向模式
  - 只读不改: 仅调用 keyword_search / hybrid_search / vector search
  - FAIL-OPEN: 异常返回 degraded, 不崩溃
  - 所有后端依赖 (Whoosh/ChromaDB) 不可用时自动降级为空结果
"""
import sys
import os
import json
import traceback


def _resolve_rag_infra_dir():
    """解析 2-KNOWLEDGE/9-RAG-INFRA 绝对路径。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate1 = os.path.normpath(os.path.join(
        script_dir, '..', '2-KNOWLEDGE', '9-RAG-INFRA'
    ))
    if os.path.exists(candidate1):
        return candidate1
    candidate2 = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/9-RAG-INFRA'
    if os.path.exists(candidate2):
        return candidate2
    return candidate1


def _safe_print(payload):
    """唯一向 stdout 输出的入口，确保单行 JSON。"""
    sys.stdout = sys.__stdout__
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    if len(sys.argv) < 2:
        _safe_print({"ok": False, "error": "missing command argument"})
        return

    command = sys.argv[1]
    args_raw = sys.argv[2] if len(sys.argv) > 2 else '{}'
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError as e:
        _safe_print({"ok": False, "error": f"invalid args JSON: {e}"})
        return

    # === 关键: import 和 handler 执行期间把 stdout 重定向到 stderr ===
    sys.stdout = sys.stderr

    try:
        rag_dir = _resolve_rag_infra_dir()
        if rag_dir not in sys.path:
            sys.path.insert(0, rag_dir)

        # 尝试导入各检索模块，各自独立 FAIL-OPEN
        _keyword_search = None
        _hybrid_search = None
        _vector_search = None

        try:
            from rag_engine.keyword_search import keyword_search
            _keyword_search = keyword_search
        except Exception:
            pass

        try:
            from rag_engine.hybrid_retriever import hybrid_search
            _hybrid_search = hybrid_search
        except Exception:
            pass

        try:
            from vector_store.search import search as vs_search
            _vector_search = vs_search
        except Exception:
            pass

    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"import_failed: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })
        return

    try:
        if command == "search":
            query = args.get("query", "")
            top_k = int(args.get("top_k", 5))
            method = args.get("method", "hybrid")

            if not query:
                _safe_print({"ok": True, "data": {
                    "results": [], "method": method, "degraded": False
                }})
                return

            results = []
            degraded = False

            if method == "fts":
                if _keyword_search is not None:
                    raw = _keyword_search(query, top_k=top_k)
                    results = _format_results(raw, "fts")
                else:
                    degraded = True

            elif method == "vector":
                if _vector_search is not None:
                    raw = _vector_search(query, top_k=top_k)
                    results = _format_results(raw, "vector")
                else:
                    degraded = True

            else:  # hybrid (default)
                if _hybrid_search is not None:
                    raw = _hybrid_search(query, top_k=top_k)
                    results = _format_results(raw, "hybrid")
                elif _keyword_search is not None:
                    # 降级: hybrid 不可用 → 用 keyword
                    raw = _keyword_search(query, top_k=top_k)
                    results = _format_results(raw, "fts")
                    degraded = True
                else:
                    degraded = True

            _safe_print({"ok": True, "data": {
                "results": results[:top_k],
                "method": method,
                "degraded": degraded,
            }})

        else:
            _safe_print({"ok": False, "error": f"unknown command: {command}"})

    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"handler_failed: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })


def _format_results(raw_results, method):
    """统一格式化检索结果为 SPEC 响应格式。"""
    formatted = []
    for r in raw_results:
        item = {
            "content": r.get("content", ""),
            "score": round(float(r.get("score", r.get("final_score", 0))), 4),
            "source": r.get("source_file", r.get("source", "")),
            "heading": r.get("heading", ""),
            "domain": r.get("domain", ""),
        }
        # chunk_id 用于引用追踪
        if r.get("source_file"):
            item["chunk_id"] = f"{r['source_file']}#{r.get('heading', '')}"
        formatted.append(item)
    return formatted


if __name__ == "__main__":
    main()
