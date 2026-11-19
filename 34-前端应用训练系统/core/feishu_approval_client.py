# -*- coding: utf-8 -*-
"""P0-D3D Phase 2: 真实飞书审批 REST 客户端。

定位：飞书只是“人类授权通道”，不持有 GateFlow 状态。

硬约束：
  - 凭据只从环境变量读取（FEISHU_APP_ID / FEISHU_APP_SECRET），禁止硬编码；
  - HTTP transport 可注入，单测无需真实凭据/网络；
  - 所有失败结构化返回（FeishuResult），FAIL-OPEN，不把异常抛进主链路；
  - tenant_access_token 带过期缓存。
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_BASE_URL = "https://open.feishu.cn"
TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
CREATE_INSTANCE_PATH = "/open-apis/approval/v4/instances"
INSTANCE_PATH = "/open-apis/approval/v4/instances/{instance_code}"
APPROVAL_TASK_PATH = "/open-apis/approval/v4/instances/{instance_code}/tasks/{task_id}/{action}"
MESSAGE_PATH = "/open-apis/im/v1/messages"

# 飞书限流/瞬时错误：可重试；权限/参数错误不可重试。
_RETRYABLE_CODES = frozenset({99991400, 99991661, 99991663, 99991664})


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str
    base_url: str = DEFAULT_BASE_URL
    user_id_type: str = "user_id"

    @classmethod
    def from_env(cls, environ: Optional[Dict[str, str]] = None) -> Optional["FeishuConfig"]:
        env = os.environ if environ is None else environ
        app_id = str(env.get("FEISHU_APP_ID") or "").strip()
        app_secret = str(env.get("FEISHU_APP_SECRET") or "").strip()
        if not app_id or not app_secret:
            return None
        return cls(
            app_id=app_id,
            app_secret=app_secret,
            base_url=str(env.get("FEISHU_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            user_id_type=str(env.get("FEISHU_USER_ID_TYPE") or "user_id"),
        )


@dataclass
class FeishuResult:
    ok: bool
    code: int = 0
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    retryable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "code": self.code,
            "error": self.error,
            "retryable": self.retryable,
            "data": self.data,
        }


# transport(method, url, headers, body, timeout) -> (http_status, payload)
HttpTransport = Callable[
    [str, str, Dict[str, str], Optional[bytes], float], Tuple[int, Dict[str, Any]]
]


def urllib_transport(
    method: str,
    url: str,
    headers: Dict[str, str],
    body: Optional[bytes],
    timeout: float,
) -> Tuple[int, Dict[str, Any]]:
    """默认 HTTP 传输；网络异常返回 (0, {...})，由调用方统一降级。"""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code or 0)
        raw = exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - FAIL-OPEN
        return 0, {"error": str(exc)}
    if not raw:
        return status, {}
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {"raw": raw[:500]}
    return status, payload if isinstance(payload, dict) else {"raw": payload}


class FeishuApprovalClient:
    """飞书审批 + IM 的最小 REST 客户端（只做通道，不做状态机）。"""

    def __init__(
        self,
        config: Optional[FeishuConfig] = None,
        *,
        transport: Optional[HttpTransport] = None,
        timeout: float = 10.0,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.config = config if config is not None else FeishuConfig.from_env()
        self.transport = transport or urllib_transport
        self.timeout = float(timeout)
        self._clock = clock or time.time
        self._token = ""
        self._token_expiry = 0.0
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self.config is not None

    # ── 内部 ──────────────────────────────────────────────────────────────
    def _call(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> FeishuResult:
        if not self.config:
            return FeishuResult(False, error="feishu_not_configured")
        token = self.get_tenant_access_token()
        if not token:
            return FeishuResult(False, error="feishu_token_unavailable", retryable=True)

        url = self.config.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            status, data = self.transport(method, url, headers, payload, self.timeout)
        except Exception as exc:  # noqa: BLE001 - FAIL-OPEN
            return FeishuResult(False, error="transport_error:%s" % exc, retryable=True)

        if not status:
            return FeishuResult(
                False,
                error="transport_error:%s" % str(data.get("error") or "unknown"),
                retryable=True,
            )
        code = int(data.get("code") or 0)
        if status >= 500:
            return FeishuResult(
                False, code=code, data=data, error="http_%s" % status, retryable=True
            )
        if status >= 400 or code != 0:
            return FeishuResult(
                False,
                code=code,
                data=data,
                error=str(data.get("msg") or "http_%s" % status),
                retryable=code in _RETRYABLE_CODES,
            )
        inner = data.get("data")
        return FeishuResult(True, code=code, data=inner if isinstance(inner, dict) else data)

    # ── token ─────────────────────────────────────────────────────────────
    def get_tenant_access_token(self, force: bool = False) -> str:
        if not self.config:
            return ""
        with self._lock:
            now = float(self._clock())
            if not force and self._token and now < self._token_expiry:
                return self._token
            body = json.dumps(
                {"app_id": self.config.app_id, "app_secret": self.config.app_secret}
            ).encode("utf-8")
            try:
                status, data = self.transport(
                    "POST",
                    self.config.base_url + TOKEN_PATH,
                    {"Content-Type": "application/json; charset=utf-8"},
                    body,
                    self.timeout,
                )
            except Exception:
                return ""
            if not status or int(data.get("code") or 0) != 0:
                return ""
            token = str(data.get("tenant_access_token") or "")
            if not token:
                return ""
            expire = float(data.get("expire") or 7200)
            # 提前 120s 过期，避免临界失效。
            self._token = token
            self._token_expiry = now + max(60.0, expire - 120.0)
            return token

    # ── 审批实例 ──────────────────────────────────────────────────────────
    def create_approval_instance(
        self,
        approval_code: str,
        form_values: List[Dict[str, Any]],
        user_id: str,
        *,
        uuid: str = "",
    ) -> FeishuResult:
        if not approval_code:
            return FeishuResult(False, error="approval_code_required")
        if not user_id:
            return FeishuResult(False, error="requester_user_id_required")
        body: Dict[str, Any] = {
            "approval_code": str(approval_code),
            "user_id": str(user_id),
            "form": json.dumps(form_values or [], ensure_ascii=False),
        }
        if uuid:
            body["uuid"] = str(uuid)
        result = self._call(
            "POST",
            CREATE_INSTANCE_PATH,
            body=body,
            params={"user_id_type": self.config.user_id_type} if self.config else None,
        )
        if result.ok and not result.data.get("instance_code"):
            return FeishuResult(
                False, code=result.code, data=result.data, error="missing_instance_code"
            )
        return result

    def get_instance(self, instance_code: str) -> FeishuResult:
        if not instance_code:
            return FeishuResult(False, error="instance_code_required")
        return self._call(
            "GET",
            INSTANCE_PATH.format(instance_code=urllib.parse.quote(str(instance_code), safe="")),
            params={"user_id_type": self.config.user_id_type} if self.config else None,
        )

    def get_approval_status(self, instance_code: str) -> FeishuResult:
        """返回 data = {status, task_id, approver, raw}。"""
        result = self.get_instance(instance_code)
        if not result.ok:
            return result
        raw = result.data
        tasks = raw.get("task_list")
        if not isinstance(tasks, list):
            tasks = []
        chosen: Dict[str, Any] = {}
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if str(task.get("status") or "").upper() == "APPROVED":
                chosen = task
                break
            if not chosen:
                chosen = task
        approver = str(
            chosen.get("user_id") or chosen.get("open_id") or chosen.get("approver") or ""
        )
        return FeishuResult(
            True,
            code=result.code,
            data={
                "status": str(raw.get("status") or "UNKNOWN").upper(),
                "task_id": str(chosen.get("id") or ""),
                "approver": approver,
                "raw": raw,
            },
        )

    def execute_approval(
        self,
        instance_code: str,
        task_id: str,
        approve: bool,
        *,
        reason: str = "",
        user_id: str = "",
    ) -> FeishuResult:
        if not instance_code or not task_id:
            return FeishuResult(False, error="instance_and_task_required")
        action = "approve" if approve else "reject"
        body: Dict[str, Any] = {"comment": str(reason or "")}
        if user_id:
            body["user_id_type"] = self.config.user_id_type if self.config else "user_id"
            body["user_id"] = str(user_id)
        return self._call(
            "POST",
            APPROVAL_TASK_PATH.format(
                instance_code=urllib.parse.quote(str(instance_code), safe=""),
                task_id=urllib.parse.quote(str(task_id), safe=""),
                action=action,
            ),
            body=body,
        )

    # ── IM ────────────────────────────────────────────────────────────────
    def send_message(self, chat_id: str, text: str) -> FeishuResult:
        if not chat_id:
            return FeishuResult(False, error="chat_id_required")
        return self._call(
            "POST",
            MESSAGE_PATH,
            body={
                "receive_id": str(chat_id),
                "msg_type": "text",
                "content": json.dumps({"text": str(text or "")}, ensure_ascii=False),
            },
            params={"receive_id_type": "chat_id"},
        )
