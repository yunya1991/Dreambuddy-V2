"""
ftc_similarity — FTC 与知识锚点的相似度计算器

两层相似度:
  层1 结构化匹配 (0.5 权重):
    - 步骤类型序列模式匹配 (如 condition→inference→condition→action)
    - 数据依赖图同构性 (简化为: 依赖边数比例)

  层2 语义匹配 (0.5 权重):
    - inference 步骤的 knowledge_ref 与锚点名称匹配
    - condition/action 的 gene_ref 与锚点关联基因匹配
    - 关键词匹配 (FTC 步骤描述/逻辑中的关键词 vs 锚点关键词)

相似度 ∈ [0, 1]
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional

from .ftc_schema import FTC, KnowledgeAlignment
from .knowledge_anchors import KnowledgeAnchor, get_all_anchors


def _structural_similarity(ftc: FTC, anchor: KnowledgeAnchor) -> float:
    """层1: 结构化匹配 — 步骤类型序列 + 依赖结构"""
    ftc_seq = [s.type for s in ftc.steps]
    anchor_seq = anchor.step_type_sequence

    if not ftc_seq or not anchor_seq:
        return 0.0

    # 步骤类型序列匹配 (用最长公共子序列比例)
    matcher = SequenceMatcher(None, ftc_seq, anchor_seq)
    seq_sim = matcher.ratio()

    # 依赖结构匹配: 比较依赖边数占比
    ftc_deps = sum(len(s.depends_on) for s in ftc.steps)
    ftc_total = len(ftc.steps)
    ftc_dep_ratio = ftc_deps / max(1, ftc_total)

    # 锚点没有依赖结构信息，用步骤数比例做粗略匹配
    anchor_total = len(anchor_seq)
    size_sim = min(len(ftc_seq), anchor_total) / max(len(ftc_seq), anchor_total)

    # 加权: 序列匹配 0.7, 大小匹配 0.3
    return seq_sim * 0.7 + size_sim * 0.3


def _semantic_similarity(ftc: FTC, anchor: KnowledgeAnchor) -> float:
    """层2: 语义匹配 — knowledge_ref + gene_ref + 关键词"""
    scores: list[float] = []

    # 2a. inference 的 knowledge_ref 与锚点名称匹配
    for step in ftc.inference_steps:
        if step.knowledge_ref:
            name_sim = SequenceMatcher(
                None, step.knowledge_ref.lower(), anchor.name.lower()
            ).ratio()
            scores.append(min(1.0, name_sim * 2))  # 放大，因为名称短

    # 2b. condition/action 的 gene_ref 与锚点关联基因匹配
    anchor_genes = {g.upper() for g in anchor.associated_genes}
    gene_matches = 0
    gene_total = 0
    for step in ftc.condition_steps + ftc.action_steps:
        if step.gene_ref:
            gene_total += 1
            if step.gene_ref.upper() in anchor_genes:
                gene_matches += 1
    if gene_total > 0:
        scores.append(gene_matches / gene_total)

    # 2c. 关键词匹配: FTC 所有步骤的 description/logic vs 锚点 keywords
    ftc_text = " ".join(
        (s.description or "") + " " + (s.logic or "")
        for s in ftc.steps
    ).lower()
    keyword_matches = 0
    for kw in anchor.keywords:
        if kw.lower() in ftc_text:
            keyword_matches += 1
    if anchor.keywords:
        scores.append(keyword_matches / len(anchor.keywords))

    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def compute_similarity(ftc: FTC, anchor: KnowledgeAnchor) -> float:
    """计算 FTC 与单个知识锚点的综合相似度"""
    struct = _structural_similarity(ftc, anchor)
    semantic = _semantic_similarity(ftc, anchor)
    # 两层各占 0.5 权重
    return round(struct * 0.5 + semantic * 0.5, 4)


def align_to_anchors(ftc: FTC, top_k: int = 3) -> list[KnowledgeAlignment]:
    """
    将 FTC 与所有知识锚点对齐，返回 top_k 个最相似的锚点
    """
    all_anchors = get_all_anchors()
    alignments: list[KnowledgeAlignment] = []

    for anchor in all_anchors:
        sim = compute_similarity(ftc, anchor)
        if sim > 0.05:  # 过滤极低相似度
            alignments.append(KnowledgeAlignment(
                theory=anchor.name,
                similarity=sim,
            ))

    # 按相似度降序
    alignments.sort(key=lambda a: a.similarity, reverse=True)
    return alignments[:top_k]


def get_track_by_similarity(similarity: float) -> str:
    """
    根据相似度返回轨道:
      >= 0.60 → exploit (利用)
      0.30 - 0.59 → mixed (混合)
      0.15 - 0.29 → explore (探索)
      < 0.15 → discard (丢弃)
    """
    if similarity >= 0.60:
        return "exploit"
    elif similarity >= 0.30:
        return "mixed"
    elif similarity >= 0.15:
        return "explore"
    else:
        return "discard"
