"""
Dreambuddy OS 多场景测试套件
=============================

覆盖维度:
    1. State 层: 序列化/快照/聚合/边界
    2. Registry 层: 注册/查询/线程安全
    3. S 层 IntentEngine: 规则识别/LLM降级/预算管理/澄清
    4. A 层 GraphPlanner: 链路选择/节点筛选/预算分配
    5. C 层 GraphExecutor: 执行/反射/重试/提前终止
    6. Aggregator: 方向投票/分歧检测/置信度计算
    7. G 层 GraphStore: 检查点/压缩/历史
    8. Evolution: 教训蒸馏/差距分析
    9. Budget: 全局预算/降级链
    10. 端到端: S->A->C->G 全链路
    11. 边界与 Bug: 空输入/循环/溢出/类型错误
"""

import sys
import os
import threading
import time
import copy
import traceback
from typing import List, Dict, Any, Optional

# 确保可以 import dreamos
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dreamos.shared.state import State, NodeResult, NodeStatus, new_state
from dreamos.shared.interfaces import Node, Edge
from dreamos.shared.errors import ErrorCode, OSError
from dreamos.shared.utils import Timer, safe_get, safe_json, chunk, dedupe, retry
from dreamos.shared.llm_client import LLMClient, LLMMessage, LLMResponse, NoOpLLMClient

from dreamos.registry.node_registry import NodeRegistry, get_default_registry, set_default_registry

from dreamos.core.sense.intent_engine import IntentEngine
from dreamos.core.sense.types import (
    IntentType, IntentInput, IntentResult, RecognizerResult,
    get_intent_definition, register_intent_type,
)
from dreamos.core.sense.token_budget import TokenBudgetManager, BudgetLevel
from dreamos.core.sense.recognizers.rule_based import RuleBasedRecognizer
from dreamos.core.sense.recognizers.llm_based import LLMBasedRecognizer
from dreamos.core.sense.recognizers.base import BaseRecognizer

from dreamos.core.arrange.graph_planner import GraphPlanner
from dreamos.core.arrange.types import (
    ExecutionPlan, NodeMeta, ChainSpec, BudgetAllocation,
    STANDARD_CHAINS, INTENT_CHAIN_MAP,
)
from dreamos.core.arrange.node_selector import NodeSelector
from dreamos.core.arrange.budget_allocator import BudgetAllocator
from dreamos.core.arrange.execution_graph import SequentialGraph, ConditionalGraph

from dreamos.core.compute.graph_executor import GraphExecutor
from dreamos.core.compute.node_runner import NodeRunner
from dreamos.core.compute.reflector import Reflector
from dreamos.core.compute.aggregator import Aggregator
from dreamos.core.compute.types import (
    ReflectAction, ReflectDecision, ExecutionReport, NodeExecutionRecord,
)

from dreamos.core.graph_store.store import GraphStore
from dreamos.core.graph_store.types import Checkpoint, CompressedState, HistoryEntry

from dreamos.evolution.engine import EvolutionEngine
from dreamos.evolution.types import EvolutionReport, Lesson, GapAnalysis

from dreamos.budget.global_budget import GlobalBudgetManager, BudgetLevel as GlobalBudgetLevel


# ============================================================
# 测试工具
# ============================================================

class TestResult:
    """单个测试结果"""
    def __init__(self, name: str, category: str):
        self.name = name
        self.category = category
        self.passed = False
        self.error = ""
        self.duration_ms = 0.0
        self.bug_found = False
        self.bug_description = ""

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        bug = " [BUG]" if self.bug_found else ""
        return f"[{status}]{bug} {self.category}/{self.name}"


class MockNode(Node):
    """模拟节点 - 用于测试"""
    def __init__(self, node_id: str, confidence: float = 0.7,
                 direction: str = "LONG", chain: str = "A",
                 fail: bool = False, delay: float = 0,
                 tags: List[str] = None, estimated_tokens: int = 100):
        self.node_id = node_id
        self.name = node_id
        self.description = f"Mock node {node_id}"
        self.chain = chain
        self.tags = tags or []
        self.estimated_tokens = estimated_tokens
        self.estimated_latency_ms = 10
        self._confidence = confidence
        self._direction = direction
        self._fail = fail
        self._delay = delay
        self._call_count = 0

    def execute(self, state: State) -> NodeResult:
        self._call_count += 1
        if self._delay:
            time.sleep(self._delay)
        if self._fail:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.FAILED,
                error="模拟失败",
                error_code=ErrorCode.EXEC_002,
            )
        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS,
            confidence=self._confidence,
            direction=self._direction,
            outputs={"call_count": self._call_count},
        )


class FlakyNode(Node):
    """不稳定节点 - 前N次失败，之后成功"""
    def __init__(self, node_id: str, fail_times: int = 2, confidence: float = 0.6):
        self.node_id = node_id
        self.name = node_id
        self.description = f"Flaky node {node_id}"
        self.chain = "A"
        self.tags = []
        self.estimated_tokens = 50
        self.estimated_latency_ms = 5
        self._fail_times = fail_times
        self._call_count = 0
        self._confidence = confidence

    def execute(self, state: State) -> NodeResult:
        self._call_count += 1
        if self._call_count <= self._fail_times:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.FAILED,
                error=f"第{self._call_count}次失败",
                error_code=ErrorCode.EXEC_002,
            )
        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS,
            confidence=self._confidence,
            direction="LONG",
        )


class MockLLMClient(LLMClient):
    """模拟 LLM 客户端"""
    def __init__(self, response_content: str = "", tokens: int = 100):
        self._response = response_content or '{"intent_type": "TREND_FOLLOWING", "confidence": 0.8, "rationale": "LLM识别", "recommended_chain": "A"}'
        self._tokens = tokens
        self.call_count = 0

    def chat(self, messages, model=None, temperature=0.7, max_tokens=None, tools=None):
        self.call_count += 1
        return LLMResponse(
            content=self._response,
            tokens_input=self._tokens,
            tokens_output=20,
            latency_ms=0.5,
        )

    async def achat(self, messages, model=None, temperature=0.7, max_tokens=None, tools=None):
        return self.chat(messages, model, temperature, max_tokens, tools)

    def count_tokens(self, messages):
        return self._tokens


# ============================================================
# 测试收集器
# ============================================================

_all_tests: List[TestResult] = []


def run_test(name: str, category: str, fn, expect_bug: bool = False):
    """运行单个测试"""
    result = TestResult(name, category)
    timer = Timer(name)
    try:
        with timer:
            fn()
        result.passed = True
    except AssertionError as e:
        result.passed = False
        result.error = str(e)
        if expect_bug:
            result.bug_found = True
            result.bug_description = str(e)
    except Exception as e:
        result.passed = False
        result.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}"
        if expect_bug:
            result.bug_found = True
            result.bug_description = str(e)
    result.duration_ms = timer.elapsed_ms
    _all_tests.append(result)
    return result


def assert_eq(a, b, msg=""):
    assert a == b, f"{msg}: expected {b}, got {a}"


def assert_true(v, msg=""):
    assert v, f"{msg}: expected True, got {v}"


def assert_false(v, msg=""):
    assert not v, f"{msg}: expected False, got {v}"


def assert_in(item, collection, msg=""):
    assert item in collection, f"{msg}: {item} not in {collection}"


def assert_gt(a, b, msg=""):
    assert a > b, f"{msg}: expected {a} > {b}"


def assert_gte(a, b, msg=""):
    assert a >= b, f"{msg}: expected {a} >= {b}"


def assert_lt(a, b, msg=""):
    assert a < b, f"{msg}: expected {a} < {b}"


