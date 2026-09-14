#!/usr/bin/env python3
"""
V1-6: 硬约束集成测试

验证所有硬约束在 Phase 1 新架构下仍生效。

硬约束清单:
  HC-1a: 不修改其他目录代码
  HC-1b: 仅通过 Python import 或 IPC 调用 DreamBuddy
  HC-1c: 测试套件互不影响
  HC-2:  交易路径必须通过 constraint_passed
  HC-3:  session-consumer 不持有交易状态
  HC-5:  reward 信号由 DreamBuddy 内部计算
  HC-7:  所有 HTTP 调用 FAIL-OPEN

测试:
  1. 新增 plugin 在 dream-harness-bridge/ 内 (HC-1a)
  2. Python server 不直接 import DreamBuddy (HC-1b)
  3. 硬约束检查对交易路径生效 (HC-2)
  4. session_consumer 不持有交易状态 (HC-3)
  5. 所有新方法 FAIL-OPEN (HC-7)
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


def test_hc1a_plugins_in_bridge_dir():
    """HC-1a: 所有新增 plugin 在 dream-harness-bridge/ 内"""
    plugin_dirs = [
        "packages/cordis-plugin-indicators",
        "packages/cordis-plugin-fundamental",
        "packages/cordis-plugin-session-consumer",
        "packages/cordis-plugin-graph-planner",
        "packages/cordis-plugin-reflector",
    ]

    for d in plugin_dirs:
        full_path = BRIDGE_DIR / d
        assert full_path.exists(), f"plugin 目录应在 dream-harness-bridge/ 内: {d}"
        assert (full_path / "package.json").exists(), f"package.json 应存在: {d}"
        assert (full_path / "lib" / "index.js").exists(), f"lib/index.js 应存在: {d}"
        print(f"  ✓ {d} 在 dream-harness-bridge/ 内")

    print("  HC-1a PASS: 所有新增 plugin 在 dream-harness-bridge/ 内")


def test_hc1b_no_direct_dreambuddy_import():
    """HC-1b: Python server 不直接 import DreamBuddy 模块"""
    server_code = SERVER_PATH.read_text(encoding="utf-8")

    # 检查不应有直接 import DreamBuddy 的语句
    forbidden_imports = [
        "from dreambuddy",
        "import dreambuddy",
        "from 10-经典指标系统",
        "from 9-基本面分析",
        "from 1-ARCHITECTURE.dreambuddy",
    ]

    for forbidden in forbidden_imports:
        assert forbidden not in server_code, \
            f"server.py 不应包含 '{forbidden}' — HC-1b 违规"

    # 应该有 HTTP 调用（通过 urllib）而非直接 import
    assert "urllib.request" in server_code, "server.py 应通过 HTTP 调用外部 API"

    print("  ✓ server.py 不直接 import DreamBuddy")
    print("  ✓ 通过 HTTP (urllib) 调用外部 API")
    print("  HC-1b PASS: 仅通过 HTTP/IPC 调用，不直接 import")


def test_hc2_trading_path_constraint():
    """HC-2: 交易路径必须通过 constraint_passed"""
    harness = IPCHarness()
    harness.start()

    try:
        # 交易路径方法应触发硬约束检查
        trading_methods = ["execute_node", "open_position", "close_position", "modify_position"]

        for method in trading_methods:
            result = harness.call_method(method, {"node_id": "test"})
            assert result.get("ok"), f"交易方法 {method} 应返回 ok"
            # 交易路径应有 constraint_passed 标记
            assert "constraint_passed" in str(result), \
                f"交易方法 {method} 应有 constraint_passed 标记"
            print(f"  ✓ {method}: constraint_passed={result.get('constraint_passed')}")

        # 非交易路径不应有 constraint_passed
        non_trading = harness.call_method("technical_indicators", {"symbol": "BTC"})
        assert non_trading.get("ok"), "非交易方法应返回 ok"
        assert not non_trading.get("constraint_passed") or non_trading.get("constraint_passed") is False, \
            "非交易方法不应有 constraint_passed=True"

        print("  ✓ 非交易方法无 constraint_passed")
        print("  HC-2 PASS: 交易路径硬约束检查生效")
    finally:
        harness.stop()


def test_hc3_session_consumer_stateless():
    """HC-3: session_consumer 不持有交易状态"""
    harness = IPCHarness()
    harness.start()

    try:
        # session_consumer 只消费事件，不持有交易状态
        # 验证：连续写入不同事件类型不产生状态依赖
        events = [
            {"event_type": "node_execution", "event_data": {"seq": 1}, "session_id": "s1"},
            {"event_type": "node_result", "event_data": {"seq": 2}, "session_id": "s1"},
            {"event_type": "intent_gate", "event_data": {"seq": 3}, "session_id": "s2"},
        ]

        for event in events:
            result = harness.call_method("session_consumer", event)
            assert result.get("ok"), f"session_consumer 应成功: {result}"
            r = result.get("result", {})
            assert r.get("status") == "ok", f"写入应成功: {r}"
            # session_consumer 返回中不应包含任何交易状态
            assert "position" not in r, "session_consumer 不应返回 position"
            assert "order" not in r, "session_consumer 不应返回 order"
            assert "trade" not in r, "session_consumer 不应返回 trade"

        print("  ✓ session_consumer 只消费事件，不持有交易状态")
        print("  HC-3 PASS: session_consumer 无状态")
    finally:
        harness.stop()


def test_hc7_all_methods_fail_open():
    """HC-7: 所有新方法 FAIL-OPEN"""
    harness = IPCHarness()
    harness.start()

    try:
        # technical_indicators: 8092 不可达 → degraded
        r1 = harness.call_method("technical_indicators", {"symbol": "BTC"})
        assert r1.get("ok"), "technical_indicators 应返回 ok (FAIL-OPEN)"
        result1 = r1.get("result", {})
        assert result1.get("status") == "degraded", "应为 degraded"
        assert result1.get("neutral_default", {}).get("signal") == "neutral"
        print(f"  ✓ technical_indicators: FAIL-OPEN (degraded + neutral)")

        # fundamental_analysis: 3456 不可达 → degraded
        r2 = harness.call_method("fundamental_analysis", {"symbol": "BTC"})
        assert r2.get("ok"), "fundamental_analysis 应返回 ok (FAIL-OPEN)"
        result2 = r2.get("result", {})
        assert result2.get("status") == "degraded", "应为 degraded"
        assert result2.get("neutral_default", {}).get("signal") == "neutral"
        print(f"  ✓ fundamental_analysis: FAIL-OPEN (degraded + neutral)")

        # session_consumer: 文件写入 → 即使文件系统问题也不崩溃
        r3 = harness.call_method("session_consumer", {
            "event_type": "graph_node",
            "event_data": {"seq": 1},
            "session_id": "hc7-test",
        })
        assert r3.get("ok"), "session_consumer 应返回 ok"
        result3 = r3.get("result", {})
        assert result3.get("status") in ("ok", "degraded"), \
            f"session_consumer 应为 ok 或 degraded, got: {result3.get('status')}"
        print(f"  ✓ session_consumer: {result3.get('status')}")

        # IntentGateway: 即使误判也不阻塞
        r4 = harness.call_method("intent_gateway", {"user_input": "test query"})
        assert r4.get("ok"), "intent_gateway 应返回 ok (FAIL-OPEN)"
        print(f"  ✓ intent_gateway: FAIL-OPEN")

        print("  HC-7 PASS: 所有方法 FAIL-OPEN")
    finally:
        harness.stop()


def main():
    print("=" * 60)
    print("V1-6: 硬约束集成测试")
    print("=" * 60)

    print("\n[HC-1a] 新增 plugin 在 dream-harness-bridge/ 内...")
    test_hc1a_plugins_in_bridge_dir()

    print("\n[HC-1b] 不直接 import DreamBuddy...")
    test_hc1b_no_direct_dreambuddy_import()

    print("\n[HC-2] 交易路径硬约束检查...")
    test_hc2_trading_path_constraint()

    print("\n[HC-3] session_consumer 无状态...")
    test_hc3_session_consumer_stateless()

    print("\n[HC-7] 所有方法 FAIL-OPEN...")
    test_hc7_all_methods_fail_open()

    print("\n" + "=" * 60)
    print("V1-6 全部通过 — 所有硬约束在 Phase 1 新架构下仍生效")
    print("=" * 60)


if __name__ == "__main__":
    main()
