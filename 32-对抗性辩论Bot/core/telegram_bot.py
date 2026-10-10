"""telegram_bot.py — TelegramDualBot 双 Bot 封装

SPEC 3.5:
- 持有 bull/bear/(judge) 三个 Bot 实例
- send_as(role, chat_id, text) 按角色路由
- 长消息自动分段（4096 字符限制）
- 发送前 sleep 1-2s 规避 rate limit
- 发送失败重试 1 次（指数退避 2s），仍失败则抛出异常

采用 Protocol 注入模式（与 LLMClient 一致），便于测试 mock。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger("debate.telegram")


class TelegramBotClient(Protocol):
    """Telegram Bot 客户端接口（duck-typed）。

    任何拥有 async send_message(chat_id, text) -> dict 的对象均可。
    """

    async def send_message(self, chat_id: int, text: str) -> dict:
        """发送消息到指定 chat，返回 message 信息。"""
        ...


class TelegramDualBot:
    """双 Bot 封装：按角色路由消息发送。

    - bull/bear bot 必须提供
    - judge bot 可选（用于裁判发言）
    - 长消息自动分段（4096 字符限制）
    - 发送前 sleep 1-2s 规避 rate limit
    - 发送失败重试 1 次（指数退避 2s），仍失败则抛出异常
    """

    MAX_MESSAGE_LENGTH = 4096

    def __init__(
        self,
        bull_bot: TelegramBotClient,
        bear_bot: TelegramBotClient,
        judge_bot: TelegramBotClient | None = None,
        send_delay: float = 1.5,
        retry_delay: float = 2.0,
        max_retries: int = 1,
    ):
        self.bull = bull_bot
        self.bear = bear_bot
        self.judge = judge_bot
        self.send_delay = send_delay
        self.retry_delay = retry_delay
        self.max_retries = max_retries

    async def send_as(self, role: str, chat_id: int, text: str) -> dict:
        """按角色发送消息。

        Args:
            role: 'bull' | 'bear' | 'judge'
            chat_id: Telegram 群 ID
            text: 消息文本

        Returns:
            最后一条分段消息的返回值

        Raises:
            ValueError: 无效 role 或 judge 未配置
            Exception: 重试后仍发送失败
        """
        bot = self._get_bot(role)
        segments = self._split_message(text)

        last_result: dict | None = None
        for segment in segments:
            last_result = await self._send_with_retry(bot, chat_id, segment)

        return last_result or {}

    def _get_bot(self, role: str) -> TelegramBotClient:
        """根据角色获取对应 bot。"""
        if role == "bull":
            return self.bull
        if role == "bear":
            return self.bear
        if role == "judge":
            if self.judge is None:
                raise ValueError("judge bot 未配置")
            return self.judge
        raise ValueError(f"无效的 role: {role}（可选: bull/bear/judge）")

    def _split_message(self, text: str) -> list[str]:
        """长消息分段，每段不超过 4096 字符。"""
        if len(text) <= self.MAX_MESSAGE_LENGTH:
            return [text]
        return [
            text[i:i + self.MAX_MESSAGE_LENGTH]
            for i in range(0, len(text), self.MAX_MESSAGE_LENGTH)
        ]

    async def _send_with_retry(
        self, bot: TelegramBotClient, chat_id: int, text: str,
    ) -> dict:
        """发送单段消息，失败重试 max_retries 次。"""
        # 发送前 sleep 规避 rate limit
        await asyncio.sleep(self.send_delay)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await bot.send_message(chat_id, text)
            except Exception as e:
                last_error = e
                logger.warning(
                    "发送失败 (attempt %d/%d): %s",
                    attempt + 1, self.max_retries + 1, e,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay)

        raise last_error  # type: ignore[misc]
