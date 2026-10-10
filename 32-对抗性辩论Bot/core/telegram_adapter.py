"""telegram_adapter.py — Telegram Bot API 直接 HTTP 客户端

P0-2：实现 TelegramBotClient Protocol，直接 HTTP 调用 Telegram Bot API
（参考 15-监控告警系统/feishu_alert.py 的 requests 模式，但用 httpx 异步）。

Telegram Bot API 端点：
- sendMessage:  POST https://api.telegram.org/bot{token}/sendMessage
- getUpdates:   GET  https://api.telegram.org/bot{token}/getUpdates
- getChatMember: GET https://api.telegram.org/bot{token}/getChatMember
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("debate.telegram_adapter")

API_BASE = "https://api.telegram.org"

ADMIN_STATUSES = {"creator", "administrator"}


class TelegramHTTPClient:
    """Telegram Bot API 直接 HTTP 客户端。

    实现 TelegramBotClient Protocol（async send_message），
    同时提供 get_updates / get_chat_member / is_admin 供 listener 使用。
    """

    def __init__(self, token: str, api_base: str = API_BASE,
                 timeout: float = 30.0):
        self.token = token
        self.api_base = api_base
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def _request(self, method: str, endpoint: str,
                       **kwargs) -> dict:
        """统一请求处理，校验 ok 字段。"""
        client = self._get_client()
        url = self._url(endpoint)
        if method == "GET":
            resp = await client.get(url, params=kwargs)
        else:
            resp = await client.post(url, json=kwargs)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(
                f"Telegram API error ({endpoint}): "
                f"{data.get('description', 'unknown')}"
            )
        return data["result"]

    # ─── TelegramBotClient Protocol ───────────────────────────

    async def send_message(self, chat_id: int, text: str) -> dict:
        """发送消息到指定 chat。"""
        return await self._request(
            "POST", "sendMessage", chat_id=chat_id, text=text,
        )

    # ─── Listener 辅助方法 ────────────────────────────────────

    async def get_updates(self, offset: int = 0,
                          timeout: int = 30) -> list[dict]:
        """长轮询获取新消息。

        Args:
            offset: 上次处理的最后一条 update_id + 1
            timeout: 长轮询超时（秒）

        Returns:
            update 列表
        """
        return await self._request(
            "GET", "getUpdates", offset=offset, timeout=timeout,
        )

    async def get_chat_member(self, chat_id: int,
                               user_id: int) -> str:
        """获取用户在群中的成员状态。

        Returns:
            状态字符串（creator/administrator/member/left/kicked）
        """
        result = await self._request(
            "GET", "getChatMember", chat_id=chat_id, user_id=user_id,
        )
        return result["status"]

    async def is_admin(self, chat_id: int, user_id: int) -> bool:
        """判断用户是否为群管理员（creator 或 administrator）。"""
        status = await self.get_chat_member(chat_id, user_id)
        return status in ADMIN_STATUSES

    # ─── 资源管理 ──────────────────────────────────────────────

    async def close(self):
        """关闭 HTTP 客户端。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
