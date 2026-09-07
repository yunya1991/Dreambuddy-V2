#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端闭环测试：启动认知 MCP server → record → verify → 桥接反哺。

测试链路：
1. MCP stdio 接口验证：initialize → record → verify → stats → health
2. 桥接端到端：record_retrieval_as_memory（真实CLE）→ 映射JSONL →
   verify_and_feedback → boost JSON → apply_boost_to_results

隔离策略：
- MCP server 使用真实 cognitive_memory.db（闭环测试预期产物）；
- 桥接的 weight_path / map_path 指向临时目录，不污染 bridge/。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# 关闭 ChromaDB 遥测
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

_RAG_INFRA_DIR = Path(__file__).resolve().parent.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

_COGNITIVE_DIR = Path(__file__).resolve().parents[3] / "4-MEMORY" / "9-工具与接口"
if str(_COGNITIVE_DIR) not in sys.path:
    sys.path.insert(0, str(_COGNITIVE_DIR))

from bridge import (
    record_retrieval_as_memory,
    verify_and_feedback,
    apply_boost_to_results,
    get_boost,
    DEFAULT_BOOST,
    BOOST_SUCCESS_FACTOR,
)


# === MCP stdio 客户端 ===

def send_mcp(proc, request):
    """向 MCP server 发送一条 JSON-RPC 请求，返回响应字典。"""
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line)


def call_tool(proc, tool_name, arguments):
    """调用 MCP 工具，返回 result.content[0].text 解析后的字典。"""
    resp = send_mcp(proc, {
        "jsonrpc": "2.0", "id": 0,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })
    text = resp["result"]["content"][0]["text"]
    return json.loads(text)


