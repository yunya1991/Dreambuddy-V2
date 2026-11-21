"""通知通道：真实通道只在运行期使用，测试注入 FakeNotifier。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
from typing import Protocol, runtime_checkable


@runtime_checkable
class Channel(Protocol):
    NAME: str

    def send(self, message: str) -> None: ...


class FakeNotifier:
    """测试替身：记录每次调用，可注入失败次数。"""

    NAME = "fake"

    def __init__(self, fail_times: int = 0) -> None:
        self.calls: list[str] = []
        self.fail_times = fail_times

    def send(self, message: str) -> None:
        self.calls.append(message)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("fake channel failure")


class LocalChannel:
    NAME = "local"

    def send(self, message: str) -> None:
        if not shutil.which("osascript"):
            raise RuntimeError("本机无 osascript，无法发送本地通知")
        script = 'display notification "{}" with title "手机预约助手"'.format(
            message.replace('"', "'")[:180]
        )
        subprocess.run(["osascript", "-e", script], check=True, timeout=10)


class FeishuChannel:
    NAME = "feishu"

    def __init__(self, webhook: str = "") -> None:
        self.webhook = webhook or os.environ.get("MRA_FEISHU_WEBHOOK", "")

    def send(self, message: str) -> None:
        if not self.webhook:
            raise RuntimeError("未配置 MRA_FEISHU_WEBHOOK")
        payload = json.dumps(
            {"msg_type": "text", "content": {"text": message}}, ensure_ascii=False
        ).encode("utf-8")
        request = urllib.request.Request(
            self.webhook, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=10) as resp:
            if resp.status >= 400:
                raise RuntimeError("飞书返回 HTTP {}".format(resp.status))


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
        elif name == "local":
            channels.append(LocalChannel())
        elif name == "fake":
            channels.append(FakeNotifier())
        else:
            raise ValueError("未知通知通道：{}".format(name))
    return Notifier(channels, retries=retries)
