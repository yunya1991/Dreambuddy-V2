"""Memory Health Audit — 记忆健康度审计工具。

定期扫描认知记忆库，检测重复记忆、过时记忆、矛盾记忆，
生成 JSON 审计报告供人工审核。

工程约束：HC-1a（独立模块）/ FAIL-OPEN / 不自动修改
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BAYESIAN_PATH = _REPO_ROOT / "4-MEMORY" / "2-交易记忆单元" / "bayesian_memories.json"

# 审计阈值
_DUPLICATE_SIMILARITY = 0.85
_STALE_CONFIDENCE = 0.3
_STALE_VERIFY_MIN = 5
_CONFLICT_CONFIDENCE_DIFF = 0.5
_IMPROVEMENT_LOW = 0.3
_IMPROVEMENT_HIGH = 0.5
_IMPROVEMENT_VERIFY_MIN = 3  # FR-A1: 可提升检测需 verify_count >= 3


def _load_memories() -> list[dict[str, Any]]:
    try:
        if not _BAYESIAN_PATH.exists():
            return []
        data = json.loads(_BAYESIAN_PATH.read_text(encoding="utf-8"))
        return data.get("memories", [])
    except Exception:
        return []


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z\u4e00-\u9fff]+", text.lower())
    return [t for t in tokens if len(t) >= 2]


def _build_tfidf_vectors(memories: list[dict[str, Any]]) -> list[dict[str, float]]:
    docs = [_tokenize(m.get("content", "")) for m in memories]
    n = len(docs)
    if n == 0:
        return []
    df: dict[str, int] = defaultdict(int)
    for doc in docs:
        for t in set(doc):
            df[t] += 1
    idf = {t: math.log((n + 1) / (d + 1)) + 1 for t, d in df.items()}
    vectors = []
    for doc in docs:
        counts: dict[str, int] = defaultdict(int)
        for t in doc:
            counts[t] += 1
        total = len(doc) or 1
        tf = {t: c / total for t, c in counts.items()}
        vectors.append({t: tf.get(t, 0) * idf.get(t, 0) for t in doc})
    return vectors


def _cosine_sim(a: dict[str, float], b: dict[str, float]) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _detect_duplicates(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检测重复记忆（相似度 >= 0.85）。"""
    if len(memories) < 2:
        return []
    vectors = _build_tfidf_vectors(memories)
    duplicates: list[dict[str, Any]] = []
    n = len(memories)
    visited = [False] * n
    for i in range(n):
        if visited[i]:
            continue
        group = [i]
        for j in range(i + 1, n):
            if visited[j]:
                continue
            if _cosine_sim(vectors[i], vectors[j]) >= _DUPLICATE_SIMILARITY:
                group.append(j)
        if len(group) > 1:
            for idx in group:
                visited[idx] = True
            duplicates.append({
                "group_size": len(group),
                "memory_ids": [memories[idx].get("memory_id", f"m-{idx}") for idx in group],
                "representative": memories[group[0]].get("content", "")[:150],
                "avg_confidence": round(
                    sum(memories[idx].get("confidence", 0) for idx in group) / len(group), 4
                ),
            })
    return duplicates


def _detect_stale(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检测过时记忆（confidence < 0.3 且 verify_count >= 5）。"""
    stale = []
    for m in memories:
        conf = m.get("confidence", 1.0)
        verify = m.get("verify_count", 0)
        if conf < _STALE_CONFIDENCE and verify >= _STALE_VERIFY_MIN:
            stale.append({
                "memory_id": m.get("memory_id", "unknown"),
                "confidence": conf,
                "verify_count": verify,
                "content": m.get("content", "")[:150],
            })
    return stale


def _detect_contradictions(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检测矛盾记忆（同 category 下 confidence 差异 > 0.5）。"""
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in memories:
        by_cat[m.get("category", "unknown")].append(m)

    contradictions = []
    for cat, mems in by_cat.items():
        if len(mems) < 2:
            continue
        sorted_mems = sorted(mems, key=lambda x: x.get("confidence", 0))
        low, high = sorted_mems[0], sorted_mems[-1]
        diff = high.get("confidence", 0) - low.get("confidence", 0)
        if diff > _CONFLICT_CONFIDENCE_DIFF:
            contradictions.append({
                "category": cat,
                "low_memory_id": low.get("memory_id"),
                "low_confidence": low.get("confidence"),
                "high_memory_id": high.get("memory_id"),
                "high_confidence": high.get("confidence"),
                "confidence_diff": round(diff, 4),
            })
    return contradictions


def _detect_improvements(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检测可优化记忆（confidence 0.3-0.5 且 verify_count >= 3）。"""
    improvements = []
    for m in memories:
        conf = m.get("confidence", 0)
        verify = m.get("verify_count", 0)
        if _IMPROVEMENT_LOW <= conf < _IMPROVEMENT_HIGH and verify >= _IMPROVEMENT_VERIFY_MIN:
            improvements.append({
                "memory_id": m.get("memory_id", "unknown"),
                "confidence": conf,
                "verify_count": verify,
                "content": m.get("content", "")[:150],
            })
    return improvements


def run_health_audit() -> dict[str, Any]:
    """执行记忆健康度审计，返回 JSON 报告。不自动修改记忆。"""
    try:
        memories = _load_memories()
        timestamp = datetime.now(timezone.utc).isoformat()

        duplicates = _detect_duplicates(memories)
        stale = _detect_stale(memories)
        contradictions = _detect_contradictions(memories)
        improvements = _detect_improvements(memories)

        total_issues = len(duplicates) + len(stale) + len(contradictions)
        health_score = max(0, 100 - (len(duplicates) * 2 + len(stale) * 3 + len(contradictions) * 5))

        return {
            "status": "ok",
            "timestamp": timestamp,
            "total_memories": len(memories),
            "health_score": health_score,
            "issues": {
                "duplicates": duplicates,
                "stale": stale,
                "contradictions": contradictions,
                "improvement_opportunities": improvements,
            },
            "summary": {
                "duplicate_groups": len(duplicates),
                "stale_memories": len(stale),
                "contradiction_groups": len(contradictions),
                "improvement_opportunities": len(improvements),
                "total_issues": total_issues,
            },
            "note": "审计报告仅供参考，不自动修改记忆，需人工审核后处理",
        }
    except Exception as e:
        return {
            "status": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "total_memories": 0,
            "health_score": 0,
            "issues": {},
            "summary": {},
        }


# FR-A1: spec 要求的函数名别名
audit_memory_health = run_health_audit


def main(argv: list[str] | None = None) -> int:
    result = run_health_audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
