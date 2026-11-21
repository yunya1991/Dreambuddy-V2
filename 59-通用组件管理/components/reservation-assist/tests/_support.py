"""测试支撑：注入离线 Transport / Notifier，语义与运行期一致。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = COMPONENT_ROOT / "skill" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from adapters.base import Response, TransportError  # noqa: E402


class FakeTransport:
    def __init__(self, body: str = "", status: int = 200, error: Exception | None = None) -> None:
        self.body = body
        self.status = status
        self.error = error
        self.requests: list[dict] = []

    def fetch(self, req: dict) -> Response:
        self.requests.append(req)
        if self.error:
            raise self.error
        return Response(status=self.status, body=self.body)


class FakeNotifier:
    NAME = "fake"

    def __init__(self, fail_times: int = 0) -> None:
        self.calls: list[str] = []
        self.fail_times = fail_times

    def send(self, message: str) -> None:
        self.calls.append(message)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("fake channel failure")


def network_error() -> TransportError:
    return TransportError("offline")


def temp_dir() -> str:
    return tempfile.mkdtemp(prefix="ra-test-")


def make_task(adapter: str = "railway", **overrides) -> dict:
    task = {
        "id": "task1",
        "adapter": adapter,
        "target": {"target_id": "T1", "session": "2026-12-01"},
        "rule": {"max_price": 600, "identity_selected": True},
        "window_start": 1764547200000,
        "window_end": 1764547800000,
        "interval_ms": 1000,
        "submit_enabled": 0,
        "max_orders": 1,
    }
    task.update(overrides)
    return task
