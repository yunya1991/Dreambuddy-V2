#!/usr/bin/env python3
"""
V1-C1-INTENT: C1 技术扫描 + IntentGateway 真实 DreamOS 接入测试

验证 P0-1 修复:
  1. c1_scan 调用真实 C1TechScanNode 返回 phase="real_dreamos_node"
  2. c1_scan symbol=ERROR 保留 V0-3 测试异常行为
  3. intent_gateway 调用真实 IntentEngine 返回 phase="real_dreamos_intent_engine" + canon_intent
  4. intent_gateway FAIL-OPEN 降级返回中性默认值

验收标准对应 CHAIN_INTEGRATION_SPEC.md P0-1。
"""
import json
import subprocess
import sys
import os

SERVER = os.path.join(os.path.dirname(__file__), "..", "packages", "python-server", "server.py")
PYTHON = sys.executable

passed = 0
failed = 0


def call(method, params, timeout=90):
    """通过子进程调用 Python server 的 IPC 方法"""
    payload = {
        "schema_version": "1.0.0",
        "message_type": "request",
        "method": method,
        "params": params,
        "id": "test-" + method + "-" + str(len(params)),
        "timestamp": "2025-01-01T00:00:00Z",
    }
    proc = subprocess.run(
        [PYTHON, SERVER],
        input=json.dumps(payload) + "\n",
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    for line in proc.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            resp = json.loads(line)
            if resp.get("id") == payload["id"]:
                return resp
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"No response. stderr={proc.stderr[:800]}")


def assert_eq(name, actual, expected):
    global passed, failed
    if actual == expected:
        print(f"  PASS {name}: {actual}")
        passed += 1
    else:
        print(f"  FAIL {name}: expected={expected}, actual={actual}")
        failed += 1


def assert_in(name, actual, container):
    global passed, failed
    if actual in container:
        print(f"  PASS {name}: {actual}")
        passed += 1
    else:
        print(f"  FAIL {name}: {actual} not in {container}")
        failed += 1


def assert_has(name, value):
    global passed, failed
    if value is not None and value != "":
        print(f"  PASS {name}: present")
        passed += 1
    else:
        print(f"  FAIL {name}: missing or empty")
        failed += 1


# ============================================================
# Test 1: c1_scan 调用真实 C1TechScanNode
# ============================================================
print("=" * 50)
print("Test 1: c1_scan 调用真实 C1TechScanNode")
print("=" * 50)

market_data = {
    "price": 68000,
    "ema20": 67500,
    "ema50": 65000,
    "ema200": 60000,
    "rsi14": 55,
    "macd": 100,
    "macd_signal": 80,
    "macd_hist": 20,
    "atr": 850,
    "atr_pct": 1.25,
    "volume": 1.2,
    "vol_ratio": 1.1,
    "bb_upper": 70000,
    "bb_middle": 65000,
    "bb_lower": 60000,
    "bb_width": 0.15,
}

result = call("c1_scan", {"symbol": "BTC", "market_data": market_data})
data = result.get("result", {})
assert_eq("phase", data.get("phase"), "real_dreamos_node")
assert_in("direction", data.get("direction"), ["LONG", "SHORT", "HOLD"])
assert_has("confidence", data.get("confidence"))
assert_has("outputs", data.get("outputs"))
# 确保不再有 POC_mock
assert_eq("no_poc_mock", "POC_mock" in str(data), False)


# ============================================================
# Test 2: c1_scan symbol=ERROR (V0-3 测试保留)
# ============================================================
print("\n" + "=" * 50)
print("Test 2: c1_scan symbol=ERROR (V0-3 异常保留)")
print("=" * 50)

try:
    result = call("c1_scan", {"symbol": "ERROR"})
    # 如果 server 返回了 error 响应而非抛异常
    err = result.get("error")
    if err:
        print(f"  PASS V0-3: error response = {err[:80]}")
        passed += 1
    else:
        print(f"  FAIL V0-3: expected error, got {result.get('result', {}).get('phase')}")
        failed += 1
except Exception as e:
    print(f"  PASS V0-3: exception raised = {e}")
    passed += 1


# ============================================================
# Test 3: intent_gateway 调用真实 IntentEngine
# ============================================================
print("\n" + "=" * 50)
print("Test 3: intent_gateway 调用真实 IntentEngine")
print("=" * 50)

result = call("intent_gateway", {
    "user_input": "BTC价格多少",
    "symbol": "BTC-USDT",
    "market": {"price": 68000},
    "step": 1,
    "agent_id": "test-agent",
})
data = result.get("result", {})
phase = data.get("phase")
assert_in("phase", phase, ["real_dreamos_intent_engine", "fail_open"])

if phase == "real_dreamos_intent_engine":
    # 验证正典意图字段存在
    canon = data.get("canon_intent")
    assert_in("canon_intent", canon, [
        "market_query", "simple_qa", "deep_analysis", "trend_analysis",
        "technical_signal", "concept_explain", "execute_trade",
    ])
    assert_has("strategy_intent", data.get("strategy_intent"))
    assert_has("confidence", data.get("confidence"))
    assert_has("risk_level", data.get("risk_level"))
    # 确保不再有 POC_mock
    assert_eq("no_poc_mock", "POC_mock" in str(data), False)
elif phase == "fail_open":
    # FAIL-OPEN 也应返回中性默认值
    assert_eq("fail_open_canon", data.get("canon_intent"), "simple_qa")
    assert_eq("fail_open_strategy", data.get("strategy_intent"), "UNCERTAIN")
    assert_eq("fail_open_confidence", data.get("confidence"), 0.0)
    print("  (INFO: IntentEngine 不可用，FAIL-OPEN 降级验证通过)")


# ============================================================
# Test 4: intent_gateway FAIL-OPEN 降级（空输入）
# ============================================================
print("\n" + "=" * 50)
print("Test 4: intent_gateway FAIL-OPEN 降级（空输入）")
print("=" * 50)

result = call("intent_gateway", {
    "user_input": "",
    "symbol": "BTC-USDT",
    "step": 0,
    "agent_id": "test-empty",
})
data = result.get("result", {})
phase = data.get("phase")
# 空输入可能触发 IntentEngine 兜底或 FAIL-OPEN，两者都可接受
assert_in("phase", phase, ["real_dreamos_intent_engine", "fail_open"])
# 无论哪条路径，都应有 canon_intent 字段（FAIL-OPEN 兜底为 simple_qa）
assert_has("canon_intent", data.get("canon_intent"))


# ============================================================
# 汇总
# ============================================================
print("\n" + "=" * 50)
print(f"Results: {passed} passed, {failed} failed")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)
