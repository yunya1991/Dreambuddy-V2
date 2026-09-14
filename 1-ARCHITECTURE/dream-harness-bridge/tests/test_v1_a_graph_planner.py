#!/usr/bin/env python3
"""
V1-A: A 层 GraphPlanner IPC 契约测试

验证 Python server 的 graph_planner 方法:
  1. 接收 intent_gateway 的输出 (intent_type, recommended_chain, base_chain, confidence)
  2. 调用 DreamOS GraphPlanner.plan_from_intent()
  3. 返回 ExecutionPlan JSON (planned_chain, selected_nodes, budget, rationale)
  4. 参数缺失时降级到默认全链 (FAIL-OPEN, HC-7)
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


def test_graph_planner_returns_plan():
    """graph_planner 方法应返回 ExecutionPlan JSON"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("graph_planner", {
            "intent_type": "TREND_FOLLOWING",
            "recommended_chain": "A",
            "base_chain": ["A0", "A1", "A2"],
            "confidence": 0.72,
        })
        result = resp.get("result", {})
        print(f"  response: {json.dumps(result, ensure_ascii=False)[:300]}")

        assert "planned_chain" in result, "应包含 planned_chain"
        assert "selected_nodes" in result, "应包含 selected_nodes"
        assert "budget" in result, "应包含 budget"
        assert "rationale" in result, "应包含 rationale"

        print("  PASS: graph_planner 返回 ExecutionPlan 结构")
    finally:
        harness.stop()


def test_graph_planner_missing_params_fail_open():
    """参数缺失时应降级到默认全链 (HC-7 FAIL-OPEN)"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("graph_planner", {})
        result = resp.get("result", {})
        print(f"  response: {json.dumps(result, ensure_ascii=False)[:300]}")

        assert "planned_chain" in result, "即使参数缺失也应返回 plan"
        assert result.get("planned_chain") in ("A", "C", "F"), "planned_chain 应为 A/C/F"

        print("  PASS: 参数缺失时降级到默认链")
    finally:
        harness.stop()


def test_graph_planner_method_registered():
    """graph_planner 方法应在 handle_request 路由中注册"""
    import inspect
    server_src = SERVER_PATH.read_text(encoding="utf-8")
    assert "_handle_graph_planner" in server_src, "server.py 应包含 _handle_graph_planner"
    assert '"graph_planner"' in server_src, "handle_request 应路由 graph_planner"
    print("  PASS: graph_planner 方法已注册")


if __name__ == "__main__":
    print("=" * 60)
    print("V1-A: A 层 GraphPlanner IPC 契约测试")
    print("=" * 60)

    test_graph_planner_method_registered()
    test_graph_planner_returns_plan()
    test_graph_planner_missing_params_fail_open()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
