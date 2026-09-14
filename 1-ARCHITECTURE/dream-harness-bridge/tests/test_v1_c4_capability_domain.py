#!/usr/bin/env python3
"""
V1-C4: C 层能力域接口测试

验证:
  1. execute_c_chain 不暴露内部节点，返回能力域级别的综合结果
  2. 无需 agent 提供 market_data（内部自动获取/默认值）
  3. 返回结构包含 capability / direction / confidence / details(C1/C2/C3)
  4. 外部传入 market_data 时使用传入数据
  5. 直接暴露节点的方法(c2_momentum/c3_volatility)仍可用但不作为主要能力接口
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
        "id": f"c4-{method}-{os.getpid()}",
        "timestamp": "2026-09-14T00:00:00Z",
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
print("V1-C4: C 层能力域接口测试")
print("=" * 60)

# ── 1. execute_c_chain 能力域接口 ────────────────────────
print("\n--- execute_c_chain 能力域接口 ---")

# 不传 market_data，内部自动获取（或使用默认值）
resp = call("execute_c_chain", {"symbol": "BTC", "timeframe": "4H"})
result = resp["result"]

check("返回 capability 字段", result.get("capability") == "os.c_layer.execute_c_chain",
      f"capability={result.get('capability')}")
check("返回 direction", result.get("direction") in ["LONG", "SHORT", "HOLD"],
      f"direction={result.get('direction')}")
check("返回 confidence (0-1)", 0 <= result.get("confidence", 0) <= 1,
      f"conf={result.get('confidence')}")
check("返回 details", "details" in result)
check("details 含 C1", "C1" in result.get("details", {}))
check("details 含 C2", "C2" in result.get("details", {}))
check("details 含 C3", "C3" in result.get("details", {}))
check("phase=os_c_layer_via_graph_executor", result.get("phase") == "os_c_layer_via_graph_executor")
print(f"    direction={result['direction']}, confidence={result['confidence']}")
print(f"    C1={result['details']['C1']['direction']}({result['details']['C1']['confidence']:.2f})")
print(f"    C2={result['details']['C2']['direction']}({result['details']['C2']['confidence']:.2f})")
print(f"    C3={result['details']['C3']['direction']}({result['details']['C3']['confidence']:.2f})")

# ── 2. 外部传入 market_data ─────────────────────────────
print("\n--- 外部传入 market_data ---")
bull_mkt = {
    "price": 70000, "change_1h": 0.5, "change_4h": 1.2, "change_24h": 5.0,
    "rsi14": 62, "macd": 150.0, "macd_signal": 100.0, "macd_hist": 50.0,
    "ema20": 68000, "ema50": 65000, "ema200": 60000,
    "atr": 850.0, "atr_pct": 0.025,
    "bb_upper": 72000, "bb_middle": 67000, "bb_lower": 62000,
    "bb_width": 0.15, "vol_ratio": 1.2, "atr_change": 0.1,
}
resp = call("execute_c_chain", {"symbol": "BTC", "market_data": bull_mkt})
result = resp["result"]
check("牛市数据 → 综合方向非 HOLD", result["direction"] in ["LONG", "SHORT"],
      f"direction={result['direction']}")
check("C2 牛市 → LONG", result["details"]["C2"]["direction"] == "LONG")
print(f"    direction={result['direction']}, confidence={result['confidence']}")

# ── 3. 验证不再直接暴露节点作为能力接口 ──────────────────
print("\n--- 架构边界验证 ---")
# execute_c_chain 的返回中不直接暴露 node_id 作为顶层字段
check("顶层无 node_id（能力域接口不暴露节点）", "node_id" not in result,
      "顶层无 node_id 字段")
check("顶层用 capability 标识", "capability" in result)

# ── 4. 直接节点方法仍存在但标记为内部 ────────────────────
print("\n--- 内部节点方法（保留用于调试，不作为主要能力接口）---")
# c2_momentum 和 c3_volatility 方法仍然可调用（底层实现保留）
resp = call("c2_momentum", {"symbol": "BTC", "market_data": bull_mkt})
check("c2_momentum 底层方法仍可调用", resp["result"]["phase"] == "real_dreamos_node")

resp = call("c3_volatility", {"symbol": "BTC", "market_data": bull_mkt})
check("c3_volatility 底层方法仍可调用", resp["result"]["phase"] == "real_dreamos_node")

# ── 汇总 ────────────────────────────────────────────────
print("\n" + "=" * 60)
if failed == 0:
    print(f"ALL TESTS PASSED ({passed} passed)")
    sys.exit(0)
else:
    print(f"FAILED: {failed} failed, {passed} passed")
    sys.exit(1)
