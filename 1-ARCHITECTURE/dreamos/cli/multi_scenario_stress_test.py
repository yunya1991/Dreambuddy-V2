"""
Dream OS 多场景模拟压力测试

覆盖维度:
  1) 36 种完整市场场景（3趋势 × 4波动率 × 3动量）
  2) 8 种交易币种
  3) 5 种图编排模式
  4) 边缘场景（极值、边界、异常）
  5) 编排记忆回测验证（L0/L1/L2/L3）

测试指标:
  - 场景覆盖率
  - 编排节点数 vs 实际执行数一致性
  - 节点成功率
  - 端到端延迟分布
  - 记忆表命中分布
  - 方向/置信度分布
"""

from __future__ import annotations

import os
import sys
import json
import time
import random
import logging
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from dreamos.registry import get_default_registry
from dreamos.capabilities.trading.nodes import register_all
from dreamos.core.compute.graph_executor import GraphExecutor
from dreamos.core.arrange.execution_graph import SequentialGraph
from dreamos.core.sense.scenario_classifier import ScenarioClassifier
from dreamos.core.memory.orchestration_memory import OrchestrationMemory
from dreamos.shared.state import new_state


# ── 36 场景枚举 ──────────────────────────────────────────────
TRENDS = ["BULL", "BEAR", "NEUTRAL"]
VOLATILITIES = ["LOW", "NORMAL", "HIGH", "EXTREME"]
MOMENTUMS = ["ACCELERATING", "DECELERATING", "EXHAUSTION"]

ALL_36_SCENARIOS = [
    f"{t}_{v}_{m}"
    for t in TRENDS
    for v in VOLATILITIES
    for m in MOMENTUMS
]

SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "ARB", "OP", "DOT"]


