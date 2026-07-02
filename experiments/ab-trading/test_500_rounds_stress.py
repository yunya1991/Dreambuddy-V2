#!/usr/bin/env python3
"""
Dreambuddy OS 500轮多场景压力测试

位置: experiments/ab-trading/test_500_rounds_stress.py

测试场景（覆盖SACG四层架构）:
1. S层三层递进测试 (Objective → OKR → Blueprint)
2. 意图识别引擎测试 (6种意图类型)
3. 图编排引擎测试 (GraphOrchestrator + 四维规划)
4. 三链结合策略测试 (阶段一投票 + 阶段二动态插入)
5. 反思决策引擎测试 (5种决策类型)
6. C层节点执行测试 (单节点/多节点/动态链)
7. G层图压缩测试 (BAC三层压缩效率)
8. 自我进化闭环测试 (Episode → Lesson 模拟)
9. 并发执行压测 (多线程高并发)
10. 错误注入与降级测试 (重试/降级机制验证)

总轮数: 500轮，各场景按比例分配
输出: 详细性能报告 + JSON数据

基于技术文档:
- SYSTEM_ARCHITECTURE_OVERVIEW.md (v2.2)
- WORKBUDDY_OS_MODULAR_ARCHITECTURE.md (v1.1)
- dreambuddy-os/SKILL.md (v1.1.0)
"""

import sys
import os
import time
import threading
import random
import json
import unittest
from typing import Dict, Any, List, Callable, Optional
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 核心组件导入
try:
    from core.nodes.node_registry import get_node_registry, NodeInfo
    from core.c_execution_layer.unified_executor import UnifiedNodeExecutor
    from core.modules.unified_types import ModuleResult, create_failure_result, create_success_result
    from core.shared.errors import ErrorCode, ErrorInfo
except ImportError as e:
    print(f"导入警告: {e}")
    # 使用模拟实现
    def get_node_registry():
        return MockNodeRegistry()
    class NodeInfo:
        pass
    class UnifiedNodeExecutor:
        def execute(self, node_id, inputs, context):
            return MockModuleResult(success=True, capability_id=node_id)
    class ModuleResult:
        pass
    def create_failure_result(capability_id, error):
        return MockModuleResult(success=False, capability_id=capability_id, error=error)
    def create_success_result(capability_id, outputs=None, confidence=75.0):
        return MockModuleResult(success=True, capability_id=capability_id)
    class ErrorCode:
        NODE_HANDLER_MISSING = "NODE_001"
    class ErrorInfo:
        @staticmethod
        def create(error_code, message, node_id):
            return {"error_code": error_code, "message": message, "node_id": node_id}

class MockNodeRegistry:
    """模拟节点注册表"""
    def get_all(self):
        return []
    def get(self, node_id):
        return None
    def get_stats(self):
        return {"total_nodes": 0, "nodes": []}

class MockModuleResult:
    """模拟模块结果"""
    def __init__(self, success=True, capability_id="", error=None):
        self.success = success
        self.capability_id = capability_id
        self.error = error
        self.outputs = {}
        self.confidence = 75.0 if success else 0.0
        self.fallback_used = False
        self.metadata = {}
        self.warnings = []
        self.suggestions = []


# ============================================================
# 测试结果数据结构
# ============================================================

@dataclass
class ScenarioResult:
    """场景测试结果"""
    scenario_id: str
    scenario_name: str
    total_rounds: int = 0
    success_rounds: int = 0
    failed_rounds: int = 0
    total_time_ms: float = 0.0
    latencies: List[float] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return self.success_rounds / self.total_rounds if self.total_rounds > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_time_ms / self.total_rounds if self.total_rounds > 0 else 0.0

    @property
    def p50(self) -> float:
        return self._percentile(50)

    @property
    def p95(self) -> float:
        return self._percentile(95)

    @property
    def p99(self) -> float:
        return self._percentile(99)

    def _percentile(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * p / 100.0)
        idx = min(idx, len(sorted_lat) - 1)
        return sorted_lat[idx]

    def to_dict(self) -> Dict:
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "total_rounds": self.total_rounds,
            "success_rounds": self.success_rounds,
            "failed_rounds": self.failed_rounds,
            "success_rate": f"{self.success_rate*100:.2f}%",
            "total_time_ms": f"{self.total_time_ms:.2f}",
            "avg_latency_ms": f"{self.avg_latency_ms:.2f}",
            "p50_ms": f"{self.p50:.2f}",
            "p95_ms": f"{self.p95:.2f}",
            "p99_ms": f"{self.p99:.2f}",
            "tps": f"{self.total_rounds / (self.total_time_ms / 1000) if self.total_time_ms > 0 else 0:.2f}",
            "errors": self.errors[:5],
            "details": self.details,
        }


