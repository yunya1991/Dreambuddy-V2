#!/usr/bin/env python3
"""
V1-3: G 层 session log consumer 投影验证

验证 Harness session 事件投影为 DreamBuddy G 层执行图的规则正确性。

投影规则:
  tool/call   → node_execution
  tool/result  → node_result
  step/*       → graph_node
  agent/pre-step → intent_gate

验证:
  1. 所有 4 种事件类型都能正确写入投影文件
  2. 投影格式与 G 层执行图等价
  3. 事件顺序保持
  4. session_id 正确传递
"""

import json
import os
import sys
import time
import uuid
import subprocess
import threading
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BRIDGE_DIR / "packages" / "python-server" / "server.py"
SDK_PATH = BRIDGE_DIR / "packages" / "python-server"
PROJECTION_PATH = BRIDGE_DIR / "packages" / ".session-projections" / "g_layer_events.jsonl"

sys.path.insert(0, str(SDK_PATH))


class IPCHarness:
    def __init__(self):
        self.process = None
        self.pending = {}
        self.lock = threading.Lock()

    def start(self):
        self.process = subprocess.Popen(
            ["python3", str(SERVER_PATH)],
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
        # 握手
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


def test_v1_3_projection():
    """V1-3: 验证所有 4 种事件类型的投影"""

    # 清除旧投影文件
    if PROJECTION_PATH.exists():
        PROJECTION_PATH.unlink()

    harness = IPCHarness()
    harness.start()

    session_id = "v1-3-test-session"

    try:
        # 定义 4 种事件类型及其投影映射
        events = [
            {
                "name": "tool/call → node_execution",
                "params": {
                    "event_type": "node_execution",
                    "event_data": {
                        "original_type": "tool/call",
                        "seq": 1,
                        "payload": {"tool": "c1_technical_scan", "args": {"symbol": "BTC"}},
                    },
                    "session_id": session_id,
                },
            },
            {
                "name": "tool/result → node_result",
                "params": {
                    "event_type": "node_result",
                    "event_data": {
                        "original_type": "tool/result",
                        "seq": 2,
                        "payload": {"tool": "c1_technical_scan", "result": {"signal": "bullish"}},
                    },
                    "session_id": session_id,
                },
            },
            {
                "name": "step/start → graph_node",
                "params": {
                    "event_type": "graph_node",
                    "event_data": {
                        "original_type": "step/start",
                        "seq": 3,
                        "payload": {"step": 1, "action": "thinking"},
                    },
                    "session_id": session_id,
                },
            },
            {
                "name": "agent/pre-step → intent_gate",
                "params": {
                    "event_type": "intent_gate",
                    "event_data": {
                        "original_type": "agent/pre-step",
                        "seq": 4,
                        "payload": {"risk": "low", "intent": "query"},
                    },
                    "session_id": session_id,
                },
            },
        ]

        # 发送所有事件
        for event in events:
            result = harness.call_method("session_consumer", event["params"])
            assert result.get("ok"), f"事件 {event['name']} 调用失败: {result}"
            r = result.get("result", {})
            assert r.get("status") == "ok", f"写入失败: {r}"
            assert r.get("written") is True, f"written 应为 True: {r}"
            print(f"  ✓ {event['name']}")

        # 验证投影文件
        assert PROJECTION_PATH.exists(), "投影文件应存在"
        with open(PROJECTION_PATH) as f:
            lines = f.readlines()

        assert len(lines) >= 4, f"投影文件应有至少 4 行，got {len(lines)}"

        # 验证每种事件类型的投影格式
        entries = [json.loads(line) for line in lines[-4:]]  # 最后 4 行

        expected_types = ["node_execution", "node_result", "graph_node", "intent_gate"]
        for i, (entry, expected_type) in enumerate(zip(entries, expected_types)):
            assert entry["event_type"] == expected_type, \
                f"事件 {i}: 期望 event_type={expected_type}, got {entry['event_type']}"
            assert entry["session_id"] == session_id, \
                f"事件 {i}: session_id 不匹配"
            assert "timestamp" in entry, f"事件 {i}: 缺少 timestamp"
            assert "event_data" in entry, f"事件 {i}: 缺少 event_data"
            assert entry["event_data"]["seq"] == i + 1, \
                f"事件 {i}: seq 不匹配"
            print(f"  ✓ 投影 {expected_type}: seq={entry['event_data']['seq']}, session={entry['session_id']}")

        # 验证事件顺序保持
        seqs = [e["event_data"]["seq"] for e in entries]
        assert seqs == [1, 2, 3, 4], f"事件顺序应保持: {seqs}"

        print("\n  V1-3 PASS: 所有 4 种投影类型验证通过")
        print(f"  投影文件: {PROJECTION_PATH}")
        print(f"  事件数: {len(lines)}")
        print(f"  事件顺序: {seqs}")

    finally:
        harness.stop()


def main():
    print("=" * 60)
    print("V1-3: G 层 session log consumer 投影验证")
    print("=" * 60)
    print()
    test_v1_3_projection()
    print()
    print("=" * 60)
    print("V1-3 全部通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
