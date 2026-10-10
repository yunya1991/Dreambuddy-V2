"""models.py — 对抗性辩论 Bot 数据模型

定义 SPEC 中的全部数据结构：
- Argument: 辩手结构化输出（thesis/arguments/quote/confidence/raw）
- Turn: 单轮发言记录（speaker/round/content/timestamp）
- Verdict: 裁判裁决（summary/winner/key_insights/topic_angle）
- MarketingMaterial: 营销素材（quotes/hashtags/highlight_paragraph/short_copy/debate_title）
- DebateQualityScore: 质量评分（overall/grade/dimensions/rule_score/llm_score/highlights/suggestions）
- DebateResult: 辩论完整结果（topic/transcript/verdict/material/quality_score/status）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Union


@dataclass
class Argument:
    """辩手结构化输出契约。"""
    thesis: str           # 核心论点
    arguments: list[str]  # 论据列表
    quote: str            # 金句（用于营销提取）
    confidence: float     # 本方置信度（0-1）
    raw: str              # 原始 LLM 输出

    @classmethod
    def fallback(cls) -> "Argument":
        """FAIL-OPEN 兜底：LLM 失败或 JSON 解析失败时返回。"""
        return cls(
            thesis="（本方因技术原因无法输出完整论点）",
            arguments=[],
            quote="",
            confidence=0.0,
            raw="",
        )


@dataclass
class CrossExamination:
    """交叉质询记录（SPEC v2.0-rc3 第 4.2 节）。

    交叉质询不是 Argument，是独立的问答数据类型。
    questioner 和 respondent 互为对方（bull/bear）。
    """
    questioner: str          # 提问方: 'bull' | 'bear'
    respondent: str          # 回答方: 'bull' | 'bear'（与 questioner 相反）
    questions: list[str]     # 提问列表（2-3 个）
    answers: list[str]       # 回答列表（与 questions 一一对应）
    raw: str                 # 原始 LLM 输出


@dataclass
class Turn:
    """单轮发言记录。

    speaker: 'bull' | 'bear' | 'judge' | 'inject'
    round: 第几轮（inject 记为 0）
    content: 辩手为 Argument，交叉质询为 CrossExamination，inject 为纯文本
    """
    speaker: str
    round: int
    content: Union[Argument, CrossExamination, str]
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Verdict:
    """裁判裁决。"""
    summary: str              # 辩论总结
    winner: str | None        # 'bull' | 'bear' | None(平局)
    key_insights: list[str]   # 核心洞察
    topic_angle: str          # 话题升华角度（用于营销）


@dataclass
class MarketingMaterial:
    """营销素材。"""
    quotes: list[str]              # 金句摘录
    hashtags: list[str]            # 话题标签（#xxx）
    highlight_paragraph: str       # 精华段落
    short_copy: list[str]          # 短文案（3-5 条）
    debate_title: str              # 辩论标题


@dataclass
class DebateQualityScore:
    """辩论质量评分。"""
    overall: float              # 综合分 0-10
    grade: str                  # S/A/B/C
    dimensions: dict            # 各维度分
    rule_score: float           # 规则分
    llm_score: float            # LLM 分
    highlights: list[str]       # 质量亮点
    suggestions: list[str]      # 改进建议

    @staticmethod
    def grade_from_score(overall: float) -> str:
        """根据综合分返回等级。

        >= 8.0: S (精品)
        6.0-7.9: A (优质)
        4.0-5.9: B (一般)
        < 4.0: C (不合格)
        """
        if overall >= 8.0:
            return "S"
        elif overall >= 6.0:
            return "A"
        elif overall >= 4.0:
            return "B"
        else:
            return "C"


@dataclass
class DebateResult:
    """辩论完整结果。"""
    topic: str
    transcript: list[Turn]
    verdict: Verdict | None
    material: MarketingMaterial
    quality_score: DebateQualityScore
    status: str  # 'completed' | 'stopped'

    def to_dict(self) -> dict:
        """序列化为 JSON 安全的字典。"""
        return {
            "topic": self.topic,
            "transcript": [
                {
                    "speaker": t.speaker,
                    "round": t.round,
                    "content": t.content if isinstance(t.content, str)
                    else t.content.__dict__ if hasattr(t.content, "__dict__")
                    else str(t.content),
                    "timestamp": t.timestamp.isoformat(),
                }
                for t in self.transcript
            ],
            "verdict": self.verdict.__dict__ if self.verdict else None,
            "material": self.material.__dict__,
            "quality_score": self.quality_score.__dict__,
            "status": self.status,
        }
