"""orchestrator.py — DebateOrchestrator 辩论编排器

SPEC 3.1 + 2.2 + 10 的核心组件：
- 状态机驱动（idle → preparing → bull_turn → bear_turn → ... → done）
- 轮次控制（max_rounds）
- 上下文注入（background / injected_views）
- 并发锁（asyncio.Lock per chat_id）
- /stop：跳过剩余轮次，仍执行 judging + marketing + quality，status='stopped'
- /inject：注入观点传给辩手
- /pause + /resume：暂停/恢复（超时自动 stop）
"""
from __future__ import annotations

import asyncio
import logging

from core.agents import BullAgent, BearAgent, JudgeAgent
from core.marketing import MarketingExtractor
from core.models import (
    Argument, Turn, Verdict, MarketingMaterial,
    DebateQualityScore, DebateResult,
)
from core.quality import QualityEvaluator
from core.telegram_bot import TelegramDualBot

logger = logging.getLogger("debate.orchestrator")


def _format_argument(arg: Argument, side_name: str) -> str:
    """格式化 Argument 为 Telegram 消息文本。"""
    lines = [f"【{side_name}】{arg.thesis}"]
    if arg.arguments:
        lines.append("论据：" + "；".join(arg.arguments))
    if arg.quote:
        lines.append(f"💬 {arg.quote}")
    return "\n".join(lines)


def _format_verdict(verdict: Verdict) -> str:
    """格式化 Verdict 为 Telegram 消息文本。"""
    lines = ["【裁判裁决】"]
    if verdict.summary:
        lines.append(verdict.summary)
    if verdict.winner:
        winner_name = "正方" if verdict.winner == "bull" else "反方"
        lines.append(f"🏆 胜方：{winner_name}")
    if verdict.key_insights:
        lines.append("核心洞察：" + "；".join(verdict.key_insights))
    if verdict.topic_angle:
        lines.append(f"📌 {verdict.topic_angle}")
    return "\n".join(lines)


