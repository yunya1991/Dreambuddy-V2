"""marketing.py — MarketingExtractor 营销素材提取器

SPEC 3.4 差异化核心：将辩论转化为可传播的营销素材。
- 金句：双方 quote 字段
- 话题标签：topic 关键词提取
- 精华段落：Judge 综合 + 最强论点；无 Judge 时 fallback 拼接
- 短文案/标题：LLM 生成，失败 fallback
"""
from __future__ import annotations

import json
import logging
import re

from core.agents import LLMClient, _extract_json
from core.models import Argument, CrossExamination, Turn, Verdict, MarketingMaterial

logger = logging.getLogger("debate.marketing")

# 短文案/标题 LLM prompt
_MARKETING_SYSTEM_PROMPT = """你是营销文案专家。根据辩论内容生成可传播的短文案和标题。
规则：
1. 生成 3 条短文案（小红书/推特风格，有吸引力）
2. 生成 1 个辩论标题（吸引点击）
3. 输出 JSON: {"copies": ["文案1", "文案2", "文案3"], "title": "辩论标题"}
4. 只输出 JSON
"""


def _extract_quotes(transcript: list[Turn]) -> list[str]:
    """从 transcript 中提取双方金句。"""
    quotes = []
    for turn in transcript:
        if isinstance(turn.content, Argument) and turn.content.quote:
            quotes.append(turn.content.quote)
    return quotes


def _extract_hashtags(topic: str, transcript: list[Turn]) -> list[str]:
    """从 topic 和论点中提取话题标签。

    策略：从 topic 提取关键词 + 论点高频词，生成 #标签。
    """
    hashtags = set()

    # 从 topic 提取关键词
    # 中文按字符截取关键短语，英文按单词
    keywords = set()

    # 英文关键词（BTC, ETH 等大写词）
    for match in re.findall(r'[A-Za-z]{2,}', topic):
        if len(match) >= 2:
            keywords.add(match)

    # 中文关键词（简单分词：2-4字短语）
    # 去掉标点后按常见停用词分割
    cleaned = re.sub(r'[？?！!。，,、；;：:]', '', topic)
    # 提取 2-6 字的中文片段
    for match in re.findall(r'[\u4e00-\u9fff]{2,6}', cleaned):
        keywords.add(match)

    for kw in keywords:
        hashtags.add(f"#{kw}")

    # 从论点提取
    for turn in transcript:
        if isinstance(turn.content, Argument):
            for match in re.findall(r'[A-Za-z]{2,}', turn.content.thesis):
                hashtags.add(f"#{match}")

    # 限制数量，取前 5 个
    return list(hashtags)[:5]


def _build_highlight(transcript: list[Turn],
                     verdict: Verdict | None) -> str:
    """构建精华段落。

    有 Verdict：Judge 总结 + 双方最强论点。
    无 Verdict：双方最强论点直接拼接（fallback）。
    """
    parts = []

    if verdict and verdict.summary:
        parts.append(f"【裁判总结】{verdict.summary}")
        if verdict.topic_angle:
            parts.append(f"【话题升华】{verdict.topic_angle}")

    # 双方最强论点（按 confidence 排序取最高）
    bull_best = None
    bear_best = None
    for turn in transcript:
        if isinstance(turn.content, Argument):
            if turn.speaker == "bull" and (
                    bull_best is None
                    or turn.content.confidence > bull_best.confidence):
                bull_best = turn.content
            elif turn.speaker == "bear" and (
                    bear_best is None
                    or turn.content.confidence > bear_best.confidence):
                bear_best = turn.content

    if bull_best:
        parts.append(f"【正方核心观点】{bull_best.thesis}："
                     f"{'；'.join(bull_best.arguments[:2])}")
        if bull_best.quote:
            parts.append(f"正方金句：「{bull_best.quote}」")

    if bear_best:
        parts.append(f"【反方核心观点】{bear_best.thesis}："
                     f"{'；'.join(bear_best.arguments[:2])}")
        if bear_best.quote:
            parts.append(f"反方金句：「{bear_best.quote}」")

    return "\n\n".join(parts) if parts else ""


