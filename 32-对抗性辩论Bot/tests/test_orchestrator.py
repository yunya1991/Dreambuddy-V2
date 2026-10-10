"""test_orchestrator.py — DebateOrchestrator 单元测试（TDD RED phase）

测试 SPEC 3.1 + 2.2 + 10 的核心设计：
- 状态机驱动（idle → preparing → bull_turn → bear_turn → ... → done）
- 轮次控制（max_rounds）
- 上下文注入（background / injected_views）
- 并发锁（asyncio.Lock per chat_id）
- /stop：跳过剩余轮次，仍执行 judging + marketing + quality，status='stopped'
- /inject：注入观点传给辩手
- /pause + /resume
- Telegram 消息发送
"""
from __future__ import annotations

import asyncio
from typing import Sequence

import pytest

from core.models import (
    Argument, Turn, Verdict, MarketingMaterial, DebateQualityScore,
    DebateResult,
)
from core.orchestrator import DebateOrchestrator


# ─── Mock 组件 ───────────────────────────────────────────────────

class MockBullAgent:
    """记录 argue 调用，返回预设 Argument。"""

    def __init__(self, arg: Argument | None = None):
        self._arg = arg or Argument(
            thesis="正方论点", arguments=["论据1", "论据2"],
            quote="正方金句", confidence=0.8, raw="{}",
        )
        self.calls: list[dict] = []

    async def argue(self, topic: str, transcript: list[Turn],
                    background: str = "",
                    injected_views: list[str] | None = None) -> Argument:
        self.calls.append({
            "topic": topic, "transcript_len": len(transcript),
            "background": background,
            "injected_views": injected_views,
        })
        return self._arg


class MockBearAgent:
    """记录 rebut 调用，返回预设 Argument。"""

    def __init__(self, arg: Argument | None = None):
        self._arg = arg or Argument(
            thesis="反方论点", arguments=["反驳1", "反驳2"],
            quote="反方金句", confidence=0.7, raw="{}",
        )
        self.calls: list[dict] = []

    async def rebut(self, topic: str, transcript: list[Turn],
                    background: str = "",
                    injected_views: list[str] | None = None) -> Argument:
        self.calls.append({
            "topic": topic, "transcript_len": len(transcript),
            "background": background,
            "injected_views": injected_views,
        })
        return self._arg


class MockJudgeAgent:
    """记录 synthesize 调用，返回预设 Verdict。"""

    def __init__(self, verdict: Verdict | None = None):
        self._verdict = verdict or Verdict(
            summary="综合裁决", winner="bull",
            key_insights=["洞察1"], topic_angle="升华角度",
        )
        self.calls: list[dict] = []

    async def synthesize(self, topic: str, transcript: list[Turn]) -> Verdict:
        self.calls.append({"topic": topic, "transcript_len": len(transcript)})
        return self._verdict


class MockMarketingExtractor:
    """记录 extract 调用，返回预设 MarketingMaterial。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def extract(self, topic: str, transcript: list[Turn],
                      verdict: Verdict | None = None) -> MarketingMaterial:
        self.calls.append({
            "topic": topic,
            "transcript_len": len(transcript),
            "verdict": verdict,
        })
        return MarketingMaterial(
            quotes=["金句1"], hashtags=["#标签"],
            highlight_paragraph="精华", short_copy=["文案"],
            debate_title="辩论标题",
        )


class MockQualityEvaluator:
    """记录 evaluate 调用，返回预设 DebateQualityScore。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def evaluate(self, topic: str, transcript: list[Turn],
                       material: MarketingMaterial) -> DebateQualityScore:
        self.calls.append({
            "topic": topic,
            "transcript_len": len(transcript),
            "material": material,
        })
        return DebateQualityScore(
            overall=7.5, grade="A",
            dimensions={"冲突强度": 8.0},
            rule_score=7.0, llm_score=8.0,
            highlights=["亮点"], suggestions=[],
        )