def assert_none(v, msg=""):
    assert v is None, f"{msg}: expected None, got {v}"


def assert_not_none(v, msg=""):
    assert v is not None, f"{msg}: expected not None"


# ============================================================
# 1. State 层测试
# ============================================================

def test_state_creation():
    """测试 State 创建"""
    s = new_state(cycle_id="test_001")
    assert_eq(s.cycle_id, "test_001")
    assert_true(s.started_at is not None)
    assert_eq(len(s.results), 0)
    assert_eq(len(s.trace), 0)


def test_state_update_and_get():
    """测试 State 更新和查询"""
    s = new_state(cycle_id="test_002")
    r = NodeResult(node_id="A1", confidence=0.7, direction="LONG")
    s.update("A1", r)
    assert_true(s.has_node("A1"))
    assert_eq(s.get_result("A1").confidence, 0.7)
    assert_eq(s.get_confidence("A1"), 0.7)
    assert_eq(s.get_direction("A1"), "LONG")
    assert_eq(len(s.trace), 1)


def test_state_aggregate_confidence():
    """测试置信度聚合"""
    s = new_state()
    s.update("A1", NodeResult(node_id="A1", confidence=0.6, direction="LONG"))
    s.update("A2", NodeResult(node_id="A2", confidence=0.8, direction="LONG"))
    avg = s.aggregate_confidence()
    assert_eq(round(avg, 2), 0.7)


def test_state_serialization_roundtrip():
    """测试 State 序列化往返"""
    s = new_state(cycle_id="test_003", intent={"intent_type": "TREND_FOLLOWING"})
    s.update("A1", NodeResult(node_id="A1", confidence=0.7, direction="LONG"))
    d = s.to_dict()
    s2 = State.from_dict(d)
    assert_eq(s2.cycle_id, "test_003")
    assert_eq(s2.get_confidence("A1"), 0.7)
    assert_eq(s2.get_direction("A1"), "LONG")


def test_state_snapshot_independence():
    """测试快照独立性"""
    s = new_state()
    s.update("A1", NodeResult(node_id="A1", confidence=0.7))
    snap = s.snapshot()
    snap.update("A1", NodeResult(node_id="A1", confidence=0.1))
    # 原始 State 不应被修改
    assert_eq(s.get_confidence("A1"), 0.7, "快照修改不应影响原始State")


def test_state_is_all_success_with_missing_nodes():
    """BUG #1: is_all_success 跳过未执行节点"""
    s = new_state()
    s.update("A1", NodeResult(node_id="A1", confidence=0.7))
    # A2 未执行, 但 is_all_success 返回 True
    result = s.is_all_success(["A1", "A2"])
    # 这里期望 False (因为 A2 未执行), 但实际返回 True
    # 这是 BUG: 未执行节点被跳过了
    if result:
        raise AssertionError(
            "BUG#1: is_all_success(['A1','A2']) 返回 True, "
            "但 A2 未执行 - 未执行节点被静默跳过"
        )


def test_state_empty_aggregate():
    """测试空 State 聚合"""
    s = new_state()
    assert_eq(s.aggregate_confidence(), 0.0)
    assert_eq(s.is_all_success(), True)  # 空 all() 返回 True


# ============================================================
# 2. Registry 层测试
# ============================================================

def test_registry_basic():
    """测试注册表基本操作"""
    reg = NodeRegistry()
    node = MockNode("A1")
    reg.register(node)
    assert_true(reg.exists("A1"))
    assert_eq(reg.get("A1"), node)
    assert_eq(len(reg), 1)


def test_registry_duplicate():
    """测试重复注册"""
    reg = NodeRegistry()
    reg.register(MockNode("A1"))
    try:
        reg.register(MockNode("A1"))
        raise AssertionError("BUG: 重复注册未抛出异常")
    except OSError as e:
        assert_eq(e.code, ErrorCode.NODE_002)


def test_registry_unregister():
    """测试注销"""
    reg = NodeRegistry()
    reg.register(MockNode("A1"))
    assert_true(reg.unregister("A1"))
    assert_false(reg.exists("A1"))
    assert_false(reg.unregister("A1"))  # 已注销返回 False


def test_registry_empty_id():
    """测试空 node_id 注册"""
    reg = NodeRegistry()
    node = MockNode("")
    try:
        reg.register(node)
        raise AssertionError("BUG: 空 node_id 注册未抛出异常")
    except OSError as e:
        assert_eq(e.code, ErrorCode.NODE_003)


def test_registry_list_by_chain():
    """测试按链路过滤"""
    reg = NodeRegistry()
    reg.register(MockNode("A1", chain="A"))
    reg.register(MockNode("A2", chain="A"))
    reg.register(MockNode("C1", chain="C"))
    a_nodes = reg.list_nodes(chain="A")
    assert_eq(len(a_nodes), 2)
    c_nodes = reg.list_nodes(chain="C")
    assert_eq(len(c_nodes), 1)


def test_registry_list_by_tag():
    """测试按标签过滤"""
    reg = NodeRegistry()
    reg.register(MockNode("A1", tags=["trend", "required"]))
    reg.register(MockNode("A2", tags=["momentum"]))
    tagged = reg.list_nodes(tag="trend")
    assert_eq(len(tagged), 1)
    assert_eq(tagged[0].node_id, "A1")


def test_registry_thread_safety():
    """测试线程安全"""
    reg = NodeRegistry()
    errors = []

    def register_batch(prefix: str, count: int):
        try:
            for i in range(count):
                reg.register(MockNode(f"{prefix}_{i}"))
        except OSError:
            errors.append("duplicate")

    threads = []
    for t in range(4):
        threads.append(threading.Thread(
            target=register_batch, args=(f"T{t}", 50)
        ))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 应该有 200 个节点（无冲突）
    assert_eq(len(reg), 200, "线程安全注册应成功200个")


def test_registry_register_many():
    """测试批量注册"""
    reg = NodeRegistry()
    nodes = [MockNode(f"A{i}") for i in range(10)]
    count = reg.register_many(nodes)
    assert_eq(count, 10)
    # 重复注册
    count = reg.register_many(nodes)
    assert_eq(count, 0)


# ============================================================
# 3. S 层 IntentEngine 测试
# ============================================================

def test_intent_engine_trend_following():
    """测试趋势跟随意图识别"""
    engine = IntentEngine(use_llm_based=False, use_dynamic=False)
    market = {
        "price": 50000,
        "change_24h": 6.0,
        "rsi14": 55,
        "ema20": 49000,
        "ema50": 47000,
        "ema200": 45000,
        "adx": 35,
        "vol_ratio": 1.2,
    }
    result = engine.recognize(market=market, symbol="BTC-USDT")
    assert_eq(result.intent_type, "TREND_FOLLOWING")
    assert_gt(result.confidence, 0.3)


def test_intent_engine_mean_reversion():
    """测试均值回归意图识别"""
    engine = IntentEngine(use_llm_based=False, use_dynamic=False)
    market = {
        "price": 50000,
        "change_24h": -0.5,
        "rsi14": 80,
        "ema20": 48000,
        "ema50": 47000,
        "ema200": 46000,
        "vol_ratio": 0.5,
    }
    result = engine.recognize(market=market)
    # RSI=80 应该触发均值回归
    assert_eq(result.intent_type, "MEAN_REVERSION")


def test_intent_engine_breakout():
    """测试突破意图识别"""
    engine = IntentEngine(use_llm_based=False, use_dynamic=False)
    market = {
        "price": 55000,
        "change_24h": 8.0,
        "change_4h": 3.5,
        "rsi14": 60,
        "vol_ratio": 2.5,
        "high_24h": 55200,
        "low_24h": 50000,
    }
    result = engine.recognize(market=market)
    assert_eq(result.intent_type, "BREAKOUT")