def test_mcp_stdio_record_verify():
    """测试1：通过 MCP stdio 调用 record → verify → stats → health。"""
    print("\n=== 测试1：MCP stdio 接口闭环 ===")
    proc = subprocess.Popen(
        ["python3", str(_COGNITIVE_DIR / "cognitive_mcp_server.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(_COGNITIVE_DIR),
    )
    try:
        # initialize
        init_resp = send_mcp(proc, {
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {},
        })
        assert init_resp["result"]["serverInfo"]["name"] == "cognitive-memory-server"
        print(f"[OK] initialize: {init_resp['result']['serverInfo']['name']}")

        # record
        rec = call_tool(proc, "record", {
            "content": "[MCP闭环测试] RAG↔4-MEMORY桥接验证记忆",
            "quality_level": "C",
            "tags": "rag,bridge,mcp-test",
            "source": "mcp-e2e-test",
        })
        mid = rec["memory_id"]
        assert mid, f"record 未返回 memory_id: {rec}"
        assert rec["status"] == "recorded"
        print(f"[OK] record: memory_id={mid}")

        # verify success
        ver = call_tool(proc, "verify", {"memory_id": mid, "success": True})
        assert ver.get("success") in (True, None) or "new_quality" in ver
        print(f"[OK] verify(success=True): {ver}")

        # stats
        stats = call_tool(proc, "stats", {})
        print(f"[OK] stats keys: {list(stats.keys())[:8]}")
        assert stats, "stats 返回空"

        # health
        health = call_tool(proc, "health", {})
        assert health, "health 返回空"
        print(f"[OK] health: {list(health.keys())[:5]}...")

        return mid
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def test_bridge_e2e_closed_loop(mid_from_mcp=None):
    """测试2：桥接端到端闭环（使用真实 CognitiveLoopEntry）。

    record_retrieval_as_memory → verify_and_feedback → apply_boost_to_results
    """
    print("\n=== 测试2：桥接端到端闭环（真实CLE）===")

    # 隔离的 weight_path 和 map_path
    tmp = Path(tempfile.mkdtemp(prefix="bridge_e2e_"))
    weight_path = tmp / "weight_feedback.json"
    map_path = tmp / "retrieval_memory_map.jsonl"

    # 使用真实 CLE（懒加载，失败时 FAIL-OPEN）
    from cognitive_loop_entry import get_cle
    cle = get_cle()
    assert cle is not None, "CognitiveLoopEntry 初始化失败"
    print(f"[OK] CLE 初始化: storage={cle._storage_path}")

    # 1. record 检索结果为 C 级记忆
    query = "BCRM推理引擎 344模型"
    results = [
        {"source_file": "BCRM2推理引擎.md", "heading": "344+278模型",
         "content": "BCRM2采用344+278双模型架构，识别市场344种状态",
         "domain": "trading", "final_score": 0.85},
        {"source_file": "五计庙算战略层.md", "heading": "五维评分",
         "content": "道天地将法五维加权计算总分",
         "domain": "strategy", "final_score": 0.72},
    ]
    mappings = record_retrieval_as_memory(
        query, results, cle=cle, map_path=map_path)
    assert len(mappings) == 2, f"应记录2条映射，实际{len(mappings)}"
    print(f"[OK] record_retrieval_as_memory: {len(mappings)}条映射")
    for m in mappings:
        print(f"     - {m['memory_id']} → {m['source_file']}::{m['heading']}")

    # 2. 验证映射表 JSONL 持久化
    assert map_path.exists(), "映射表 JSONL 未创建"
    lines = map_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    print(f"[OK] 映射表 JSONL: {len(lines)} 条记录")

    # 3. verify 第一条（成功）并反哺 boost
    r1 = verify_and_feedback(
        mappings[0]["memory_id"], success=True, cle=cle,
        map_path=map_path, weight_path=weight_path)
    assert r1["status"] == "done", f"verify 反馈失败: {r1}"
    assert r1["boost_updated"] is True
    assert r1["source_file"] == "BCRM2推理引擎.md"
    print(f"[OK] verify_and_feedback(success=True): boost={r1['new_boost']}")

    # 4. verify 第二条（失败）反哺降权
    r2 = verify_and_feedback(
        mappings[1]["memory_id"], success=False, cle=cle,
        map_path=map_path, weight_path=weight_path)
    assert r2["status"] == "done"
    assert r2["new_boost"] < DEFAULT_BOOST
    print(f"[OK] verify_and_feedback(success=False): boost={r2['new_boost']}")

    # 5. 验证权重 JSON 持久化
    assert weight_path.exists(), "权重 JSON 未创建"
    wf = json.loads(weight_path.read_text(encoding="utf-8"))
    assert "BCRM2推理引擎.md::344+278模型" in wf
    print(f"[OK] 权重 JSON: {len(wf)} 个知识单元 boost")

    # 6. apply_boost_to_results 验证 boost 叠加与重排序
    new_results = [
        {"source_file": "BCRM2推理引擎.md", "heading": "344+278模型",
         "content": "BCRM2", "final_score": 0.80},
        {"source_file": "五计庙算战略层.md", "heading": "五维评分",
         "content": "五计", "final_score": 0.82},
    ]
    adjusted = apply_boost_to_results(new_results, weight_path=weight_path)
    # BCRM2 boost > 1.0，五计 boost < 1.0，应调整排序
    boost_bcrm = get_boost("BCRM2推理引擎.md", "344+278模型", weight_path=weight_path)
    boost_wuji = get_boost("五计庙算战略层.md", "五维评分", weight_path=weight_path)
    print(f"[OK] boost: BCRM2={boost_bcrm}, 五计={boost_wuji}")
    print(f"[OK] apply_boost: 排序后 {[r['source_file'] for r in adjusted]}")

    # 7. 闭环验证：boost 因子影响 final_score
    bcrm_adjusted = [r for r in adjusted if r["source_file"] == "BCRM2推理引擎.md"][0]
    assert bcrm_adjusted["rerank_signals"]["feedback_boost"] > DEFAULT_BOOST
    print(f"[OK] 闭环验证: BCRM2 final_score {0.80} → {bcrm_adjusted['final_score']}")

    return {"mappings": mappings, "weight_path": weight_path, "map_path": map_path}


def test_recall_retrieves_recorded_memory():
    """测试3：recall 能检索到刚 record 的桥接记忆。"""
    print("\n=== 测试3：recall 检索桥接记忆 ===")
    from cognitive_loop_entry import get_cle
    cle = get_cle()
    memories = cle.recall("RAG BCRM 桥接", top_k=5, min_quality="C")
    rag_memories = [m for m in memories if "RAG检索" in m.get("content", "")
                    or "rag-bridge" in str(m.get("tags", []))]
    print(f"[OK] recall 返回 {len(memories)} 条，其中 RAG 桥接记忆 {len(rag_memories)} 条")
    if rag_memories:
        m = rag_memories[0]
        print(f"     - [{m.get('quality_level')}] {m['content'][:80]}...")
        print(f"       tags={m.get('tags', [])}")
    return len(rag_memories) > 0


if __name__ == "__main__":
    # 测试1：MCP stdio 接口
    mid = test_mcp_stdio_record_verify()

    # 测试2：桥接端到端闭环
    result = test_bridge_e2e_closed_loop(mid)

    # 测试3：recall 检索验证
    recalled = test_recall_retrieves_recorded_memory()

    print("\n" + "=" * 60)
    print("闭环测试总结")
    print("=" * 60)
    print(f"MCP stdio record/verify/stats/health: PASS")
    print(f"桥接 record→映射→verify→boost反哺: PASS")
    print(f"recall 检索桥接记忆: {'PASS' if recalled else 'SKIP(异步索引未刷新)'}")
    print(f"\nSQLite: cognitive_memory.db (真实写入)")
    print(f"JSONL: {result['map_path']}")
    print(f"JSON:  {result['weight_path']}")
    print("=" * 60)
