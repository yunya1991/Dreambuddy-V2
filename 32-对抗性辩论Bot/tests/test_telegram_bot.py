"""test_telegram_bot.py — TelegramDualBot 单元测试（TDD RED phase）

测试 SPEC 3.5 核心设计：
- 双 bot token 封装（bull / bear / judge 可选）
- send_as(role, chat_id, text) 按角色路由
- 长消息自动分段（4096 字符限制）
- 发送前 sleep 规避 rate limit
- 发送失败重试 1 次（指数退避），仍失败则抛出异常
"""
from __future__ import annotations

from typing import Sequence

import pytest

from core.telegram_bot import TelegramDualBot, TelegramBotClient


# ─── Mock Telegram Bot ───────────────────────────────────────────

class MockTelegramBot:
    """可控的 Telegram Bot mock：可配置成功/失败/返回值。"""

    def __init__(self, responses: Sequence[dict | Exception] | None = None):
        """responses 为 None 表示总是成功返回默认 dict。

        若 responses 列表提供，按顺序返回；Exception 实例则 raise。
        """
        self._responses = list(responses) if responses else None
        self._call_idx = 0
        self.calls: list[dict] = []  # 记录每次调用的参数

    async def send_message(self, chat_id: int, text: str) -> dict:
        self.calls.append({"chat_id": chat_id, "text": text})
        if self._responses is not None:
            if self._call_idx >= len(self._responses):
                raise RuntimeError("MockTelegramBot: no more responses")
            resp = self._responses[self._call_idx]
            self._call_idx += 1
            if isinstance(resp, Exception):
                raise resp
            return resp
        return {"message_id": self._call_idx + 1, "chat_id": chat_id, "text": text}


# ─── 初始化测试 ──────────────────────────────────────────────────

class TestTelegramDualBotInit:
    """测试 __init__ 初始化。"""

    def test_init_bull_bear_no_judge(self):
        """无 judge_bot 时 judge 属性为 None。"""
        bull = MockTelegramBot()
        bear = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=bear)
        assert bot.bull is bull
        assert bot.bear is bear
        assert bot.judge is None

    def test_init_with_judge(self):
        """提供 judge_bot 时 judge 属性非 None。"""
        bull = MockTelegramBot()
        bear = MockTelegramBot()
        judge = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=bear, judge_bot=judge)
        assert bot.judge is judge


# ─── send_as 路由测试 ─────────────────────────────────────────────

class TestSendAsRouting:
    """测试 send_as 角色路由。"""

    @pytest.mark.asyncio
    async def test_send_as_bull_routes_to_bull(self):
        """bull 角色发送到 bull bot。"""
        bull = MockTelegramBot()
        bear = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=bear)
        await bot.send_as("bull", chat_id=123, text="正方发言")
        assert len(bull.calls) == 1
        assert bull.calls[0]["chat_id"] == 123
        assert bull.calls[0]["text"] == "正方发言"
        assert len(bear.calls) == 0

    @pytest.mark.asyncio
    async def test_send_as_bear_routes_to_bear(self):
        """bear 角色发送到 bear bot。"""
        bull = MockTelegramBot()
        bear = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=bear)
        await bot.send_as("bear", chat_id=456, text="反方反驳")
        assert len(bear.calls) == 1
        assert bear.calls[0]["chat_id"] == 456
        assert bear.calls[0]["text"] == "反方反驳"
        assert len(bull.calls) == 0

    @pytest.mark.asyncio
    async def test_send_as_judge_routes_to_judge(self):
        """judge 角色发送到 judge bot。"""
        bull = MockTelegramBot()
        bear = MockTelegramBot()
        judge = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=bear, judge_bot=judge)
        await bot.send_as("judge", chat_id=789, text="裁判裁决")
        assert len(judge.calls) == 1
        assert judge.calls[0]["chat_id"] == 789

    @pytest.mark.asyncio
    async def test_send_as_judge_no_judge_bot_raises(self):
        """无 judge_bot 时 send_as('judge') 抛 ValueError。"""
        bull = MockTelegramBot()
        bear = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=bear)
        with pytest.raises(ValueError, match="judge"):
            await bot.send_as("judge", chat_id=123, text="裁判")

    @pytest.mark.asyncio
    async def test_send_as_invalid_role_raises(self):
        """无效 role 抛 ValueError。"""
        bull = MockTelegramBot()
        bear = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=bear)
        with pytest.raises(ValueError, match="role"):
            await bot.send_as("admin", chat_id=123, text="xxx")


# ─── 长消息分段测试 ───────────────────────────────────────────────

