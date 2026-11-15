#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intent_embedder_bridge.py — embedding 子进程桥接（云端 41 venv 无 st 时回退）

协议：stdin 收 {"texts": [...], "model": "BAAI/bge-small-zh-v1.5"|"sentence-transformers/all-MiniLM-L6-v2"}
      stdout 出 {"vectors": [[...], ...]}
FAIL-OPEN：任何异常输出 {"vectors": []}。

使用方式（由 embedder_bridge.py 自动调用，无需手动运行）：
    echo '{"texts": ["你好"], "model": "BAAI/bge-small-zh-v1.5"}' | python intent_embedder_bridge.py
"""

import json
import sys

# 9-RAG-INFRA 路径（云端 /home/luke/dreambuddy，本地自动定位）
try:
    from pathlib import Path

    _RAG_INFRA = str(Path(__file__).resolve().parents[2] / "2-KNOWLEDGE" / "9-RAG-INFRA")
except Exception:
    _RAG_INFRA = "/home/luke/dreambuddy/2-KNOWLEDGE/9-RAG-INFRA"


def main() -> None:
    try:
        req = json.loads(sys.stdin.read() or "{}")
        texts = req.get("texts", [])
        model = req.get("model", "BAAI/bge-small-zh-v1.5")
        if not texts:
            print(json.dumps({"vectors": []}))
            return

        sys.path.insert(0, _RAG_INFRA)
        from vector_store.embedder import Embedder

        embedder = Embedder(model)
        vecs = embedder.embed_batch(texts)
        out = [v.tolist() for v in vecs]
        print(json.dumps({"vectors": out}))
    except Exception as e:
        # FAIL-OPEN
        print(json.dumps({"vectors": [], "error": str(e)[:200]}))


if __name__ == "__main__":
    main()
