#!/usr/bin/env python3
"""fis_vector_supplement.py — 41 L3 向量通道补充适配器（D1 集成，§13.6）
=====================================================================
为 c_drive_v3_router Step 1（recall + 匹配评估）补充语义候选：
BM25 召回可能漏掉语义近邻案例，向量通道（ChromaDB 常驻桥接）补充，
提升 case_density 估计的召回率与 match_score 的准确性，
间接提升 jev 裁决质量（believability = density × match 对召回数量敏感）。

直连常驻桥接 socket（/tmp/fis_vector_bridge.sock，~12ms），
避免 CLI spawn 的 ~1.3s 热路径开销。

FAIL-OPEN：任何异常返回空列表（决策链路退化为纯 BM25 召回）。

用法::
    from adapters.fis_vector_supplement import vector_supplement
    extra = vector_supplement(context="node:x dir:LONG", top_k=5)
    # → [{"score": 0.38, "path": "...", "snippet": "...", "heading": "..."}]
"""
from __future__ import annotations

import json
import socket
from typing import Any, Dict, List

_DAEMON_SOCK = "/tmp/fis_vector_bridge.sock"
_TIMEOUT = 2.0  # 秒（超时视为向量通道不可用，FAIL-OPEN）


def vector_supplement(context: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """向量通道补充语义候选（FAIL-OPEN，异常返回空列表）。

    Args:
        context: 检索上下文（如 "node:x dir:LONG hint:..."）
        top_k: 补充候选数量上限

    Returns:
        候选列表，每项含 score 键（与 evaluate_match 兼容）
    """
    query = str(context or "").strip()
    if not query:
        return []
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(_TIMEOUT)
        s.connect(_DAEMON_SOCK)
        s.sendall(json.dumps({"query": query, "top_k": max(1, min(int(top_k), 20))}).encode("utf-8") + b"\n")
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        line = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
        if not line:
            return []
        resp = json.loads(line)
        if not resp.get("ok"):
            return []
        items = resp.get("results")
        if not isinstance(items, list):
            return []
        out: List[Dict[str, Any]] = []
        for it in items:
            score = float(it.get("score") or 0.0)
            out.append({
                "score": round(min(score, 1.0), 4),
                "path": str(it.get("source_file") or ""),
                "snippet": str(it.get("snippet") or "")[:120],
                "heading": str(it.get("heading") or ""),
                "source_tag": "fis_vector_supplement",
            })
        return out
    except Exception:
        return []  # FAIL-OPEN


if __name__ == "__main__":
    # 自测：python adapters/fis_vector_supplement.py
    result = vector_supplement("部署 文档", top_k=3)
    print("SELF_TEST_N=" + str(len(result)))
    for r in result:
        print(str(r["score"]) + " " + r["path"])