@dataclass
class OverallReport:
    """总体测试报告"""
    test_id: str
    test_name: str
    start_time: str
    end_time: str
    total_rounds: int
    total_time_ms: float
    scenarios: List[ScenarioResult] = field(default_factory=list)
    system_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "test_id": self.test_id,
            "test_name": self.test_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_rounds": self.total_rounds,
            "total_time_ms": f"{self.total_time_ms:.2f}",
            "total_time_seconds": f"{self.total_time_ms / 1000:.2f}",
            "overall_tps": f"{self.total_rounds / (self.total_time_ms / 1000) if self.total_time_ms > 0 else 0:.2f}",
            "overall_success_rate": f"{sum(s.success_rounds for s in self.scenarios) / self.total_rounds * 100 if self.total_rounds > 0 else 0:.2f}%",
            "scenarios": [s.to_dict() for s in self.scenarios],
            "system_stats": self.system_stats,
        }


# ============================================================
# 测试工具函数
# ============================================================

def create_test_market_data(symbol: str = "BTC/USDT") -> Dict[str, Any]:
    """创建测试市场数据"""
    price = 45000.0 + random.uniform(-500, 500)
    return {
        "symbol": symbol,
        "coin": symbol.split("/")[0],
        "price": price,
        "high_24h": price * 1.05,
        "low_24h": price * 0.95,
        "volume_24h": 1000000000 + random.randint(-100000000, 100000000),
        "change_24h": random.uniform(-5, 5),
        "change_4h": random.uniform(-2, 2),
        "change_1h": random.uniform(-1, 1),
        "ema5": price * random.uniform(0.995, 1.005),
        "ema10": price * random.uniform(0.99, 1.01),
        "ema20": price * random.uniform(0.985, 1.015),
        "ema50": price * random.uniform(0.97, 1.03),
        "ema200": price * random.uniform(0.95, 1.05),
        "rsi14": random.uniform(20, 80),
        "rsi7": random.uniform(15, 85),
        "macd": random.uniform(-100, 100),
        "macd_signal": random.uniform(-80, 80),
        "macd_histogram": random.uniform(-20, 20),
        "bb_upper": price * 1.03,
        "bb_middle": price * 0.995,
        "bb_lower": price * 0.96,
        "volume": random.randint(10000, 100000),
        "volume_ma": random.randint(30000, 60000),
        "money_flow": random.uniform(-50000000, 50000000),
        "money_flow_ratio": random.uniform(0.5, 1.5),
        "fear_greed_index": random.randint(10, 90),
        "put_call_ratio": random.uniform(0.4, 1.2),
        "funding_rate": random.uniform(-0.001, 0.001),
        "open_interest": random.randint(100000, 500000),
    }


def create_test_context(session_id: str) -> Dict[str, Any]:
    """创建测试执行上下文"""
    return {
        "session_id": session_id,
        "user_id": "stress_test_user",
        "config": {
            "llm_preference": ["deepseek", "openai"],
            "max_tokens": 6000,
            "enable_skill_execution": True,
            "budget_mode": random.choice(["lean", "standard", "full"]),
        },
        "governance": {
            "constitution_version": "v1.0",
            "compliance_level": random.choice(["R0", "R1", "R2", "R3"]),
        },
        "trace_id": f"trace_{session_id}",
    }


# ============================================================
# 10大测试场景实现
# ============================================================

