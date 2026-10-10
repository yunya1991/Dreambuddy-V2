"""test_bot_handler.py — CommandHandler 单元测试（TDD RED phase）

测试 SPEC 第十章管理员命令集：
- /debate <话题> — 发起辩论（后台 task）
- /stop — 终止辩论
- /pause — 暂停辩论
- /resume — 恢复辩论
- /inject <观点> — 注入观点
- /change_topic <新话题> — 终止当前 + 新开
- 权限校验：非管理员 → 拒绝
- 话题黑名单过滤
- 未知命令 → 帮助文本
"""
from __future__ import annotations

import asyncio

import pytest

from core.bot_handler import CommandHandler
from core.config import AppConfig, TelegramConfig, TopicFilterConfig


# ─── Mock Orchestrator ───────────────────────────────────────────

class MockOrchestrator:
    """记录所有控制方法调用。"""

    def __init__(self):
        self.stop_calls: list[int] = []
        self.pause_calls: list[int] = []
        self.resume_calls: list[int] = []
        self.inject_calls: list[tuple[int, str]] = []
        self.clear_inject_calls: list[int] = []
        self.run_calls: list[dict] = []
        self.status = "idle"

    def stop(self, chat_id: int):
        self.stop_calls.append(chat_id)
        self.status = "done"

    def pause(self, chat_id: int):
        self.pause_calls.append(chat_id)
        self.status = "paused"

    def resume(self, chat_id: int):
        self.resume_calls.append(chat_id)
        self.status = "bull_turn"

    def inject(self, chat_id: int, view: str):
        self.inject_calls.append((chat_id, view))

    def clear_injected_views(self, chat_id: int):
        self.clear_inject_calls.append(chat_id)

    async def run(self, topic: str, chat_id: int, max_rounds: int = 2,
                  background: str = ""):
        self.run_calls.append({
            "topic": topic, "chat_id": chat_id,
            "max_rounds": max_rounds, "background": background,
        })
        self.status = "done"
        return None  # Mock DebateResult


