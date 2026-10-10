"""test_listener.py — TelegramListener 单元测试（TDD RED phase）

测试 P0-3：长轮询 getUpdates + is_admin 校验 + 路由到 CommandHandler + 回复消息。

Listener 职责：
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

from typing import Sequence

import pytest

from core.listener import TelegramListener


# ─── Mock 组件 ───────────────────────────────────────────────────

class MockTelegramClient:
    """模拟 TelegramHTTPClient。"""

    def __init__(self, updates_seq: Sequence[list[dict]] | None = None,
                 admin_map: dict[tuple[int, int], bool] | None = None):
        self._updates_seq = list(updates_seq) if updates_seq else []
        self._idx = 0
        self.admin_map = admin_map or {}
        self.send_calls: list[dict] = []
        self.get_updates_calls: list[dict] = []

    async def get_updates(self, offset: int = 0, timeout: int = 30) -> list[dict]:
        self.get_updates_calls.append({"offset": offset, "timeout": timeout})
        if self._idx < len(self._updates_seq):
            result = self._updates_seq[self._idx]
            self._idx += 1
            return result
        return []  # 无更多更新 → 空列表

    async def is_admin(self, chat_id: int, user_id: int) -> bool:
        return self.admin_map.get((chat_id, user_id), False)

    async def send_message(self, chat_id: int, text: str) -> dict:
        self.send_calls.append({"chat_id": chat_id, "text": text})
        return {"message_id": len(self.send_calls)}


class MockCommandHandler:
    """模拟 CommandHandler。"""

    def __init__(self, replies: dict[str, str] | None = None):
        self._replies = replies or {}
        self.calls: list[dict] = []

    async def handle_command(self, text: str, chat_id: int, user_id: int,
                             is_admin: bool) -> str:
        self.calls.append({
            "text": text, "chat_id": chat_id,
            "user_id": user_id, "is_admin": is_admin,
        })
        return self._replies.get(text, f"回复: {text}")


def make_listener(
    updates_seq=None, admin_map=None, replies=None,
):
    tg = MockTelegramClient(updates_seq, admin_map)
    handler = MockCommandHandler(replies)
    listener = TelegramListener(telegram_client=tg, command_handler=handler)
    return listener, tg, handler


def make_update(update_id: int, chat_id: int, user_id: int,
                text: str, is_bot: bool = False) -> dict:
    """构造 Telegram update 对象。"""
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id},
            "from": {"id": user_id, "is_bot": is_bot},
            "text": text,
        },
    }


# ─── 基本路由测试 ────────────────────────────────────────────────

class TestBasicRouting:

    @pytest.mark.asyncio
    async def test_processes_command_sends_reply(self):
        """收到命令后调用 handler 并发送回复。"""
        listener, tg, handler = make_listener(
            updates_seq=[[make_update(1, 100, 200, "/debate 测试")]],
            admin_map={(100, 200): True},
        )
        await listener.run_once()

        # handler 被调用
        assert len(handler.calls) == 1
        assert handler.calls[0]["text"] == "/debate 测试"
        assert handler.calls[0]["chat_id"] == 100
        assert handler.calls[0]["is_admin"] is True

        # 回复被发送
        assert len(tg.send_calls) == 1
        assert tg.send_calls[0]["chat_id"] == 100

    @pytest.mark.asyncio
    async def test_skips_bot_messages(self):
        """bot 发送的消息被跳过。"""
        listener, tg, handler = make_listener(
            updates_seq=[[make_update(1, 100, 200, "bot msg", is_bot=True)]],
            admin_map={(100, 200): True},
        )
        await listener.run_once()
        assert len(handler.calls) == 0
        assert len(tg.send_calls) == 0

    @pytest.mark.asyncio
    async def test_skips_updates_without_message(self):
        """无 message 字段的 update 被跳过（如 callback_query）。"""
        listener, tg, handler = make_listener(
            updates_seq=[[{"update_id": 1, "callback_query": {}}]],
        )
        await listener.run_once()
        assert len(handler.calls) == 0


# ─── 权限校验测试 ────────────────────────────────────────────────

class TestAdminCheck:

    @pytest.mark.asyncio
    async def test_admin_status_passed_to_handler(self):
        """is_admin 结果传递给 handler。"""
        listener, _, handler = make_listener(
            updates_seq=[[make_update(1, 100, 200, "/stop")]],
            admin_map={(100, 200): False},  # 非管理员
        )
        await listener.run_once()
        assert handler.calls[0]["is_admin"] is False

    @pytest.mark.asyncio
    async def test_non_admin_command_gets_rejected_reply(self):
        """非管理员命令收到拒绝回复。"""
        listener, tg, handler = make_listener(
            updates_seq=[[make_update(1, 100, 200, "/stop")]],
            admin_map={(100, 200): False},
            replies={"/stop": "⚠️ 仅群主/管理员可操作此命令"},
        )
        await listener.run_once()
        # 回复中应包含管理员提示
        assert "管理员" in tg.send_calls[0]["text"]


# ─── offset 维护测试 ─────────────────────────────────────────────

class TestOffsetManagement:

    @pytest.mark.asyncio
    async def test_offset_updated_to_max_id_plus_one(self):
        """offset 更新为最大 update_id + 1。"""
        listener, tg, _ = make_listener(
            updates_seq=[
                [make_update(10, 100, 200, "a"),
                 make_update(12, 100, 200, "b")],
            ],
            admin_map={(100, 200): True},
        )
        await listener.run_once()
        # 下一次 get_updates 的 offset 应为 13
        assert listener.offset == 13

    @pytest.mark.asyncio
    async def test_offset_passed_to_get_updates(self):
        """offset 传递给 get_updates。"""
        listener, tg, _ = make_listener(
            updates_seq=[[make_update(5, 100, 200, "a")]],
            admin_map={(100, 200): True},
        )
        listener.offset = 5
        await listener.run_once()
        assert tg.get_updates_calls[0]["offset"] == 5


# ─── 长轮询循环测试 ──────────────────────────────────────────────

class TestRunLoop:

    @pytest.mark.asyncio
    async def test_run_loops_until_no_updates(self):
        """run() 持续轮询，直到无更新。"""
        listener, tg, _ = make_listener(
            updates_seq=[
                [make_update(1, 100, 200, "/debate a")],
                [],  # 第二次空 → 退出
            ],
            admin_map={(100, 200): True},
        )
        await listener.run(max_cycles=2)
        # 调用了 2 次 get_updates
        assert len(tg.get_updates_calls) == 2

    @pytest.mark.asyncio
    async def test_run_handles_multiple_updates_per_cycle(self):
        """单次 get_updates 返回多条消息时全部处理。"""
        listener, _, handler = make_listener(
            updates_seq=[
                [make_update(1, 100, 200, "/debate a"),
                 make_update(2, 100, 200, "/debate b")],
                [],
            ],
            admin_map={(100, 200): True},
        )
        await listener.run(max_cycles=2)
        assert len(handler.calls) == 2