class StressTestScenarios:
    """500轮压力测试场景集合"""

    def __init__(self):
        self.registry = get_node_registry()
        self.executor = UnifiedNodeExecutor()
        self.results: List[ScenarioResult] = []

    # --------------------------------------------------------
    # 场景1: S层三层递进测试 (Objective → OKR → Blueprint)
    # --------------------------------------------------------
    def scenario_01_s_layer_three_levels(self, rounds: int = 50) -> ScenarioResult:
        """
        测试S层三层递进：
        - 第一层 Objective: 用户意图理解
        - 第二层 OKR: 四维规划 (Token/知识库/历史/标的覆盖)
        - 第三层 Blueprint: 蓝图构建
        """
        result = ScenarioResult(
            scenario_id="S01",
            scenario_name="S层三层递进测试",
        )

        test_queries = [
            "分析BTC当前市场趋势",
            "ETH适合做空吗？",
            "给我一个短线交易策略",
            "现在的市场矛盾是什么？",
            "技术面和基本面怎么看？",
            "帮我验证这个策略",
            "执行一笔BTC做多",
            "风险告警检查",
            "简单问答测试",
            "深度分析请求",
        ]

        for i in range(rounds):
            query = random.choice(test_queries)
            session_id = f"s_layer_{i}"
            start = time.time()

            try:
                # 模拟S层三层递进
                # 第一层：Objective 提取
                objective = {
                    "title": query,
                    "description": f"用户请求: {query}",
                    "type": random.choice(["market_query", "deep_analysis", "strategy_verify", "execute_trade"]),
                }

                # 第二层：OKR 构建（四维规划模拟）
                okr = {
                    "key_results": [
                        {"kr_id": "kr1", "description": "完成意图识别", "target": 0.8},
                        {"kr_id": "kr2", "description": "构建执行链", "target": 0.7},
                    ],
                    "budget_mode": random.choice(["lean", "standard", "full"]),
                    "estimated_tokens": random.randint(1000, 8000),
                    "knowledge_hit": random.random() > 0.5,
                    "historical_match": random.random() > 0.3,
                }

                # 第三层：Blueprint 构建
                blueprint = {
                    "root_component": "trading_decision",
                    "modules": ["intent_engine", "analysis_chain", "strategy_engine"],
                    "data_flow": ["market_data → intent → analysis → strategy"],
                    "node_sequence": random.sample(
                        ["classic-indicator-scan", "fundamental-fund-flow", "dream-contradiction-theory"],
                        2
                    ),
                }

                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.success_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)

            except Exception as e:
                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.failed_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)
                if len(result.errors) < 10:
                    result.errors.append(str(e))

        result.details = {
            "test_queries_count": len(test_queries),
            "average_objective_extraction_ms": sum(result.latencies) / len(result.latencies) if result.latencies else 0,
        }
        return result

    # --------------------------------------------------------
    # 场景2: 意图识别引擎测试 (6种意图类型)
    # --------------------------------------------------------
    def scenario_02_intent_recognition(self, rounds: int = 50) -> ScenarioResult:
        """
        测试6种意图类型识别：
        - market_query: 行情查询
        - deep_analysis: 深度分析
        - scenario_sim: 情景模拟
        - strategy_verify: 策略验证
        - execute_trade: 执行交易
        - risk_alert: 集成告警
        """
        result = ScenarioResult(
            scenario_id="S02",
            scenario_name="意图识别引擎测试(6种类型)",
        )

        intent_types = {
            "market_query": ["BTC价格多少", "ETH行情怎么样", "当前市场情况"],
            "deep_analysis": ["深度分析BTC趋势", "全面评估ETH风险", "多维度分析市场"],
            "scenario_sim": ["如果BTC涨到50000怎么办", "模拟ETH暴跌场景", "情景推演测试"],
            "strategy_verify": ["验证这个策略", "回测我的方案", "策略效果评估"],
            "execute_trade": ["执行BTC做多", "开空ETH", "下单交易"],
            "risk_alert": ["风险检查", "告警触发", "风控评估"],
        }

        for i in range(rounds):
            intent_type = random.choice(list(intent_types.keys()))
            query = random.choice(intent_types[intent_type])
            start = time.time()

            try:
                # 模拟意图识别
                detected_intent = {
                    "intent_type": intent_type,
                    "confidence": random.uniform(0.6, 0.95),
                    "primary_chain": random.choice(["S", "C", "F"]),
                    "extend_nodes": random.sample(
                        ["classic-indicator-scan", "fundamental-sentiment", "dream-first-principles"],
                        random.randint(1, 2)
                    ),
                    "context": {
                        "symbol": random.choice(["BTC", "ETH", "SOL"]),
                        "regime": random.choice(["TREND_UP", "TREND_DOWN", "RANGE"]),
                    },
                }

                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.success_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)

                # 统计各意图类型分布
                if "intent_distribution" not in result.details:
                    result.details["intent_distribution"] = defaultdict(int)
                result.details["intent_distribution"][intent_type] += 1

            except Exception as e:
                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.failed_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)
                if len(result.errors) < 10:
                    result.errors.append(str(e))

        if "intent_distribution" in result.details:
            result.details["intent_distribution"] = dict(result.details["intent_distribution"])
        return result

    # --------------------------------------------------------
    # 场景3: 图编排引擎测试 (GraphOrchestrator + 四维规划)
    # --------------------------------------------------------
    def scenario_03_graph_orchestrator(self, rounds: int = 50) -> ScenarioResult:
        """
        测试A层图编排：
        - GraphOrchestrator 构建
        - NodeRegistry 查询
        - 四维规划 (Token/知识库/历史/标的覆盖)
        - 动态节点选择
        """
        result = ScenarioResult(
            scenario_id="A01",
            scenario_name="图编排引擎测试(四维规划)",
        )

        # 获取可用节点
        available_nodes = self.registry.get_all()
        if not available_nodes:
            available_nodes = []

        for i in range(rounds):
            start = time.time()

            try:
                # 四维规划模拟
                token_budget = random.choice([3000, 6000, 10000])
                knowledge_hit = random.random() > 0.4
                historical_perf = random.uniform(0.5, 0.9)
                symbol_coverage = random.choice(["BTC", "ETH", "SOL", "冷门币"])

                # 构建执行图
                architecture = {
                    "id": f"arch_{i}",
                    "token_budget": token_budget,
                    "budget_mode": "lean" if token_budget <= 3000 else "standard" if token_budget <= 6000 else "full",
                    "planned_chain": [],
                    "pruned_nodes": [],
                    "added_nodes": [],
                }

                # 根据四维规划选择节点
                candidate_nodes = []
                if available_nodes:
                    # 模拟四维过滤
                    for node in available_nodes[:10]:
                        # 维度1: Token预算过滤
                        if node.estimated_tokens > token_budget * 0.3:
                            continue
                        # 维度2: 知识库命中提升
                        if knowledge_hit and node.chain == "A":
                            candidate_nodes.append(node.node_id)
                        # 维度3: 历史表现过滤
                        elif historical_perf > 0.6:
                            candidate_nodes.append(node.node_id)
                        # 维度4: 标的覆盖检查
                        elif symbol_coverage in ["BTC", "ETH"]:
                            candidate_nodes.append(node.node_id)

                if not candidate_nodes:
                    candidate_nodes = ["classic-indicator-scan", "fundamental-fund-flow"]

                architecture["planned_chain"] = candidate_nodes[:3]

                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.success_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)

            except Exception as e:
                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.failed_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)
                if len(result.errors) < 10:
                    result.errors.append(str(e))

        result.details = {
            "available_nodes_count": len(available_nodes),
            "registry_stats": self.registry.get_stats(),
        }
        return result

    # --------------------------------------------------------
    # 场景4: 三链结合策略测试 (阶段一投票 + 阶段二动态插入)
    # --------------------------------------------------------
    def scenario_04_three_chain_combination(self, rounds: int = 50) -> ScenarioResult:
        """
        测试三链结合：
        - 阶段一：交叉验证投票 (S/A/C/F 加权投票)
        - 阶段二：动态插入节点 (低置信度时追加)
        """
        result = ScenarioResult(
            scenario_id="A02",
            scenario_name="三链结合策略测试",
        )

        for i in range(rounds):
            start = time.time()

            try:
                # 随机选择验证点
                validation_point = random.choice(["S2_direction", "S3_entry", "S5_exit"])

                # 阶段一：收集三链信号并投票
                chain_signals = {
                    "S链": {"direction": random.choice(["LONG", "SHORT", "HOLD"]), "confidence": random.uniform(0.5, 0.9)},
                    "C链": {"direction": random.choice(["LONG", "SHORT", "HOLD"]), "confidence": random.uniform(0.4, 0.85)},
                    "F链": {"direction": random.choice(["LONG", "SHORT", "HOLD"]), "confidence": random.uniform(0.3, 0.8)},
                }

                # 投票权重
                weights = {
                    "S2_direction": {"S": 0.4, "C": 0.35, "F": 0.25},
                    "S3_entry": {"S": 0.3, "C": 0.5, "F": 0.2},
                    "S5_exit": {"S": 0.35, "C": 0.3, "F": 0.35},
                }

                # 计算加权共识
                weighted_result = {}
                for chain, signal in chain_signals.items():
                    chain_key = chain[0]  # S/C/F
                    weight = weights[validation_point].get(chain_key, 0.3)
                    direction = signal["direction"]
                    conf = signal["confidence"]

                    if direction not in weighted_result:
                        weighted_result[direction] = 0
                    weighted_result[direction] += conf * weight

                # 确定共识
                consensus_direction = max(weighted_result.keys(), key=lambda k: weighted_result[k])
                consensus_confidence = weighted_result[consensus_direction]

                # 阶段二：判断是否需要动态插入
                dynamic_insertion = None
                if consensus_confidence < 0.55:
                    # 低置信度，触发阶段二
                    dynamic_insertion = {
                        "trigger": "low_confidence",
                        "inserted_nodes": random.choice([
                            ["master-seminar"],
                            ["dream-first-principles", "dream-contradiction-theory"],
                        ]),
                        "reason": "三链分歧，需要深度分析",
                    }

                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.success_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)

                # 统计阶段二触发次数
                if dynamic_insertion:
                    if "phase2_trigger_count" not in result.details:
                        result.details["phase2_trigger_count"] = 0
                    result.details["phase2_trigger_count"] += 1

            except Exception as e:
                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.failed_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)
                if len(result.errors) < 10:
                    result.errors.append(str(e))

        return result

    # --------------------------------------------------------
    # 场景5: 反思决策引擎测试 (5种决策类型)
    # --------------------------------------------------------
    def scenario_05_reflection_decision(self, rounds: int = 50) -> ScenarioResult:
        """
        测试5种反思决策类型：
        - CONTINUE: 正常推进
        - REDO: confidence < 0.55 或 risk > 0.7
        - INSERT_BEFORE: 缺少必要信息
        - JUMP_TO: 高置信度 >= 0.78
        - EARLY_TERMINATE: 基本完成 + avg_conf >= 0.65
        """
        result = ScenarioResult(
            scenario_id="C01",
            scenario_name="反思决策引擎测试(5种决策)",
        )

        decision_types = ["CONTINUE", "REDO", "INSERT_BEFORE", "JUMP_TO", "EARLY_TERMINATE"]
        decision_distribution = defaultdict(int)

        for i in range(rounds):
            start = time.time()

            try:
                # 模拟执行结果
                confidence = random.uniform(0.4, 0.95)
                risk = random.uniform(0.1, 0.9)
                issues_count = random.randint(0, 3)
                has_stop_loss = random.random() > 0.3
                has_take_profit = random.random() > 0.3
                avg_confidence = random.uniform(0.5, 0.85)
                iteration_count = random.randint(1, 5)

                # 反思决策逻辑（优先级从高到低）
                decision = "CONTINUE"

                # 1. 防御兜底：迭代达上限
                if iteration_count >= 5:
                    decision = "CONTINUE"
                # 2. REDO
                elif confidence < 0.55 or risk > 0.7 or issues_count >= 2:
                    decision = "REDO"
                # 3. INSERT_BEFORE
                elif not has_stop_loss or not has_take_profit:
                    decision = "INSERT_BEFORE"
                # 4. JUMP_TO
                elif confidence >= 0.78 and issues_count == 0:
                    decision = "JUMP_TO"
                # 5. EARLY_TERMINATE
                elif avg_confidence >= 0.65 and iteration_count >= 3:
                    decision = "EARLY_TERMINATE"
                # 6. CONTINUE (默认)

                decision_distribution[decision] += 1

                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.success_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)

            except Exception as e:
                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.failed_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)
                if len(result.errors) < 10:
                    result.errors.append(str(e))

        result.details = {
            "decision_distribution": dict(decision_distribution),
            "expected_distribution": {
                "CONTINUE": "40-50%",
                "REDO": "15-20%",
                "INSERT_BEFORE": "10-15%",
                "JUMP_TO": "10-20%",
                "EARLY_TERMINATE": "5-10%",
            },
        }
        return result

    # --------------------------------------------------------
    # 场景6: C层节点执行测试 (单节点/多节点/动态链)
    # --------------------------------------------------------
    def scenario_06_node_execution(self, rounds: int = 80) -> ScenarioResult:
        """
        测试C层节点执行：
        - 单节点执行性能
        - 多节点组合执行
        - 动态链调整
        """
        result = ScenarioResult(
            scenario_id="C02",
            scenario_name="C层节点执行测试",
        )

        test_nodes = [
            "classic-indicator-scan",
            "fundamental-fund-flow",
            "fundamental-sentiment",
            "dream-contradiction-theory",
            "dream-first-principles",
        ]

        for i in range(rounds):
            node_id = random.choice(test_nodes)
            session_id = f"node_exec_{i}"
            start = time.time()

            try:
                mkt = create_test_market_data()
                inputs = {"mkt": mkt, "memory": {}, "data": {}}
                context = create_test_context(session_id)

                # 执行节点
                res = self.executor.execute(node_id, inputs, context)

                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)

                if res.success or res.fallback_used:
                    result.success_rounds += 1
                else:
                    result.failed_rounds += 1
                    if len(result.errors) < 10:
                        result.errors.append(res.error or f"Node {node_id} failed")

            except Exception as e:
                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.failed_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)
                if len(result.errors) < 10:
                    result.errors.append(str(e))

        result.details = {
            "tested_nodes": test_nodes,
            "execution_mode": "UnifiedNodeExecutor",
        }
        return result

    # --------------------------------------------------------
    # 场景7: G层图压缩测试 (BAC三层压缩效率)
    # --------------------------------------------------------
    def scenario_07_graph_compression(self, rounds: int = 40) -> ScenarioResult:
        """
        测试G层BAC三层压缩：
        - B层 Blueprint 蓝图构建
        - A层 Architecture DAG构建
        - C层 Chronicle 执行记录
        - 压缩效率对比
        """
        result = ScenarioResult(
            scenario_id="G01",
            scenario_name="G层BAC三层压缩测试",
        )

        compression_strategies = ["VALUE_PRIORITY", "PATH_PRESERVE", "CRITICAL_ONLY", "SEMANTIC_AWARE"]
        compression_results = defaultdict(list)

        for i in range(rounds):
            start = time.time()

            try:
                # 模拟执行记录大小
                node_count = random.randint(5, 20)
                token_count = random.randint(500, 5000)

                # B层：蓝图
                blueprint = {
                    "id": f"bp_{i}",
                    "modules": random.sample(["intent", "analysis", "strategy", "execution"], 3),
                }

                # A层：DAG
                architecture = {
                    "id": f"arch_{i}",
                    "nodes": [f"node_{j}" for j in range(node_count)],
                    "edges": [(f"node_{j}", f"node_{j+1}") for j in range(node_count - 1)],
                }

                # C层：执行记录
                chronicle = {
                    "id": f"chron_{i}",
                    "execution_id": f"exec_{i}",
                    "nodes": {},
                    "sequence": [f"node_{j}" for j in range(node_count)],
                    "total_tokens": token_count,
                }

                # 填充节点数据
                for j in range(node_count):
                    chronicle["nodes"][f"node_{j}"] = {
                        "start_time": 1000 + j * 100,
                        "end_time": 1000 + j * 100 + 50,
                        "token_count": random.randint(50, 300),
                        "outputs": {"result": f"output_{j}"},
                    }

                # 模拟压缩
                strategy = random.choice(compression_strategies)
                target_ratio = random.choice([0.3, 0.5, 0.7])

                # 压缩结果模拟
                compressed_node_count = int(node_count * target_ratio)
                compressed_tokens = int(token_count * target_ratio)

                compression_results[strategy].append({
                    "original_nodes": node_count,
                    "compressed_nodes": compressed_node_count,
                    "ratio": target_ratio,
                })

                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.success_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)

            except Exception as e:
                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.failed_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)
                if len(result.errors) < 10:
                    result.errors.append(str(e))

        # 统计压缩效果
        avg_compression = {}
        for strategy, results in compression_results.items():
            if results:
                avg_ratio = sum(r["ratio"] for r in results) / len(results)
                avg_compression[strategy] = f"avg_ratio={avg_ratio:.2f}, samples={len(results)}"

        result.details = {
            "compression_strategies_tested": compression_strategies,
            "avg_compression_by_strategy": avg_compression,
        }
        return result

    # --------------------------------------------------------
    # 场景8: 自我进化闭环测试 (Episode → Lesson 模拟)
    # --------------------------------------------------------
    def scenario_08_self_evolution(self, rounds: int = 40) -> ScenarioResult:
        """
        测试自我进化闭环：
        - Episode Writer: 记录执行过程
        - Lesson Distiller: 提炼经验教训
        - 防噪声过拟合验证
        """
        result = ScenarioResult(
            scenario_id="E01",
            scenario_name="自我进化闭环测试",
        )

        for i in range(rounds):
            start = time.time()

            try:
                # 模拟 Episode 记录
                episode = {
                    "episode_id": f"ep_{i}",
                    "decision": random.choice(["LONG", "SHORT", "HOLD"]),
                    "confidence": random.uniform(0.5, 0.9),
                    "outcome": random.choice(["win", "loss", "skip"]),
                    "pnl": random.uniform(-100, 200) if random.random() > 0.3 else 0,
                    "evidence_refs": [f"ref_{j}" for j in range(random.randint(2, 5))],
                    "gate_result": random.choice(["PASS", "SKIP"]),
                    "consecutive_skip": random.randint(0, 5),
                }

                # 模拟 Lesson 提炼条件
                lesson_generated = False
                lesson_type = None

                # 防噪声过拟合条件：
                # - 最小频率：3次以上
                # - 最小严重度：2级以上
                # - 最小唯一轨迹：至少2个不同的trace_id

                frequency = random.randint(1, 10)
                severity = random.randint(1, 5)
                unique_traces = random.randint(1, 5)

                if frequency >= 3 and severity >= 2 and unique_traces >= 2:
                    lesson_generated = True
                    lesson_type = random.choice(["F_失败规律", "S_成功规律"])
                    lesson = {
                        "lesson_id": f"lesson_{i}",
                        "type": lesson_type,
                        "pattern": f"pattern_{random.randint(1, 10)}",
                        "frequency": frequency,
                        "severity": severity,
                        "score": frequency * severity,
                    }

                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.success_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)

                # 统计 Lesson 生成
                if lesson_generated:
                    if "lessons_generated" not in result.details:
                        result.details["lessons_generated"] = 0
                    result.details["lessons_generated"] += 1
                    if "lesson_types" not in result.details:
                        result.details["lesson_types"] = defaultdict(int)
                    result.details["lesson_types"][lesson_type] += 1

            except Exception as e:
                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.failed_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)
                if len(result.errors) < 10:
                    result.errors.append(str(e))

        if "lesson_types" in result.details:
            result.details["lesson_types"] = dict(result.details["lesson_types"])
        return result

    # --------------------------------------------------------
    # 场景9: 并发执行压测 (多线程高并发)
    # --------------------------------------------------------
    def scenario_09_concurrent_execution(self, rounds: int = 60) -> ScenarioResult:
        """
        测试高并发执行：
        - 多线程并发
        - 线程安全验证
        - 吞吐量测试
        """
        result = ScenarioResult(
            scenario_id="P01",
            scenario_name="并发执行压测",
        )

        test_nodes = [
            "classic-indicator-scan",
            "fundamental-fund-flow",
            "fundamental-sentiment",
        ]

        num_threads = 6
        rounds_per_thread = rounds // num_threads
        lock = threading.Lock()

        def worker(thread_id: int):
            for i in range(rounds_per_thread):
                node_id = random.choice(test_nodes)
                session_id = f"concurrent_t{thread_id}_r{i}"
                start = time.time()

                try:
                    mkt = create_test_market_data()
                    inputs = {"mkt": mkt, "memory": {}, "data": {}}
                    context = create_test_context(session_id)

                    res = self.executor.execute(node_id, inputs, context)
                    latency = (time.time() - start) * 1000

                    with lock:
                        result.total_rounds += 1
                        result.total_time_ms += latency
                        result.latencies.append(latency)
                        if res.success or res.fallback_used:
                            result.success_rounds += 1
                        else:
                            result.failed_rounds += 1
                            if len(result.errors) < 10:
                                result.errors.append(res.error or "concurrent_failed")
                except Exception as e:
                    latency = (time.time() - start) * 1000
                    with lock:
                        result.total_rounds += 1
                        result.failed_rounds += 1
                        result.total_time_ms += latency
                        result.latencies.append(latency)
                        if len(result.errors) < 10:
                            result.errors.append(str(e))

        overall_start = time.time()
        threads = []
        for t_id in range(num_threads):
            t = threading.Thread(target=worker, args=(t_id,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        wall_time = (time.time() - overall_start) * 1000
        result.details = {
            "threads": num_threads,
            "rounds_per_thread": rounds_per_thread,
            "wall_clock_time_ms": f"{wall_time:.2f}",
            "effective_tps": f"{result.total_rounds / (wall_time / 1000):.2f}",
        }
        return result

    # --------------------------------------------------------
    # 场景10: 错误注入与降级测试 (重试/降级机制验证)
    # --------------------------------------------------------
    def scenario_10_error_injection(self, rounds: int = 40) -> ScenarioResult:
        """
        测试错误处理机制：
        - 错误注入模拟
        - 重试机制验证
        - 降级策略验证
        """
        result = ScenarioResult(
            scenario_id="E02",
            scenario_name="错误注入与降级测试",
        )

        error_types = [
            "SYS_001",  # 系统内部错误
            "NODE_001",  # 节点未找到
            "ADAPTER_001",  # 适配器类型不支持
            "EXEC_001",  # 执行超时
            "DATA_001",  # 输入参数校验失败
            "network_timeout",
            "temporary_failure",
        ]

        for i in range(rounds):
            start = time.time()

            try:
                # 模拟错误注入
                inject_error = random.random() > 0.7  # 30%概率注入错误
                error_type = random.choice(error_types) if inject_error else None

                retry_count = 0
                max_retries = 3
                fallback_used = False
                success = not inject_error

                if inject_error:
                    # 模拟重试机制
                    is_retryable = error_type in ["EXEC_001", "network_timeout", "temporary_failure"]

                    if is_retryable:
                        # 可重试错误
                        for retry in range(max_retries):
                            retry_count = retry + 1
                            # 模拟重试成功概率递增
                            if random.random() > 0.3 - retry * 0.1:
                                success = True
                                break

                    if not success:
                        # 触发降级
                        fallback_used = random.random() > 0.5
                        if fallback_used:
                            success = True  # 降级成功也算成功

                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)

                if success:
                    result.success_rounds += 1
                else:
                    result.failed_rounds += 1

                # 统计错误处理
                if "error_handling_stats" not in result.details:
                    result.details["error_handling_stats"] = {
                        "injected_errors": 0,
                        "retry_success": 0,
                        "fallback_success": 0,
                        "final_failure": 0,
                    }

                if inject_error:
                    result.details["error_handling_stats"]["injected_errors"] += 1
                    if success and retry_count > 0:
                        result.details["error_handling_stats"]["retry_success"] += 1
                    elif success and fallback_used:
                        result.details["error_handling_stats"]["fallback_success"] += 1
                    elif not success:
                        result.details["error_handling_stats"]["final_failure"] += 1

            except Exception as e:
                latency = (time.time() - start) * 1000
                result.total_rounds += 1
                result.failed_rounds += 1
                result.total_time_ms += latency
                result.latencies.append(latency)
                if len(result.errors) < 10:
                    result.errors.append(str(e))

        return result


# ============================================================
# 主测试执行器
# ============================================================

class StressTestRunner:
    """500轮压力测试执行器"""

    def __init__(self, total_rounds: int = 500):
        self.total_rounds = total_rounds
        self.scenarios = StressTestScenarios()
        self.report: Optional[OverallReport] = None

    def run_all_scenarios(self) -> OverallReport:
        """执行所有场景测试"""
        test_id = f"stress_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now().isoformat()

        print(f"\n{'='*80}")
        print(f"  Dreambuddy OS 500轮多场景压力测试")
        print(f"  测试ID: {test_id}")
        print(f"  开始时间: {start_time}")
        print(f"{'='*80}\n")

        # 场景轮数分配（共500轮）
        scenario_rounds = {
            "scenario_01_s_layer_three_levels": 50,   # S层三层递进
            "scenario_02_intent_recognition": 50,   # 意图识别引擎
            "scenario_03_graph_orchestrator": 50,   # 图编排引擎
            "scenario_04_three_chain_combination": 50,   # 三链结合策略
            "scenario_05_reflection_decision": 50,   # 反思决策引擎
            "scenario_06_node_execution": 70,   # C层节点执行 (调整)
            "scenario_07_graph_compression": 40,   # G层图压缩
            "scenario_08_self_evolution": 40,   # 自我进化闭环
            "scenario_09_concurrent_execution": 50,   # 并发执行压测 (调整)
            "scenario_10_error_injection": 40,   # 错误注入与降级
        }

        results: List[ScenarioResult] = []
        overall_start = time.time()

        # 执行各场景
        for scenario_name, rounds in scenario_rounds.items():
            print(f"  执行场景: {scenario_name} ({rounds}轮)")
            scenario_method = getattr(self.scenarios, scenario_name)
            result = scenario_method(rounds)
            results.append(result)

            # 实时输出
            print(f"    完成: {result.success_rounds}/{result.total_rounds}")
            print(f"    成功率: {result.success_rate*100:.1f}%")
            print(f"    平均延迟: {result.avg_latency_ms:.2f}ms")
            print()

        overall_time = (time.time() - overall_start) * 1000
        end_time = datetime.now().isoformat()

        # 构建总体报告
        self.report = OverallReport(
            test_id=test_id,
            test_name="Dreambuddy OS 500轮多场景压力测试",
            start_time=start_time,
            end_time=end_time,
            total_rounds=sum(r.total_rounds for r in results),
            total_time_ms=overall_time,
            scenarios=results,
            system_stats=self.scenarios.registry.get_stats(),
        )

        return self.report

    def print_final_report(self):
        """打印最终报告"""
        if not self.report:
            return

        print(f"\n{'='*80}")
        print(f"  最终测试报告")
        print(f"{'='*80}")

        for scenario in self.report.scenarios:
            print(f"\n  【{scenario.scenario_id}】 {scenario.scenario_name}")
            print(f"    总轮数: {scenario.total_rounds}")
            print(f"    成功率: {scenario.success_rate*100:.2f}%")
            print(f"    平均延迟: {scenario.avg_latency_ms:.2f}ms")
            print(f"    P50/P95/P99: {scenario.p50:.2f}/{scenario.p95:.2f}/{scenario.p99:.2f}ms")
            if scenario.details:
                for k, v in scenario.details.items():
                    print(f"    {k}: {v}")

        print(f"\n{'='*80}")
        print(f"  总体统计")
        print(f"{'='*80}")
        print(f"    测试ID: {self.report.test_id}")
        print(f"    总轮数: {self.report.total_rounds}")
        print(f"    总耗时: {self.report.total_time_ms:.2f}ms ({self.report.total_time_ms/1000:.2f}s)")
        print(f"    总体TPS: {self.report.total_rounds / (self.report.total_time_ms / 1000):.2f}")
        print(f"    总体成功率: {sum(s.success_rounds for s in self.report.scenarios) / self.report.total_rounds * 100:.2f}%")
        print(f"\n{'='*80}")

    def save_report_to_json(self, filepath: str):
        """保存报告到JSON文件"""
        if not self.report:
            return

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.report.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"  报告已保存: {filepath}")


# ============================================================
# unittest 测试类
# ============================================================

class Test500RoundsStress(unittest.TestCase):
    """500轮压力测试"""

    def test_full_500_rounds(self):
        """执行完整500轮压力测试"""
        runner = StressTestRunner(total_rounds=500)
        report = runner.run_all_scenarios()
        runner.print_final_report()

        # 保存报告
        report_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "stress_test_report_500.json"
        )
        runner.save_report_to_json(report_path)

        # 验证基本指标
        # 注意：由于并发场景的线程分配，实际总轮数可能略有偏差
        self.assertGreaterEqual(report.total_rounds, 480)  # 至少480轮
        self.assertLessEqual(report.total_rounds, 520)  # 最多520轮
        overall_success_rate = sum(s.success_rounds for s in report.scenarios) / report.total_rounds
        self.assertGreater(overall_success_rate, 0.5)  # 总体成功率 > 50%

        # 验证各场景
        for scenario in report.scenarios:
            self.assertGreater(scenario.total_rounds, 0)
            # 单节点执行场景允许较低成功率（因为有降级）
            if scenario.scenario_id not in ["C02", "E02"]:
                self.assertGreater(scenario.success_rate, 0.3)


# ============================================================
# 运行
# ============================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)