def test_intent_engine_no_input():
    """测试无输入"""
    engine = IntentEngine(use_llm_based=False, use_dynamic=False)
    result = engine.recognize()
    assert_eq(result.intent_type, "UNCERTAIN")
    assert_eq(result.confidence, 0.0)


def test_intent_engine_nlp_keywords():
    """测试 NLP 关键词匹配"""
    engine = IntentEngine(use_llm_based=False, use_dynamic=False)
    result = engine.recognize(user_message="BTC趋势很强，均线多头排列，顺势做多")
    assert_eq(result.intent_type, "TREND_FOLLOWING")


def test_intent_engine_clarify_needed():
    """测试低置信度澄清"""
    engine = IntentEngine(
        use_llm_based=False,
        use_dynamic=False,
        clarify_threshold=0.5,
    )
    # 给一个非常模糊的输入
    result = engine.recognize(market={"price": 50000})
    if result.confidence < 0.5:
        assert_true(result.clarify_needed, "低置信度应触发澄清")


def test_intent_engine_llm_fallback():
    """测试 LLM 降级调用"""
    mock_llm = MockLLMClient()
    engine = IntentEngine(
        llm=mock_llm,
        use_llm_based=True,
        use_dynamic=False,
        llm_trigger_threshold=0.9,  # 设高阈值强制触发 LLM
    )
    market = {
        "price": 50000,
        "change_24h": 1.0,
        "rsi14": 50,
    }
    result = engine.recognize(market=market, user_message="分析BTC")
    # 规则识别置信度低 → 触发 LLM
    assert_gt(mock_llm.call_count, 0, "应触发LLM调用")


def test_intent_engine_budget_exhausted():
    """测试预算耗尽时降级"""
    engine = IntentEngine(
        budget_mode="lean",
        use_llm_based=True,
        use_dynamic=False,
        llm_trigger_threshold=0.0,  # 总是触发 LLM
    )
    # 先消耗大量预算
    for _ in range(20):
        engine.budget.consume(200, layer="sense")
    # 再识别 - LLM 不应被调用
    mock_llm = MockLLMClient()
    engine._recognizers = [r for r in engine._recognizers if r.name != "llm_based"]
    engine._recognizers.append(LLMBasedRecognizer(llm=mock_llm))
    result = engine.recognize(market={"price": 50000})
    assert_eq(mock_llm.call_count, 0, "预算不足时不应调用LLM")


def test_rule_recognizer_recommend_chain():
    """测试规则识别器推荐链路"""
    rec = RuleBasedRecognizer()
    inp = IntentInput(market={
        "price": 50000, "ema20": 49000, "ema50": 47000,
        "ema200": 45000, "change_24h": 6, "adx": 35
    })
    result = rec.recognize(inp)
    assert_eq(result.intent_type, "TREND_FOLLOWING")
    assert_true(len(result.base_chain) > 0, "应推荐非空链路")
    assert_in("A2", result.base_chain)


# ============================================================
# 4. A 层 GraphPlanner 测试
# ============================================================

def test_graph_planner_basic():
    """测试图规划器基本功能"""
    # 准备注册表
    reg = NodeRegistry()
    for nid in ["A1", "A2", "A3", "A4", "A5", "A9"]:
        reg.register(MockNode(nid, chain="A"))
    set_default_registry(reg)
    try:
        planner = GraphPlanner()
        state = new_state(intent={
            "intent_type": "TREND_FOLLOWING",
            "recommended_chain": "A",
            "base_chain": ["A1", "A2", "A3", "A4"],
            "confidence": 0.7,
        })
        plan = planner.plan(state)
        assert_eq(plan.planned_chain, "A")
        assert_true(len(plan.selected_nodes) > 0)
        assert_not_none(state.plan)
    finally:
        set_default_registry(NodeRegistry())


def test_graph_planner_infer_chain():
    """测试链路推断"""
    reg = NodeRegistry()
    for nid in ["A1", "A2", "A3", "A4", "A5", "A9", "C1", "C3"]:
        reg.register(MockNode(nid, chain=nid[0] if nid[0] in "AC" else "A"))
    set_default_registry(reg)
    try:
        planner = GraphPlanner()
        plan = planner.plan_from_intent(
            intent_type="BREAKOUT",
            recommended_chain="",  # 空应触发推断
            confidence=0.6,
        )
        assert_eq(plan.planned_chain, "C", "BREAKOUT应映射到C链")
    finally:
        set_default_registry(NodeRegistry())


def test_graph_planner_budget_allocation():
    """测试预算分配"""
    reg = NodeRegistry()
    for nid in ["A1", "A2", "A3", "A4", "A5", "A9"]:
        reg.register(MockNode(nid, chain="A", estimated_tokens=500))
    set_default_registry(reg)
    try:
        planner = GraphPlanner(budget_total=6000)
        plan = planner.plan_from_intent(
            intent_type="TREND_FOLLOWING",
            recommended_chain="A",
            base_chain=["A1", "A2", "A3", "A4"],
            confidence=0.7,
            budget_total=6000,
        )
        # 预算应被分配
        total_allocated = sum(m.allocated_tokens for m in plan.selected_nodes)
        assert_gt(total_allocated, 0, "应分配非零预算")
        # 不应超过总预算
        assert_lte(total_allocated, 6000 + 100, "分配不应超过总预算")
    finally:
        set_default_registry(NodeRegistry())


def assert_lte(a, b, msg=""):
    assert a <= b, f"{msg}: expected {a} <= {b}"


def test_node_selector_confidence_modes():
    """测试不同置信度下的节点选择"""
    reg = NodeRegistry()
    for nid in ["A1", "A2", "A3", "A4", "A5", "A9"]:
        reg.register(MockNode(nid, chain="A"))
    set_default_registry(reg)
    try:
        selector = NodeSelector()

        # 高置信度 → 精简模式
        metas_high = selector.select(chain="A", intent_confidence=0.9)
        # 低置信度 → 包含可选节点
        metas_low = selector.select(chain="A", intent_confidence=0.3)
        assert_gte(len(metas_low), len(metas_high), "低置信度应选更多节点")
    finally:
        set_default_registry(NodeRegistry())


def test_budget_allocator_priorities():
    """测试预算分配优先级"""
    allocator = BudgetAllocator(total=6000)
    nodes = [
        NodeMeta(node_id="A1", priority=0, estimated_tokens=1000),
        NodeMeta(node_id="A2", priority=0, estimated_tokens=500),
        NodeMeta(node_id="A3", priority=1, estimated_tokens=800),
        NodeMeta(node_id="C1", priority=2, estimated_tokens=300),
    ]
    alloc = allocator.allocate(nodes)
    # 必须节点应优先分配
    assert_true(alloc.get("A1") > 0, "必须节点A1应有预算")
    assert_true(alloc.get("A2") > 0, "必须节点A2应有预算")
    # 预留预算
    assert_gt(alloc.reserved, 0, "应有预留预算")


def test_budget_allocator_zero_nodes():
    """测试空节点列表"""
    allocator = BudgetAllocator(total=6000)
    alloc = allocator.allocate([])
    assert_eq(alloc.total_allocated, 0)
    assert_gt(alloc.reserved, 0)


def test_budget_allocator_reallocate():
    """测试预算回收"""
    allocator = BudgetAllocator(total=6000)
    nodes = [NodeMeta(node_id="A1", priority=0, estimated_tokens=500)]
    alloc = allocator.allocate(nodes)
    original = alloc.get("A1")
    # 执行后实际只用了 200
    alloc = allocator.reallocate(alloc, "A1", 200)
    saved = original - 200
    assert_eq(alloc.reserved, int(6000 * 0.15) + saved, "节省的预算应回流到预留池")


