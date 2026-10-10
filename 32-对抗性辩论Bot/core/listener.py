"""listener.py — Telegram 消息监听器

P0-3：长轮询 getUpdates + is_admin 校验 + 路由到 CommandHandler + 回复。

职责：
1. 长轮询 getUpdates(offset, timeout)
2. 对每条含 message 的 update：
   - 跳过 bot 消息（from.is_bot == True）
   - 提取 text / chat_id / user_id
   - 调用 is_admin(chat_id, user_id) 获取权限
   - 调用 command_handler.handle_command(text, chat_id, user_id, is_admin)
   - 将回复通过 send_message 发回群
3. 维护 update_id offset（取最大 update_id + 1）
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("debate.listener")


class TelegramListener:
    """Telegram 消息监听器：长轮询 + 路由到 CommandHandler。"""

    def __init__(self, telegram_client, command_handler,
                 poll_timeout: int = 30):
        """
        Args:
            telegram_client: TelegramHTTPClient（需有 get_updates/is_admin/send_message）
            command_handler: CommandHandler（需有 handle_command）
            poll_timeout: 长轮询超时（秒）
        """
        self.tg = telegram_client
        self.handler = command_handler
        self.poll_timeout = poll_timeout
        self.offset: int = 0
        self._running = False

    async def run_once(self) -> int:
        """执行一次轮询周期，返回处理的 update 数量。"""
        updates = await self.tg.get_updates(
            offset=self.offset, timeout=self.poll_timeout,
        )
        if not updates:
            return 0

        for update in updates:
            await self._process_update(update)

        # 更新 offset 为最大 update_id + 1
        max_id = max(u["update_id"] for u in updates)
        self.offset = max_id + 1
        return len(updates)

    async def run(self, max_cycles: int | None = None):
        """启动长轮询循环。

        Args:
            max_cycles: 最大轮询次数（None=无限），用于测试
        """
        self._running = True
        cycle = 0
        logger.info("TelegramListener 启动，开始长轮询")
        try:
            while self._running:
                await self.run_once()
                cycle += 1
                if max_cycles is not None and cycle >= max_cycles:
                    break
        finally:
            self._running = False
            logger.info("TelegramListener 停止")

    def stop(self):
        """停止轮询循环。"""
        self._running = False

    async def _process_update(self, update: dict):
        """处理单条 update。"""
        message = update.get("message")
        if not message:
            return

        sender = message.get("from", {})
        # 跳过 bot 消息，杜绝死循环
        if sender.get("is_bot", False):
            return

        text = message.get("text", "")
        if not text:
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        user_id = sender.get("id")
        if chat_id is None or user_id is None:
            return

        try:
            is_admin = await self.tg.is_admin(chat_id, user_id)
        except Exception as e:
            logger.warning("is_admin 校验失败: %s", e)
            is_admin = False

        try:
            reply = await self.handler.handle_command(
                text, chat_id, user_id, is_admin,
            )
        except Exception as e:
            logger.exception("命令处理异常: %s", e)
            reply = "⚠️ 命令处理异常，请稍后重试"

        if reply:
            try:
                await self.tg.send_message(chat_id, reply)
            except Exception as e:
                logger.warning("回复消息发送失败: %s", e)
