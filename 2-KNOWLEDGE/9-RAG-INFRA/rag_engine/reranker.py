# -*- coding: utf-8 -*-
"""多信号重排序（阶段3）：对混合检索结果按多维信号加权排序。

重排序信号（默认权重）：
- 向量相似度 0.35：来自向量检索的 cosine 相似度
- 图谱关联度 0.25：来自图谱检索的邻域关联得分
- BM25 得分   0.20：来自关键词检索的 BM25 得分
- 域匹配度     0.10：结果域信息与查询的匹配程度
- 文档新鲜度   0.10：文档时间新鲜度（当前无时间戳数据，返回中性值）

各路检索得分跨结果做 min-max 归一化到 [0, 1] 后加权求和。
"""

from typing import Dict, List, Optional

# 默认重排序信号权重
DEFAULT_RERANK_WEIGHTS = {
    "vector": 0.35,
    "graph": 0.25,
    "bm25": 0.20,
    "domain": 0.10,
    "freshness": 0.10,
}


def _normalize_signal(results: List[Dict], key: str) -> Dict[int, float]:
    """对指定信号跨结果做 min-max 归一化。

    仅对拥有该信号的结果参与归一化。若无有效值返回空字典。
    """
    raw: Dict[int, float] = {}
    for i, r in enumerate(results):
        v = r.get(key)
        if v is not None:
            try:
                raw[i] = float(v)
            except (TypeError, ValueError):
                pass

    if not raw:
        return {}

    lo = min(raw.values())
    hi = max(raw.values())
    if hi - lo < 1e-9:
        return {i: 1.0 for i in raw}

    return {i: (v - lo) / (hi - lo) for i, v in raw.items()}


def _domain_match(query: str, result: Dict) -> float:
    """域匹配度：结果有明确域信息得 1.0，root 或空域得 0.5。"""
    domain = result.get("domain", "")
    if domain and domain != "root":
        return 1.0
    return 0.5


def _freshness(result: Dict) -> float:
    """文档新鲜度：当前无时间戳数据，返回中性值 1.0。

    后续可接入文件修改时间或内容中的日期信息。
    """
    return 1.0


def rerank(query: str, results: List[Dict],
           weights: Optional[Dict] = None) -> List[Dict]:
    """对检索结果做多信号加权重排序。

    Args:
        query: 原始查询文本。
        results: 检索结果列表，每项应含 content / source_file / domain /
                 heading / score，以及可选的 vector_score / graph_score /
                 keyword_score（由混合检索合并时填充）。
        weights: 信号权重覆盖，默认 DEFAULT_RERANK_WEIGHTS。

    Returns:
        排序后的结果列表（降序），每项附带 final_score 与 rerank_signals。
    """
    if not results:
        return []

    w = dict(DEFAULT_RERANK_WEIGHTS)
    if weights:
        w.update(weights)

    # 各路信号归一化
    vec_norm = _normalize_signal(results, "vector_score")
    graph_norm = _normalize_signal(results, "graph_score")
    bm25_norm = _normalize_signal(results, "keyword_score")

    for i, r in enumerate(results):
        signals = {
            "vector": vec_norm.get(i, 0.0),
            "graph": graph_norm.get(i, 0.0),
            "bm25": bm25_norm.get(i, 0.0),
            "domain": _domain_match(query, r),
            "freshness": _freshness(r),
        }
        final_score = sum(signals[k] * w.get(k, 0.0) for k in signals)
        r["final_score"] = round(final_score, 4)
        r["rerank_signals"] = {k: round(v, 4) for k, v in signals.items()}

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results