# ============================================================
# 5. C 层 GraphExecutor 测试
# ============================================================

def test_executor_simple_sequence():
    """测试简单顺序执行"""
    graph = SequentialGraph()
    graph.add_node(MockNode("A1", confidence=0.7, direction="LONG"))
    graph.add_node(MockNode("A2", confidence=0.8, direction="LONG"))
    graph.add_node(MockNode("A3", confidence=0.75, direction="LONG"))

    executor = GraphExecutor(enable_reflect=False)
    state = new_state()
    report = executor.execute(graph, state)

    assert_eq(report.executed_nodes, 3)
    assert_eq(report.success_nodes, 3)
    assert_eq(report.failed_nodes, 0)


def test_executor_with_failure():
    """测试节点失败"""
    graph = SequentialGraph()
    graph.add_node(MockNode("A1", confidence=0.7))
    graph.add_node(MockNode("A2", fail=True))
    graph.add_node(MockNode("A3", confidence=0.7))

    executor = GraphExecutor(max_retries=1, enable_reflect=False)
    state = new_state()
    report = executor.execute(graph, state)

    # A2 失败但执行继续
    assert_eq(report.executed_nodes, 3)
    assert_gte(report.failed_nodes, 1)


def test_executor_empty_graph():
    """测试空图"""
    graph = SequentialGraph()
    executor = GraphExecutor()
    state = new_state()
    report = executor.execute(graph, state)
    assert_eq(report.executed_nodes, 0)
    assert_not_none(report.termination_reason)


def test_executor_max_steps():
    """测试最大步数限制"""
    # 创建循环图
    graph = ConditionalGraph()
    graph.add_node(MockNode("A1"))
    graph.add_node(MockNode("A2"))
    graph.add_edge("A1", "A2")  # A2 → A1 → A2 ... 循环
    graph.add_edge("A2", "A1")

    executor = GraphExecutor(max_steps=5, enable_reflect=False)
    state = new_state()
    report = executor.execute(graph, state)
    assert_lte(report.executed_nodes, 5, "不应超过max_steps")


def test_executor_early_terminate():
    """测试提前终止"""
    graph = SequentialGraph()
    graph.add_node(MockNode("A1", confidence=0.9, direction="LONG"))
    graph.add_node(MockNode("A2", confidence=0.9, direction="LONG"))
    graph.add_node(MockNode("A3", confidence=0.9, direction="LONG"))
    graph.add_node(MockNode("A4", confidence=0.9, direction="LONG"))

    executor = GraphExecutor(enable_reflect=True, enable_early_terminate=True)
    state = new_state()
    report = executor.execute(graph, state)

    # 3个方向一致 + 高置信度 → 提前终止
    if report.early_terminated:
        assert_lt(report.executed_nodes, 4, "提前终止应减少执行节点")


def test_reflector_continue():
    """测试反射器正常继续"""
    reflector = Reflector()
    state = new_state()
    result = NodeResult(node_id="A1", confidence=0.7, direction="LONG")
    state.update("A1", result)

    graph = SequentialGraph()
    graph.add_node(MockNode("A1"))
    graph.add_node(MockNode("A2"))

    decision = reflector.decide(
        current_node_id="A1", result=result, state=state,
        graph=graph, executed_count=1, max_nodes=3,
    )
    assert_eq(decision.action, ReflectAction.CONTINUE)


def test_reflector_redo_on_failure():
    """测试失败重试决策"""
    reflector = Reflector(max_retries_per_node=3)
    state = new_state()
    result = NodeResult(
        node_id="A1", status=NodeStatus.FAILED,
        error="测试失败", error_code=ErrorCode.EXEC_002,
    )
    state.update("A1", result)
    graph = SequentialGraph()
    graph.add_node(MockNode("A1"))

    record = NodeExecutionRecord(node_id="A1", status="failed", retries=1)
    decision = reflector.decide(
        current_node_id="A1", result=result, state=state,
        graph=graph, executed_count=1, max_nodes=3, record=record,
    )
    assert_eq(decision.action, ReflectAction.REDO)


def test_reflector_skip_on_max_retries():
    """测试重试耗尽跳过"""
    reflector = Reflector(max_retries_per_node=2)
    state = new_state()
    result = NodeResult(
        node_id="A1", status=NodeStatus.FAILED,
        error="持续失败", error_code=ErrorCode.EXEC_002,
    )
    state.update("A1", result)
    graph = SequentialGraph()
    graph.add_node(MockNode("A1"))

    record = NodeExecutionRecord(node_id="A1", status="failed", retries=2)
    decision = reflector.decide(
        current_node_id="A1", result=result, state=state,
        graph=graph, executed_count=1, max_nodes=3, record=record,
    )
    assert_eq(decision.action, ReflectAction.SKIP)


def test_node_runner_retry():
    """测试节点执行器重试"""
    runner = NodeRunner(max_retries=3)
    flaky = FlakyNode("A1", fail_times=2, confidence=0.6)
    state = new_state()
    record = runner.run(flaky, state)
    assert_eq(record.status, "success")
    assert_eq(flaky._call_count, 3, "应重试3次才成功")


def test_node_runner_fallback_on_exception():
    """测试异常时降级"""
    class CrashNode(Node):
        node_id = "CRASH"
        name = "Crash"
        chain = "A"
        tags = []
        estimated_tokens = 0
        estimated_latency_ms = 0
        def execute(self, state):
            raise RuntimeError("严重崩溃")
        def fallback(self, state):
            return NodeResult(node_id="CRASH", status=NodeStatus.DEGRADED, confidence=0.1)

    runner = NodeRunner(max_retries=2)
    state = new_state()
    record = runner.run(CrashNode(), state)
    assert_eq(record.status, "degraded", "异常应触发降级")


# ============================================================
# 6. Aggregator 测试
# ============================================================

def test_aggregator_long_direction():
    """测试多头方向聚合"""
    state = new_state()
    state.update("A1", NodeResult(node_id="A1", confidence=0.8, direction="LONG"))
    state.update("A2", NodeResult(node_id="A2", confidence=0.75, direction="LONG"))
    state.update("A3", NodeResult(node_id="A3", confidence=0.7, direction="LONG"))

    agg = Aggregator()
    report = agg.aggregate(state)
    assert_eq(report.final_action, "LONG")
    assert_gt(report.final_confidence, 0.5)


def test_aggregator_short_direction():
    """测试空头方向聚合"""
    state = new_state()
    state.update("A1", NodeResult(node_id="A1", confidence=0.8, direction="SHORT"))
    state.update("A2", NodeResult(node_id="A2", confidence=0.75, direction="SHORT"))

    agg = Aggregator()
    report = agg.aggregate(state)
    assert_eq(report.final_action, "SHORT")


def test_aggregator_hold_on_disagreement():
    """测试方向分歧→HOLD"""
    state = new_state()
    state.update("A1", NodeResult(node_id="A1", confidence=0.6, direction="LONG"))
    state.update("A2", NodeResult(node_id="A2", confidence=0.6, direction="SHORT"))

    agg = Aggregator()
    report = agg.aggregate(state)
    assert_eq(report.final_action, "HOLD", "方向分歧应返回HOLD")


def test_aggregator_empty_state():
    """测试空 State 聚合"""
    state = new_state()
    agg = Aggregator()
    report = agg.aggregate(state)
    assert_eq(report.final_action, "HOLD")
    assert_eq(report.final_confidence, 0.0)


