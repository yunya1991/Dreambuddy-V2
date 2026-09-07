# -*- coding: utf-8 -*-
"""RAG 生成层（阶段3）：组装检索上下文为结构化 prompt，供上层 LLM 调用。

设计原则：
- 不直接调用 LLM（环境不确定），返回组装好的 prompt 字符串与引用信息；
- 置信度基于检索结果平均得分计算；
- 检索结果为空时返回明确的"未找到"提示。
"""

from typing import Dict, List

# 空检索结果提示
EMPTY_ANSWER = "知识库中未找到相关信息"


def generate(query: str, retrieved_chunks: List[Dict]) -> Dict:
    """将检索结果组装为结构化 RAG prompt。

    Args:
        query: 用户查询文本。
        retrieved_chunks: 检索结果列表（来自 hybrid_search 或其他检索器），
                          每项应含 content / source_file / heading / score
                          及可选的 final_score。

    Returns:
        dict 含以下字段：
        - answer_prompt: 组装好的 prompt 字符串（供上层 LLM 调用）
        - citations: 引用列表，每项含 index / source_file / heading / score
        - confidence: 置信度（0~1），基于检索结果平均得分
        - raw_chunks: 原始检索结果
    """
    # 空检索结果 → 直接返回未找到提示
    if not retrieved_chunks:
        return {
            "answer_prompt": EMPTY_ANSWER,
            "citations": [],
            "confidence": 0.0,
            "raw_chunks": [],
        }

    # 组装检索上下文与引用列表
    context_parts: List[str] = []
    citations: List[Dict] = []

    for i, chunk in enumerate(retrieved_chunks):
        idx = i + 1
        content = chunk.get("content", "")
        source = chunk.get("source_file", "")
        heading = chunk.get("heading", "")
        score = chunk.get("final_score", chunk.get("score", 0))

        context_parts.append(
            f"[{idx}] 来源: {source} | 标题: {heading} | 相关度: {score}\n{content}"
        )
        citations.append({
            "index": idx,
            "source_file": source,
            "heading": heading,
            "score": score,
        })

    context = "\n\n".join(context_parts)

    # 组装 prompt
    answer_prompt = (
        f"请基于以下知识库检索结果回答问题。"
        f"如果检索结果不足以回答，请说明。\n\n"
        f"问题: {query}\n\n"
        f"检索结果:\n{context}\n\n"
        f"请基于上述检索结果回答问题，并在回答中引用对应的来源编号"
        f"（如 [1]、[2]）。"
    )

    # 置信度：检索结果平均得分
    scores = [
        c.get("final_score", c.get("score", 0))
        for c in retrieved_chunks
    ]
    try:
        confidence = round(sum(scores) / len(scores), 4)
    except (TypeError, ZeroDivisionError):
        confidence = 0.0

    return {
        "answer_prompt": answer_prompt,
        "citations": citations,
        "confidence": confidence,
        "raw_chunks": retrieved_chunks,
    }
