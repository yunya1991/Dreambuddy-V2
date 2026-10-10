"""bot_handler.py — Telegram 命令处理器

SPEC 第十章管理员命令集：
- /debate <话题> — 发起辩论（后台 task）
- /stop — 终止辩论（当前轮完成后停）
- /pause — 暂停辩论
- /resume — 恢复辩论
- /inject <观点> — 注入群主观点（/inject clear 清空）
- /change_topic <新话题> — 终止当前 + 新开
- 权限校验：非管理员拒绝
- 话题黑名单过滤
- 群白名单过滤
"""
from __future__ import annotations

import asyncio
import logging

from core.config import AppConfig

logger = logging.getLogger("debate.bot_handler")

_ADMIN_ONLY_COMMANDS = {"/stop", "/pause", "/resume", "/inject", "/change_topic"}


class CommandHandler:
    """Telegram 命令处理器：解析命令 → 权限校验 → 路由到 orchestrator。"""

    def __init__(self, orchestrator, telegram_bot, config: AppConfig):
        self.orchestrator = orchestrator
        self.telegram_bot = telegram_bot
        self.config = config

    async def handle_command(
        self, text: str, chat_id: int, user_id: int,
        is_admin: bool,
    ) -> str:
        """处理用户命令，返回回复文本。

        Args:
            text: 用户发送的原始文本
            chat_id: Telegram 群 ID
            user_id: 发送者用户 ID
            is_admin: 是否为群管理员
        """
        parts = text.strip().split(maxsplit=1)
        if not parts or not parts[0].startswith("/"):
            return self._help_text()

        command = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        # 所有命令都需要管理员权限
        if command in _ADMIN_ONLY_COMMANDS and not is_admin:
            return "⚠️ 仅群主/管理员可操作此命令"

        if command == "/debate":
            return await self._handle_debate(args, chat_id, is_admin)
        if command == "/stop":
            return self._handle_stop(chat_id)
        if command == "/pause":
            return self._handle_pause(chat_id)
        if command == "/resume":
            return self._handle_resume(chat_id)
        if command == "/inject":
            return self._handle_inject(args, chat_id)
        if command == "/change_topic":
            return await self._handle_change_topic(args, chat_id)

        return self._help_text()

    # ─── /debate ──────────────────────────────────────────────

    async def _handle_debate(self, topic: str, chat_id: int,
                             is_admin: bool) -> str:
        if not is_admin:
            return "⚠️ 仅群主/管理员可操作此命令"
        if not topic:
            return "用法：/debate <话题>"

        # 群白名单
        whitelist = self.config.telegram.allowed_chat_ids
        if whitelist and chat_id not in whitelist:
            return "⚠️ 此群未在白名单中，无权使用辩论 Bot"

        # 话题黑名单
        blacklist = self.config.topic_filter.blacklist_keywords
        for kw in blacklist:
            if kw in topic:
                return f"⚠️ 话题包含敏感关键词「{kw}」，请修改后重试"

        # 后台启动辩论
        max_rounds = self.config.debate.max_rounds
        asyncio.create_task(
            self.orchestrator.run(topic, chat_id, max_rounds)
        )
        logger.info("辩论启动 (chat_id=%s, topic=%s)", chat_id, topic)
        return f"🎤 辩论开始：{topic}（{max_rounds} 轮）"

    # ─── /stop ────────────────────────────────────────────────

    def _handle_stop(self, chat_id: int) -> str:
        self.orchestrator.stop(chat_id)
        return "⏹️ 辩论将在当前轮完成后停止，仍会生成完整记录"

    # ─── /pause ───────────────────────────────────────────────

    def _handle_pause(self, chat_id: int) -> str:
        self.orchestrator.pause(chat_id)
        return "⏸️ 辩论已暂停，使用 /resume 恢复（30 分钟内未恢复将自动停止）"

    # ─── /resume ──────────────────────────────────────────────

    def _handle_resume(self, chat_id: int) -> str:
        self.orchestrator.resume(chat_id)
        return "▶️ 辩论已恢复"

    # ─── /inject ──────────────────────────────────────────────

    def _handle_inject(self, args: str, chat_id: int) -> str:
        if not args:
            return "用法：/inject <观点>（或 /inject clear 清空已注入观点）"
        if args.lower() == "clear":
            self.orchestrator.clear_injected_views(chat_id)
            return "🧹 已清空注入观点"
        self.orchestrator.inject(chat_id, args)
        return f"💉 已注入观点：「{args}」，下一轮辩手将回应此观点"

    # ─── /change_topic ───────────────────────────────────────

    async def _handle_change_topic(self, topic: str, chat_id: int) -> str:
        if not topic:
            return "用法：/change_topic <新话题>"
        # 先停止当前辩论
        self.orchestrator.stop(chat_id)
        # 话题黑名单
        blacklist = self.config.topic_filter.blacklist_keywords
        for kw in blacklist:
            if kw in topic:
                return f"⚠️ 话题包含敏感关键词「{kw}」，请修改后重试"
        # 启动新辩论
        max_rounds = self.config.debate.max_rounds
        asyncio.create_task(
            self.orchestrator.run(topic, chat_id, max_rounds)
        )
        return f"🔄 话题切换：{topic}（旧辩论已停止，新辩论启动中）"

    # ─── 帮助文本 ──────────────────────────────────────────────

    def _help_text(self) -> str:
        return (
            "📋 可用命令：\n"
            "/debate <话题> — 发起一场辩论\n"
            "/stop — 停止辩论（当前轮完成后）\n"
            "/pause — 暂停辩论\n"
            "/resume — 恢复辩论\n"
            "/inject <观点> — 注入群主观点\n"
            "/inject clear — 清空注入观点\n"
            "/change_topic <新话题> — 切换话题\n"
            "（所有命令仅群主/管理员可用）"
        )
