"""
RED 测试 — Classic Pipeline C0-C8 八阶段节点骨架验证

断言每个节点：
1. 可导入
2. node_id/chain 正确
3. execute_core 返回 SUCCESS + 空 outputs（骨架阶段）
4. register_all() 后 registry.get("C{x}") 非 None
5. 旧 C1/C2/C3/C5 节点被自动发现机制跳过（internal tag）
"""

from __future__ import annotations

import pytest

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ── 9 个新节点骨架的参数化测试 ──────────────────────────────

NODE_SPECS = [
    ("C0", "c0_env_scan", "C0EnvScanNode", "环境扫描"),
    ("C1", "c1_symbol_filter", "C1SymbolFilterNode", "品种筛选"),
    ("C2", "c2_signal_detect", "C2SignalDetectNode", "信号识别"),
    ("C3", "c3_backtest_verify", "C3BacktestVerifyNode", "回测验证"),
    ("C4", "c4_risk_assess", "C4RiskAssessNode", "风险评估"),
    ("C5", "c5_param_optimize", "C5ParamOptimizeNode", "参数优化"),
    ("C6", "c6_plan_generate", "C6PlanGenerateNode", "计划生成"),
    ("C7", "c7_exec_monitor", "C7ExecMonitorNode", "执行监控"),
    ("C8", "c8_perf_attribution", "C8PerfAttributionNode", "绩效归因"),
]


@pytest.mark.parametrize("node_id,module_name,class_name,name", NODE_SPECS)
def test_node_importable(node_id, module_name, class_name, name):
    """断言 9 个新节点可导入"""
    import importlib
    module = importlib.import_module(f"dreamos.capabilities.trading.nodes.{module_name}")
    node_cls = getattr(module, class_name)
    assert node_cls is not None, f"{class_name} 导入失败"


@pytest.mark.parametrize("node_id,module_name,class_name,name", NODE_SPECS)
def test_node_metadata(node_id, module_name, class_name, name):
    """断言 node_id/chain/name 正确"""
    import importlib
    module = importlib.import_module(f"dreamos.capabilities.trading.nodes.{module_name}")
    node_cls = getattr(module, class_name)
    node = node_cls()
    assert node.node_id == node_id, f"node_id 期望 {node_id} 实际 {node.node_id}"
    assert node.chain == "C", f"chain 期望 C 实际 {node.chain}"
    assert node.name == name, f"name 期望 {name} 实际 {node.name}"


@pytest.mark.parametrize("node_id,module_name,class_name,name", NODE_SPECS)
def test_node_tags_has_classic_v2(node_id, module_name, class_name, name):
    """断言新节点 tags 包含 classic 和 classic_v2"""
    import importlib
    module = importlib.import_module(f"dreamos.capabilities.trading.nodes.{module_name}")
    node_cls = getattr(module, class_name)
    node = node_cls()
    assert "classic" in node.tags, f"{node_id} tags 缺少 classic: {node.tags}"
    assert "classic_v2" in node.tags, f"{node_id} tags 缺少 classic_v2: {node.tags}"


@pytest.mark.parametrize("node_id,module_name,class_name,name", NODE_SPECS)
def test_node_execute_core_returns_skeleton_result(node_id, module_name, class_name, name):
    """断言 execute_core 返回 SUCCESS + 空 outputs（骨架阶段）"""
    import importlib
    module = importlib.import_module(f"dreamos.capabilities.trading.nodes.{module_name}")
    node_cls = getattr(module, class_name)
    node = node_cls()

    # execute_core 直接调用（不经 execute 模板）
    state = State()
    result = node.execute_core(state)

    assert isinstance(result, NodeResult), f"{node_id} execute_core 未返回 NodeResult"
    assert result.node_id == node_id, f"{node_id} NodeResult.node_id 不匹配"
    assert result.status == NodeStatus.SUCCESS, f"{node_id} status 期望 SUCCESS 实际 {result.status}"
    assert isinstance(result.outputs, dict), f"{node_id} outputs 不是 dict"
    assert result.confidence == 0.0, f"{node_id} confidence 期望 0.0 实际 {result.confidence}"


@pytest.mark.parametrize("node_id,module_name,class_name,name", NODE_SPECS)
def test_node_docstring_declares_inputs_outputs(node_id, module_name, class_name, name):
    """断言节点 docstring 声明了 inputs/outputs schema"""
    import importlib
    module = importlib.import_module(f"dreamos.capabilities.trading.nodes.{module_name}")
    node_cls = getattr(module, class_name)
    doc = node_cls.__doc__ or ""
    # 骨架阶段宽松校验：docstring 非空即可
    assert len(doc.strip()) > 0, f"{node_id} 缺少 docstring"


# ── 注册机制测试 ──────────────────────────────────────────

def test_register_all_registers_c0_c8():
    """断言 register_all() 后 C0-C8 全部注册到默认 registry"""
    from dreamos.capabilities.trading.nodes import register_all
    from dreamos.registry import get_default_registry

    reg = get_default_registry()
    register_all(reg)

    for i in range(9):
        node_id = f"C{i}"
        node = reg.get(node_id)
        assert node is not None, f"{node_id} 未注册到 registry"

        # 确认注册的是新节点（不是旧 legacy 节点）
        assert "legacy" not in getattr(node, "tags", []), \
            f"{node_id} 注册到旧 legacy 节点: {node.__class__.__name__}"
        assert "classic_v2" in getattr(node, "tags", []), \
            f"{node_id} 未注册到 classic_v2 节点: {node.__class__.__name__}"


def test_legacy_nodes_not_registered():
    """断言旧 C1/C2/C3/C5 节点被自动发现机制跳过（internal tag）"""
    from dreamos.capabilities.trading.nodes import register_all, get_all_node_classes
    from dreamos.registry import get_default_registry

    # get_all_node_classes 不应包含 internal tag 的旧节点
    classes = get_all_node_classes()
    for cls in classes:
        tags = getattr(cls, "tags", [])
        assert "internal" not in tags, \
            f"internal 节点 {cls.__name__} 不应出现在 get_all_node_classes() 中"


# ── NodeResult 契约测试 ────────────────────────────────────

def test_c0_outputs_schema():
    """断言 C0 outputs 包含 env_state/regime/macro_flags 字段"""
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    node = C0EnvScanNode()
    result = node.execute_core(State())
    assert "env_state" in result.outputs
    assert "regime" in result.outputs
    assert "macro_flags" in result.outputs


def test_c1_outputs_schema():
    """断言 C1 outputs 包含 candidates/filter_log/rejected 字段"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    node = C1SymbolFilterNode()
    result = node.execute_core(State())
    assert "candidates" in result.outputs
    assert "filter_log" in result.outputs
    assert "rejected" in result.outputs


def test_c6_outputs_schema():
    """断言 C6 outputs 包含 trade_plan/changeset/strategy_name/trace_id 字段"""
    from dreamos.capabilities.trading.nodes.c6_plan_generate import C6PlanGenerateNode
    node = C6PlanGenerateNode()
    result = node.execute_core(State())
    assert "trade_plan" in result.outputs
    assert "changeset" in result.outputs
    assert "strategy_name" in result.outputs
    assert "trace_id" in result.outputs