def test_aggregator_hold_confidence_discount():
    """测试 HOLD 置信度打折"""
    state = new_state()
    state.update("A1", NodeResult(node_id="A1", confidence=0.5, direction="LONG"))
    state.update("A2", NodeResult(node_id="A2", confidence=0.5, direction="SHORT"))
    agg = Aggregator()
    report = agg.aggregate(state)
    # HOLD 时置信度应打折 (×0.6)
    assert_lt(report.final_confidence, 0.5, "HOLD时置信度应打折")


def test_aggregator_weighted_confidence():
    """测试加权置信度"""
    state = new_state()
    state.update("A4", NodeResult(node_id="A4", confidence=0.9, direction="LONG"))
    state.update("C1", NodeResult(node_id="C1", confidence=0.5, direction="LONG"))

    agg = Aggregator()
    report = agg.aggregate(state)
    # A4 权重 2.0, C1 权重 0.8
    # 加权 = (0.9*2.0 + 0.5*0.8) / (2.0+0.8) = 2.2/2.8 ≈ 0.786
    assert_gt(report.final_confidence, 0.7, "高权重节点应拉高置信度")


def test_aggregator_disagreement_threshold_bug():
    """BUG #2: 分歧阈值过于激进"""
    state = new_state()
    state.update("A1", NodeResult(node_id="A1", confidence=0.8, direction="LONG"))
    state.update("A2", NodeResult(node_id="A2", confidence=0.8, direction="LONG"))
    state.update("A3", NodeResult(node_id="A3", confidence=0.6, direction="SHORT"))

    agg = Aggregator()
    report = agg.aggregate(state)
    # 2个LONG + 1个SHORT, 但因为分歧检测可能太激进
    scores = report.final_direction_scores
    long_s = scores.get("LONG", 0)
    short_s = scores.get("SHORT", 0)
    non_neutral = long_s + short_s
    if non_neutral > 0:
        disagreement = 1.0 - abs(long_s - short_s) / non_neutral
        # 如果 LONG 明显大于 SHORT 但仍返回 HOLD
        if long_s > short_s * 1.5 and report.final_action == "HOLD":
            raise AssertionError(
                f"BUG#2: LONG({long_s:.3f}) 明显大于 SHORT({short_s:.3f}) "
                f"但返回HOLD (disagreement={disagreement:.3f}) "
                "- 分歧阈值过于激进"
            )


# ============================================================
# 7. G 层 GraphStore 测试
# ============================================================

def test_graph_store_checkpoint():
    """测试检查点"""
    store = GraphStore()
    state = new_state(cycle_id="test_cp_001")
    state.update("A1", NodeResult(node_id="A1", confidence=0.7))
    cp_id = store.checkpoint(state, node_id="A1")
    assert_not_none(cp_id)

    # 回滚
    restored = store.rollback(cp_id)
    assert_not_none(restored)
    assert_eq(restored.cycle_id, "test_cp_001")
    assert_eq(restored.get_confidence("A1"), 0.7)


def test_graph_store_history():
    """测试历史记录"""
    store = GraphStore()
    state = new_state(cycle_id="test_hist_001")
    state.update("A1", NodeResult(node_id="A1", confidence=0.7, direction="LONG"))
    state.final_action = "LONG"
    state.final_confidence = 0.7

    entry = store.record(state, {"total_tokens": 500, "success_rate": 1.0})
    assert_eq(entry.cycle_id, "test_hist_001")

    history = store.query_history()
    assert_gte(len(history), 1)


def test_graph_store_compression():
    """测试状态压缩"""
    store = GraphStore(compress_threshold=100)
    state = new_state(cycle_id="test_compress")
    # 制造大量 trace
    for i in range(200):
        state.update(f"N{i}", NodeResult(node_id=f"N{i}", confidence=0.5))

    compressed = store.compress(state)
    assert_gt(compressed.original_size, 0)
    assert_gt(compressed.removed_trace_count, 0, "应移除部分trace")


def test_graph_store_summary():
    """测试存储摘要"""
    store = GraphStore()
    summary = store.summary()
    assert_in("checkpoints", summary)
    assert_in("history_entries", summary)


# ============================================================
# 8. Evolution Engine 测试
# ============================================================

def test_evolution_empty():
    """测试空历史进化"""
    engine = EvolutionEngine()
    report = engine.evolve([])
    assert_eq(report.cycles_analyzed, 0)


def test_evolution_gap_analysis():
    """测试差距分析"""
    engine = EvolutionEngine()
    state = new_state()
    state.update("A1", NodeResult(node_id="A1", confidence=0.8, direction="LONG"))
    state.update("A2", NodeResult(node_id="A2", confidence=0.7, direction="LONG"))

    gap = engine.analyze_gap(state)
    # 高置信度 + 全部成功 → gap 小
    assert_lt(gap, 0.5, "高置信度全成功gap应小")


def test_evolution_gap_high():
    """测试高差距"""
    engine = EvolutionEngine()
    state = new_state()
    state.update("A1", NodeResult(
        node_id="A1", status=NodeStatus.FAILED, confidence=0.0
    ))
    state.update("A2", NodeResult(
        node_id="A2", status=NodeStatus.FAILED, confidence=0.0
    ))
    gap = engine.analyze_gap(state)
    assert_gt(gap, 0.8, "全失败gap应接近1.0")


def test_evolution_record_and_evolve():
    """测试记录和进化"""
    engine = EvolutionEngine()
    for i in range(5):
        entry = HistoryEntry(
            cycle_id=f"cycle_{i}",
            intent_type="TREND_FOLLOWING",
            final_action="LONG" if i < 3 else "HOLD",
            final_confidence=0.7 - i * 0.05,
            total_tokens=500 + i * 100,
            success_rate=1.0 if i < 3 else 0.5,
        )
        engine.record(entry)

    report = engine.evolve()
    assert_eq(report.cycles_analyzed, 5)
    assert_in("avg_confidence", report.performance_metrics)


# ============================================================
# 9. Budget 测试
# ============================================================

def test_global_budget_basic():
    """测试全局预算"""
    budget = GlobalBudgetManager(mode="standard")
    cid = budget.begin_cycle()
    assert_not_none(cid)

    consumed = budget.consume(500, layer="sense")
    assert_eq(consumed, 500)
    assert_eq(budget.used_per_cycle, 500)

    budget.end_cycle()
    assert_eq(budget.total_cycles, 1)


def test_global_budget_levels():
    """测试预算等级"""
    budget = GlobalBudgetManager(mode="standard")
    budget.begin_cycle()
    # 消耗 50% → WARNING
    budget.consume(3000)  # standard=6000, 50%
    level = budget.level()
    assert_in(level, [GlobalBudgetLevel.WARNING, GlobalBudgetLevel.TIGHT])

    # 消耗 95% → EXHAUSTED
    budget.consume(2700)  # total 5700/6000 = 95%
    level = budget.level()
    assert_eq(level, GlobalBudgetLevel.EXHAUSTED)


def test_global_budget_degradation():
    """测试降级链"""
    budget = GlobalBudgetManager(mode="standard")
    budget.begin_cycle()
    budget.consume(5000)  # 83% → CRITICAL
    assert_true(budget.should_degrade_llm(), "CRITICAL应降级LLM")
    assert_false(budget.should_use_classic_only(), "CRITICAL不应只用经典指标")

    budget.consume(700)  # 95% → EXHAUSTED
    assert_true(budget.should_use_classic_only(), "EXHAUSTED应只用经典指标")


