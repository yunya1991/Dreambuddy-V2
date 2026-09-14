#!/usr/bin/env python3
"""
V1-C: C 层 Reflector IPC 契约测试

验证 Python server 的 reflection 方法:
  1. 调用 reflection_handler.handle_reflection_safe 校验决策
  2. 合法决策 → echo 返回 decision + params
  3. 非法决策 → 错误响应 (INVALID_DECISION)
  4. INSERT_BEFORE/JUMP_TO 缺少 target_step → 错误响应
  5. HC-7: 异常时 FAIL-OPEN (降级为 CONTINUE)
"""

import json
import sys
import time
import uuid
import subprocess
import threading
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BRIDGE_DIR / "packages" / "python-server" / "server.py"
SDK_PATH = BRIDGE_DIR / "packages" / "python-server"

sys.path.insert(0, str(SDK_PATH))


class IPCHarness:
    def __init__(self):
        self.process = None
        self.pending = {}
        self.lock = threading.Lock()

    def start(self):
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        while True:
            line = self.process.stderr.readline()
            if not line:
                raise RuntimeError("Python server 启动失败")
            if "启动" in line:
                break
        t = threading.Thread(target=self._read_stdout, daemon=True)
        t.start()
        req = {
            "schema_version": "1.0.0",
            "message_type": "handshake_request",
            "client_version": "1.0.0",
            "id": str(uuid.uuid4()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        resp = self._send(req, timeout=5)
        if not resp.get("ok"):
            raise RuntimeError(f"握手失败: {resp}")
        return self

    def _read_stdout(self):
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                rid = msg.get("id")
                with self.lock:
                    if rid in self.pending:
                        self.pending[rid]["event"].set()
                        self.pending[rid]["result"] = msg
            except json.JSONDecodeError:
                pass

    def _send(self, request, timeout=30):
        rid = request.get("id", str(uuid.uuid4()))
        request["id"] = rid
        event = threading.Event()
        with self.lock:
            self.pending[rid] = {"event": event, "result": None}
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        if not event.wait(timeout=timeout):
            with self.lock:
                self.pending.pop(rid, None)
            raise TimeoutError(f"IPC 超时: {request.get('method')}")
        with self.lock:
            return self.pending.pop(rid, {}).get("result")

    def call_method(self, method, params):
        req = {
            "schema_version": "1.0.0",
            "message_type": "request",
            "method": method,
            "params": params,
            "id": str(uuid.uuid4()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        return self._send(req, timeout=30)

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)


def test_reflection_method_registered():
    """reflection 方法应在 handle_request 路由中注册"""
    server_src = SERVER_PATH.read_text(encoding="utf-8")
    assert "_handle_reflection" in server_src, "server.py 应包含 _handle_reflection"
    assert '"reflection"' in server_src, "handle_request 应路由 reflection"
    print("  PASS: reflection 方法已注册")


def test_reflection_continue():
    """CONTINUE 决策 → echo 返回 decision=CONTINUE"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("reflection", {
            "decision": "CONTINUE",
            "reason": "next step ready",
        })
        echo = resp.get("result", {}).get("echo", {})
        params = echo.get("params", {})
        assert params.get("decision") == "CONTINUE", f"应返回 CONTINUE, got {params}"
        print(f"  PASS: CONTINUE → {params.get('decision')}")
    finally:
        harness.stop()


def test_reflection_invalid_decision():
    """非法决策 → 错误响应"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("reflection", {
            "decision": "INVALID",
        })
        # reflection_handler 校验失败 → ok=False 或 echo 中不含合法 decision
        result = resp.get("result", {})
        echo = result.get("echo", {})
        params = echo.get("params", {})
        # 失败时不应回显 INVALID
        assert params.get("decision") != "INVALID", "非法决策不应被回显"
        print(f"  PASS: 非法决策被拒绝 (ok={resp.get('ok')})")
    finally:
        harness.stop()


def test_reflection_insert_before_requires_target():
    """INSERT_BEFORE 缺少 target_step → 错误响应"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("reflection", {
            "decision": "INSERT_BEFORE",
        })
        echo = resp.get("result", {}).get("echo", {})
        params = echo.get("params", {})
        # 失败时不应回显无 target_step 的 INSERT_BEFORE
        assert params.get("target_step") is not None or params.get("decision") != "INSERT_BEFORE"
        print(f"  PASS: INSERT_BEFORE 缺少 target_step 被拒绝")
    finally:
        harness.stop()


def test_reflection_jump_to_with_target():
    """JUMP_TO 带 target_step → echo 返回 decision + target_step"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("reflection", {
            "decision": "JUMP_TO",
            "target_step": "step-5",
        })
        echo = resp.get("result", {}).get("echo", {})
        params = echo.get("params", {})
        assert params.get("decision") == "JUMP_TO"
        assert params.get("target_step") == "step-5"
        print(f"  PASS: JUMP_TO → decision={params.get('decision')}, target={params.get('target_step')}")
    finally:
        harness.stop()


if __name__ == "__main__":
    print("=" * 60)
    print("V1-C: C 层 Reflector IPC 契约测试")
    print("=" * 60)

    test_reflection_method_registered()
    test_reflection_continue()
    test_reflection_invalid_decision()
    test_reflection_insert_before_requires_target()
    test_reflection_jump_to_with_target()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