class MockTelegramDualBot:
    """记录 send_as 调用。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def send_as(self, role: str, chat_id: int, text: str) -> dict:
        self.calls.append({"role": role, "chat_id": chat_id, "text": text})
        return {"message_id": len(self.calls), "role": role}


def make_orchestrator(
    bull: MockBullAgent | None = None,
    bear: MockBearAgent | None = None,
    judge: MockJudgeAgent | None = None,
    marketing: MockMarketingExtractor | None = None,
    quality: MockQualityEvaluator | None = None,
    telegram: MockTelegramDualBot | None = None,
    pause_timeout: float = 10.0,
) -> tuple[DebateOrchestrator, dict]:
    """创建带 mock 依赖的 orchestrator，返回 (orchestrator, mocks)。"""
    bull = bull or MockBullAgent()
    bear = bear or MockBearAgent()
    marketing = marketing or MockMarketingExtractor()
    quality = quality or MockQualityEvaluator()
    telegram = telegram or MockTelegramDualBot()
    orch = DebateOrchestrator(
        bull_agent=bull, bear_agent=bear, judge_agent=judge,
        marketing_extractor=marketing, quality_evaluator=quality,
        telegram_dual_bot=telegram,
        pause_timeout=pause_timeout,
    )
    return orch, {"bull": bull, "bear": bear, "judge": judge,
                  "marketing": marketing, "quality": quality,
                  "telegram": telegram}


# ─── 基本流程测试 ────────────────────────────────────────────────

class TestBasicFlow:
    """测试完整辩论流程。"""

    @pytest.mark.asyncio
    async def test_run_2_rounds_transcript_has_4_turns(self):
        """2 轮辩论 → transcript 有 4 条 Turn（2 bull + 2 bear）。"""
        orch, mocks = make_orchestrator(judge=MockJudgeAgent())
        result = await orch.run(topic="BTC 是数字黄金", chat_id=123,
                                max_rounds=2)
        # 4 辩手 turns + 1 judge turn = 5
        assert len(result.transcript) == 5
        speakers = [t.speaker for t in result.transcript]
        assert speakers == ["bull", "bear", "bull", "bear", "judge"]

    @pytest.mark.asyncio
    async def test_run_returns_debate_result(self):
        """返回 DebateResult 实例。"""
        orch, _ = make_orchestrator(judge=MockJudgeAgent())
        result = await orch.run(topic="测试", chat_id=1, max_rounds=1)
        assert isinstance(result, DebateResult)
        assert result.topic == "测试"

    @pytest.mark.asyncio
    async def test_run_status_completed(self):
        """正常完成 status='completed'。"""
        orch, _ = make_orchestrator(judge=MockJudgeAgent())
        result = await orch.run(topic="测试", chat_id=1, max_rounds=1)
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_telegram_messages_sent_each_turn(self):
        """每轮发送消息到 Telegram。"""
        orch, mocks = make_orchestrator(judge=MockJudgeAgent())
        await orch.run(topic="测试", chat_id=42, max_rounds=2)
        # 4 辩手 + 1 judge = 5 条消息
        roles = [c["role"] for c in mocks["telegram"].calls]
        assert roles == ["bull", "bear", "bull", "bear", "judge"]
        assert all(c["chat_id"] == 42 for c in mocks["telegram"].calls)

    @pytest.mark.asyncio
    async def test_background_passed_to_agents(self):
        """background 参数传入辩手。"""
        orch, mocks = make_orchestrator(judge=MockJudgeAgent())
        await orch.run(topic="测试", chat_id=1, max_rounds=1,
                       background="背景材料")
        assert mocks["bull"].calls[0]["background"] == "背景材料"
        assert mocks["bear"].calls[0]["background"] == "背景材料"


# ─── Judge 可选测试 ──────────────────────────────────────────────

class TestJudgeOptional:
    """测试 judge_agent 为 None 时的行为。"""

    @pytest.mark.asyncio
    async def test_no_judge_skips_judging(self):
        """judge_agent=None 时跳过 judging 阶段。"""
        orch, mocks = make_orchestrator(judge=None)
        result = await orch.run(topic="测试", chat_id=1, max_rounds=1)
        # transcript 只有 2 辩手 turns，无 judge turn
        assert len(result.transcript) == 2
        assert all(t.speaker in ("bull", "bear")
                   for t in result.transcript)

    @pytest.mark.asyncio
    async def test_no_judge_verdict_none(self):
        """judge_agent=None 时 verdict 为 None。"""
        orch, _ = make_orchestrator(judge=None)
        result = await orch.run(topic="测试", chat_id=1, max_rounds=1)
        assert result.verdict is None

    @pytest.mark.asyncio
    async def test_no_judge_no_judge_telegram(self):
        """judge_agent=None 时不发送 judge 消息。"""
        orch, mocks = make_orchestrator(judge=None)
        await orch.run(topic="测试", chat_id=1, max_rounds=1)
        roles = [c["role"] for c in mocks["telegram"].calls]
        assert "judge" not in roles


# ─── /stop 测试 ──────────────────────────────────────────────────

class TestStop:
    """测试 /stop 机制。"""

    @pytest.mark.asyncio
    async def test_stop_skips_remaining_rounds(self):
        """/stop 后跳过剩余轮次，只保留已完成的轮次。"""
        orch, mocks = make_orchestrator(judge=MockJudgeAgent())

        # 在第一轮 bull 发言后触发 stop
        original_argue = mocks["bull"].argue

        async def argue_then_stop(topic, transcript, background="",
                                  injected_views=None):
            result = await original_argue(topic, transcript, background,
                                          injected_views)
            orch.stop(123)  # 触发 stop
            return result

        mocks["bull"].argue = argue_then_stop

        result = await orch.run(topic="测试", chat_id=123, max_rounds=3)
        # bull 发言了 1 次（第 1 轮），bear 仍发言 1 次（当前轮完成）
        # 但跳过第 2、3 轮
        assert len(mocks["bull"].calls) == 1
        assert len(mocks["bear"].calls) == 1

    @pytest.mark.asyncio
    async def test_stop_still_runs_judging_marketing_quality(self):
        """/stop 后仍执行 judging + marketing + quality。"""
        orch, mocks = make_orchestrator(judge=MockJudgeAgent())

        original_rebut = mocks["bear"].rebut

        async def rebut_then_stop(topic, transcript, background="",
                                  injected_views=None):
            result = await original_rebut(topic, transcript, background,
                                          injected_views)
            orch.stop(1)
            return result

        mocks["bear"].rebut = rebut_then_stop

        result = await orch.run(topic="测试", chat_id=1, max_rounds=5)
        # judge 仍被调用
        assert len(mocks["judge"].calls) == 1
        # marketing 仍被调用
        assert len(mocks["marketing"].calls) == 1
        # quality 仍被调用
        assert len(mocks["quality"].calls) == 1

    @pytest.mark.asyncio
    async def test_stop_status_stopped(self):
        """/stop 后 status='stopped'。"""
        orch, mocks = make_orchestrator(judge=MockJudgeAgent())

        original_argue = mocks["bull"].argue

        async def argue_then_stop(topic, transcript, background="",
                                  injected_views=None):
            result = await original_argue(topic, transcript, background,
                                          injected_views)
            orch.stop(1)
            return result

        mocks["bull"].argue = argue_then_stop

        result = await orch.run(topic="测试", chat_id=1, max_rounds=3)
        assert result.status == "stopped"


# ─── /inject 测试 ────────────────────────────────────────────────

class TestInject:
    """测试 /inject 机制。"""

    @pytest.mark.asyncio
    async def test_inject_views_passed_to_agents(self):
        """inject 的观点传入辩手的 injected_views 参数。"""
        orch, mocks = make_orchestrator(judge=MockJudgeAgent())
        orch.inject(1, "群主观点A")
        await orch.run(topic="测试", chat_id=1, max_rounds=1)

        # bull 第一次调用应有 injected_views
        assert mocks["bull"].calls[0]["injected_views"] == ["群主观点A"]
        assert mocks["bear"].calls[0]["injected_views"] == ["群主观点A"]

    @pytest.mark.asyncio
    async def test_inject_multiple_accumulates(self):
        """多次 inject 累积。"""
        orch, mocks = make_orchestrator(judge=MockJudgeAgent())
        orch.inject(1, "观点1")
        orch.inject(1, "观点2")
        await orch.run(topic="测试", chat_id=1, max_rounds=1)
        assert mocks["bull"].calls[0]["injected_views"] == ["观点1", "观点2"]

    @pytest.mark.asyncio
    async def test_inject_recorded_in_transcript(self):
        """inject 观点记录到 transcript（speaker='inject'）。"""
        orch, _ = make_orchestrator(judge=MockJudgeAgent())
        orch.inject(1, "注入观点")
        result = await orch.run(topic="测试", chat_id=1, max_rounds=1)
        inject_turns = [t for t in result.transcript if t.speaker == "inject"]
        assert len(inject_turns) == 1
        assert inject_turns[0].content == "注入观点"


# ─── 并发锁测试 ──────────────────────────────────────────────────

class TestConcurrencyLock:
    """测试并发锁（asyncio.Lock per chat_id）。"""

    @pytest.mark.asyncio
    async def test_same_chat_id_concurrent_is_serialized(self):
        """同一 chat_id 并发辩论被串行化。"""
        bull = MockBullAgent()
        bear = MockBearAgent()
        call_order: list[str] = []

        async def slow_argue(topic, transcript, background="",
                              injected_views=None):
            call_order.append("bull_start")
            await asyncio.sleep(0.01)
            call_order.append("bull_end")
            return Argument(thesis="t", arguments=[], quote="",
                            confidence=0.5, raw="")

        bull.argue = slow_argue
        orch, _ = make_orchestrator(bull=bull, bear=bear,
                                    judge=MockJudgeAgent())

        # 并发发起两场辩论
        await asyncio.gather(
            orch.run(topic="A", chat_id=1, max_rounds=1),
            orch.run(topic="B", chat_id=1, max_rounds=1),
        )
        # 第一场完全结束后第二场才开始
        assert call_order == ["bull_start", "bull_end", "bull_start", "bull_end"]

    @pytest.mark.asyncio
    async def test_different_chat_ids_concurrent_ok(self):
        """不同 chat_id 可并发辩论。"""
        bull = MockBullAgent()
        call_order: list[str] = []

        original_argue = bull.argue

        async def tracked_argue(topic, transcript, background="",
                                injected_views=None):
            call_order.append(f"{topic}_start")
            await asyncio.sleep(0.01)
            call_order.append(f"{topic}_end")
            return await original_argue(topic, transcript, background,
                                        injected_views)

        bull.argue = tracked_argue
        orch, _ = make_orchestrator(bull=bull, bear=MockBearAgent(),
                                    judge=MockJudgeAgent())

        await asyncio.gather(
            orch.run(topic="A", chat_id=1, max_rounds=1),
            orch.run(topic="B", chat_id=2, max_rounds=1),
        )
        # 两场并发执行（不严格串行）
        assert call_order[0].endswith("_start")
        assert call_order[1].endswith("_start")  # 第二个也先 start


# ─── 状态转换测试 ────────────────────────────────────────────────

class TestStatusTransitions:
    """测试状态机转换。"""

    @pytest.mark.asyncio
    async def test_status_starts_idle(self):
        """初始状态为 idle。"""
        orch, _ = make_orchestrator()
        assert orch.status == "idle"

    @pytest.mark.asyncio
    async def test_status_done_after_run(self):
        """run 完成后状态为 done。"""
        orch, _ = make_orchestrator(judge=MockJudgeAgent())
        await orch.run(topic="测试", chat_id=1, max_rounds=1)
        assert orch.status == "done"


# ─── /pause + /resume 测试 ────────────────────────────────────────

class TestPauseResume:
    """测试 /pause + /resume 机制。"""

    @pytest.mark.asyncio
    async def test_pause_then_resume_completes(self):
        """/pause 后 /resume 能继续完成辩论。"""
        orch, mocks = make_orchestrator(judge=MockJudgeAgent(),
                                        pause_timeout=10.0)
        original_argue = mocks["bull"].argue

        async def argue_then_pause(topic, transcript, background="",
                                   injected_views=None):
            result = await original_argue(topic, transcript, background,
                                          injected_views)
            orch.pause(1)  # 在 bull 发言后请求暂停
            return result

        mocks["bull"].argue = argue_then_pause

        # 启动辩论（会在 bull 发言后暂停）
        task = asyncio.create_task(
            orch.run(topic="测试", chat_id=1, max_rounds=1)
        )

        # 等待 orchestrator 进入 paused 状态（task 会阻塞在 resume 事件上）
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert task not in done  # task 未完成（仍在暂停等待）
        assert orch.status == "paused"

        # resume
        orch.resume(1)

        result = await asyncio.wait_for(task, timeout=5.0)
        assert result.status == "completed"
        assert orch.status == "done"
