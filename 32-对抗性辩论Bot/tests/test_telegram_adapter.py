"""test_telegram_adapter.py — TelegramHTTPClient 单元测试（TDD RED phase）

测试 P0-2：直接 HTTP 调用 Telegram Bot API。

TelegramBotClient Protocol（来自 core.telegram_bot）：
    async def send_message(chat_id: int, text: str) -> dict

Telegram Bot API 端点：
- sendMessage: POST https://api.telegram.org/bot{token}/sendMessage
- getUpdates:  GET  https://api.telegram.org/bot{token}/getUpdates
- getChatMember: GET https://api.telegram.org/bot{token}/getChatMember
"""
from __future__ import annotations

import pytest

from core.telegram_adapter import TelegramHTTPClient


# ─── Mock httpx.AsyncClient ─────────────────────────────────────

class FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    """模拟 httpx.AsyncClient，记录请求并返回预设响应。"""

    def __init__(self, responses: list[dict] | None = None):
        self._responses = responses or []
        self._idx = 0
        self.requests: list[dict] = []

    async def post(self, url: str, json: dict = None, **kwargs):
        self.requests.append({"method": "POST", "url": url, "json": json})
        return self._next_response()

    async def get(self, url: str, params: dict = None, **kwargs):
        self.requests.append({"method": "GET", "url": url, "params": params})
        return self._next_response()

    def _next_response(self) -> FakeResponse:
        if self._idx < len(self._responses):
            data = self._responses[self._idx]
            self._idx += 1
            return FakeResponse(data)
        return FakeResponse({"ok": False, "description": "no more responses"})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def make_client(token="123:abc", responses=None):
    client = TelegramHTTPClient(token=token)
    fake = FakeAsyncClient(responses)
    client._client = fake  # 注入 mock
    return client, fake


# ─── send_message 测试 ───────────────────────────────────────────

class TestSendMessage:

    @pytest.mark.asyncio
    async def test_send_message_calls_sendMessage_endpoint(self):
        """send_message 调用 sendMessage API。"""
        client, fake = make_client(
            token="123:abc",
            responses=[{"ok": True, "result": {"message_id": 1}}],
        )
        result = await client.send_message(chat_id=456, text="hello")
        assert result["message_id"] == 1
        assert fake.requests[0]["method"] == "POST"
        assert "bot123:abc/sendMessage" in fake.requests[0]["url"]

    @pytest.mark.asyncio
    async def test_send_message_passes_chat_id_and_text(self):
        """send_message 传递 chat_id 和 text。"""
        client, fake = make_client(
            responses=[{"ok": True, "result": {"message_id": 1}}],
        )
        await client.send_message(chat_id=789, text="test text")
        body = fake.requests[0]["json"]
        assert body["chat_id"] == 789
        assert body["text"] == "test text"

    @pytest.mark.asyncio
    async def test_send_message_api_error_raises(self):
        """API 返回 ok=False 时抛异常。"""
        client, _ = make_client(
            responses=[{"ok": False, "description": "chat not found"}],
        )
        with pytest.raises(RuntimeError, match="chat not found"):
            await client.send_message(chat_id=1, text="x")


# ─── get_updates 测试 ────────────────────────────────────────────

class TestGetUpdates:

    @pytest.mark.asyncio
    async def test_get_updates_calls_getUpdates_endpoint(self):
        """get_updates 调用 getUpdates API。"""
        client, fake = make_client(
            responses=[{"ok": True, "result": []}],
        )
        updates = await client.get_updates(offset=0, timeout=30)
        assert updates == []
        assert fake.requests[0]["method"] == "GET"
        assert "getUpdates" in fake.requests[0]["url"]

    @pytest.mark.asyncio
    async def test_get_updates_passes_offset_and_timeout(self):
        """get_updates 传递 offset 和 timeout 参数。"""
        client, fake = make_client(
            responses=[{"ok": True, "result": []}],
        )
        await client.get_updates(offset=123, timeout=30)
        params = fake.requests[0]["params"]
        assert params["offset"] == 123
        assert params["timeout"] == 30

    @pytest.mark.asyncio
    async def test_get_updates_returns_result_list(self):
        """get_updates 返回 result 列表。"""
        update_data = [{"update_id": 1, "message": {"text": "/debate test"}}]
        client, _ = make_client(
            responses=[{"ok": True, "result": update_data}],
        )
        updates = await client.get_updates(offset=0)
        assert len(updates) == 1
        assert updates[0]["update_id"] == 1


# ─── get_chat_member 测试 ────────────────────────────────────────

class TestGetChatMember:

    @pytest.mark.asyncio
    async def test_get_chat_member_returns_status(self):
        """get_chat_member 返回成员状态。"""
        client, fake = make_client(
            responses=[{"ok": True, "result": {"status": "administrator"}}],
        )
        status = await client.get_chat_member(chat_id=456, user_id=789)
        assert status == "administrator"
        assert fake.requests[0]["method"] == "GET"
        assert "getChatMember" in fake.requests[0]["url"]
        params = fake.requests[0]["params"]
        assert params["chat_id"] == 456
        assert params["user_id"] == 789

    @pytest.mark.asyncio
    async def test_get_chat_member_api_error_raises(self):
        """API 返回 ok=False 时抛异常。"""
        client, _ = make_client(
            responses=[{"ok": False, "description": "user not found"}],
        )
        with pytest.raises(RuntimeError, match="user not found"):
            await client.get_chat_member(chat_id=1, user_id=2)


# ─── is_admin 测试 ───────────────────────────────────────────────

class TestIsAdmin:

    @pytest.mark.asyncio
    async def test_is_admin_creator(self):
        """creator 是管理员。"""
        client, _ = make_client(
            responses=[{"ok": True, "result": {"status": "creator"}}],
        )
        assert await client.is_admin(chat_id=1, user_id=2) is True

    @pytest.mark.asyncio
    async def test_is_admin_administrator(self):
        """administrator 是管理员。"""
        client, _ = make_client(
            responses=[{"ok": True, "result": {"status": "administrator"}}],
        )
        assert await client.is_admin(chat_id=1, user_id=2) is True

    @pytest.mark.asyncio
    async def test_is_admin_member_not_admin(self):
        """member 不是管理员。"""
        client, _ = make_client(
            responses=[{"ok": True, "result": {"status": "member"}}],
        )
        assert await client.is_admin(chat_id=1, user_id=2) is False

    @pytest.mark.asyncio
    async def test_is_admin_left_not_admin(self):
        """left 不是管理员。"""
        client, _ = make_client(
            responses=[{"ok": True, "result": {"status": "left"}}],
        )
        assert await client.is_admin(chat_id=1, user_id=2) is False