def test_global_budget_layer_limits():
    """测试层预算限制"""
    budget = GlobalBudgetManager(mode="standard")
    budget.begin_cycle()
    # sense 层预算 = 6000 * 0.10 = 600
    sense_budget = budget.layer_budget_per_cycle("sense")
    assert_eq(sense_budget, 600)

    budget.consume(500, layer="sense")
    remaining = budget.layer_remaining_per_cycle("sense")
    assert_lte(remaining, 100, "sense层剩余应<=100")


def test_token_budget_modes():
    """测试 S 层预算档位"""
    lean = TokenBudgetManager(mode="lean")
    standard = TokenBudgetManager(mode="standard")
    full = TokenBudgetManager(mode="full")
    assert_eq(lean.total, 3000)
    assert_eq(standard.total, 6000)
    assert_eq(full.total, 10000)


def test_token_budget_degradation():
    """测试 S 层预算降级"""
    budget = TokenBudgetManager(mode="lean")  # 3000
    budget.consume(2500)  # 83% used → CRITICAL
    assert_true(budget.should_degrade_llm())
    assert_false(budget.should_switch_classic())

    budget.consume(400)  # 97% → EXHAUSTED
    assert_true(budget.should_switch_classic())


# ============================================================
# 10. 端到端集成测试
# ============================================================

def test_e2e_full_pipeline():
    """端到端: S -> A -> C -> G 全链路"""
    # 准备注册表
    reg = NodeRegistry()
    for nid in ["A1", "A2", "A3", "A4", "A5", "A9"]:
        reg.register(MockNode(nid, chain="A", confidence=0.7, direction="LONG"))
    set_default_registry(reg)

    try:
        # S 层: 意图识别
        engine = IntentEngine(use_llm_based=False, use_dynamic=False)
        intent = engine.recognize(market={
            "price": 50000, "change_24h": 6, "rsi14": 55,
            "ema20": 49000, "ema50": 47000, "ema200": 45000,
            "adx": 35, "vol_ratio": 1.2,
        })

        # A 层: 图规划
        planner = GraphPlanner()
        state = new_state(intent=intent.to_dict())
        plan = planner.plan(state)

        # 构建图
        graph = planner.build_graph(plan)

        # C 层: 执行
        executor = GraphExecutor()
        report = executor.execute(graph, state, plan=plan)

        # G 层: 记录
        store = GraphStore()
        store.record(state, report.to_dict())

        # 验证
        assert_true(report.executed_nodes > 0, "应执行节点")
        assert_not_none(report.final_action, "应有最终方向")
        assert_gte(store.history.total, 1, "应记录历史")

    finally:
        set_default_registry(NodeRegistry())


def test_e2e_with_failures():
    """端到端: 包含失败的完整流程"""
    reg = NodeRegistry()
    reg.register(MockNode("A1", confidence=0.7, direction="LONG"))
    reg.register(MockNode("A2", fail=True))  # A2 失败
    reg.register(MockNode("A3", confidence=0.6, direction="LONG"))
    reg.register(MockNode("A4", confidence=0.7, direction="LONG"))
    set_default_registry(reg)

    try:
        planner = GraphPlanner()
        state = new_state(intent={
            "intent_type": "TREND_FOLLOWING",
            "recommended_chain": "A",
            "base_chain": ["A1", "A2", "A3", "A4"],
            "confidence": 0.6,
        })
        plan = planner.plan(state)
        graph = planner.build_graph(plan)

        executor = GraphExecutor(max_retries=1)
        report = executor.execute(graph, state, plan=plan)

        assert_gte(report.failed_nodes, 1, "A2应失败")
        assert_gte(report.executed_nodes, 3, "应执行3+个节点")

    finally:
        set_default_registry(NodeRegistry())


def test_e2e_conditional_graph():
    """端到端: 条件图执行"""
    reg = NodeRegistry()
    reg.register(MockNode("A1", confidence=0.9, direction="LONG"))
    reg.register(MockNode("A2", confidence=0.7, direction="LONG"))
    reg.register(MockNode("A3", confidence=0.8, direction="LONG"))
    set_default_registry(reg)

    try:
        graph = ConditionalGraph()
        graph.add_node(MockNode("A1", confidence=0.9))
        graph.add_node(MockNode("A2", confidence=0.7))
        graph.add_node(MockNode("A3", confidence=0.8))
        # A1 置信度高 → 跳过 A2 到 A3
        graph.add_edge("A1", "A3", condition=lambda s: s.get_confidence("A1") > 0.8)

        executor = GraphExecutor(enable_reflect=False)
        state = new_state()
        report = executor.execute(graph, state)

        assert_gte(report.executed_nodes, 2, "条件图应执行至少2个节点")

    finally:
        set_default_registry(NodeRegistry())


# ============================================================
# 11. 边界与 Bug 检测
# ============================================================

def test_bug_executor_redo_infinite_loop():
    """BUG #3: REDO 可能导致无限循环"""
    # 如果 Reflector 返回 REDO 但节点始终失败
    # NodeRunner 内部已重试耗尽, 但 Reflector 可能再次 REDO
    class AlwaysFailNode(Node):
        node_id = "FAIL"
        name = "AlwaysFail"
        chain = "A"
        tags = []
        estimated_tokens = 0
        estimated_latency_ms = 0
        def execute(self, state):
            return NodeResult(
                node_id="FAIL", status=NodeStatus.FAILED,
                error="永远失败", error_code=ErrorCode.EXEC_002,
            )

    graph = SequentialGraph()
    graph.add_node(AlwaysFailNode())
    graph.add_node(MockNode("A2"))

    executor = GraphExecutor(max_retries=1, max_steps=10)
    state = new_state()
    report = executor.execute(graph, state)

    # max_steps 应防止无限循环
    assert_lte(report.executed_nodes, 10, "max_steps应防止无限循环")


def test_bug_aggregator_neutral_dominates():
    """BUG #4: NEUTRAL 方向不计入分歧但影响归一化"""
    state = new_state()
    state.update("A1", NodeResult(node_id="A1", confidence=0.5, direction="NEUTRAL"))
    state.update("A2", NodeResult(node_id="A2", confidence=0.8, direction="LONG"))

    agg = Aggregator()
    report = agg.aggregate(state)

    # NEUTRAL 参与了 direction_scores 但 long/short 比较忽略了它
    # 如果 NEUTRAL 权重很大, LONG 的归一化分数会很低
    scores = report.final_direction_scores
    long_score = scores.get("LONG", 0)
    neutral_score = scores.get("NEUTRAL", 0)

    # LONG 应该占主导
    if long_score < neutral_score:
        raise AssertionError(
            f"BUG#4: LONG({long_score:.3f}) < NEUTRAL({neutral_score:.3f}) "
            "- NEUTRAL 参与归一化但不参与方向判定, 导致LONG被稀释"
        )


def test_bug_reflector_jumpto_missing_node():
    """BUG #5: JUMP_TO 目标节点不存在时静默忽略"""
    reflector = Reflector()
    state = new_state()
    state.update("A1", NodeResult(node_id="A1", confidence=0.2))

    graph = SequentialGraph()
    graph.add_node(MockNode("A1", confidence=0.2))
    graph.add_node(MockNode("A2"))

    # 构造一个 jump_to 不存在的决策
    decision = ReflectDecision(
        action=ReflectAction.JUMP_TO,
        jump_to="NON_EXISTENT",
    )

    # GraphExecutor 会尝试 graph.get_node("NON_EXISTENT")
    node = graph.get_node("NON_EXISTENT") if hasattr(graph, "get_node") else None
    assert_none(node, "不存在的节点应返回None")

    # 如果 node 是 None, executor 会 fallthrough 到 get_next
    next_node = graph.get_next("A1", state)
    assert_not_none(next_node, "应回退到顺序执行下一个")


