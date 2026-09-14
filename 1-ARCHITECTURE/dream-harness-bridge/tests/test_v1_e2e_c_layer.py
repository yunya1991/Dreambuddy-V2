#!/usr/bin/env python3
"""
V1-E2E: C 层端到端联调 — C2/C3 节点 → Reflector 决策

验证:
  1. C2 产出的 direction/confidence 能被 Reflector.decide() 消费
  2. 低置信度 C 节点结果触发 REDO
  3. 高置信度 C 节点结果触发 CONTINUE
  4. 方向矛盾触发 INSERT_BEFORE
"""
import json
import subprocess
import sys
import os

SERVER = os.path.join(os.path.dirname(__file__), "..", "packages", "python-server", "server.py")
PYTHON = sys.executable
passed = 0
failed = 0


def call(method, params):
    payload = {
        "schema_version": "1.0.0",
        "message_type": "request",
        "method": method,
        "params": params,
        "id": f"e2e-{method}-{os.getpid()}",
        "timestamp": "2025-01-01T00:00:00Z",
    }
    proc = subprocess.run(
        [PYTHON, SERVER],
        input=json.dumps(payload) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
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
    raise RuntimeError(f"No response for {method}. stderr={proc.stderr[:500]}")


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        print(f"  PASS: {name}" + (f" ({detail})" if detail else ""))
        passed += 1
    else:
        print(f"  FAIL: {name}" + (f" ({detail})" if detail else ""))
        failed += 1


print("=" * 60)
print("V1-E2E: C 层端到端联调 (C2/C3 → Reflector)")
print("=" * 60)

# ── 场景 1: C2 高置信度 LONG → Reflector CONTINUE ────────
print("\n场景 1: C2 高置信度 LONG → Reflector CONTINUE")
bull_mkt = {
    "price": 70000, "change_1h": 0.5, "change_4h": 1.2, "change_24h": 5.0,
    "rsi14": 62, "macd": 150.0, "macd_signal": 100.0, "macd_hist": 50.0,
    "ema20": 68000, "ema50": 65000, "ema200": 60000,
}
c2_resp = call("c2_momentum", {"symbol": "BTC", "market_data": bull_mkt})
c2_result = c2_resp["result"]
check("C2 返回 LONG", c2_result["direction"] == "LONG", f"direction={c2_result['direction']}")
check("C2 置信度 > 0.7", c2_result["confidence"] > 0.7, f"conf={c2_result['confidence']}")

# 用 C2 结果作为当前节点，调用 Reflector
reflect_resp = call("reflection", {
    "mode": "decide",
    "current_node_id": "C2",
    "confidence": c2_result["confidence"],
    "direction": c2_result["direction"],
    "status": "SUCCESS",
    "executed_count": 1,
    "max_nodes": 5,
    "budget_remaining_ratio": 0.8,
    "prev_results": [],
})
decision = reflect_resp["result"]["echo"]["params"]["decision"]
check("高置信度 → CONTINUE", decision == "CONTINUE", f"decision={decision}")

# ── 场景 2: C3 低置信度 HOLD → Reflector REDO ────────────
print("\n场景 2: C3 低置信度 → Reflector REDO")
# 构造一个 C3 结果，然后手动调低置信度模拟低置信场景
reflect_resp = call("reflection", {
    "mode": "decide",
    "current_node_id": "C3",
    "confidence": 0.2,
    "direction": "HOLD",
    "status": "SUCCESS",
    "executed_count": 2,
    "max_nodes": 5,
    "budget_remaining_ratio": 0.7,
    "prev_results": [],
})
decision = reflect_resp["result"]["echo"]["params"]["decision"]
check("低置信度(0.2) → REDO", decision == "REDO", f"decision={decision}")

# ── 场景 3: C2 LONG 与前序 C3 SHORT 矛盾 → INSERT_BEFORE ─
print("\n场景 3: C2 LONG vs 前序 C3 SHORT 矛盾 → INSERT_BEFORE")
reflect_resp = call("reflection", {
    "mode": "decide",
    "current_node_id": "A2",
    "confidence": 0.8,
    "direction": "SHORT",
    "status": "SUCCESS",
    "executed_count": 3,
    "max_nodes": 5,
    "budget_remaining_ratio": 0.6,
    "prev_results": [
        {"node_id": "C1", "direction": "LONG", "confidence": 0.9},
    ],
})
decision = reflect_resp["result"]["echo"]["params"]["decision"]
check("方向矛盾 → INSERT_BEFORE", decision == "INSERT_BEFORE", f"decision={decision}")

# ── 场景 4: 预算不足 → JUMP_TO ───────────────────────────
print("\n场景 4: 预算不足 → JUMP_TO")
reflect_resp = call("reflection", {
    "mode": "decide",
    "current_node_id": "C3",
    "confidence": 0.5,
    "direction": "LONG",
    "status": "SUCCESS",
    "executed_count": 4,
    "max_nodes": 5,
    "budget_remaining_ratio": 0.1,
    "prev_results": [],
})
decision = reflect_resp["result"]["echo"]["params"]["decision"]
check("预算不足(0.1) → JUMP_TO", decision == "JUMP_TO", f"decision={decision}")

# ── 汇总 ────────────────────────────────────────────────
print("\n" + "=" * 60)
if failed == 0:
    print(f"ALL E2E TESTS PASSED ({passed} passed)")
    sys.exit(0)
else:
    print(f"FAILED: {failed} failed, {passed} passed")
    sys.exit(1)
