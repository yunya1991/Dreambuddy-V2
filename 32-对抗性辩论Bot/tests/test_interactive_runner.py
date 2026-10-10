"""test_interactive_runner.py — 交互式辩论驱动器测试

验证 InteractiveRunner 逐步发送 Argument/Verdict/Marketing/Quality 的正确性。
"""
import asyncio
from datetime import datetime

import pytest

from core.interactive_runner import InteractiveRunner
from core.models import Argument, Turn, Verdict, MarketingMaterial, DebateQualityScore, DebateResult
from core.telegram_bot import TelegramDualBot


# ─── Mock Bot ─────────────────────────────────────────────────

class MockBot:
    """记录所有发送消息的 mock bot。"""
    def __init__(self, name="mock"):
        self.name = name
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> dict:
        self.messages.append((chat_id, text))
        return {"message_id": len(self.messages)}


def make_runner(chat_id: int = -100, judge: bool = True) -> tuple[InteractiveRunner, MockBot, MockBot]:
    bull_bot = MockBot("bull")
    bear_bot = MockBot("bear")
    judge_bot = MockBot("judge") if judge else None
    dual = TelegramDualBot(bull_bot, bear_bot, judge_bot, send_delay=0, retry_delay=0)
    runner = InteractiveRunner(dual, "测试话题", chat_id, max_rounds=2, judge_enabled=judge)
    return runner, bull_bot, bear_bot


# ─── 测试 ─────────────────────────────────────────────────────

pytestmark = pytest.mark.asyncio


async def test_send_bull():
    """正方发言：transcript 记录 + Telegram 发送。"""
    runner, bull_bot, bear_bot = make_runner()
    turn = await runner.send_bull("正方论点", ["论据1", "论据2"], "金句", 0.85)

    assert len(runner.transcript) == 1
    assert runner.transcript[0].speaker == "bull"
    assert runner.transcript[0].round == 1
    assert isinstance(turn.content, Argument)
    assert turn.content.thesis == "正方论点"
    assert turn.content.arguments == ["论据1", "论据2"]
    assert turn.content.quote == "金句"
    assert turn.content.confidence == 0.85
    assert len(bull_bot.messages) == 1
    assert "正方" in bull_bot.messages[0][1]
    assert "正方论点" in bull_bot.messages[0][1]


async def test_send_bear():
    """反方发言：transcript 记录 + Telegram 发送。"""
    runner, bull_bot, bear_bot = make_runner()
    await runner.send_bull("正方论点", ["论据1"])
    turn = await runner.send_bear("反方反驳", ["反驳1"])

    assert len(runner.transcript) == 2
    assert runner.transcript[1].speaker == "bear"
    assert runner.transcript[1].round == 1
    assert len(bear_bot.messages) == 1
    assert "反方" in bear_bot.messages[0][1]


async def test_multiple_rounds():
    """多轮辩论：轮次递增。"""
    runner, _, _ = make_runner()
    await runner.send_bull("正方1", ["论据"])
    await runner.send_bear("反方1", ["反驳"])
    await runner.send_bull("正方2", ["论据"])
    await runner.send_bear("反方2", ["反驳"])

    assert len(runner.transcript) == 4
    assert runner.current_round == 2
    assert runner.transcript[0].round == 1
    assert runner.transcript[2].round == 2


async def test_send_verdict():
    """裁判裁决：verdict 记录 + Telegram 发送。"""
    runner, _, _ = make_runner()
    await runner.send_bull("正方", ["论据"])
    await runner.send_bear("反方", ["反驳"])
    verdict = await runner.send_verdict("总结", "bull", ["洞察1"], "升华角度")

    assert runner.verdict is not None
    assert verdict.summary == "总结"
    assert verdict.winner == "bull"
    assert verdict.key_insights == ["洞察1"]
    assert verdict.topic_angle == "升华角度"


async def test_send_marketing():
    """营销素材：material 记录 + Telegram 发送。"""
    runner, bull_bot, _ = make_runner()
    material = await runner.send_marketing(
        quotes=["金句1", "金句2"],
        hashtags=["#BTC", "#黄金"],
        highlight_paragraph="精华段落",
        short_copy=["文案1", "文案2"],
        debate_title="辩论标题",
    )

    assert runner.material is not None
    assert material.quotes == ["金句1", "金句2"]
    assert material.hashtags == ["#BTC", "#黄金"]
    assert material.debate_title == "辩论标题"
    assert len(bull_bot.messages) == 1
    assert "辩论标题" in bull_bot.messages[0][1]


async def test_send_quality():
    """质量评分：score 记录 + 等级计算。"""
    runner, _, _ = make_runner()
    score = await runner.send_quality(
        overall=8.5,
        dimensions={"冲突强度": 9, "传播力": 8},
        highlights=["亮点1"],
        suggestions=["建议1"],
    )

    assert runner.quality_score is not None
    assert score.overall == 8.5
    assert score.grade == "S"  # >= 8.0
    assert score.highlights == ["亮点1"]


async def test_build_result():
    """完整结果构建。"""
    runner, _, _ = make_runner()
    await runner.send_bull("正方", ["论据"])
    await runner.send_bear("反方", ["反驳"])
    await runner.send_verdict("总结", "bull")
    await runner.send_marketing(quotes=["金句"], debate_title="标题")
    await runner.send_quality(overall=7.5)

    result = runner.build_result()

    assert isinstance(result, DebateResult)
    assert result.topic == "测试话题"
    assert len(result.transcript) == 2
    assert result.verdict is not None
    assert result.material is not None
    assert result.quality_score is not None
    assert result.status == "completed"
    assert result.quality_score.grade == "A"  # 6.0-7.9


async def test_build_result_without_judge():
    """无裁判时 build_result 仍有默认值。"""
    runner, _, _ = make_runner(judge=False)
    await runner.send_bull("正方", ["论据"])
    await runner.send_bear("反方", ["反驳"])

    result = runner.build_result(status="stopped")

    assert result.verdict is None
    assert result.status == "stopped"


async def test_get_transcript_summary():
    """transcript 摘要包含所有轮次信息。"""
    runner, _, _ = make_runner()
    await runner.send_bull("正方论点", ["论据1"], "金句1", 0.85)
    await runner.send_bear("反方反驳", ["反驳1"], "金句2", 0.78)

    summary = runner.get_transcript_summary()

    assert "测试话题" in summary
    assert "正方论点" in summary
    assert "反方反驳" in summary
    assert "金句1" in summary
    assert "金句2" in summary


async def test_format_message_content():
    """发送的消息文本包含格式化标记。"""
    runner, bull_bot, bear_bot = make_runner()
    await runner.send_bull("BTC是数字黄金", ["总量有限", "去中心化"], "数字黄金不可阻挡", 0.9)

    msg = bull_bot.messages[0][1]
    assert "【正方】" in msg
    assert "BTC是数字黄金" in msg
    assert "总量有限" in msg
    assert "数字黄金不可阻挡" in msg
