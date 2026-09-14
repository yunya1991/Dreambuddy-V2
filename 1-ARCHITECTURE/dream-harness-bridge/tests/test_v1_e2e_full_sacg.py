#!/usr/bin/env python3
"""
V1-E2E-FULL: S→A→C→G 全链路联调测试

模拟完整交易决策流程，验证四层协同：
  S 层 IntentGateway → 意图识别 + 风险评估
  A 层 GraphPlanner  → 执行计划编排
  C 层 C1/C2/C3 节点 → 技术分析 + Reflector 决策
  G 层 SessionConsumer → 事件投影写入 g_layer_events.jsonl

验证:
  1. 每一层 IPC 调用成功返回预期结构
  2. C 层节点产出的 direction/confidence 能驱动 Reflector 决策
  3. G 层投影文件正确写入 4 种事件类型
  4. 完整流程无异常中断（FAIL-OPEN 保障）
"""
import json
import subprocess
import sys
import os
import time

SERVER = os.path.join(os.path.dirname(__file__), "..", "packages", "python-server", "server.py")
PYTHON = sys.executable
G_LAYER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "packages", ".session-projections", "g_layer_events.jsonl"
)

passed = 0
failed = 0
session_id = f"e2e-full-{int(time.time())}"


def call(method, params):
    payload = {
        "schema_version": "1.0.0",
        "message_type": "request",
        "method": method,
        "params": params,
        "id": f"e2e-{method}-{os.getpid()}",
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


print("=" * 70)
print("V1-E2E-FULL: S→A→C→G 全链路联调")
print(f"session_id={session_id}")
print("=" * 70)

# 清理旧的 G 层投影文件（仅清理当前 session 的记录）
if os.path.exists(G_LAYER_PATH):
    with open(G_LAYER_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    with open(G_LAYER_PATH, "w", encoding="utf-8") as f:
        for line in lines:
            try:
                entry = json.loads(line)
                if entry.get("session_id") != session_id:
                    f.write(line)
            except json.JSONDecodeError:
                pass

# ═══════════════════════════════════════════════════════════════
# S 层: IntentGateway — 意图识别
# ═══════════════════════════════════════════════════════════════
print("\n[S 层] IntentGateway — 意图识别")
user_input = "分析 BTC 趋势，判断当前市场方向"
s_resp = call("intent_gateway", {
    "user_input": user_input,
    "step": 0,
    "agent_id": "e2e-test-agent",
})
s_result = s_resp["result"]
check("S 层返回 intent 字段", "intent" in s_result)
check("S 层 intent=market_analysis", s_result["intent"] == "market_analysis",
      f"intent={s_result['intent']}")
check("S 层 risk_level=low", s_result["risk_level"] == "low",
      f"risk={s_result['risk_level']}")
print(f"    intent={s_result['intent']}, risk={s_result['risk_level']}")

# G 层投影: intent_gate 事件
g_resp = call("session_consumer", {
    "session_id": session_id,
    "event_type": "intent_gate",
    "event_data": {
        "intent": s_result["intent"],
        "risk_level": s_result["risk_level"],
        "user_input": user_input,
    },
})
check("G 层 intent_gate 投影写入成功", g_resp["result"]["written"] is True)

# ═══════════════════════════════════════════════════════════════
# A 层: GraphPlanner — 执行计划编排
# ═══════════════════════════════════════════════════════════════
print("\n[A 层] GraphPlanner — 执行计划编排")
a_resp = call("graph_planner", {
    "intent_type": "TREND_FOLLOWING",
    "recommended_chain": "C",
    "confidence": 0.7,
})
a_result = a_resp["result"]
check("A 层返回 planned_chain", "planned_chain" in a_result)
check("A 层 selected_nodes 非空", len(a_result.get("selected_nodes", [])) > 0,
      f"nodes={a_result.get('selected_nodes', [])}")
check("A 层 budget 存在", "budget" in a_result)
print(f"    chain={a_result.get('planned_chain')}, "
      f"nodes={a_result.get('selected_nodes', [])[:5]}...")

# G 层投影: graph_node (A 层编排)
g_resp = call("session_consumer", {
    "session_id": session_id,
    "event_type": "graph_node",
    "event_data": {
        "phase": "A_planner",
        "planned_chain": a_result.get("planned_chain"),
        "selected_nodes": a_result.get("selected_nodes", []),
    },
})
check("G 层 graph_node(A层) 投影写入成功", g_resp["result"]["written"] is True)

# ═══════════════════════════════════════════════════════════════
# C 层: C1 技术扫描
# ═══════════════════════════════════════════════════════════════
print("\n[C 层] C1 技术扫描")
c1_resp = call("c1_scan", {"symbol": "BTC", "timeframe": "4H"})
c1_result = c1_resp["result"]
check("C1 返回 overall_signal", "overall_signal" in c1_result)
check("C1 返回 confidence", "confidence" in c1_result)
print(f"    signal={c1_result['overall_signal']}, conf={c1_result['confidence']}")

# G 层投影: node_execution (C1 call)
call("session_consumer", {
    "session_id": session_id,
    "event_type": "node_execution",
    "event_data": {"node_id": "C1", "symbol": "BTC", "timeframe": "4H"},
})
# G 层投影: node_result (C1 result)
call("session_consumer", {
    "session_id": session_id,
    "event_type": "node_result",
    "event_data": {
        "node_id": "C1",
        "signal": c1_result["overall_signal"],
        "confidence": c1_result["confidence"],
    },
})

# ═══════════════════════════════════════════════════════════════
# C 层: C2 动量分析
# ═══════════════════════════════════════════════════════════════
print("\n[C 层] C2 动量分析")
bull_mkt = {
    "price": 70000, "change_1h": 0.5, "change_4h": 1.2, "change_24h": 5.0,
    "rsi14": 62, "macd": 150.0, "macd_signal": 100.0, "macd_hist": 50.0,
    "ema20": 68000, "ema50": 65000, "ema200": 60000,
}
c2_resp = call("c2_momentum", {"symbol": "BTC", "market_data": bull_mkt})
c2_result = c2_resp["result"]
check("C2 返回 direction", c2_result["direction"] in ["LONG", "SHORT", "HOLD"])
check("C2 返回 confidence", 0 <= c2_result["confidence"] <= 1)
print(f"    direction={c2_result['direction']}, conf={c2_result['confidence']}")

call("session_consumer", {
    "session_id": session_id,
    "event_type": "node_result",
    "event_data": {
        "node_id": "C2",
        "direction": c2_result["direction"],
        "confidence": c2_result["confidence"],
    },
})

# ═══════════════════════════════════════════════════════════════
# C 层: C3 波动率分析
# ═══════════════════════════════════════════════════════════════
print("\n[C 层] C3 波动率分析")
normal_mkt = {
    "price": 67000, "atr": 850.0, "atr_pct": 0.025,
    "bb_upper": 70000, "bb_middle": 67000, "bb_lower": 64000,
    "bb_width": 0.045, "vol_ratio": 1.0, "change_24h": 1.0, "atr_change": 0.0,
}
c3_resp = call("c3_volatility", {"symbol": "BTC", "market_data": normal_mkt})
c3_result = c3_resp["result"]
check("C3 返回 direction", c3_result["direction"] in ["LONG", "SHORT", "HOLD"])
check("C3 返回 volatility_level", "volatility_level" in c3_result)
print(f"    direction={c3_result['direction']}, vol={c3_result['volatility_level']}")

call("session_consumer", {
    "session_id": session_id,
    "event_type": "node_result",
    "event_data": {
        "node_id": "C3",
        "direction": c3_result["direction"],
        "confidence": c3_result["confidence"],
        "volatility_level": c3_result["volatility_level"],
    },
})

# ═══════════════════════════════════════════════════════════════
# C 层: Reflector 决策（真实 Reflector.decide()）
# ═══════════════════════════════════════════════════════════════
print("\n[C 层] Reflector — 反射决策")
reflect_resp = call("reflection", {
    "mode": "decide",
    "current_node_id": "C3",
    "confidence": c2_result["confidence"],
    "direction": c2_result["direction"],
    "status": "SUCCESS",
    "executed_count": 3,
    "max_nodes": len(a_result.get("selected_nodes", [5])),
    "budget_remaining_ratio": 0.7,
    "prev_results": [
        {"node_id": "C1", "direction": "LONG", "confidence": 0.68},
        {"node_id": "C2", "direction": c2_result["direction"], "confidence": c2_result["confidence"]},
    ],
})
reflect_result = reflect_resp["result"]["echo"]["params"]
decision = reflect_result["decision"]
check("Reflector 返回合法决策", decision in ["CONTINUE", "REDO", "INSERT_BEFORE", "JUMP_TO", "EARLY_TERMINATE"])
print(f"    decision={decision}, reason={reflect_result.get('reason', '')[:60]}")

# G 层投影: graph_node (Reflector 决策)
call("session_consumer", {
    "session_id": session_id,
    "event_type": "graph_node",
    "event_data": {
        "phase": "C_reflector",
        "decision": decision,
        "reason": reflect_result.get("reason", ""),
    },
})

# ═══════════════════════════════════════════════════════════════
# G 层: 验证 g_layer_events.jsonl 投影完整性
# ═══════════════════════════════════════════════════════════════
print("\n[G 层] 验证 g_layer_events.jsonl 投影完整性")
time.sleep(0.5)  # 等待文件写入
check("G 层投影文件存在", os.path.exists(G_LAYER_PATH))

session_events = []
if os.path.exists(G_LAYER_PATH):
    with open(G_LAYER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("session_id") == session_id:
                    session_events.append(entry)
            except json.JSONDecodeError:
                pass

check(f"G 层投影记录数 >= 6", len(session_events) >= 6,
      f"count={len(session_events)}")

event_types = [e["event_type"] for e in session_events]
for etype in ["intent_gate", "node_execution", "node_result", "graph_node"]:
    check(f"G 层包含 {etype} 事件", etype in event_types)

# 打印 G 层投影摘要
print("\n    G 层投影事件序列:")
for i, e in enumerate(session_events):
    data = e["event_data"]
    summary = ""
    if e["event_type"] == "intent_gate":
        summary = f"intent={data.get('intent')}"
    elif e["event_type"] == "node_execution":
        summary = f"node={data.get('node_id')}"
    elif e["event_type"] == "node_result":
        summary = f"node={data.get('node_id')}, dir={data.get('direction', data.get('signal'))}"
    elif e["event_type"] == "graph_node":
        summary = f"phase={data.get('phase')}, decision={data.get('decision', '')}"
    print(f"      [{i+1}] {e['event_type']:15s} {summary}")

# ═══════════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
if failed == 0:
    print(f"ALL E2E FULL-CHAIN TESTS PASSED ({passed} passed)")
    print(f"G 层投影: {len(session_events)} events written to g_layer_events.jsonl")
    sys.exit(0)
else:
    print(f"FAILED: {failed} failed, {passed} passed")
    sys.exit(1)
