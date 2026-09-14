#!/usr/bin/env python3
"""G6-G10 索引系统集成测试

验证三大索引子系统接入底座：
  G6+G7: 产物索引 IPC + A7 查询
  G8:   交易索引接入 A7 反思
  G9:   交易经验回流认知系统
  G10:  认知蒸馏产物自动构建向量索引
"""
import json
import subprocess
import sys
import os
import time
from datetime import datetime

SERVER = os.path.join(os.path.dirname(__file__), "..", "packages", "python-server", "server.py")
PYTHON = sys.executable

PASS = 0
FAIL = 0


def call(method, params):
    payload = {
        "schema_version": "1.0.0", "message_type": "request",
        "method": method, "params": params,
        "id": f"test-{method}-{time.time()}",
        "timestamp": datetime.utcnow().isoformat(),
    }
    proc = subprocess.run(
        [PYTHON, SERVER],
        input=json.dumps(payload) + "\n",
        capture_output=True, text=True, timeout=60,
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
    raise RuntimeError(f"No response for {method}")


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


def test_g6_g7_artifact_index():
    """G6+G7: 产物索引 IPC"""
    print("\n── G6+G7: 产物索引 IPC ──")

    # list
    r = call("artifact_index", {"action": "list"})
    check("产物索引 list", r["ok"] and r["result"]["node_id"] == "artifact_index",
          f"status={r['result']['status']}, total={r['result'].get('total', 0)}")

    # detail
    r = call("artifact_index", {"action": "detail", "slug": "research/test"})
    check("产物索引 detail", r["ok"] and "detail" in r["result"],
          f"found={r['result']['detail'].get('found', False)}")

    # relations
    r = call("artifact_index", {"action": "relations"})
    check("产物索引 relations", r["ok"] and "relations" in r["result"],
          f"relations_count={len(r['result'].get('relations', []))}")

    # phase_groups
    r = call("artifact_index", {"action": "phase_groups", "limit": 3})
    check("产物索引 phase_groups", r["ok"] and "phase_groups" in r["result"])

    # search
    r = call("artifact_index", {"action": "search", "query": "research"})
    check("产物索引 search", r["ok"] and "items" in r["result"],
          f"total={r['result'].get('total', 0)}")

    # FAIL-OPEN: unknown action
    r = call("artifact_index", {"action": "invalid"})
    check("产物索引 未知action FAIL-OPEN", r["ok"] and r["result"]["status"] == "error")


def test_g8_trade_index():
    """G8: 交易索引 IPC"""
    print("\n── G8: 交易索引 IPC ──")

    # query
    r = call("trade_index", {"action": "query", "limit": 10})
    check("交易索引 query", r["ok"] and r["result"]["node_id"] == "trade_index",
          f"status={r['result']['status']}, total={r['result'].get('total', 0)}")

    # stats
    r = call("trade_index", {"action": "stats"})
    check("交易索引 stats", r["ok"] and "stats" in r["result"],
          f"stats={r['result'].get('stats', {})}")

    # FAIL-OPEN: no index
    r = call("trade_index", {"action": "query", "symbol": "NONEXIST"})
    check("交易索引 FAIL-OPEN(空结果)", r["ok"] and r["result"]["status"] in ("ok", "degraded"),
          f"status={r['result']['status']}")


def test_g9_trade_to_cognitive():
    """G9: 交易经验回流认知系统"""
    print("\n── G9: 交易经验回流认知 ──")

    r = call("trade_index", {"action": "record_to_cognitive"})
    check("交易经验 record_to_cognitive", r["ok"] and r["result"]["node_id"] == "trade_index",
          f"status={r['result']['status']}, recorded={r['result'].get('recorded', 0)}")


def test_g10_vector_index():
    """G10: 向量索引构建"""
    print("\n── G10: 向量索引构建 ──")

    # 增量构建
    r = call("build_vector_index", {"force": False})
    check("向量索引 增量构建", r["ok"] and r["result"]["node_id"] == "vector_index",
          f"status={r['result']['status']}")

    # 检查返回有统计或降级信息
    has_info = ("stats" in r["result"] or "total_md_files" in r["result"]
                or "reason" in r["result"])
    check("向量索引 返回信息", has_info)


def test_a7_index_integration():
    """A7 索引系统集成"""
    print("\n── A7 索引系统集成 ──")

    try:
        # 测试在 dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/tests/
        # dreamos 在 1-ARCHITECTURE/ 下，即 tests 的上两级
        dreamos_arch = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", ".."
        ))
        if dreamos_arch not in sys.path:
            sys.path.insert(0, dreamos_arch)

        from dreamos.capabilities.trading.nodes.a7_practice_gate import A7PracticeGateNode
        node = A7PracticeGateNode()

        check("A7 有 _query_index_system 方法", hasattr(node, "_query_index_system"))

        # 用轻量 mock state 测试调用不崩溃
        class MockState:
            intent = {"symbol": "BTC"}
        insights = node._query_index_system(MockState(), "LONG")
        check("A7 索引查询不崩溃", isinstance(insights, list),
              f"insights_count={len(insights)}")

    except Exception as e:
        check("A7 索引集成", False, f"error={type(e).__name__}: {e}")


def test_regression_all_ipc():
    """回归测试：已有 IPC 方法不受影响"""
    print("\n── 回归：已有 IPC 方法 ──")

    methods = [
        ("intent_gateway", {"user_input": "BTC", "step": 1, "agent_id": "reg"}),
        ("execute_c_chain", {"symbol": "BTC", "timeframe": "4H"}),
        ("reflection", {"mode": "validate", "decision": "CONTINUE"}),
        ("session_consumer", {"session_id": "reg", "event_type": "intent_gate",
                              "event_data": {"test": True}}),
    ]
    for method, params in methods:
        r = call(method, params)
        check(f"回归 {method}", r["ok"], f"ok={r['ok']}")


def main():
    print("🚀 G6-G10 索引系统集成测试")
    print("=" * 60)

    tests = [
        test_g6_g7_artifact_index,
        test_g8_trade_index,
        test_g9_trade_to_cognitive,
        test_g10_vector_index,
        test_a7_index_integration,
        test_regression_all_ipc,
    ]

    for test in tests:
        try:
            test()
        except Exception as e:
            global FAIL
            FAIL += 1
            print(f"  ❌ {test.__name__} — ERROR: {e}")

    print(f"\n{'=' * 60}")
    total = PASS + FAIL
    print(f"总计: {total} | ✅ 通过: {PASS} | ❌ 失败: {FAIL}")
    if FAIL == 0:
        print("🎉 全部通过 — 索引系统完美集成")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