def generate_market_data_for_scenario(scenario_id: str, symbol: str = "BTC") -> Dict[str, Any]:
    """根据场景 ID 生成符合该场景特征的模拟行情数据

    通过调整 price/ema/rsi/atr/change 等指标，让 ScenarioClassifier
    稳定地将其分类为目标场景。
    """
    parts = scenario_id.split("_")
    trend, vol, mom = parts[0], parts[1], "_".join(parts[2:])

    base_price = {
        "BTC": 65000, "ETH": 3500, "SOL": 150, "AVAX": 40,
        "LINK": 18, "ARB": 1.2, "OP": 2.5, "DOT": 8,
    }.get(symbol, 100)

    # ── 波动率映射 ──
    atr_pct_map = {
        "LOW": 0.005,      # 0.5%
        "NORMAL": 0.015,    # 1.5%
        "HIGH": 0.03,       # 3%
        "EXTREME": 0.06,    # 6%
    }
    atr_pct = atr_pct_map[vol]

    # ── 趋势映射（价格 vs EMA 排列）──
    if trend == "BULL":
        ema20 = base_price * 0.98
        ema50 = base_price * 0.95
        ema200 = base_price * 0.90
        change_24h = 3.5
    elif trend == "BEAR":
        ema20 = base_price * 1.02
        ema50 = base_price * 1.05
        ema200 = base_price * 1.10
        change_24h = -3.5
    else:  # NEUTRAL
        ema20 = base_price * 1.005
        ema50 = base_price * 0.995
        ema200 = base_price
        change_24h = 0.8

    # ── 动量加速度映射 ──
    if mom == "ACCELERATING":
        change_1h = change_24h * 0.15
        change_4h = change_24h * 0.4
        rsi = 70 if trend == "BULL" else 30
    elif mom == "DECELERATING":
        change_1h = change_24h * 0.03
        change_4h = change_24h * 0.5
        rsi = 55 if trend == "BULL" else 45
    else:  # EXHAUSTION
        # 衰竭: 24h有明显趋势，但1h反向，RSI接近极端
        if trend == "BULL":
            change_24h = 4.0
            change_1h = -0.8
            change_4h = change_24h * 0.45
            rsi = 72
        elif trend == "BEAR":
            change_24h = -4.0
            change_1h = 0.8
            change_4h = change_24h * 0.45
            rsi = 28
        else:  # NEUTRAL + EXHAUSTION: 构造震荡衰竭
            # 24h小幅波动但短期剧烈反向 + RSI极端
            change_24h = 2.5  # 轻微上涨但接近中性边界
            change_1h = -1.2  # 短期明显回落
            change_4h = 1.5
            rsi = 68  # 接近超买后回落

    atr = base_price * atr_pct

    return {
        "symbol": symbol,
        "price": base_price,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "change_1h": change_1h,
        "change_4h": change_4h,
        "change_24h": change_24h,
        "rsi14": rsi,
        "atr_pct": atr_pct,
        "atr": atr,
        "volume_24h": base_price * 1000 * random.uniform(0.8, 1.2),
        "high_24h": base_price * (1 + atr_pct * 0.8),
        "low_24h": base_price * (1 - atr_pct * 0.8),
        # 基本面数据（模拟，供 F 链消费）
        "mvrv_z_score": 1.5 + random.uniform(-0.5, 0.5),
        "sopr": 1.02 + random.uniform(-0.02, 0.02),
        "ahr999": 1.2 + random.uniform(-0.3, 0.3),
        "mayer_multiple": 0.9 + random.uniform(-0.2, 0.2),
        "pi_cycle_top": 0.5 + random.uniform(-0.2, 0.2),
        "active_addresses": 1000000 + random.randint(-100000, 100000),
        "address_change_24h": random.uniform(-5, 5),
        "whale_accumulation_score": 50 + random.uniform(-20, 20),
        "whale_balance_change": random.uniform(-3, 3),
        "miner_position": 50 + random.uniform(-15, 15),
        "gas_price_gwei": 30 + random.uniform(-10, 20),
        "policy_score": 50 + random.uniform(-15, 15),
        "dxy_strength": 50 + random.uniform(-10, 10),
        "rate_impact": random.uniform(-0.2, 0.1),
        "crypto_friendly_score": 55 + random.uniform(-15, 15),
        # Freqtrade 信号（模拟）
        "freqtrade_signal": {
            "direction": random.choice(["LONG", "SHORT", "HOLD"]),
            "confidence": round(random.uniform(0.3, 0.9), 2),
            "strategy_count": random.randint(0, 6),
            "long_votes": random.randint(0, 5),
            "short_votes": random.randint(0, 5),
        },
    }


