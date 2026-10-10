"""quality.py — 辩论质量评估器

SPEC 9.2-9.4 五维评估体系：
- 规则分（40%）：金句密度 + 观点多样性
- LLM 分（60%）：冲突强度 + 话题升华度 + 文案可转化度
- 综合分 = rule×0.4 + llm×0.6 → S/A/B/C 分级
"""
from __future__ import annotations

import json
import logging

from core.agents import LLMClient, _extract_json
from core.models import (
    Argument, Turn, MarketingMaterial, DebateQualityScore,
)

logger = logging.getLogger("debate.quality")

_QUALITY_SYSTEM_PROMPT = """你是辩论质量评估专家。请从以下三个维度评估辩论质量（0-10分）：
1. 冲突强度：双方是否真正在对抗，是否针对对方论点反驳
2. 话题升华度：是否从表层争论上升到深度洞察
3. 文案可转化度：产出的短文案是否有传播吸引力

同时提供：
- highlights: 质量亮点（列表）
- suggestions: 改进建议（列表，低分时给出）

输出 JSON: {"conflict_intensity": 0-10, "topic_elevation": 0-10, "copy_convertibility": 0-10, "highlights": ["..."], "suggestions": ["..."]}
只输出 JSON。
"""


def _calc_quote_density(transcript: list[Turn],
                        material: MarketingMaterial) -> float:
    """金句密度：金句数 / 总字数 × 1000（千字含金句数）。

    归一化到 0-10：千字含 5 句金句 = 满分 10。
    """
    total_chars = 0
    for turn in transcript:
        if isinstance(turn.content, Argument):
            total_chars += len(turn.content.thesis)
            total_chars += sum(len(a) for a in turn.content.arguments)
            total_chars += len(turn.content.quote)
        elif isinstance(turn.content, str):
            total_chars += len(turn.content)

    if total_chars == 0:
        return 0.0

    quote_count = len(material.quotes)
    density = quote_count / total_chars * 1000  # 千字含金句数
    # 5 句/千字 = 满分
    return min(density / 5.0 * 10.0, 10.0)


def _calc_diversity(transcript: list[Turn]) -> float:
    """观点多样性：去重后论点数 / 总论点数。

    重复率低 = 多样性高。归一化到 0-10。
    """
    all_args: list[str] = []
    for turn in transcript:
        if isinstance(turn.content, Argument):
            all_args.extend(turn.content.arguments)

    if not all_args:
        return 0.0

    unique_count = len(set(all_args))
    total_count = len(all_args)
    diversity_ratio = unique_count / total_count
    return diversity_ratio * 10.0


def _calc_balance(transcript: list[Turn]) -> float:
    """立场均衡度 = 1 - |bull_avg_confidence - bear_avg_confidence|。

    辅助信号（不纳入综合分），用于标记是否一边倒。
    """
    bull_confs = [t.content.confidence for t in transcript
                  if t.speaker == "bull" and isinstance(t.content, Argument)]
    bear_confs = [t.content.confidence for t in transcript
                  if t.speaker == "bear" and isinstance(t.content, Argument)]

    if not bull_confs or not bear_confs:
        return 1.0

    bull_avg = sum(bull_confs) / len(bull_confs)
    bear_avg = sum(bear_confs) / len(bear_confs)
    return 1.0 - abs(bull_avg - bear_avg)


class QualityEvaluator:
    """辩论质量评估器。"""

    def __init__(self, llm_client: LLMClient | None = None,
                 max_tokens: int = 500):
        self.llm = llm_client
        self.max_tokens = max_tokens

    async def evaluate(
        self, topic: str, transcript: list[Turn],
        material: MarketingMaterial,
    ) -> DebateQualityScore:
        """评估辩论质量。"""
        # 规则分
        quote_density = _calc_quote_density(transcript, material)
        diversity = _calc_diversity(transcript)
        rule_score = quote_density * 0.5 + diversity * 0.5

        # LLM 分
        llm_result = await self._llm_evaluate(topic, transcript, material)
        conflict = llm_result.get("conflict_intensity", 5.0)
        elevation = llm_result.get("topic_elevation", 5.0)
        convertibility = llm_result.get("copy_convertibility", 5.0)
        highlights = llm_result.get("highlights", [])
        suggestions = llm_result.get("suggestions", [])

        llm_score = conflict * 0.3 + elevation * 0.35 + convertibility * 0.35

        # 综合分
        overall = rule_score * 0.4 + llm_score * 0.6
        grade = DebateQualityScore.grade_from_score(overall)

        # 补充规则层面的 highlights
        if quote_density >= 5.0 and "金句密度高" not in highlights:
            highlights.append("金句密度高")
        if diversity >= 8.0 and "论点多样" not in highlights:
            highlights.append("论点多样")

        balance = _calc_balance(transcript)
        if balance < 0.6:
            suggestions.append("立场失衡，建议调整弱势方 prompt 强度")

        return DebateQualityScore(
            overall=round(overall, 2),
            grade=grade,
            dimensions={
                "金句密度": round(quote_density, 2),
                "观点多样性": round(diversity, 2),
                "冲突强度": round(conflict, 2),
                "话题升华度": round(elevation, 2),
                "文案可转化度": round(convertibility, 2),
                "立场均衡度": round(balance, 2),
            },
            rule_score=round(rule_score, 2),
            llm_score=round(llm_score, 2),
            highlights=highlights,
            suggestions=suggestions,
        )

    async def _llm_evaluate(
        self, topic: str, transcript: list[Turn],
        material: MarketingMaterial,
    ) -> dict:
        """调用 LLM 评估三个维度，失败时 fallback。"""
        if self.llm is None:
            return self._fallback_llm_result()

        debate_summary = "\n".join(
            f"{'正方' if t.speaker == 'bull' else '反方'}：{t.content.thesis}"
            f"（论据：{', '.join(t.content.arguments[:2]) if isinstance(t.content, Argument) else ''}）"
            for t in transcript
            if isinstance(t.content, Argument)
        )
        copy_summary = "；".join(material.short_copy[:3]) if material.short_copy else "无"

        user_prompt = (
            f"辩论话题：{topic}\n\n"
            f"辩论记录：\n{debate_summary}\n\n"
            f"营销短文案：{copy_summary}\n\n"
            f"金句：{', '.join(material.quotes)}\n"
        )

        try:
            raw = await self.llm.chat(
                _QUALITY_SYSTEM_PROMPT, user_prompt, self.max_tokens,
            )
        except Exception as e:
            logger.warning("质量评估 LLM 调用异常: %s", e)
            return self._fallback_llm_result()

        data = _extract_json(raw)
        if data is None:
            logger.warning("质量评估 JSON 解析失败，使用 fallback")
            return self._fallback_llm_result()

        return {
            "conflict_intensity": float(data.get("conflict_intensity", 5.0)),
            "topic_elevation": float(data.get("topic_elevation", 5.0)),
            "copy_convertibility": float(data.get("copy_convertibility", 5.0)),
            "highlights": list(data.get("highlights", [])),
            "suggestions": list(data.get("suggestions", [])),
        }

    def _fallback_llm_result(self) -> dict:
        """无 LLM 或失败时的默认评分。"""
        return {
            "conflict_intensity": 5.0,
            "topic_elevation": 5.0,
            "copy_convertibility": 5.0,
            "highlights": [],
            "suggestions": ["LLM 评估不可用，使用默认分"],
        }
