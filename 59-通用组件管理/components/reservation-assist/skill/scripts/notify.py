"""通知通道：真实通道只在运行期使用，测试注入 FakeNotifier。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from typing import Protocol, runtime_checkable


@runtime_checkable
class Channel(Protocol):
    NAME: str

    def send(self, message: str) -> None: ...


class FakeNotifier:
    """测试替身：记录每次调用，可注入失败。"""

    NAME = "fake"

    def __init__(self, fail_times: int = 0) -> None:
        self.calls: list[str] = []
        self.fail_times = fail_times

    def send(self, message: str) -> None:
        self.calls.append(message)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("fake channel failure")


FEISHU_KEYCHAIN_SERVICE = "com.reservation-assist.feishu"


def _keychain_webhook() -> str:
    """从登录钥匙串读取飞书 webhook，避免把凭据写进 plist 或环境变量。"""
    if not shutil.which("security"):
        return ""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", FEISHU_KEYCHAIN_SERVICE],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


class FeishuChannel:
    NAME = "feishu"

    def __init__(self, webhook: str = "") -> None:
        self.webhook = webhook or os.environ.get("RA_FEISHU_WEBHOOK", "") or _keychain_webhook()

    def send(self, message: str) -> None:
        if not self.webhook:
            raise RuntimeError("未配置 RA_FEISHU_WEBHOOK")
        payload = json.dumps(
            {"msg_type": "text", "content": {"text": message}}, ensure_ascii=False
        ).encode("utf-8")
        request = urllib.request.Request(
            self.webhook, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=10) as resp:
            if resp.status >= 400:
                raise RuntimeError("飞书返回 HTTP {}".format(resp.status))


FEISHU_APP_KEYCHAIN_SERVICE = "com.reservation-assist.feishu-app"


def _keychain_json(service: str) -> dict:
    if not shutil.which("security"):
        return {}
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}
    if out.returncode != 0:
        return {}
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class FeishuAppChannel:
    """用飞书自建应用（tenant token）向指定群发文本消息。"""

    NAME = "feishu_app"

    def __init__(self, config: dict | None = None) -> None:
        data = config if config is not None else _keychain_json(FEISHU_APP_KEYCHAIN_SERVICE)
        self.app_id = str(data.get("app_id") or "")
        self.app_secret = str(data.get("app_secret") or "")
        self.chat_id = str(data.get("chat_id") or "")

    def _post(self, url: str, payload: dict, token: str = "") -> dict:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send(self, message: str) -> None:
        if not (self.app_id and self.app_secret and self.chat_id):
            raise RuntimeError("未配置飞书应用凭据或 chat_id")
        auth = self._post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self.app_id, "app_secret": self.app_secret},
        )
        token = auth.get("tenant_access_token")
        if not token:
            raise RuntimeError("飞书 tenant token 获取失败：{}".format(auth.get("msg")))
        result = self._post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            {
                "receive_id": self.chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": message}, ensure_ascii=False),
            },
            token,
        )
        if result.get("code") not in (0, None):
            raise RuntimeError("飞书发送失败：{} {}".format(result.get("code"), result.get("msg")))


class LocalChannel:
    NAME = "local"

    def send(self, message: str) -> None:
        if not shutil.which("osascript"):
            raise RuntimeError("本机无 osascript，无法发送本地通知")
        script = 'display notification "{}" with title "预约助手"'.format(
            message.replace('"', "'")[:180]
        )
        subprocess.run(["osascript", "-e", script], check=True, timeout=10)


class Notifier:
    """按通道发送；失败重试 2 次后记 missing[]，绝不假装成功。"""

    def __init__(self, channels: list[Channel], retries: int = 2) -> None:
        self.channels = channels
        self.retries = retries
        self.missing: list[dict] = []

    def send(self, message: str) -> list[dict]:
        failures: list[dict] = []
        for channel in self.channels:
            error = ""
            for _ in range(self.retries + 1):
                try:
                    channel.send(message)
                    error = ""
                    break
                except Exception as exc:  # noqa: BLE001 - 通道异常统一记录
                    error = str(exc)
            if error:
                failures.append({"key": channel.NAME, "code": "E_CHANNEL", "detail": error})
        self.missing.extend(failures)
        return failures


def build_notifier(names: str | list[str], retries: int = 2) -> Notifier:
    if isinstance(names, str):
        names = [item.strip() for item in names.split(",") if item.strip()]
    channels: list[Channel] = []
    for name in names:
        if name == "feishu":
            channels.append(FeishuChannel())
        elif name == "feishu_app":
            channels.append(FeishuAppChannel())
        elif name == "local":
            channels.append(LocalChannel())
        else:
            raise ValueError("未知通知通道：{}".format(name))
    return Notifier(channels, retries=retries)


def deliver_once(
    store,
    notifier,
    task_id: str,
    fingerprint: str,
    message: str,
    now: int | None = None,
) -> bool:
    """首次命中才通知；notified_at 持久化保证跨进程只发一次。"""
    row = store.get_hit(task_id, fingerprint)
    if not row:
        return False
    if row.get("notified_at"):
        return False
    failures = notifier.send(message)
    if failures:
        store.add_event(
            "warn", "notify_failed", task_id, {"channels": [item["key"] for item in failures]}
        )
        return False
    store.mark_notified(task_id, fingerprint, int(now or time.time() * 1000))
    store.add_event("info", "notified", task_id, {"fingerprint": fingerprint[:12]})
    return True