def test_bug_budget_allocator_available_depletion():
    """BUG #6: 预算分配器 available 变量在循环中被修改"""
    allocator = BudgetAllocator(total=1000)
    # 5个必须节点, 每个需要 300 tokens
    nodes = [
        NodeMeta(node_id=f"N{i}", priority=0, estimated_tokens=300)
        for i in range(5)
    ]
    alloc = allocator.allocate(nodes)

    # 总需求 5*300=1500, 但总预算只有 1000
    # 预留 150, 可用 850
    # 第1个节点: cap = 850//5*2 = 340, actual = min(300, 340) = 300, available=550
    # 第2个节点: cap = 550//5*2 = 220, actual = min(300, 220) = 220, available=330
    # 第3个节点: cap = 330//5*2 = 132, actual = min(300, 132) = 132, available=198
    # ...后续节点越来越少
    n1_budget = alloc.get("N0")
    n5_budget = alloc.get("N4")

    # 后面的节点应该比前面少
    if n5_budget >= n1_budget:
        raise AssertionError(
            f"BUG#6: 后面的节点(N4={n5_budget}) >= 前面节点(N0={n1_budget}) "
            "- available 在循环中被修改导致分配不均"
        )


def test_bug_state_from_dict_missing_timestamps():
    """BUG #7: from_dict 不恢复 started_at/updated_at"""
    s = new_state(cycle_id="test_ts")
    s.started_at = s.started_at  # 确保有值
    original_started = s.started_at

    d = s.to_dict()
    s2 = State.from_dict(d)

    if s2.started_at is None:
        raise AssertionError(
            "BUG#7: from_dict 未恢复 started_at/updated_at - "
            "序列化往返丢失时间戳信息"
        )


def test_edge_case_none_intent():
    """边界: State.intent 为 None"""
    planner = GraphPlanner()
    state = new_state()
    state.intent = None
    plan = planner.plan(state)
    # 应使用默认值, 不崩溃
    assert_eq(plan.planned_chain, "A")


def test_edge_case_empty_user_message():
    """边界: 空用户消息"""
    engine = IntentEngine(use_llm_based=False, use_dynamic=False)
    result = engine.recognize(user_message="", market={"price": 50000})
    assert_not_none(result)


def test_edge_case_extreme_market_data():
    """边界: 极端市场数据"""
    engine = IntentEngine(use_llm_based=False, use_dynamic=False)
    result = engine.recognize(market={
        "price": 0,
        "change_24h": 1000,  # 1000% 涨幅
        "rsi14": 100,
        "ema20": 0,
        "ema50": 0,
        "ema200": 0,
        "adx": 100,
        "vol_ratio": 100,
    })
    # 不应崩溃
    assert_not_none(result.intent_type)


def test_edge_case_negative_tokens():
    """边界: 负数 Token"""
    budget = TokenBudgetManager(mode="standard")
    consumed = budget.consume(-100)
    # 负数不应增加可用预算
    assert_true(consumed >= 0, "负数消耗应被限制为0")


def test_edge_case_registry_clear():
    """边界: 清空注册表"""
    reg = NodeRegistry()
    reg.register(MockNode("A1"))
    reg.register(MockNode("A2"))
    count = reg.clear()
    assert_eq(count, 2)
    assert_eq(len(reg), 0)


