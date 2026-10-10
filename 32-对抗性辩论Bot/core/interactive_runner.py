"""interactive_runner.py — 交互式辩论驱动器（方案B）

不调用 LLM API，由 Trae 自身作为"大脑"生成正反方论点，
逐步发送到 Telegram 群，实现真正实时对抗。

工作流程：
1. Trae（AI agent）研究话题 → 生成正方 Argument → send_bull()
2. Trae 读取 transcript → 生成反方反驳 Argument → send_bear()
3. 重复 N 轮
4. Trae 生成裁判裁决 → send_verdict()
5. Trae 生成营销素材 → send_marketing()
6. Trae 生成质量评分 → send_quality()
7. build_result() 输出完整 DebateResult

与 orchestrator.run() 的区别：
- orchestrator 是自主循环（一口气跑完），LLM 在循环内被调用
- interactive_runner 是逐步驱动（每步由 Trae 手动生成内容）
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from core.models import (
    Argument, Turn, Verdict, MarketingMaterial,
    DebateQualityScore, DebateResult,
)
from core.telegram_bot import TelegramDualBot
from core.orchestrator import _format_argument, _format_verdict

logger = logging.getLogger("debate.interactive")


class InteractiveRunner:
    """交互式辩论驱动器。

    由 Trae 逐步调用，每步发送一个 Argument/Verdict/Material 到 Telegram。
    维护 transcript 状态，最终输出完整 DebateResult。
    """

    def __init__(
        self,
        telegram_dual_bot: TelegramDualBot,
        topic: str,
        chat_id: int,
        max_rounds: int = 2,
        judge_enabled: bool = True,
    ):
        self.bot = telegram_dual_bot
        self.topic = topic
        self.chat_id = chat_id
        self.max_rounds = max_rounds
        self.judge_enabled = judge_enabled

        # 状态
        self.transcript: list[Turn] = []
        self.current_round: int = 0
        self.verdict: Verdict | None = None
        self.material: MarketingMaterial | None = None
        self.quality_score: DebateQualityScore | None = None

    async def send_bull(
        self,
        thesis: str,
        arguments: list[str],
        quote: str = "",
        confidence: float = 0.8,
    ) -> Turn:
        """发送正方发言。

        Trae 生成论点后调用此方法，自动格式化并发送到 Telegram。
        """
        self.current_round += 1
        arg = Argument(
            thesis=thesis,
            arguments=arguments,
            quote=quote,
            confidence=confidence,
            raw="",  # 无 LLM 原始输出
        )
        turn = Turn(
            speaker="bull",
            round=self.current_round,
            content=arg,
            timestamp=datetime.now(),
        )
        self.transcript.append(turn)

        # 发送到 Telegram
        text = _format_argument(arg, "正方")
        await self.bot.send_as("bull", self.chat_id, text)
        logger.info("正方第%d轮已发送: %s", self.current_round, thesis[:30])
        return turn

    async def send_bear(
        self,
        thesis: str,
        arguments: list[str],
        quote: str = "",
        confidence: float = 0.8,
    ) -> Turn:
        """发送反方发言。

        Trae 基于 transcript 中正方论点生成反驳后调用此方法。
        """
        arg = Argument(
            thesis=thesis,
            arguments=arguments,
            quote=quote,
            confidence=confidence,
            raw="",
        )
        turn = Turn(
            speaker="bear",
            round=self.current_round,
            content=arg,
            timestamp=datetime.now(),
        )
        self.transcript.append(turn)

        text = _format_argument(arg, "反方")
        await self.bot.send_as("bear", self.chat_id, text)
        logger.info("反方第%d轮已发送: %s", self.current_round, thesis[:30])
        return turn

    async def send_verdict(
        self,
        summary: str,
        winner: str | None = None,
        key_insights: list[str] | None = None,
        topic_angle: str = "",
    ) -> Verdict:
        """发送裁判裁决。"""
        self.verdict = Verdict(
            summary=summary,
            winner=winner,
            key_insights=key_insights or [],
            topic_angle=topic_angle,
        )

        text = _format_verdict(self.verdict)
        await self.bot.send_as("judge", self.chat_id, text)
        logger.info("裁判裁决已发送: winner=%s", winner)
        return self.verdict

    async def send_marketing(
        self,
        quotes: list[str] | None = None,
        hashtags: list[str] | None = None,
        highlight_paragraph: str = "",
        short_copy: list[str] | None = None,
        debate_title: str = "",
    ) -> MarketingMaterial:
        """发送营销素材到群。"""
        self.material = MarketingMaterial(
            quotes=quotes or [],
            hashtags=hashtags or [],
            highlight_paragraph=highlight_paragraph,
            short_copy=short_copy or [],
            debate_title=debate_title,
        )

        # 格式化并发送
        lines = [f"📣 {debate_title}", ""]
        if quotes:
            lines.append("💬 金句：")
            for q in quotes:
                lines.append(f"  • {q}")
            lines.append("")
        if highlight_paragraph:
            lines.append(f"精华段落：{highlight_paragraph}")
            lines.append("")
        if short_copy:
            lines.append("📝 短文案：")
            for i, copy in enumerate(short_copy, 1):
                lines.append(f"  {i}. {copy}")
            lines.append("")
        if hashtags:
            lines.append(" ".join(hashtags))

        text = "\n".join(lines)
        # 营销素材用正方 bot 发送（或可配置）
        await self.bot.send_as("bull", self.chat_id, text)
        logger.info("营销素材已发送: title=%s", debate_title)
        return self.material

    async def send_quality(
        self,
        overall: float,
        dimensions: dict | None = None,
        highlights: list[str] | None = None,
        suggestions: list[str] | None = None,
    ) -> DebateQualityScore:
        """发送质量评分到群。"""
        grade = DebateQualityScore.grade_from_score(overall)
        self.quality_score = DebateQualityScore(
            overall=overall,
            grade=grade,
            dimensions=dimensions or {},
            rule_score=overall * 0.4,
            llm_score=overall * 0.6,
            highlights=highlights or [],
            suggestions=suggestions or [],
        )

        lines = [f"📊 辩论质量评分：{overall}/10 ({grade}级)", ""]
        if dimensions:
            for dim, score in dimensions.items():
                lines.append(f"  {dim}: {score}")
            lines.append("")
        if highlights:
            lines.append("✨ 亮点：")
            for h in highlights:
                lines.append(f"  • {h}")
            lines.append("")
        if suggestions:
            lines.append("💡 建议：")
            for s in suggestions:
                lines.append(f"  • {s}")

        text = "\n".join(lines)
        await self.bot.send_as("bull", self.chat_id, text)
        logger.info("质量评分已发送: %s/10 (%s)", overall, grade)
        return self.quality_score

    def build_result(self, status: str = "completed") -> DebateResult:
        """构建完整辩论结果。"""
        if self.material is None:
            self.material = MarketingMaterial(
                quotes=[], hashtags=[], highlight_paragraph="",
                short_copy=[], debate_title="",
            )
        if self.quality_score is None:
            self.quality_score = DebateQualityScore(
                overall=0.0, grade="C", dimensions={},
                rule_score=0.0, llm_score=0.0,
                highlights=[], suggestions=[],
            )
        return DebateResult(
            topic=self.topic,
            transcript=list(self.transcript),
            verdict=self.verdict,
            material=self.material,
            quality_score=self.quality_score,
            status=status,
        )

    def get_transcript_summary(self) -> str:
        """获取 transcript 摘要（供 Trae 生成下一轮时参考）。"""
        lines = [f"话题：{self.topic}", f"当前轮次：{self.current_round}/{self.max_rounds}", ""]
        for turn in self.transcript:
            if isinstance(turn.content, Argument):
                side = "正方" if turn.speaker == "bull" else "反方"
                lines.append(f"【{side}·第{turn.round}轮】")
                lines.append(f"  论点：{turn.content.thesis}")
                lines.append(f"  论据：{'；'.join(turn.content.arguments)}")
                lines.append(f"  金句：{turn.content.quote}")
                lines.append(f"  置信度：{turn.content.confidence}")
                lines.append("")
        return "\n".join(lines)
