#!/usr/bin/env python3
"""
V1-C3: C 层 C2/C3 节点真实 DreamOS 节点集成测试

验证:
  1. c2_momentum 调用真实 C2MomentumNode 返回 direction/confidence
  2. c3_volatility 调用真实 C3VolatilityNode 返回 volatility_level/squeeze
  3. 不同市场数据输入产生不同方向决策
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
    """通过子进程调用 Python server 的 IPC 方法"""
    payload = {
        "schema_version": "1.0.0",
        "message_type": "request",
        "method": method,
        "params": params,
        "id": "test-" + method,
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
    raise RuntimeError(f"No response. stderr={proc.stderr[:500]}")


def assert_eq(name, actual, expected):
    global passed, failed
    if actual == expected:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}: expected {expected}, got {actual}")
        failed += 1


def assert_in(name, value, container):
    global passed, failed
    if value in container:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}: {value} not in {container}")
        failed += 1


print("=" * 60)
print("V1-C3: C 层 C2/C3 节点真实 DreamOS 节点集成")
print("=" * 60)

# ── C2 动量分析 ──────────────────────────────────────────
print("\n--- C2 动量分析 ---")

# 强势上涨场景
bull_mkt = {
    "price": 70000,
    "change_1h": 0.5,
    "change_4h": 1.2,
    "change_24h": 5.0,
    "rsi14": 62,
    "macd": 150.0,
    "macd_signal": 100.0,
    "macd_hist": 50.0,
    "ema20": 68000,
    "ema50": 65000,
    "ema200": 60000,
}
resp = call("c2_momentum", {"symbol": "BTC", "market_data": bull_mkt})
result = resp["result"]
assert_in("C2 返回 LONG 方向", result["direction"], ["LONG", "SHORT", "HOLD"])
assert_eq("C2 强势上涨 → LONG", result["direction"], "LONG")
assert 0 <= result["confidence"] <= 1, "confidence 应在 0-1"
print(f"    confidence={result['confidence']}, momentum_score={result['outputs']['momentum_score']}")

# 强势下跌场景
bear_mkt = {
    "price": 60000,
    "change_1h": -0.5,
    "change_4h": -1.2,
    "change_24h": -5.0,
    "rsi14": 38,
    "macd": -150.0,
    "macd_signal": -100.0,
    "macd_hist": -50.0,
    "ema20": 62000,
    "ema50": 65000,
    "ema200": 68000,
}
resp = call("c2_momentum", {"symbol": "BTC", "market_data": bear_mkt})
result = resp["result"]
assert_eq("C2 强势下跌 → SHORT", result["direction"], "SHORT")
print(f"    confidence={result['confidence']}")

# 背离检测
div_mkt = {
    "price": 70000,
    "change_1h": 0.3,
    "change_4h": 0.8,
    "change_24h": 2.0,
    "rsi14": 48,  # 价格上涨但 RSI 偏低 → 看涨背离
    "macd": 80.0,
    "macd_signal": 60.0,
    "macd_hist": 20.0,
    "ema20": 69000,
    "ema50": 67000,
    "ema200": 62000,
}
resp = call("c2_momentum", {"symbol": "BTC", "market_data": div_mkt})
result = resp["result"]
assert_in("C2 背离检测", result["outputs"]["divergence"],
          ["none", "bullish_divergence", "bearish_divergence"])
print(f"    divergence={result['outputs']['divergence']}")

# phase 标记
assert_eq("C2 phase=real_dreamos_node", result["phase"], "real_dreamos_node")

# ── C3 波动率分析 ────────────────────────────────────────
print("\n--- C3 波动率分析 ---")

# 正常波动
normal_mkt = {
    "price": 67000,
    "atr": 850.0,
    "atr_pct": 0.025,
    "bb_upper": 70000,
    "bb_middle": 67000,
    "bb_lower": 64000,
    "bb_width": 0.045,
    "vol_ratio": 1.0,
    "change_24h": 1.0,
    "atr_change": 0.0,
}
resp = call("c3_volatility", {"symbol": "BTC", "market_data": normal_mkt})
result = resp["result"]
assert_in("C3 返回有效方向", result["direction"], ["LONG", "SHORT", "HOLD"])
assert_eq("C3 正常波动 → normal", result["volatility_level"], "normal")
print(f"    direction={result['direction']}, confidence={result['confidence']}")

# 波动率挤压（窄布林带）
squeeze_mkt = {
    "price": 67000,
    "atr": 300.0,
    "atr_pct": 0.005,
    "bb_upper": 67500,
    "bb_middle": 67000,
    "bb_lower": 66500,
    "bb_width": 0.015,
    "vol_ratio": 0.8,
    "change_24h": 0.5,
    "atr_change": -0.1,
}
resp = call("c3_volatility", {"symbol": "BTC", "market_data": squeeze_mkt})
result = resp["result"]
assert_eq("C3 挤压 → squeeze", result["volatility_level"], "squeeze")
assert_eq("C3 squeeze=True", result["squeeze"], True)
print(f"    direction={result['direction']}, confidence={result['confidence']}")

# 高波动
high_vol_mkt = {
    "price": 67000,
    "atr": 3500.0,
    "atr_pct": 0.052,
    "bb_upper": 75000,
    "bb_middle": 67000,
    "bb_lower": 59000,
    "bb_width": 0.09,
    "vol_ratio": 2.5,
    "change_24h": 3.0,
    "atr_change": 0.3,
}
resp = call("c3_volatility", {"symbol": "BTC", "market_data": high_vol_mkt})
result = resp["result"]
assert_eq("C3 高波动 → high", result["volatility_level"], "high")
print(f"    direction={result['direction']}, confidence={result['confidence']}")

# phase 标记
assert_eq("C3 phase=real_dreamos_node", result["phase"], "real_dreamos_node")

# ── 汇总 ────────────────────────────────────────────────
print("\n" + "=" * 60)
if failed == 0:
    print(f"ALL TESTS PASSED ({passed} passed)")
    sys.exit(0)
else:
    print(f"FAILED: {failed} failed, {passed} passed")
    sys.exit(1)