class MultiScenarioStressTest:
    """多场景模拟压力测试框架"""

    def __init__(self, rounds_per_scenario: int = 3):
        self.rounds_per_scenario = rounds_per_scenario
        self.total_rounds = len(ALL_36_SCENARIOS) * rounds_per_scenario
        self.results: List[Dict] = []
        self.stats = {
            "total_rounds": 0,
            "success_rounds": 0,
            "failed_rounds": 0,
            "scenario_coverage": set(),
            "scenario_classification_errors": [],
            "planned_vs_executed_mismatch": [],
            "latency_distribution": defaultdict(list),
            "node_success_rate": defaultdict(lambda: {"success": 0, "total": 0}),
            "memory_fallback_distribution": defaultdict(int),
            "pattern_distribution": defaultdict(int),
            "direction_distribution": defaultdict(int),
            "confidence_buckets": defaultdict(int),
            "edge_case_results": {},
            "errors": [],
        }

        self.registry = get_default_registry()
        register_all(self.registry)
        self.scenario_classifier = ScenarioClassifier()
        self.orchestration_memory = OrchestrationMemory()
        self.orchestration_memory.load()
        self.graph_executor = GraphExecutor(registry=self.registry, max_steps=30)

    # ── 核心测试方法 ──────────────────────────────────────────

    def test_scenario_classification_accuracy(self) -> Dict[str, Any]:
        """测试1: 场景分类准确性

        为每种场景生成模拟数据，验证 ScenarioClassifier 能正确分类。
        """
        print("\n" + "=" * 60)
        print("🧪 测试1: 36场景分类准确性验证")
        print("=" * 60)

        results = {}
        misclassified = []

        for scenario_id in ALL_36_SCENARIOS:
            mkt = generate_market_data_for_scenario(scenario_id, "BTC")
            classified = self.scenario_classifier.classify(mkt)
            is_correct = classified.scenario_id == scenario_id

            results[scenario_id] = {
                "expected": scenario_id,
                "actual": classified.scenario_id,
                "correct": is_correct,
                "trend_score": round(classified.trend_score, 3),
                "volatility_pct": round(classified.volatility_pct, 4),
                "momentum_speed": round(classified.momentum_speed, 2),
                "momentum_accel": round(classified.momentum_accel, 3),
                "exhaustion": classified.exhaustion,
            }

            if not is_correct:
                misclassified.append(scenario_id)

        correct_count = sum(1 for r in results.values() if r["correct"])
        accuracy = correct_count / len(ALL_36_SCENARIOS) * 100

        print(f"\n  总场景数: {len(ALL_36_SCENARIOS)}")
        print(f"  正确分类: {correct_count}")
        print(f"  准确率: {accuracy:.1f}%")

        if misclassified:
            print(f"\n  ⚠️  误分类场景 ({len(misclassified)}个):")
            for s in misclassified[:10]:
                r = results[s]
                print(f"    期望: {r['expected']} → 实际: {r['actual']}")

        return {
            "total_scenarios": len(ALL_36_SCENARIOS),
            "correct_count": correct_count,
            "accuracy_pct": round(accuracy, 2),
            "misclassified": misclassified,
            "details": results,
        }

    def test_orchestration_memory_coverage(self) -> Dict[str, Any]:
        """测试2: 编排记忆表覆盖率

        验证36种场景都能在 OrchestrationMemory 中找到对应配置。
        """
        print("\n" + "=" * 60)
        print("🧠 测试2: 编排记忆表36场景覆盖率")
        print("=" * 60)

        results = {}
        fallback_counts = defaultdict(int)
        pattern_counts = defaultdict(int)
        node_counts = defaultdict(int)

        for scenario_id in ALL_36_SCENARIOS:
            choice = self.orchestration_memory.select(scenario_id)
            fallback_counts[choice.fallback_level] += 1
            pattern_counts[choice.pattern] += 1
            for nid in choice.nodes:
                node_counts[nid] += 1
            results[scenario_id] = {
                "pattern": choice.pattern,
                "nodes": list(choice.nodes),
                "fallback_level": choice.fallback_level,
            }

        l0_l2_count = sum(v for k, v in fallback_counts.items() if k != "L3")
        coverage = l0_l2_count / len(ALL_36_SCENARIOS) * 100

        print(f"\n  总场景数: {len(ALL_36_SCENARIOS)}")
        print(f"  记忆表命中(L0/L1/L2): {l0_l2_count} ({coverage:.1f}%)")
        print(f"  默认降级(L3): {fallback_counts.get('L3', 0)}")
        print(f"\n  降级层级分布:")
        for level, count in sorted(fallback_counts.items()):
            print(f"    {level}: {count}个场景")
        print(f"\n  编排模式分布:")
        for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
            print(f"    {pattern}: {count}个场景")

        return {
            "total_scenarios": len(ALL_36_SCENARIOS),
            "coverage_pct": round(coverage, 2),
            "fallback_distribution": dict(fallback_counts),
            "pattern_distribution": dict(pattern_counts),
            "node_coverage": dict(node_counts),
            "details": results,
        }

    def test_graph_execution_consistency(self) -> Dict[str, Any]:
        """测试3: 图执行一致性（编排节点数 vs 实际执行数）"""
        print("\n" + "=" * 60)
        print("📊 测试3: 图编排-执行一致性验证")
        print("=" * 60)

        results = []
        mismatches = []
        latency_stats = []
        node_stats = defaultdict(lambda: {"success": 0, "failed": 0, "total": 0})

        test_cases = []
        # 每个场景跑1次，共36次
        for scenario_id in ALL_36_SCENARIOS:
            symbol = random.choice(SYMBOLS)
            mkt = generate_market_data_for_scenario(scenario_id, symbol)
            test_cases.append((scenario_id, symbol, mkt))

        total = len(test_cases)
        for i, (scenario_id, symbol, mkt) in enumerate(test_cases):
            choice = self.orchestration_memory.select(scenario_id)
            planned_nodes = list(choice.nodes)
            planned_count = len(planned_nodes)

            graph = SequentialGraph()
            for node_id in planned_nodes:
                node = self.registry.get(node_id)
                if node:
                    graph.add_node(node)

            cycle_id = f"stress_consistency_{scenario_id}_{i}"
            state = new_state(cycle_id=cycle_id)
            state.market_data = mkt
            state.inputs = {"mkt": mkt, "symbol": symbol}

            start = time.time()
            report = self.graph_executor.execute(graph, state)
            latency_ms = (time.time() - start) * 1000

            executed_count = report.executed_nodes
            success_count = report.success_nodes
            # 一致性判断：检查所有计划节点都有执行结果（success or fail）
            # 注：executed_nodes 统计的是内部子步骤数，不是顶层节点数
            # 因此用 state.get_result 是否返回有效结果来判断顶层节点是否被执行
            executed_top_nodes = sum(
                1 for nid in planned_nodes if state.get_result(nid) is not None
            )
            is_match = executed_top_nodes == planned_count

            # 统计每个节点的成功/失败
            for nid in planned_nodes:
                node_stats[nid]["total"] += 1
                result = state.get_result(nid)
                if result:
                    status = getattr(result, "status", None)
                    # NodeStatus 枚举或字符串都兼容（不区分大小写）
                    status_str = status.value if hasattr(status, "value") else str(status)
                    if "success" in status_str.lower():
                        node_stats[nid]["success"] += 1
                    else:
                        node_stats[nid]["failed"] += 1
                else:
                    node_stats[nid]["failed"] += 1

            result_item = {
                "scenario_id": scenario_id,
                "symbol": symbol,
                "pattern": choice.pattern,
                "fallback_level": choice.fallback_level,
                "planned_nodes": planned_count,
                "executed_top_nodes": executed_top_nodes,
                "executed_substeps": executed_count,
                "success_nodes": success_count,
                "latency_ms": round(latency_ms, 2),
                "consistent": is_match,
                "final_direction": getattr(state, "final_direction", None),
            }
            results.append(result_item)
            latency_stats.append(latency_ms)

            if not is_match:
                mismatches.append(result_item)

            if (i + 1) % 9 == 0:
                print(f"  进度: {i+1}/{total} 场景")

        # 统计
        match_count = total - len(mismatches)
        match_rate = match_count / total * 100
        avg_latency = sum(latency_stats) / len(latency_stats) if latency_stats else 0
        latency_stats.sort()
        p50 = latency_stats[len(latency_stats) // 2]
        p95 = latency_stats[int(len(latency_stats) * 0.95)]
        p99 = latency_stats[int(len(latency_stats) * 0.99)]

        print(f"\n  总图数: {total}")
        print(f"  编排-执行一致: {match_count} ({match_rate:.1f}%)")
        print(f"  不一致: {len(mismatches)}")
        print(f"\n  延迟分布:")
        print(f"    平均: {avg_latency:.1f}ms")
        print(f"    P50:  {p50:.1f}ms")
        print(f"    P95:  {p95:.1f}ms")
        print(f"    P99:  {p99:.1f}ms")

        print(f"\n  节点成功率:")
        for nid, stats in sorted(node_stats.items(), key=lambda x: -x[1]["total"]):
            rate = stats["success"] / stats["total"] * 100 if stats["total"] > 0 else 0
            print(f"    {nid}: {stats['success']}/{stats['total']} ({rate:.1f}%)")

        return {
            "total_graphs": total,
            "consistent_count": match_count,
            "consistency_rate_pct": round(match_rate, 2),
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
            "latency": {
                "avg_ms": round(avg_latency, 2),
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "p99_ms": round(p99, 2),
            },
            "node_stats": {k: dict(v) for k, v in node_stats.items()},
        }

    def test_edge_cases(self) -> Dict[str, Any]:
        """测试4: 边缘场景压力测试"""
        print("\n" + "=" * 60)
        print("⚡ 测试4: 边缘场景压力测试")
        print("=" * 60)

        edge_cases = {
            "zero_atr": {"atr_pct": 0.0, "rsi14": 50, "change_24h": 0, "change_4h": 0, "change_1h": 0,
                         "price": 65000, "ema20": 65000, "ema50": 65000, "ema200": 65000},
            "extreme_high_atr": {"atr_pct": 0.20, "rsi14": 99, "change_24h": 50, "change_4h": 20, "change_1h": 5,
                                 "price": 65000, "ema20": 40000, "ema50": 30000, "ema200": 20000},
            "rsi_0": {"atr_pct": 0.02, "rsi14": 0.1, "change_24h": -20, "change_4h": -8, "change_1h": -2,
                      "price": 30000, "ema20": 40000, "ema50": 50000, "ema200": 60000},
            "rsi_100": {"atr_pct": 0.02, "rsi14": 99.9, "change_24h": 20, "change_4h": 8, "change_1h": 2,
                        "price": 80000, "ema20": 70000, "ema50": 60000, "ema200": 50000},
            "price_crash": {"atr_pct": 0.15, "rsi14": 10, "change_24h": -30, "change_4h": -15, "change_1h": -5,
                            "price": 20000, "ema20": 35000, "ema50": 45000, "ema200": 55000},
            "price_rally": {"atr_pct": 0.12, "rsi14": 95, "change_24h": 25, "change_4h": 10, "change_1h": 3,
                            "price": 100000, "ema20": 75000, "ema50": 60000, "ema200": 45000},
            "cross_ema": {"atr_pct": 0.01, "rsi14": 48, "change_24h": 0.5, "change_4h": 0.2, "change_1h": 0.05,
                          "price": 50000, "ema20": 50100, "ema50": 49900, "ema200": 50000},
            "empty_freqtrade": {"atr_pct": 0.015, "rsi14": 50, "change_24h": 1, "change_4h": 0.3, "change_1h": 0.05,
                                "price": 50000, "ema20": 49500, "ema50": 48000, "ema200": 45000,
                                "freqtrade_signal": None},
            "zero_strategy_freqtrade": {"atr_pct": 0.015, "rsi14": 50, "change_24h": 1, "change_4h": 0.3, "change_1h": 0.05,
                                        "price": 50000, "ema20": 49500, "ema50": 48000, "ema200": 45000,
                                        "freqtrade_signal": {"direction": "HOLD", "confidence": 0, "strategy_count": 0, "long_votes": 0, "short_votes": 0}},
            "degraded_fundamentals": {"atr_pct": 0.015, "rsi14": 50, "change_24h": 1, "change_4h": 0.3, "change_1h": 0.05,
                                      "price": 50000, "ema20": 49500, "ema50": 48000, "ema200": 45000,
                                      "_f_chain_degraded": True},
        }

        results = {}
        for name, mkt_base in edge_cases.items():
            print(f"\n  ▶ {name}")
            try:
                # 场景分类
                mkt = dict(mkt_base)
                mkt.setdefault("symbol", "BTC")
                classified = self.scenario_classifier.classify(mkt)

                # 编排
                choice = self.orchestration_memory.select(classified.scenario_id)

                # 执行
                graph = SequentialGraph()
                for nid in choice.nodes:
                    node = self.registry.get(nid)
                    if node:
                        graph.add_node(node)

                state = new_state(cycle_id=f"edge_{name}")
                state.market_data = mkt
                state.inputs = {"mkt": mkt, "symbol": "BTC"}

                start = time.time()
                report = self.graph_executor.execute(graph, state)
                latency_ms = (time.time() - start) * 1000

                # 收集方向和置信度
                directions = []
                confidences = []
                for nid in choice.nodes:
                    result = state.get_result(nid)
                    if result and hasattr(result, 'direction'):
                        directions.append(result.direction)
                        confidences.append(getattr(result, 'confidence', 0))

                results[name] = {
                    "success": True,
                    "scenario": classified.scenario_id,
                    "pattern": choice.pattern,
                    "planned_nodes": len(choice.nodes),
                    "executed_nodes": report.executed_nodes,
                    "latency_ms": round(latency_ms, 2),
                    "directions": directions,
                    "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0,
                    "error": None,
                }
                print(f"    ✅ 成功 | 场景={classified.scenario_id} | 节点={report.executed_nodes} | 延迟={latency_ms:.1f}ms")
            except Exception as e:
                results[name] = {
                    "success": False,
                    "error": str(e),
                }
                print(f"    ❌ 失败: {e}")

        success_count = sum(1 for r in results.values() if r["success"])
        print(f"\n  边缘场景总数: {len(edge_cases)}")
        print(f"  成功: {success_count}")
        print(f"  失败: {len(edge_cases) - success_count}")

        return results

    def test_full_pipeline_stress(self, rounds: int = 108) -> Dict[str, Any]:
        """测试5: 全链路压力测试（多轮多场景混合）"""
        print("\n" + "=" * 60)
        print(f"🚀 测试5: 全链路压力测试 ({rounds}轮)")
        print("=" * 60)

        results = []
        scenario_coverage = set()
        total_start = time.time()

        for i in range(rounds):
            scenario_id = random.choice(ALL_36_SCENARIOS)
            symbol = random.choice(SYMBOLS)
            mkt = generate_market_data_for_scenario(scenario_id, symbol)

            try:
                classified = self.scenario_classifier.classify(mkt)
                scenario_coverage.add(classified.scenario_id)

                choice = self.orchestration_memory.select(classified.scenario_id)

                graph = SequentialGraph()
                for nid in choice.nodes:
                    node = self.registry.get(nid)
                    if node:
                        graph.add_node(node)

                state = new_state(cycle_id=f"full_stress_{i}")
                state.market_data = mkt
                state.inputs = {"mkt": mkt, "symbol": symbol}

                start = time.time()
                report = self.graph_executor.execute(graph, state)
                latency_ms = (time.time() - start) * 1000

                # 收集所有节点结果的方向和置信度
                all_directions = []
                all_confidences = []
                for nid in choice.nodes:
                    result = state.get_result(nid)
                    if result and hasattr(result, 'direction'):
                        all_directions.append(result.direction)
                        all_confidences.append(getattr(result, 'confidence', 0))

                result_item = {
                    "round": i,
                    "scenario": classified.scenario_id,
                    "symbol": symbol,
                    "pattern": choice.pattern,
                    "fallback": choice.fallback_level,
                    "planned_nodes": len(choice.nodes),
                    "executed_nodes": report.executed_nodes,
                    "success_nodes": report.success_nodes,
                    "latency_ms": round(latency_ms, 2),
                    "directions": all_directions,
                    "success": report.success_nodes > 0,
                }
                results.append(result_item)

                # 更新全局统计
                self.stats["memory_fallback_distribution"][choice.fallback_level] += 1
                self.stats["pattern_distribution"][choice.pattern] += 1
                for d in all_directions:
                    self.stats["direction_distribution"][d] += 1

            except Exception as e:
                results.append({
                    "round": i,
                    "scenario": scenario_id,
                    "symbol": symbol,
                    "success": False,
                    "error": str(e),
                })
                self.stats["errors"].append({"round": i, "error": str(e)})

            if (i + 1) % (rounds // 10) == 0:
                elapsed = time.time() - total_start
                success = sum(1 for r in results if r.get("success"))
                rate = success / len(results) * 100
                print(f"  进度: {i+1}/{rounds} | 成功率: {rate:.1f}% | 耗时: {elapsed:.1f}s")

        total_time = time.time() - total_start
        success_count = sum(1 for r in results if r.get("success"))
        success_rate = success_count / len(results) * 100

        latencies = [r["latency_ms"] for r in results if r.get("success")]
        latencies.sort()
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        tps = rounds / total_time if total_time > 0 else 0

        print(f"\n  总轮数: {rounds}")
        print(f"  成功: {success_count} ({success_rate:.1f}%)")
        print(f"  总耗时: {total_time:.1f}s")
        print(f"  吞吐量: {tps:.2f} TPS")
        print(f"  场景覆盖: {len(scenario_coverage)}/36 ({len(scenario_coverage)/36*100:.1f}%)")
        print(f"  平均延迟: {avg_latency:.1f}ms")
        if latencies:
            print(f"  P95延迟: {latencies[int(len(latencies)*0.95)]:.1f}ms")
            print(f"  P99延迟: {latencies[int(len(latencies)*0.99)]:.1f}ms")

        return {
            "total_rounds": rounds,
            "success_count": success_count,
            "success_rate_pct": round(success_rate, 2),
            "total_time_s": round(total_time, 2),
            "tps": round(tps, 2),
            "scenario_coverage": len(scenario_coverage),
            "avg_latency_ms": round(avg_latency, 2),
            "p95_latency_ms": round(latencies[int(len(latencies)*0.95)], 2) if latencies else 0,
            "p99_latency_ms": round(latencies[int(len(latencies)*0.99)], 2) if latencies else 0,
        }

    def run_all(self) -> Dict[str, Any]:
        """运行所有压力测试"""
        full_report = {
            "test_timestamp": datetime.now().isoformat(),
            "test_suite": "multi_scenario_stress_test",
            "total_36_scenarios": len(ALL_36_SCENARIOS),
            "symbols_tested": SYMBOLS,
        }

        # 测试1: 场景分类准确性
        try:
            full_report["scenario_classification"] = self.test_scenario_classification_accuracy()
        except Exception as e:
            full_report["scenario_classification"] = {"error": str(e)}

        # 测试2: 记忆表覆盖率
        try:
            full_report["orchestration_memory"] = self.test_orchestration_memory_coverage()
        except Exception as e:
            full_report["orchestration_memory"] = {"error": str(e)}

        # 测试3: 图执行一致性
        try:
            full_report["graph_consistency"] = self.test_graph_execution_consistency()
        except Exception as e:
            full_report["graph_consistency"] = {"error": str(e)}

        # 测试4: 边缘场景
        try:
            full_report["edge_cases"] = self.test_edge_cases()
        except Exception as e:
            full_report["edge_cases"] = {"error": str(e)}

        # 测试5: 全链路压力
        try:
            full_report["full_pipeline_stress"] = self.test_full_pipeline_stress(rounds=108)
        except Exception as e:
            full_report["full_pipeline_stress"] = {"error": str(e)}

        # 综合评分
        full_report["overall_summary"] = self._compute_overall_summary(full_report)

        return full_report

    def _compute_overall_summary(self, report: Dict) -> Dict:
        """计算综合评分"""
        scores = {}

        # 场景分类准确率
        sc = report.get("scenario_classification", {})
        scores["classification_accuracy"] = sc.get("accuracy_pct", 0)

        # 记忆表覆盖率
        om = report.get("orchestration_memory", {})
        scores["memory_coverage"] = om.get("coverage_pct", 0)

        # 图执行一致性
        gc = report.get("graph_consistency", {})
        scores["graph_consistency"] = gc.get("consistency_rate_pct", 0)

        # 边缘场景通过率
        ec = report.get("edge_cases", {})
        if isinstance(ec, dict) and "error" not in ec:
            ec_success = sum(1 for r in ec.values() if isinstance(r, dict) and r.get("success"))
            scores["edge_case_pass"] = ec_success / len(ec) * 100 if ec else 0
        else:
            scores["edge_case_pass"] = 0

        # 全链路成功率
        fp = report.get("full_pipeline_stress", {})
        scores["full_pipeline_success"] = fp.get("success_rate_pct", 0)

        # 综合得分（加权平均）
        weights = {
            "classification_accuracy": 0.15,
            "memory_coverage": 0.20,
            "graph_consistency": 0.25,
            "edge_case_pass": 0.20,
            "full_pipeline_success": 0.20,
        }
        overall = sum(scores[k] * weights[k] for k in weights)

        grade = "A" if overall >= 90 else "B" if overall >= 80 else "C" if overall >= 70 else "D" if overall >= 60 else "F"

        return {
            "scores": {k: round(v, 2) for k, v in scores.items()},
            "weights": weights,
            "overall_score": round(overall, 2),
            "grade": grade,
        }


def print_summary_report(report: Dict):
    """打印综合报告"""
    print("\n" + "=" * 70)
    print("📋 多场景模拟压力测试 — 综合报告")
    print("=" * 70)

    overall = report.get("overall_summary", {})
    print(f"\n  综合评分: {overall.get('overall_score', 'N/A')} / 100  (等级: {overall.get('grade', 'N/A')})")

    print(f"\n  分项得分:")
    for name, score in overall.get("scores", {}).items():
        bar = "█" * int(score // 5) + "░" * (20 - int(score // 5))
        print(f"    {name:30s} {bar} {score:5.1f}%")

    # 场景分类
    sc = report.get("scenario_classification", {})
    print(f"\n  【场景分类】准确率: {sc.get('accuracy_pct', 'N/A')}%")
    if sc.get("misclassified"):
        print(f"    误分类: {len(sc['misclassified'])}个场景")

    # 记忆表覆盖
    om = report.get("orchestration_memory", {})
    print(f"\n  【编排记忆】覆盖率: {om.get('coverage_pct', 'N/A')}%")
    fb = om.get("fallback_distribution", {})
    for level in ["L0", "L1", "L2", "L3"]:
        if level in fb:
            print(f"    {level}: {fb[level]}个场景")

    # 图一致性
    gc = report.get("graph_consistency", {})
    print(f"\n  【图编排一致性】{gc.get('consistency_rate_pct', 'N/A')}%")
    lat = gc.get("latency", {})
    print(f"    延迟: avg={lat.get('avg_ms', 0)}ms P95={lat.get('p95_ms', 0)}ms P99={lat.get('p99_ms', 0)}ms")

    # 边缘场景
    ec = report.get("edge_cases", {})
    if isinstance(ec, dict) and "error" not in ec:
        ec_success = sum(1 for r in ec.values() if isinstance(r, dict) and r.get("success"))
        print(f"\n  【边缘场景】{ec_success}/{len(ec)} 通过")
        failed = [k for k, v in ec.items() if isinstance(v, dict) and not v.get("success")]
        if failed:
            print(f"    失败: {', '.join(failed)}")

    # 全链路压力
    fp = report.get("full_pipeline_stress", {})
    print(f"\n  【全链路压测】")
    print(f"    成功率: {fp.get('success_rate_pct', 'N/A')}%")
    print(f"    吞吐量: {fp.get('tps', 'N/A')} TPS")
    print(f"    场景覆盖: {fp.get('scenario_coverage', 'N/A')}/36")

    print("\n" + "=" * 70)


def main():
    random.seed(42)  # 可复现

    print("\n" + "=" * 70)
    print("🎯 Dream OS 多场景模拟压力测试套件")
    print("=" * 70)
    print(f"  36 种市场场景 (3趋势 × 4波动率 × 3动量)")
    print(f"  {len(SYMBOLS)} 种交易币种")
    print(f"  5 类测试（分类/记忆/一致性/边缘/全链路）")
    print("=" * 70)

    tester = MultiScenarioStressTest(rounds_per_scenario=3)
    report = tester.run_all()

    print_summary_report(report)

    # 保存报告
    report_path = Path(__file__).parent / "multi_scenario_stress_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n📄 详细报告已保存到: {report_path}")

    return report


if __name__ == "__main__":
    main()
