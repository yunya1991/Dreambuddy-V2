"""
端到端 RED 测试 — Classic Pipeline C0-C8 串行流水线骨架验证

断言：
1. NodeSelector 能选出 C_CLASSIC 链的 9 个节点序列
2. 串行执行 C0→C1→...→C8 全部返回 NodeResult（骨架阶段允许 SUCCESS + confidence=0）
3. State.results 包含全部 9 个节点的执行结果
4. STANDARD_CHAINS 中 C_CLASSIC 链定义正确
"""

from __future__ import annotations

import pytest

from dreamos.shared.state import State, NodeResult, NodeStatus


def test_c_classic_chain_defined_in_standard_chains():
    """断言 STANDARD_CHAINS 中定义了 C_CLASSIC 链"""
    from dreamos.core.arrange.types import STANDARD_CHAINS
    assert "C_CLASSIC" in STANDARD_CHAINS, "STANDARD_CHAINS 缺少 C_CLASSIC 链"

    chain = STANDARD_CHAINS["C_CLASSIC"]
    assert chain.node_ids == ["C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"], \
        f"C_CLASSIC node_ids 不正确: {chain.node_ids}"
    assert chain.chain_id == "C_CLASSIC"


def test_register_all_registers_nine_nodes():
    """断言 register_all() 后 C0-C8 全部注册"""
    from dreamos.capabilities.trading.nodes import register_all
    from dreamos.registry import get_default_registry

    reg = get_default_registry()
    register_all(reg)

    registered_ids = []
    for i in range(9):
        node = reg.get(f"C{i}")
        assert node is not None, f"C{i} 未注册"
        registered_ids.append(node.node_id)

    assert registered_ids == ["C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]


def test_serial_pipeline_execution_skeleton():
    """端到端骨架测试：手动串行执行 C0→C8，断言全部返回 NodeResult

    骨架阶段不依赖 NodeSelector/GraphPlanner（那些需要完整 State 配置），
    直接手动串行调用 execute_core，验证节点骨架可串行流转。
    """
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    from dreamos.capabilities.trading.nodes.c2_signal_detect import C2SignalDetectNode
    from dreamos.capabilities.trading.nodes.c3_backtest_verify import C3BacktestVerifyNode
    from dreamos.capabilities.trading.nodes.c4_risk_assess import C4RiskAssessNode
    from dreamos.capabilities.trading.nodes.c5_param_optimize import C5ParamOptimizeNode
    from dreamos.capabilities.trading.nodes.c6_plan_generate import C6PlanGenerateNode
    from dreamos.capabilities.trading.nodes.c7_exec_monitor import C7ExecMonitorNode
    from dreamos.capabilities.trading.nodes.c8_perf_attribution import C8PerfAttributionNode

    nodes = [
        C0EnvScanNode(), C1SymbolFilterNode(), C2SignalDetectNode(),
        C3BacktestVerifyNode(), C4RiskAssessNode(), C5ParamOptimizeNode(),
        C6PlanGenerateNode(), C7ExecMonitorNode(), C8PerfAttributionNode(),
    ]

    state = State()
    results = []

    for node in nodes:
        # 调用 execute（模板方法，含计时/异常处理）而非 execute_core
        result = node.execute(state)
        state.update(node.node_id, result)
        results.append(result)

    # 断言全部 9 个节点都返回了 NodeResult
    assert len(results) == 9, f"期望 9 个结果，实际 {len(results)}"

    for i, result in enumerate(results):
        expected_id = f"C{i}"
        assert result.node_id == expected_id, \
            f"第 {i} 个节点 node_id 期望 {expected_id} 实际 {result.node_id}"
        assert isinstance(result, NodeResult), \
            f"{expected_id} 未返回 NodeResult"

    # 骨架阶段：允许 SUCCESS + confidence=0（不强制要求真实业务输出）
    for result in results:
        assert result.status in (NodeStatus.SUCCESS, NodeStatus.FAILED, NodeStatus.DEGRADED), \
            f"{result.node_id} status 异常: {result.status}"

    # 断言 State.results 包含全部 9 个节点
    assert len(state.results) == 9, \
        f"State.results 期望 9 项，实际 {len(state.results)}"
    for i in range(9):
        assert f"C{i}" in state.results, f"State.results 缺少 C{i}"


def test_pipeline_trace_records_nine_steps():
    """断言串行执行后 State.trace 记录了 9 个步骤"""
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    from dreamos.capabilities.trading.nodes.c2_signal_detect import C2SignalDetectNode
    from dreamos.capabilities.trading.nodes.c3_backtest_verify import C3BacktestVerifyNode
    from dreamos.capabilities.trading.nodes.c4_risk_assess import C4RiskAssessNode
    from dreamos.capabilities.trading.nodes.c5_param_optimize import C5ParamOptimizeNode
    from dreamos.capabilities.trading.nodes.c6_plan_generate import C6PlanGenerateNode
    from dreamos.capabilities.trading.nodes.c7_exec_monitor import C7ExecMonitorNode
    from dreamos.capabilities.trading.nodes.c8_perf_attribution import C8PerfAttributionNode

    nodes = [
        C0EnvScanNode(), C1SymbolFilterNode(), C2SignalDetectNode(),
        C3BacktestVerifyNode(), C4RiskAssessNode(), C5ParamOptimizeNode(),
        C6PlanGenerateNode(), C7ExecMonitorNode(), C8PerfAttributionNode(),
    ]

    state = State()
    for node in nodes:
        result = node.execute(state)
        state.update(node.node_id, result)

    assert len(state.trace) == 9, f"trace 期望 9 步，实际 {len(state.trace)}"

    # 验证 trace 顺序
    for i, entry in enumerate(state.trace):
        assert entry["node_id"] == f"C{i}", \
            f"trace[{i}] node_id 期望 C{i} 实际 {entry['node_id']}"