class MockTelegramBot:
    """记录 send_as 调用。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def send_as(self, role: str, chat_id: int, text: str) -> dict:
        self.calls.append({"role": role, "chat_id": chat_id, "text": text})
        return {"message_id": len(self.calls)}


def make_handler(
    orchestrator: MockOrchestrator | None = None,
    telegram_bot: MockTelegramBot | None = None,
    config: AppConfig | None = None,
) -> tuple[CommandHandler, MockOrchestrator, MockTelegramBot]:
    """创建带 mock 依赖的 CommandHandler。"""
    orch = orchestrator or MockOrchestrator()
    bot = telegram_bot or MockTelegramBot()
    cfg = config or AppConfig()
    handler = CommandHandler(
        orchestrator=orch, telegram_bot=bot, config=cfg,
    )
    return handler, orch, bot


# ─── /debate 测试 ────────────────────────────────────────────────

class TestDebateCommand:
    """测试 /debate <话题> 命令。"""

    @pytest.mark.asyncio
    async def test_debate_starts_background_task(self):
        """/debate 创建后台任务执行辩论。"""
        handler, orch, bot = make_handler()
        reply = await handler.handle_command(
            "/debate BTC 是数字黄金", chat_id=123,
            user_id=1, is_admin=True,
        )
        assert "辩论开始" in reply or "BTC" in reply
        # 等待后台任务执行
        await asyncio.sleep(0.01)
        assert len(orch.run_calls) == 1
        assert orch.run_calls[0]["topic"] == "BTC 是数字黄金"
        assert orch.run_calls[0]["chat_id"] == 123

    @pytest.mark.asyncio
    async def test_debate_non_admin_rejected(self):
        """非管理员发起 /debate 被拒绝。"""
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/debate 测试", chat_id=1, user_id=2, is_admin=False,
        )
        assert "管理员" in reply
        await asyncio.sleep(0.01)
        assert len(orch.run_calls) == 0

    @pytest.mark.asyncio
    async def test_debate_no_topic(self):
        """/debate 无话题参数 → 提示用法。"""
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/debate", chat_id=1, user_id=1, is_admin=True,
        )
        assert "用法" in reply or "话题" in reply
        assert len(orch.run_calls) == 0

    @pytest.mark.asyncio
    async def test_debate_blacklisted_topic(self):
        """话题命中黑名单 → 警告。"""
        cfg = AppConfig(topic_filter=TopicFilterConfig(
            blacklist_keywords=["政治"],
        ))
        handler, orch, _ = make_handler(config=cfg)
        reply = await handler.handle_command(
            "/debate 政治话题", chat_id=1, user_id=1, is_admin=True,
        )
        assert "敏感" in reply or "黑名单" in reply
        await asyncio.sleep(0.01)
        assert len(orch.run_calls) == 0


# ─── /stop 测试 ──────────────────────────────────────────────────

class TestStopCommand:

    @pytest.mark.asyncio
    async def test_stop_calls_orchestrator(self):
        """/stop 调用 orchestrator.stop()。"""
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/stop", chat_id=42, user_id=1, is_admin=True,
        )
        assert "停止" in reply or "stop" in reply.lower()
        assert orch.stop_calls == [42]

    @pytest.mark.asyncio
    async def test_stop_non_admin_rejected(self):
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/stop", chat_id=1, user_id=2, is_admin=False,
        )
        assert "管理员" in reply
        assert len(orch.stop_calls) == 0


# ─── /pause /resume 测试 ─────────────────────────────────────────

class TestPauseResumeCommand:

    @pytest.mark.asyncio
    async def test_pause_calls_orchestrator(self):
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/pause", chat_id=42, user_id=1, is_admin=True,
        )
        assert "暂停" in reply
        assert orch.pause_calls == [42]

    @pytest.mark.asyncio
    async def test_resume_calls_orchestrator(self):
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/resume", chat_id=42, user_id=1, is_admin=True,
        )
        assert "恢复" in reply
        assert orch.resume_calls == [42]

    @pytest.mark.asyncio
    async def test_pause_non_admin_rejected(self):
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/pause", chat_id=1, user_id=2, is_admin=False,
        )
        assert "管理员" in reply
        assert len(orch.pause_calls) == 0


# ─── /inject 测试 ────────────────────────────────────────────────

class TestInjectCommand:

    @pytest.mark.asyncio
    async def test_inject_calls_orchestrator(self):
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/inject 这是群主观点", chat_id=42, user_id=1, is_admin=True,
        )
        assert "注入" in reply
        assert orch.inject_calls == [(42, "这是群主观点")]

    @pytest.mark.asyncio
    async def test_inject_no_view(self):
        """/inject 无参数 → 提示用法。"""
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/inject", chat_id=1, user_id=1, is_admin=True,
        )
        assert "用法" in reply or "观点" in reply
        assert len(orch.inject_calls) == 0

    @pytest.mark.asyncio
    async def test_inject_clear(self):
        """/inject clear 清空注入观点。"""
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/inject clear", chat_id=42, user_id=1, is_admin=True,
        )
        assert "清空" in reply or "clear" in reply.lower()


# ─── /change_topic 测试 ──────────────────────────────────────────

class TestChangeTopicCommand:

    @pytest.mark.asyncio
    async def test_change_topic_stops_and_starts_new(self):
        """/change_topic 停止当前辩论 + 开启新话题。"""
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/change_topic 新话题", chat_id=42, user_id=1, is_admin=True,
        )
        # 先 stop
        assert orch.stop_calls == [42]
        # 等待后台新辩论启动
        await asyncio.sleep(0.01)
        assert len(orch.run_calls) == 1
        assert orch.run_calls[0]["topic"] == "新话题"

    @pytest.mark.asyncio
    async def test_change_topic_no_topic(self):
        handler, orch, _ = make_handler()
        reply = await handler.handle_command(
            "/change_topic", chat_id=1, user_id=1, is_admin=True,
        )
        assert "用法" in reply or "话题" in reply


# ─── 未知命令测试 ────────────────────────────────────────────────

class TestUnknownCommand:

    @pytest.mark.asyncio
    async def test_unknown_command_returns_help(self):
        handler, _, _ = make_handler()
        reply = await handler.handle_command(
            "/unknown", chat_id=1, user_id=1, is_admin=True,
        )
        assert "可用命令" in reply or "帮助" in reply or "用法" in reply

    @pytest.mark.asyncio
    async def test_no_command_returns_help(self):
        handler, _, _ = make_handler()
        reply = await handler.handle_command(
            "hello world", chat_id=1, user_id=1, is_admin=True,
        )
        assert "可用命令" in reply or "帮助" in reply or "用法" in reply


# ─── 群白名单测试 ────────────────────────────────────────────────

class TestChatWhitelist:

    @pytest.mark.asyncio
    async def test_unauthorized_chat_rejected(self):
        """非白名单群发起 /debate 被拒绝。"""
        cfg = AppConfig(telegram=TelegramConfig(
            allowed_chat_ids=[100],  # 只允许 100
        ))
        handler, orch, _ = make_handler(config=cfg)
        reply = await handler.handle_command(
            "/debate 测试", chat_id=999, user_id=1, is_admin=True,
        )
        assert "授权" in reply or "白名单" in reply
        await asyncio.sleep(0.01)
        assert len(orch.run_calls) == 0

    @pytest.mark.asyncio
    async def test_empty_whitelist_allows_all(self):
        """白名单为空时允许所有群。"""
        cfg = AppConfig(telegram=TelegramConfig(allowed_chat_ids=[]))
        handler, orch, _ = make_handler(config=cfg)
        await handler.handle_command(
            "/debate 测试", chat_id=999, user_id=1, is_admin=True,
        )
        await asyncio.sleep(0.01)
        assert len(orch.run_calls) == 1
