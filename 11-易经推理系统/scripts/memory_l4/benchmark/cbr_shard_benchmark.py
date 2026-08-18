#!/usr/bin/env python3
"""
CBR 分片检索回测脚本 — 验证分片检索 vs 普通检索的质量和性能
"""
import time
import json
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.cbr_engine import CBREngine, CBRQuery, RetrievedCase


def run_benchmark():
    print("=== CBR 分片检索回测 ===")
    print("加载案例库...")

    engine_normal = CBREngine(top_k=5, similarity_threshold=0.1, use_sharded=False)
    engine_normal.load(use_index=True)
    total_cases = len(engine_normal.case_base.cases)
    print(f"案例总数: {total_cases}")

    engine_sharded = CBREngine(top_k=5, similarity_threshold=0.1, use_sharded=True)
    engine_sharded.load(use_index=True)

    print("\n=== 性能对比 ===")
    query = CBRQuery(
        inst_id="BTC-USDT-SWAP",
        regime="trend_up",
        decision="long",
        confidence=0.7,
        volatility=0.005,
        entry_price=67000.0,
    )

    n_runs = 100

    start = time.time()
    for _ in range(n_runs):
        engine_normal.retrieve(query)
    normal_time = (time.time() - start) / n_runs * 1000

    start = time.time()
    for _ in range(n_runs):
        engine_sharded.retrieve(query)
    sharded_time = (time.time() - start) / n_runs * 1000

    speedup = normal_time / sharded_time if sharded_time > 0 else 0
    print(f"普通检索: {normal_time:.2f} ms/次")
    print(f"分片检索: {sharded_time:.2f} ms/次")
    print(f"速度提升: {speedup:.1f}x")

    print("\n=== Leave-One-Out 质量对比 ===")
    sample_size = min(50, total_cases)
    cases = engine_normal.case_base.cases[:sample_size]

    normal_hits = 0
    sharded_hits = 0
    normal_top1_sim_sum = 0.0
    sharded_top1_sim_sum = 0.0

    for i, test_case in enumerate(cases):
        q = CBRQuery(
            inst_id=test_case.inst_id,
            regime=test_case.regime,
            decision=test_case.decision,
            confidence=test_case.confidence,
            volatility=test_case.volatility,
            entry_price=test_case.entry_price,
        )

        train_cases = cases[:i] + cases[i+1:]

        engine_normal.case_base.cases = train_cases
        normal_results = engine_normal.retrieve(q)

        engine_sharded._sharded_base = None
        from scripts.memory_l4.cbr_sharded_retriever import ShardedCaseBase

        engine_sharded._sharded_base = ShardedCaseBase(train_cases)
        sharded_results = engine_sharded.retrieve(q)

        if normal_results:
            normal_top1_sim_sum += normal_results[0].similarity
            normal_hits += 1

        if sharded_results:
            sharded_top1_sim_sum += sharded_results[0].similarity
            sharded_hits += 1

        if (i + 1) % 10 == 0:
            print(f"进度: {i+1}/{sample_size}")

    print(f"\n检索成功率:")
    print(f"  普通检索: {normal_hits}/{sample_size} = {normal_hits/sample_size*100:.1f}%")
    print(f"  分片检索: {sharded_hits}/{sample_size} = {sharded_hits/sample_size*100:.1f}%")

    print(f"\nTop-1 平均相似度:")
    print(f"  普通检索: {normal_top1_sim_sum/normal_hits:.4f}" if normal_hits > 0 else "  普通检索: N/A")
    print(f"  分片检索: {sharded_top1_sim_sum/sharded_hits:.4f}" if sharded_hits > 0 else "  分片检索: N/A")

    print("\n=== 极端查询测试 ===")
    edge_queries = [
        CBRQuery(inst_id="BTC-USDT-SWAP", regime="trend_down", decision="short"),
        CBRQuery(inst_id="UNKNOWN-COIN", regime="trend_up", decision="long"),
        CBRQuery(inst_id="ETH-USDT-SWAP", regime="unknown_regime", decision="short"),
    ]

    for i, eq in enumerate(edge_queries):
        normal_res = engine_normal.retrieve(eq)
        sharded_res = engine_sharded.retrieve(eq)
        print(f"查询 {i+1}: inst={eq.inst_id} regime={eq.regime}")
        print(f"  普通检索: {len(normal_res)} 个结果")
        print(f"  分片检索: {len(sharded_res)} 个结果")


if __name__ == "__main__":
    run_benchmark()
