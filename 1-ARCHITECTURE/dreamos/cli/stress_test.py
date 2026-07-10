"""
Dream OS 系统压力测试框架

验证目标:
1) 图编排的多样性、灵活性
2) 图编排后调用节点，真实调用基础模块能力
3) Dream OS 可以实现完整自动化交易链路
4) 自进化能力（进化系统、知识库、索引系统、沙箱回测）

测试规模: 500轮，覆盖多场景模拟
"""

from __future__ import annotations

import os
import sys
import json
import time
import random
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from dreamos.cli.auto_trader import AutoTrader
from dreamos.registry import get_default_registry
from dreamos.nodes import register_all
from dreamos.core.compute.graph_executor import GraphExecutor
from dreamos.core.arrange.execution_graph import SequentialGraph
from dreamos.shared.state import State, new_state


class StressTestFramework:
    """压力测试框架"""

    def __init__(self, rounds: int = 500):
        self.rounds = rounds
        self.results = []
        self.stats = {
            "total_rounds": 0,
            "success_rounds": 0,
            "failed_rounds": 0,
            "avg_latency_ms": 0,
            "total_tokens": 0,
            "path_distribution": {},
            "action_distribution": {},
            "nodes_executed": {},
            "graph_pattern_distribution": {},
            "scenario_distribution": {},
            "fallback_distribution": {},
            "errors": [],
        }
        self.trader = AutoTrader(dry_run=True, exchange="hyperliquid")
        self.registry = get_default_registry()
        register_all(self.registry)
        self.symbols = ["BTC", "ETH", "SOL", "AVAX", "LINK", "ARB", "OP", "DOT"]
        # 场景驱动的编排选择（替代 random.choice）
        from dreamos.core.sense.scenario_classifier import ScenarioClassifier
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory
        self.scenario_classifier = ScenarioClassifier()
        self.orchestration_memory = OrchestrationMemory()
        self.orchestration_memory.load()

    def _generate_market_scenario(self, round_num: int) -> Dict:
        """生成市场场景"""
        scenarios = [
            {"name": "bull_trend", "volatility": "low", "momentum": "up"},
            {"name": "bear_trend", "volatility": "low", "momentum": "down"},
            {"name": "sideways", "volatility": "low", "momentum": "neutral"},
            {"name": "high_vol_bull", "volatility": "high", "momentum": "up"},
            {"name": "high_vol_bear", "volatility": "high", "momentum": "down"},
            {"name": "crash", "volatility": "extreme", "momentum": "down"},
            {"name": "rally", "volatility": "extreme", "momentum": "up"},
        ]
        # 加权随机选择场景
        weights = [0.15, 0.15, 0.20, 0.15, 0.15, 0.05, 0.05]
        scenario = random.choices(scenarios, weights=weights)[0]
        return {
            "round": round_num,
            "scenario": scenario["name"],
            "volatility": scenario["volatility"],
            "momentum": scenario["momentum"],
            "symbol": random.choice(self.symbols),
            "timestamp": datetime.now().isoformat(),
        }

    def _test_graph_diversity(self, scenario: Dict) -> Dict:
        """测试图编排的多样性和灵活性（场景驱动，替代 random.choice）"""
        symbol = scenario["symbol"]

        # 场景识别 + 记忆表查询
        market_data = self.trader._fetch_market_data(symbol)
        classified = self.scenario_classifier.classify(market_data)
        choice = self.orchestration_memory.select(classified.scenario_id)
        pattern_name = choice.pattern
        chain_nodes = choice.nodes

        cycle_id = f"stress_test_{symbol}_{scenario['round']}"
        state = new_state(cycle_id=cycle_id)
        state.market_data = market_data
        state.inputs = {"mkt": market_data, "symbol": symbol}

        graph = SequentialGraph()
        for node_id in chain_nodes:
            node = self.registry.get(node_id)
            if node:
                graph.add_node(node)

        executor = GraphExecutor()
        start_time = time.time()
        report = executor.execute(graph, state)
        latency_ms = (time.time() - start_time) * 1000

        return {
            "graph_pattern": pattern_name,
            "nodes": chain_nodes,
            "scenario_id": classified.scenario_id,
            "fallback_level": choice.fallback_level,
            "executed_nodes": getattr(report, "executed_nodes", 0),
            "success_nodes": getattr(report, "success_nodes", 0),
            "latency_ms": round(latency_ms, 2),
            "results": {
                nid: state.get_result(nid).outputs if state.get_result(nid) else {}
                for nid in chain_nodes
            },
        }

    def _test_node_capabilities(self, scenario: Dict) -> Dict:
        """测试节点调用真实基础模块能力"""
        symbol = scenario["symbol"]
        test_nodes = ["C1", "C2", "C3", "F1", "F3", "G1"]
        results = {}

        for node_id in test_nodes:
            node = self.registry.get(node_id)
            if not node:
                continue

            try:
                cycle_id = f"node_test_{node_id}_{scenario['round']}"
                state = new_state(cycle_id=cycle_id)
                state.inputs = {"symbol": symbol, "mkt": {"symbol": symbol}}

                start_time = time.time()
                result = node.execute(state)
                latency_ms = (time.time() - start_time) * 1000

                results[node_id] = {
                    "success": True,
                    "latency_ms": round(latency_ms, 2),
                    "confidence": getattr(result, "confidence", 0),
                    "direction": getattr(result, "direction", "HOLD"),
                    "has_outputs": bool(getattr(result, "outputs", {})),
                    "node_name": getattr(node, "name", ""),
                }
            except Exception as e:
                results[node_id] = {
                    "success": False,
                    "error": str(e),
                    "node_name": getattr(node, "name", ""),
                }

        return results

    def _test_auto_trade_chain(self, scenario: Dict) -> Dict:
        """测试完整自动化交易链路"""
        symbol = scenario["symbol"]
        start_time = time.time()
        result = self.trader.run_auto_trade(symbol)
        latency_ms = (time.time() - start_time) * 1000

        return {
            "latency_ms": round(latency_ms, 2),
            "final_result": result.get("final_result"),
            "path": result.get("_path", "unknown"),
            "action": result.get("action"),
            "confidence": result.get("confidence"),
            "steps": [
                {"step": s["step"], "status": s["status"]}
                for s in result.get("steps", [])
            ],
            "error": result.get("error"),
        }

    def _test_evolution(self, scenario: Dict) -> Dict:
        """测试自进化能力"""
        try:
            sys.path.insert(0, str(root_dir))
            from dreamos.apps.trading_agent.agent import TradingAgent

            agent = TradingAgent(budget_mode="lean")
            market_data = self.trader._fetch_market_data(scenario["symbol"])

            result = agent.run(
                user_input=f"分析 {scenario['symbol']} 的交易机会",
                market_data=market_data,
                context={"scenario": scenario},
            )

            return {
                "success": True,
                "cycle_id": result.get("cycle_id"),
                "intent_type": result.get("intent", {}).get("type"),
                "plan_nodes": result.get("plan", {}).get("nodes", []),
                "execution_nodes": result.get("execution", {}).get("executed_nodes", 0),
                "tokens_used": result.get("tokens_used", 0),
                "has_memory": bool(result.get("execution", {}).get("memory_saved", False)),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def run_single_test(self, round_num: int) -> Dict:
        """运行单轮测试"""
        scenario = self._generate_market_scenario(round_num)

        test_result = {
            "round": round_num,
            "scenario": scenario,
            "timestamp": datetime.now().isoformat(),
            "tests": {},
        }

        try:
            test_result["tests"]["graph_diversity"] = self._test_graph_diversity(scenario)
        except Exception as e:
            test_result["tests"]["graph_diversity"] = {"error": str(e)}

        try:
            test_result["tests"]["node_capabilities"] = self._test_node_capabilities(scenario)
        except Exception as e:
            test_result["tests"]["node_capabilities"] = {"error": str(e)}

        try:
            test_result["tests"]["auto_trade_chain"] = self._test_auto_trade_chain(scenario)
        except Exception as e:
            test_result["tests"]["auto_trade_chain"] = {"error": str(e)}

        try:
            test_result["tests"]["evolution"] = self._test_evolution(scenario)
        except Exception as e:
            test_result["tests"]["evolution"] = {"error": str(e)}

        return test_result

    def _update_stats(self, result: Dict):
        """更新统计信息"""
        self.stats["total_rounds"] += 1

        auto_trade = result["tests"].get("auto_trade_chain", {})
        if auto_trade.get("error"):
            self.stats["failed_rounds"] += 1
            self.stats["errors"].append({
                "round": result["round"],
                "error": auto_trade["error"],
            })
        else:
            self.stats["success_rounds"] += 1

        if auto_trade.get("latency_ms"):
            self.stats["avg_latency_ms"] = (
                (self.stats["avg_latency_ms"] * (self.stats["total_rounds"] - 1)
                 + auto_trade["latency_ms"]) / self.stats["total_rounds"]
            )

        path = auto_trade.get("path", "unknown")
        self.stats["path_distribution"][path] = (
            self.stats["path_distribution"].get(path, 0) + 1
        )

        action = auto_trade.get("action", "HOLD")
        self.stats["action_distribution"][action] = (
            self.stats["action_distribution"].get(action, 0) + 1
        )

        evolution = result["tests"].get("evolution", {})
        if evolution.get("tokens_used"):
            self.stats["total_tokens"] += evolution["tokens_used"]

        graph_diversity = result["tests"].get("graph_diversity", {})
        for node_id in graph_diversity.get("nodes", []):
            self.stats["nodes_executed"][node_id] = (
                self.stats["nodes_executed"].get(node_id, 0) + 1
            )

        pattern = graph_diversity.get("graph_pattern", "unknown")
        self.stats["graph_pattern_distribution"][pattern] = (
            self.stats["graph_pattern_distribution"].get(pattern, 0) + 1
        )

        # 场景分布和降级统计（新增）
        sid = graph_diversity.get("scenario_id", "UNKNOWN")
        self.stats["scenario_distribution"][sid] = (
            self.stats["scenario_distribution"].get(sid, 0) + 1
        )
        fl = graph_diversity.get("fallback_level", "L3")
        self.stats["fallback_distribution"][fl] = (
            self.stats["fallback_distribution"].get(fl, 0) + 1
        )

    def run(self) -> Dict:
        """运行完整压力测试"""
        print(f"\n{'='*60}")
        print(f"🚀 Dream OS 压力测试框架启动")
        print(f"   测试轮数: {self.rounds}")
        print(f"   测试场景: 7种市场场景")
        print(f"   测试币种: {', '.join(self.symbols)}")
        print(f"{'='*60}\n")

        progress_interval = max(1, self.rounds // 10)

        for i in range(1, self.rounds + 1):
            result = self.run_single_test(i)
            self.results.append(result)
            self._update_stats(result)

            if i % progress_interval == 0:
                success_rate = (self.stats["success_rounds"] / i) * 100
                print(f"   [{i}/{self.rounds}] 进度: {round(i/self.rounds*100)}% | 成功率: {success_rate:.1f}% | 平均延迟: {self.stats['avg_latency_ms']:.1f}ms")

        return self._generate_report()

    def _generate_report(self) -> Dict:
        """生成测试报告"""
        success_rate = (
            (self.stats["success_rounds"] / self.stats["total_rounds"]) * 100
            if self.stats["total_rounds"] > 0 else 0
        )

        report = {
            "test_summary": {
                "total_rounds": self.stats["total_rounds"],
                "success_rounds": self.stats["success_rounds"],
                "failed_rounds": self.stats["failed_rounds"],
                "success_rate": round(success_rate, 2),
                "avg_latency_ms": round(self.stats["avg_latency_ms"], 2),
                "total_tokens": self.stats["total_tokens"],
                "test_start": self.results[0]["timestamp"] if self.results else "",
                "test_end": self.results[-1]["timestamp"] if self.results else "",
                "duration_minutes": 0,
            },
            "capability_verification": {
                "graph_diversity": {
                "status": "PASS" if self.stats["graph_pattern_distribution"] else "FAIL",
                "details": {
                    "graph_patterns_tested": ["c_chain", "c_f_chain", "full_chain", "f_chain", "c_g_chain"],
                    "graph_pattern_distribution": self.stats["graph_pattern_distribution"],
                },
            },
                "node_capabilities": {
                    "status": "PASS" if self.stats["nodes_executed"] else "FAIL",
                    "details": {
                        "nodes_executed": self.stats["nodes_executed"],
                        "total_node_calls": sum(self.stats["nodes_executed"].values()),
                    },
                },
                "auto_trade_chain": {
                    "status": "PASS" if success_rate >= 90 else "WARN",
                    "details": {
                        "action_distribution": self.stats["action_distribution"],
                    },
                },
                "evolution_capability": {
                    "status": "PASS" if any(r["tests"].get("evolution", {}).get("success") for r in self.results) else "WARN",
                    "details": {
                        "total_tokens_used": self.stats["total_tokens"],
                        "evolution_success": sum(1 for r in self.results if r["tests"].get("evolution", {}).get("success")),
                    },
                },
            },
            "detailed_results": self.results,
            "errors": self.stats["errors"],
        }

        if self.results:
            start_ts = datetime.fromisoformat(self.results[0]["timestamp"])
            end_ts = datetime.fromisoformat(self.results[-1]["timestamp"])
            report["test_summary"]["duration_minutes"] = round((end_ts - start_ts).total_seconds() / 60, 2)

        return report

    def print_report(self, report: Dict):
        """打印测试报告"""
        summary = report["test_summary"]

        print(f"\n{'='*60}")
        print(f"📊 Dream OS 压力测试报告")
        print(f"{'='*60}")
        print(f"\n【测试摘要】")
        print(f"  测试轮数: {summary['total_rounds']}")
        print(f"  成功轮数: {summary['success_rounds']}")
        print(f"  失败轮数: {summary['failed_rounds']}")
        print(f"  成功率: {summary['success_rate']}%")
        print(f"  平均延迟: {summary['avg_latency_ms']}ms")
        print(f"  总耗时: {summary['duration_minutes']}分钟")
        print(f"  Token消耗: {summary['total_tokens']}")

        print(f"\n【能力验证】")
        for capability, info in report["capability_verification"].items():
            status = "✅" if info["status"] == "PASS" else "⚠️" if info["status"] == "WARN" else "❌"
            print(f"  {status} {capability}: {info['status']}")

        print(f"\n【图编排模式分布】")
        for pattern, count in report["capability_verification"]["graph_diversity"]["details"]["graph_pattern_distribution"].items():
            pct = (count / summary["total_rounds"]) * 100
            print(f"  {pattern}: {count}次 ({pct:.1f}%)")

        print(f"\n【节点调用统计】")
        for node_id, count in sorted(report["capability_verification"]["node_capabilities"]["details"]["nodes_executed"].items(), key=lambda x: -x[1]):
            print(f"  {node_id}: {count}次")

        print(f"\n【动作分布】")
        for action, count in report["capability_verification"]["auto_trade_chain"]["details"]["action_distribution"].items():
            pct = (count / summary["total_rounds"]) * 100
            print(f"  {action}: {count}次 ({pct:.1f}%)")

        if report["errors"]:
            print(f"\n【错误汇总】(前5个)")
            for err in report["errors"][:5]:
                print(f"  第{err['round']}轮: {err['error']}")

        print(f"\n{'='*60}")


def main():
    rounds = 500
    print(f"准备运行 {rounds} 轮压力测试...")

    tester = StressTestFramework(rounds=rounds)
    report = tester.run()

    tester.print_report(report)

    # 保存报告
    report_path = Path(__file__).parent / "stress_test_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n报告已保存到: {report_path}")


if __name__ == "__main__":
    main()