class DebateOrchestrator:
    """辩论编排器：状态机驱动、轮次控制、上下文注入、结果收集。"""

    def __init__(
        self,
        bull_agent: BullAgent,
        bear_agent: BearAgent,
        judge_agent: JudgeAgent | None,
        marketing_extractor: MarketingExtractor,
        quality_evaluator: QualityEvaluator,
        telegram_dual_bot: TelegramDualBot,
        pause_timeout: float = 30 * 60,  # 30 分钟
    ):
        self.bull_agent = bull_agent
        self.bear_agent = bear_agent
        self.judge_agent = judge_agent
        self.marketing_extractor = marketing_extractor
        self.quality_evaluator = quality_evaluator
        self.telegram_dual_bot = telegram_dual_bot
        self.pause_timeout = pause_timeout

        # 全局状态（单进程单群场景）
        self.status: str = "idle"

        # per-chat_id 状态
        self._locks: dict[int, asyncio.Lock] = {}
        self._stop_flags: dict[int, bool] = {}
        self._pause_flags: dict[int, bool] = {}
        self._resume_events: dict[int, asyncio.Event] = {}
        self._injected_views: dict[int, list[str]] = {}

    # ─── 公共控制方法（供 Telegram 命令处理器调用） ──────────────

    def stop(self, chat_id: int) -> None:
        """请求停止辩论（当前轮完成后停）。"""
        self._stop_flags[chat_id] = True

    def inject(self, chat_id: int, view: str) -> None:
        """注入群主观点。"""
        if chat_id not in self._injected_views:
            self._injected_views[chat_id] = []
        self._injected_views[chat_id].append(view)

    def pause(self, chat_id: int) -> None:
        """请求暂停辩论。"""
        self._pause_flags[chat_id] = True
        if chat_id not in self._resume_events:
            self._resume_events[chat_id] = asyncio.Event()

    def resume(self, chat_id: int) -> None:
        """恢复暂停的辩论。"""
        self._pause_flags[chat_id] = False
        if chat_id not in self._resume_events:
            self._resume_events[chat_id] = asyncio.Event()
        self._resume_events[chat_id].set()

    def clear_injected_views(self, chat_id: int) -> None:
        """清空注入观点（/inject clear）。"""
        if chat_id in self._injected_views:
            self._injected_views[chat_id].clear()

    # ─── 主入口 ──────────────────────────────────────────────────

    async def run(
        self, topic: str, chat_id: int, max_rounds: int = 2,
        background: str = "",
    ) -> DebateResult:
        """执行一场完整辩论。

        Args:
            topic: 辩论话题
            chat_id: Telegram 群 ID
            max_rounds: 最大辩论轮次
            background: 背景材料（可选）

        Returns:
            DebateResult: 含完整 transcript + 营销素材
        """
        lock = self._get_lock(chat_id)
        async with lock:
            return await self._run_debate(topic, chat_id, max_rounds, background)

    # ─── 内部实现 ────────────────────────────────────────────────

    def _get_lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    async def _wait_if_paused(self, chat_id: int) -> None:
        """如果被暂停，等待 resume（超时则自动 stop）。"""
        if not self._pause_flags.get(chat_id, False):
            return

        self.status = "paused"
        logger.info("辩论暂停 (chat_id=%s)", chat_id)

        resume_event = self._resume_events.get(chat_id)
        if resume_event is None:
            return

        try:
            await asyncio.wait_for(
                resume_event.wait(),
                timeout=self.pause_timeout,
            )
            resume_event.clear()
            self._pause_flags[chat_id] = False
            logger.info("辩论恢复 (chat_id=%s)", chat_id)
        except asyncio.TimeoutError:
            logger.warning("暂停超时，自动 stop (chat_id=%s)", chat_id)
            self.stop(chat_id)

    async def _run_debate(
        self, topic: str, chat_id: int, max_rounds: int,
        background: str,
    ) -> DebateResult:
        """执行辩论主循环。"""
        self.status = "preparing"
        self._stop_flags[chat_id] = False
        self._pause_flags[chat_id] = False

        transcript: list[Turn] = []

        # 注入观点写入 transcript
        injected_views = self._injected_views.get(chat_id, [])
        for view in injected_views:
            transcript.append(Turn(
                speaker="inject", round=0, content=view,
            ))

        # 注入观点传给辩手（None 如果空）
        views_for_agents: list[str] | None = (
            list(injected_views) if injected_views else None
        )

        # ─── 辩论轮次循环 ────────────────────────────────────
        for round_num in range(1, max_rounds + 1):
            if self._stop_flags.get(chat_id, False):
                break

            # 正方发言
            self.status = "bull_turn"
            bull_arg = await self.bull_agent.argue(
                topic, transcript, background, views_for_agents,
            )
            await self.telegram_dual_bot.send_as(
                "bull", chat_id, _format_argument(bull_arg, "正方"),
            )
            transcript.append(Turn(
                speaker="bull", round=round_num, content=bull_arg,
            ))

            # 暂停检查（不检查 stop — 当前轮必须完成）
            await self._wait_if_paused(chat_id)

            # 反方反驳
            self.status = "bear_turn"
            bear_arg = await self.bear_agent.rebut(
                topic, transcript, background, views_for_agents,
            )
            await self.telegram_dual_bot.send_as(
                "bear", chat_id, _format_argument(bear_arg, "反方"),
            )
            transcript.append(Turn(
                speaker="bear", round=round_num, content=bear_arg,
            ))

            # 暂停检查
            await self._wait_if_paused(chat_id)

        # ─── 裁判综合 ────────────────────────────────────────
        verdict: Verdict | None = None
        if self.judge_agent is not None:
            self.status = "judging"
            verdict = await self.judge_agent.synthesize(topic, transcript)
            await self.telegram_dual_bot.send_as(
                "judge", chat_id, _format_verdict(verdict),
            )
            transcript.append(Turn(
                speaker="judge", round=max_rounds, content=verdict,
            ))

        # ─── 营销素材提取 ────────────────────────────────────
        self.status = "marketing"
        material = await self.marketing_extractor.extract(
            topic, transcript, verdict,
        )

        # ─── 质量评估 ────────────────────────────────────────
        self.status = "quality"
        quality_score = await self.quality_evaluator.evaluate(
            topic, transcript, material,
        )

        # ─── 完成 ────────────────────────────────────────────
        self.status = "done"
        was_stopped = self._stop_flags.get(chat_id, False)
        status = "stopped" if was_stopped else "completed"

        return DebateResult(
            topic=topic,
            transcript=transcript,
            verdict=verdict,
            material=material,
            quality_score=quality_score,
            status=status,
        )
