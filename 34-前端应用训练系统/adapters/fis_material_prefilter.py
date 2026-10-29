# -*- coding: utf-8 -*-
"""素材预筛通道 — 41 recall() 供给（C4，41 SPEC §13.3/§7.11）。
DSH 训练数据源采集器在素材量大时，先经 41 BM25 召回预筛相关文档片段，
降低全量扫描成本。FAIL-OPEN：41 不可用时返回空列表，采集器走原路径。
用法:
    from adapters.fis_material_prefilter import prefiler_material
    hits = prefiler_material("资金面 矛盾", limit=5)
"""
import json
import os
import subprocess
from typing import Any, Dict, List

_FIS_CLI = "/home/ubuntu/fis-p0/.venv/bin/python"
_FIS_SCRIPT = "/home/ubuntu/fis-p0/scripts/search_cli.py"


def prefiler_material(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """41 recall() 素材预筛：按 query 召回相关文档片段（path/snippet/score）。

    FAIL-OPEN：任何异常返回空列表，调用方降级原采集路径。
    """
    if not query:
        return []
    try:
        proc = subprocess.run(
            [_FIS_CLI, _FIS_SCRIPT],
            input=json.dumps({"cmd": "recall", "query": str(query), "limit": int(limit)}),
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "FIS_PG_PASSWORD": os.environ.get("FIS_PG_PASSWORD", "xWazSBSwFwXqZkNdZzKVpz7L9pJxCiE")},
        )
        res = json.loads(proc.stdout or "{}")
        if not res.get("success"):
            return []
        return [
            {
                "path": h.get("path"),
                "snippet": h.get("snippet", "")[:200],
                "score": h.get("score", 0.0),
                "type": h.get("type"),
            }
            for h in res.get("hits", [])
        ]
    except Exception:
        return []  # FAIL-OPEN


def search_evidence(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """41 search() Evidence 溯源（C6）：返回 path/line/score 作为 provenance。
    FAIL-OPEN：任何异常返回空列表。
    """
    if not query:
        return []
    try:
        proc = subprocess.run(
            [_FIS_CLI, _FIS_SCRIPT],
            input=json.dumps({"cmd": "search", "query": str(query), "limit": int(limit)}),
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "FIS_PG_PASSWORD": os.environ.get("FIS_PG_PASSWORD", "xWazSBSwFwXqZkNdZzKVpz7L9pJxCiE")},
        )
        res = json.loads(proc.stdout or "{}")
        if not res.get("success"):
            return []
        evidence = []
        for h in res.get("hits", []):
            src = h.get("source") or {}
            evidence.append({
                "path": src.get("path"),
                "line": src.get("line", 0),
                "score": h.get("score", 0.0),
            })
        return evidence
    except Exception:
        return []  # FAIL-OPEN