class TestMessageSplitting:
    """测试长消息自动分段（4096 字符限制）。"""

    @pytest.mark.asyncio
    async def test_short_message_no_split(self):
        """短消息不分段，只发送 1 次。"""
        bull = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=MockTelegramBot())
        await bot.send_as("bull", chat_id=1, text="短消息")
        assert len(bull.calls) == 1
        assert bull.calls[0]["text"] == "短消息"

    @pytest.mark.asyncio
    async def test_message_exactly_4096_no_split(self):
        """恰好 4096 字符不分段。"""
        bull = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=MockTelegramBot())
        text = "A" * 4096
        await bot.send_as("bull", chat_id=1, text=text)
        assert len(bull.calls) == 1

    @pytest.mark.asyncio
    async def test_message_4097_splits_into_two(self):
        """4097 字符分成 2 段。"""
        bull = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=MockTelegramBot())
        text = "B" * 4097
        await bot.send_as("bull", chat_id=1, text=text)
        assert len(bull.calls) == 2
        assert len(bull.calls[0]["text"]) == 4096
        assert len(bull.calls[1]["text"]) == 1

    @pytest.mark.asyncio
    async def test_very_long_message_multiple_splits(self):
        """超长消息（12000 字符）分成 3 段。"""
        bull = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=MockTelegramBot())
        text = "C" * 12000
        await bot.send_as("bull", chat_id=1, text=text)
        assert len(bull.calls) == 3
        assert len(bull.calls[0]["text"]) == 4096
        assert len(bull.calls[1]["text"]) == 4096
        assert len(bull.calls[2]["text"]) == 3808


# ─── Sleep 测试 ──────────────────────────────────────────────────

class TestSendDelay:
    """测试发送前 sleep 规避 rate limit。"""

    @pytest.mark.asyncio
    async def test_sleep_called_before_send(self, monkeypatch):
        """发送前调用 asyncio.sleep。"""
        sleep_calls: list[float] = []
        original_sleep = __import__("asyncio").sleep

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        monkeypatch.setattr(
            "core.telegram_bot.asyncio.sleep", fake_sleep
        )
        bull = MockTelegramBot()
        bot = TelegramDualBot(bull_bot=bull, bear_bot=MockTelegramBot())
        await bot.send_as("bull", chat_id=1, text="hi")
        # 至少调用了 1 次 sleep（发送前）
        assert len(sleep_calls) >= 1
        # sleep 时间在 1-2s 范围内
        assert 1.0 <= sleep_calls[0] <= 2.0


# ─── 重试测试 ─────────────────────────────────────────────────────

class TestRetry:
    """测试发送失败重试 1 次。"""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self, monkeypatch):
        """第一次失败，重试成功。"""
        async def fake_sleep(seconds):
            pass  # 跳过真实 sleep

        monkeypatch.setattr(
            "core.telegram_bot.asyncio.sleep", fake_sleep
        )
        bull = MockTelegramBot(responses=[
            RuntimeError("network error"),
            {"message_id": 1, "chat_id": 1, "text": "ok"},
        ])
        bot = TelegramDualBot(bull_bot=bull, bear_bot=MockTelegramBot())
        result = await bot.send_as("bull", chat_id=1, text="retry me")
        # 第一次失败 + 重试成功 → 2 次调用
        assert len(bull.calls) == 2
        assert result["message_id"] == 1

    @pytest.mark.asyncio
    async def test_retry_still_fails_raises(self, monkeypatch):
        """重试仍失败 → 抛出异常。"""
        async def fake_sleep(seconds):
            pass

        monkeypatch.setattr(
            "core.telegram_bot.asyncio.sleep", fake_sleep
        )
        error = RuntimeError("permanent failure")
        bull = MockTelegramBot(responses=[error, error])
        bot = TelegramDualBot(bull_bot=bull, bear_bot=MockTelegramBot())
        with pytest.raises(RuntimeError, match="permanent failure"):
            await bot.send_as("bull", chat_id=1, text="fail")
        # 2 次尝试（初始 + 重试）
        assert len(bull.calls) == 2

    @pytest.mark.asyncio
    async def test_retry_uses_backoff(self, monkeypatch):
        """重试时使用指数退避（2s）。"""
        sleep_calls: list[float] = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        monkeypatch.setattr(
            "core.telegram_bot.asyncio.sleep", fake_sleep
        )
        bull = MockTelegramBot(responses=[
            RuntimeError("fail"),
            {"message_id": 1, "chat_id": 1, "text": "ok"},
        ])
        bot = TelegramDualBot(bull_bot=bull, bear_bot=MockTelegramBot())
        await bot.send_as("bull", chat_id=1, text="backoff test")
        # sleep_calls: [send_delay(~1.5), retry_delay(2.0), send_delay(~1.5)]
        # 至少有 2.0 的退避
        assert 2.0 in sleep_calls
