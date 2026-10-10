"""test_null_bot.py — NullBot 单元测试 (TDD RED→GREEN)

SPEC v2.0-rc3 第 7 节：NullBot 用于内部辩论模式（不发送 Telegram）。
实现 TelegramDualBot 接口但只存储消息，不发送。
"""
from __future__ import annotations

import pytest

from core.null_bot import NullBot


class TestNullBot:
    """NullBot 不发送但保留消息。"""

    def test_create(self):
        bot = NullBot()
        assert bot is not None

    def test_messages_empty_initially(self):
        """初始化时 messages 为空。"""
        bot = NullBot()
        assert bot.messages == []

    @pytest.mark.asyncio
    async def test_send_as_bull(self):
        """send_as 存储消息而不发送。"""
        bot = NullBot()
        result = await bot.send_as("bull", chat_id=-100, text="正方论点")
        assert result["ok"] is True
        assert len(bot.messages) == 1
        assert bot.messages[0]["role"] == "bull"
        assert bot.messages[0]["text"] == "正方论点"

    @pytest.mark.asyncio
    async def test_send_as_multiple_roles(self):
        """多次发送存储所有消息。"""
        bot = NullBot()
        await bot.send_as("bull", -100, "正方")
        await bot.send_as("bear", -100, "反方")
        await bot.send_as("judge", -100, "裁判")
        assert len(bot.messages) == 3
        assert bot.messages[0]["role"] == "bull"
        assert bot.messages[1]["role"] == "bear"
        assert bot.messages[2]["role"] == "judge"

    @pytest.mark.asyncio
    async def test_send_as_returns_ok(self):
        """send_as 返回 ok=True。"""
        bot = NullBot()
        result = await bot.send_as("bull", -100, "test")
        assert "ok" in result
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_send_as_preserves_chat_id(self):
        """send_as 保留 chat_id。"""
        bot = NullBot()
        await bot.send_as("bull", -1003981441400, "test")
        assert bot.messages[0]["chat_id"] == -1003981441400
