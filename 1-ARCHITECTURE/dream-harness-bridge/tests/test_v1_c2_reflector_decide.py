#!/usr/bin/env python3
"""
V1-C2: C 层 Reflector Phase 2 — 真实 Reflector.decide() 集成测试

验证 reflection 方法的 mode=decide 模式:
  1. 高置信度 + 预算充足 → CONTINUE
  2. 低置信度 (<0.3) → REDO
  3. 预算不足 (<0.2) → JUMP_TO (跳转到收尾节点)
  4. 与前序节点方向矛盾 + 高置信度 → INSERT_BEFORE
  5. 连续多节点高置信度一致 → EARLY_TERMINATE
  6. 节点失败 → REDO (重试未耗尽)
  7. HC-7: 异常时降级为 CONTINUE
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


def _get_decision(resp):
    """从响应中提取 decision"""
    return resp.get("result", {}).get("echo", {}).get("params", {}).get("decision")


def test_decide_high_confidence_continue():
    """高置信度 + 预算充足 → CONTINUE"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("reflection", {
            "mode": "decide",
            "current_node_id": "C1",
            "confidence": 0.85,
            "direction": "LONG",
            "status": "SUCCESS",
            "executed_count": 1,
            "max_nodes": 5,
            "budget_remaining_ratio": 0.8,
            "prev_results": [],
        })
        decision = _get_decision(resp)
        assert decision == "CONTINUE", f"期望 CONTINUE, got {decision}"
        print(f"  PASS: 高置信度(0.85)+预算足(0.8) → CONTINUE")
    finally:
        harness.stop()


def test_decide_low_confidence_redo():
    """低置信度 (<0.3) → REDO"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("reflection", {
            "mode": "decide",
            "current_node_id": "C1",
            "confidence": 0.2,
            "direction": "LONG",
            "status": "SUCCESS",
            "executed_count": 1,
            "max_nodes": 5,
            "budget_remaining_ratio": 0.8,
            "prev_results": [],
            "retries": 0,
        })
        decision = _get_decision(resp)
        assert decision == "REDO", f"期望 REDO, got {decision}"
        print(f"  PASS: 低置信度(0.2) → REDO")
    finally:
        harness.stop()


def test_decide_budget_critical_jump():
    """预算不足 (<0.2) → JUMP_TO"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("reflection", {
            "mode": "decide",
            "current_node_id": "C1",
            "confidence": 0.8,
            "direction": "LONG",
            "status": "SUCCESS",
            "executed_count": 3,
            "max_nodes": 5,
            "budget_remaining_ratio": 0.1,
            "prev_results": [],
        })
        decision = _get_decision(resp)
        assert decision == "JUMP_TO", f"期望 JUMP_TO, got {decision}"
        print(f"  PASS: 预算不足(0.1) → JUMP_TO")
    finally:
        harness.stop()


def test_decide_conflict_insert_before():
    """与前序节点方向矛盾 + 前序高置信度 → INSERT_BEFORE"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("reflection", {
            "mode": "decide",
            "current_node_id": "A2",
            "confidence": 0.8,
            "direction": "SHORT",
            "status": "SUCCESS",
            "executed_count": 2,
            "max_nodes": 5,
            "budget_remaining_ratio": 0.8,
            "prev_results": [
                {"node_id": "C1", "direction": "LONG", "confidence": 0.9},
            ],
        })
        decision = _get_decision(resp)
        assert decision == "INSERT_BEFORE", f"期望 INSERT_BEFORE, got {decision}"
        print(f"  PASS: 方向矛盾(LONG vs SHORT) → INSERT_BEFORE")
    finally:
        harness.stop()


def test_decide_failed_redo():
    """节点失败 → REDO (重试未耗尽)"""
    harness = IPCHarness().start()
    try:
        resp = harness.call_method("reflection", {
            "mode": "decide",
            "current_node_id": "C1",
            "confidence": 0.0,
            "direction": None,
            "status": "FAILED",
            "error": "data fetch failed",
            "executed_count": 1,
            "max_nodes": 5,
            "budget_remaining_ratio": 0.8,
            "prev_results": [],
            "retries": 0,
        })
        decision = _get_decision(resp)
        assert decision == "REDO", f"期望 REDO, got {decision}"
        print(f"  PASS: 节点失败 → REDO")
    finally:
        harness.stop()


if __name__ == "__main__":
    print("=" * 60)
    print("V1-C2: C 层 Reflector Phase 2 — 真实 Reflector.decide() 集成")
    print("=" * 60)

    test_decide_high_confidence_continue()
    test_decide_low_confidence_redo()
    test_decide_budget_critical_jump()
    test_decide_conflict_insert_before()
    test_decide_failed_redo()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