def test_concurrent_state_update():
    """并发: State 并发更新安全性"""
    state = new_state()
    errors = []

    def update_batch(prefix: str, count: int):
        try:
            for i in range(count):
                state.update(f"{prefix}_{i}", NodeResult(
                    node_id=f"{prefix}_{i}", confidence=0.5
                ))
        except Exception as e:
            errors.append(str(e))

    threads = []
    for t in range(4):
        threads.append(threading.Thread(target=update_batch, args=(f"T{t}", 25)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert_eq(len(errors), 0, "并发更新不应有错误")
    assert_eq(len(state.results), 100, "应有100个结果")


def test_conditional_graph_no_edges():
    """边界: 条件图无边"""
    graph = ConditionalGraph()
    graph.add_node(MockNode("A1"))
    # 没有边 → get_next 返回 None
    state = new_state()
    next_node = graph.get_next("A1", state)
    assert_none(next_node)


def test_sequential_graph_condition_edge():
    """测试顺序图条件边"""
    graph = SequentialGraph()
    graph.add_node(MockNode("A1", confidence=0.9))
    graph.add_node(MockNode("A2"))
    graph.add_node(MockNode("A3"))
    # A1 置信度 > 0.8 → 跳到 A3
    graph.add_edge("A1", "A3", condition=lambda s: s.get_confidence("A1") > 0.8)

    state = new_state()
    state.update("A1", NodeResult(node_id="A1", confidence=0.9))
    next_node = graph.get_next("A1", state)
    assert_eq(next_node.node_id, "A3", "条件边应跳转")


# ============================================================
# 运行所有测试
# ============================================================

def run_all_tests():
    """运行所有测试"""
    global _all_tests
    _all_tests = []

    tests = [
        # 1. State
        ("test_state_creation", "State", test_state_creation),
        ("test_state_update_and_get", "State", test_state_update_and_get),
        ("test_state_aggregate_confidence", "State", test_state_aggregate_confidence),
        ("test_state_serialization_roundtrip", "State", test_state_serialization_roundtrip),
        ("test_state_snapshot_independence", "State", test_state_snapshot_independence),
        ("test_state_is_all_success_with_missing_nodes", "State", test_state_is_all_success_with_missing_nodes, True),
        ("test_state_empty_aggregate", "State", test_state_empty_aggregate),

        # 2. Registry
        ("test_registry_basic", "Registry", test_registry_basic),
        ("test_registry_duplicate", "Registry", test_registry_duplicate),
        ("test_registry_unregister", "Registry", test_registry_unregister),
        ("test_registry_empty_id", "Registry", test_registry_empty_id),
        ("test_registry_list_by_chain", "Registry", test_registry_list_by_chain),
        ("test_registry_list_by_tag", "Registry", test_registry_list_by_tag),
        ("test_registry_thread_safety", "Registry", test_registry_thread_safety),
        ("test_registry_register_many", "Registry", test_registry_register_many),

        # 3. S 层
        ("test_intent_engine_trend_following", "S-Intent", test_intent_engine_trend_following),
        ("test_intent_engine_mean_reversion", "S-Intent", test_intent_engine_mean_reversion),
        ("test_intent_engine_breakout", "S-Intent", test_intent_engine_breakout),
        ("test_intent_engine_no_input", "S-Intent", test_intent_engine_no_input),
        ("test_intent_engine_nlp_keywords", "S-Intent", test_intent_engine_nlp_keywords),
        ("test_intent_engine_clarify_needed", "S-Intent", test_intent_engine_clarify_needed),
        ("test_intent_engine_llm_fallback", "S-Intent", test_intent_engine_llm_fallback),
        ("test_intent_engine_budget_exhausted", "S-Intent", test_intent_engine_budget_exhausted),
        ("test_rule_recognizer_recommend_chain", "S-Intent", test_rule_recognizer_recommend_chain),

        # 4. A 层
        ("test_graph_planner_basic", "A-Planner", test_graph_planner_basic),
        ("test_graph_planner_infer_chain", "A-Planner", test_graph_planner_infer_chain),
        ("test_graph_planner_budget_allocation", "A-Planner", test_graph_planner_budget_allocation),
        ("test_node_selector_confidence_modes", "A-Planner", test_node_selector_confidence_modes),
        ("test_budget_allocator_priorities", "A-Budget", test_budget_allocator_priorities),
        ("test_budget_allocator_zero_nodes", "A-Budget", test_budget_allocator_zero_nodes),
        ("test_budget_allocator_reallocate", "A-Budget", test_budget_allocator_reallocate),
        ("test_bug_budget_allocator_available_depletion", "A-Budget", test_bug_budget_allocator_available_depletion, True),

        # 5. C 层
        ("test_executor_simple_sequence", "C-Executor", test_executor_simple_sequence),
        ("test_executor_with_failure", "C-Executor", test_executor_with_failure),
        ("test_executor_empty_graph", "C-Executor", test_executor_empty_graph),
        ("test_executor_max_steps", "C-Executor", test_executor_max_steps),
        ("test_executor_early_terminate", "C-Executor", test_executor_early_terminate),
        ("test_reflector_continue", "C-Reflect", test_reflector_continue),
        ("test_reflector_redo_on_failure", "C-Reflect", test_reflector_redo_on_failure),
        ("test_reflector_skip_on_max_retries", "C-Reflect", test_reflector_skip_on_max_retries),
        ("test_node_runner_retry", "C-Runner", test_node_runner_retry),
        ("test_node_runner_fallback_on_exception", "C-Runner", test_node_runner_fallback_on_exception),
        ("test_bug_executor_redo_infinite_loop", "C-Executor", test_bug_executor_redo_infinite_loop, True),

        # 6. Aggregator
        ("test_aggregator_long_direction", "Aggregator", test_aggregator_long_direction),
        ("test_aggregator_short_direction", "Aggregator", test_aggregator_short_direction),
        ("test_aggregator_hold_on_disagreement", "Aggregator", test_aggregator_hold_on_disagreement),
        ("test_aggregator_empty_state", "Aggregator", test_aggregator_empty_state),
        ("test_aggregator_hold_confidence_discount", "Aggregator", test_aggregator_hold_confidence_discount),
        ("test_aggregator_weighted_confidence", "Aggregator", test_aggregator_weighted_confidence),
        ("test_aggregator_disagreement_threshold_bug", "Aggregator", test_aggregator_disagreement_threshold_bug, True),
        ("test_bug_aggregator_neutral_dominates", "Aggregator", test_bug_aggregator_neutral_dominates, True),

        # 7. G 层
        ("test_graph_store_checkpoint", "G-Store", test_graph_store_checkpoint),
        ("test_graph_store_history", "G-Store", test_graph_store_history),
        ("test_graph_store_compression", "G-Store", test_graph_store_compression),
        ("test_graph_store_summary", "G-Store", test_graph_store_summary),

        # 8. Evolution
        ("test_evolution_empty", "Evolution", test_evolution_empty),
        ("test_evolution_gap_analysis", "Evolution", test_evolution_gap_analysis),
        ("test_evolution_gap_high", "Evolution", test_evolution_gap_high),
        ("test_evolution_record_and_evolve", "Evolution", test_evolution_record_and_evolve),

        # 9. Budget
        ("test_global_budget_basic", "Budget", test_global_budget_basic),
        ("test_global_budget_levels", "Budget", test_global_budget_levels),
        ("test_global_budget_degradation", "Budget", test_global_budget_degradation),
        ("test_global_budget_layer_limits", "Budget", test_global_budget_layer_limits),
        ("test_token_budget_modes", "Budget", test_token_budget_modes),
        ("test_token_budget_degradation", "Budget", test_token_budget_degradation),

        # 10. 端到端
        ("test_e2e_full_pipeline", "E2E", test_e2e_full_pipeline),
        ("test_e2e_with_failures", "E2E", test_e2e_with_failures),
        ("test_e2e_conditional_graph", "E2E", test_e2e_conditional_graph),

        # 11. 边界与 Bug
        ("test_bug_reflector_jumpto_missing_node", "Bug", test_bug_reflector_jumpto_missing_node),
        ("test_bug_state_from_dict_missing_timestamps", "Bug", test_bug_state_from_dict_missing_timestamps, True),
        ("test_edge_case_none_intent", "Edge", test_edge_case_none_intent),
        ("test_edge_case_empty_user_message", "Edge", test_edge_case_empty_user_message),
        ("test_edge_case_extreme_market_data", "Edge", test_edge_case_extreme_market_data),
        ("test_edge_case_negative_tokens", "Edge", test_edge_case_negative_tokens),
        ("test_edge_case_registry_clear", "Edge", test_edge_case_registry_clear),
        ("test_concurrent_state_update", "Edge", test_concurrent_state_update),
        ("test_conditional_graph_no_edges", "Edge", test_conditional_graph_no_edges),
        ("test_sequential_graph_condition_edge", "Graph", test_sequential_graph_condition_edge),
    ]

    print(f"\n{'='*70}")
    print(f"Dreambuddy OS 多场景测试 — 共 {len(tests)} 个测试")
    print(f"{'='*70}\n")

    for t in tests:
        if len(t) == 4:
            name, cat, fn, expect_bug = t
        else:
            name, cat, fn = t
            expect_bug = False
        result = run_test(name, cat, fn, expect_bug)
        status = "PASS" if result.passed else "FAIL"
        bug = " [BUG]" if result.bug_found else ""
        print(f"  [{status}]{bug:6s} {cat:12s} / {name:45s} ({result.duration_ms:.0f}ms)")
        if not result.passed and result.error:
            # 只打印前 200 字符
            err_short = result.error[:200].replace("\n", " ")
            print(f"         ERROR: {err_short}")

    # 汇总
    total = len(_all_tests)
    passed = sum(1 for t in _all_tests if t.passed)
    failed = total - passed
    bugs = sum(1 for t in _all_tests if t.bug_found)
    bug_fails = [t for t in _all_tests if t.bug_found and not t.passed]

    print(f"\n{'='*70}")
    print(f"汇总: {passed}/{total} 通过, {failed} 失败, {bugs} 个Bug发现")
    print(f"{'='*70}")

    if bug_fails:
        print(f"\n发现的 Bug:")
        print(f"{'-'*70}")
        for t in bug_fails:
            print(f"  [{t.category}] {t.name}")
            print(f"    {t.bug_description[:200]}")
            print()

    # 按类别统计
    categories = {}
    for t in _all_tests:
        if t.category not in categories:
            categories[t.category] = {"total": 0, "passed": 0, "failed": 0, "bugs": 0}
        categories[t.category]["total"] += 1
        if t.passed:
            categories[t.category]["passed"] += 1
        else:
            categories[t.category]["failed"] += 1
        if t.bug_found:
            categories[t.category]["bugs"] += 1

    print(f"\n按类别统计:")
    print(f"{'-'*50}")
    for cat, stats in sorted(categories.items()):
        print(f"  {cat:12s}: {stats['passed']}/{stats['total']} 通过, {stats['failed']} 失败, {stats['bugs']} Bug")

    return _all_tests


if __name__ == "__main__":
    results = run_all_tests()
    # 输出 JSON 供后续分析
    import json
    output = {
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "bugs": [r for r in results if r.bug_found],
        "categories": {},
    }
    for r in results:
        if r.category not in output["categories"]:
            output["categories"][r.category] = {"total": 0, "passed": 0, "failed": 0}
        output["categories"][r.category]["total"] += 1
        if r.passed:
            output["categories"][r.category]["passed"] += 1
        else:
            output["categories"][r.category]["failed"] += 1

    print(f"\n\nJSON Summary:")
    print(json.dumps(output, default=str, indent=2, ensure_ascii=False))

    sys.exit(0 if all(r.passed for r in results) else 1)
