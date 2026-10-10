"""null_bot.py — NullBot 空实现 Bot（内部辩论模式用）

SPEC v2.0-rc3 第 7 节：NullBot 用于 C-Drive 内部辩论模式。
实现 TelegramDualBot 的接口但不发送消息，只存储在内存中。
用于不需要 Telegram 发送的场景（如 C-Drive 自驱动辩论）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("debate.null_bot")


class NullBot:
    """空实现 Bot：不发送 Telegram，只存储消息。

    实现 send_as 接口，与 TelegramDualBot 接口兼容。
    可替换 TelegramDualBot 用于内部辩论模式。
    """

    def __init__(self):
        self.messages: list[dict] = []

    async def send_as(self, role: str, chat_id: int, text: str) -> dict:
        """按角色存储消息（不发送）。

        与 TelegramDualBot.send_as 接口兼容。

        Args:
            role: 'bull' | 'bear' | 'judge'
            chat_id: Telegram 群 ID（存储但不使用）
            text: 消息文本

        Returns:
            {"ok": True, "role": role, "text": text}
        """
        msg = {"role": role, "chat_id": chat_id, "text": text}
        self.messages.append(msg)
        logger.debug("NullBot 存储消息: role=%s text=%s", role, text[:30])
        return {"ok": True, "role": role, "text": text}