class MarketingExtractor:
    """营销素材提取器。"""

    def __init__(self, llm_client: LLMClient | None = None,
                 max_tokens: int = 800):
        self.llm = llm_client
        self.max_tokens = max_tokens

    async def extract(self, topic: str, transcript: list[Turn],
                      verdict: Verdict | None = None) -> MarketingMaterial:
        """从辩论记录提取营销素材。"""
        # 规则部分（无需 LLM）
        quotes = _extract_quotes(transcript)
        hashtags = _extract_hashtags(topic, transcript)
        highlight = _build_highlight(transcript, verdict)

        # LLM 部分（短文案 + 标题）
        short_copy, debate_title = await self._generate_copy_and_title(
            topic, transcript,
        )

        return MarketingMaterial(
            quotes=quotes,
            hashtags=hashtags,
            highlight_paragraph=highlight,
            short_copy=short_copy,
            debate_title=debate_title,
        )

    async def _generate_copy_and_title(
        self, topic: str, transcript: list[Turn],
    ) -> tuple[list[str], str]:
        """调用 LLM 生成短文案和标题，失败时 fallback。"""
        if self.llm is None:
            return self._fallback_copy_and_title(topic, transcript)

        # 构建 user prompt
        debate_summary = "\n".join(
            f"{'正方' if t.speaker == 'bull' else '反方'}：{t.content.thesis}"
            for t in transcript
            if isinstance(t.content, Argument)
        )
        user_prompt = f"辩论话题：{topic}\n\n辩论要点：\n{debate_summary}"

        try:
            raw = await self.llm.chat(
                _MARKETING_SYSTEM_PROMPT, user_prompt, self.max_tokens,
            )
        except Exception as e:
            logger.warning("营销 LLM 调用异常: %s", e)
            return self._fallback_copy_and_title(topic, transcript)

        data = _extract_json(raw)
        if data is None:
            logger.warning("营销 JSON 解析失败，使用 fallback")
            return self._fallback_copy_and_title(topic, transcript)

        copies = list(data.get("copies", []))
        title = str(data.get("title", ""))

        if not copies or not title:
            return self._fallback_copy_and_title(topic, transcript)

        return copies, title

    def _fallback_copy_and_title(
        self, topic: str, transcript: list[Turn],
    ) -> tuple[list[str], str]:
        """无 LLM 或失败时的 fallback。"""
        # 标题直接用 topic
        title = topic if len(topic) <= 30 else topic[:28] + "…"

        # 短文案从论点拼接
        theses = [
            t.content.thesis for t in transcript
            if isinstance(t.content, Argument)
        ]
        if theses:
            copy = f"{' vs '.join(theses[:2])} — 谁更有道理？"
        else:
            copy = f"关于「{topic}」的辩论"

        return [copy], title

    def _extract_cross_exam_highlights(self, transcript: list[Turn]) -> list[str]:
        """从交叉质询中提取精彩 Q&A 作为营销素材。

        SPEC v2.0-rc3 第 4.5 节。

        策略：
        1. 遍历 transcript 中 CrossExamination 类型的 Turn
        2. 筛选"被问倒"的 Q&A（answer 短于 20 字 或 question 带犀利关键词）
        3. 格式化为"反方质询正方：Q → A"的短文案
        """
        sharp_keywords = ["数据来源", "如何解释", "为什么", "矛盾"]
        highlights = []
        for turn in transcript:
            if not isinstance(turn.content, CrossExamination):
                continue
            for q, a in zip(turn.content.questions, turn.content.answers):
                # 犀利问题或简短回答（被问倒）→ 高传播价值
                is_sharp = any(kw in q for kw in sharp_keywords)
                is_stumped = len(a) < 20
                if is_sharp or is_stumped:
                    if turn.content.questioner == "bear":
                        side = "反方质询正方"
                    else:
                        side = "正方质询反方"
                    highlights.append(f"🔥 {side}\nQ: {q}\nA: {a}")
        return highlights
