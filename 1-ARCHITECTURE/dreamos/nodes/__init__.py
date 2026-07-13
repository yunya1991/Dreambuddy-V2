"""
DreamOS Trading Nodes — 交易业务节点包

基于 Dreambuddy OS 内核的真实业务节点实现。

设计原则:
    - 节点是动态发现、按需加载的，不在 __init__ 中硬编码列表
    - 每个节点继承 BaseNode，实现 execute_core()
    - 支持三种注册方式:
        1) 自动扫描: register_all() 自动发现本包所有 BaseNode 子类
        2) 装饰器: @register_node 自动注册
        3) 显式注册: registry.register(MyNode())
    - 从 state.market_data 读取市场数据
    - 返回 direction / confidence / rationale
    - 纯本地计算，零外部依赖，保证可测试

用法:
    # 自动扫描并注册所有节点
    from dreamos.nodes import register_all
    count = register_all()

    # 或用装饰器定义新节点（自动注册）
    from dreamos.nodes import register_node

    @register_node
    class MyCustomNode(BaseNode):
        node_id = "X1"
        name = "自定义节点"
        chain = "X"
        def execute_core(self, state):
            return NodeResult(node_id="X1", confidence=0.5)
"""

from __future__ import annotations

import importlib
import inspect
import os
from typing import List, Type, Optional

from dreamos.registry.base import BaseNode
from dreamos.registry.decorators import register_node  # 重新导出装饰器


# 重新导出已实现的节点（供显式导入使用）
# 这些导入是可选的——节点会通过动态扫描自动发现

def _discover_nodes(package_dir: Optional[str] = None) -> List[Type[BaseNode]]:
    """动态发现包目录下的所有 BaseNode 子类

    扫描规则:
        - 扫描当前包目录下所有 .py 文件（排除 __init__.py 和 _ 开头）
        - 导入模块并查找 BaseNode 的子类
        - 排除 BaseNode 本身和抽象类

    Returns:
        发现的节点类列表
    """
    if package_dir is None:
        package_dir = os.path.dirname(os.path.abspath(__file__))

    node_classes: List[Type[BaseNode]] = []
    package_name = "dreamos.nodes"

    for filename in sorted(os.listdir(package_dir)):
        if not filename.endswith(".py"):
            continue
        if filename.startswith("_"):
            continue
        if filename == "__init__.py":
            continue

        module_name = filename[:-3]  # 去掉 .py
        full_module = f"{package_name}.{module_name}"

        try:
            module = importlib.import_module(full_module)
        except Exception as e:
            # 导入失败则跳过（可能是依赖未安装）
            continue

        # 查找模块中所有 BaseNode 的子类
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BaseNode:
                continue
            if not issubclass(obj, BaseNode):
                continue
            # 排除抽象类（没有实现 execute_core 的）
            if getattr(obj, "__abstractmethods__", None):
                continue
            # 确保有合法的 node_id
            if not getattr(obj, "node_id", None):
                continue
            # 排除内部方法论节点 (如 A0, tags 含 "internal")
            tags = getattr(obj, "tags", [])
            if isinstance(tags, (list, tuple)) and "internal" in tags:
                continue
            if obj not in node_classes:
                node_classes.append(obj)

    return node_classes


# 动态发现（延迟加载，避免循环导入）
_ALL_NODE_CLASSES: Optional[List[Type[BaseNode]]] = None


def get_all_node_classes() -> List[Type[BaseNode]]:
    """获取所有发现的节点类（带缓存）"""
    global _ALL_NODE_CLASSES
    if _ALL_NODE_CLASSES is None:
        _ALL_NODE_CLASSES = _discover_nodes()
    return _ALL_NODE_CLASSES


def register_all(registry=None, *,
                 auto_discover: bool = True,
                 extra_nodes: Optional[List[Type[BaseNode]]] = None) -> int:
    """注册业务节点到注册表

    Args:
        registry: 目标注册表，None 则用默认
        auto_discover: 是否自动扫描包目录发现节点（默认 True）
        extra_nodes: 额外的节点类列表（用于手动补充）

    Returns:
        注册的节点数量
    """
    from dreamos.registry import get_default_registry
    reg = registry if registry is not None else get_default_registry()

    count = 0
    registered_ids = set()

    # 1. 自动发现节点
    if auto_discover:
        for node_cls in get_all_node_classes():
            try:
                instance = node_cls()
                if instance.node_id in registered_ids:
                    continue
                reg.register(instance)
                registered_ids.add(instance.node_id)
                count += 1
            except Exception:
                pass  # 已存在或其他错误则跳过

    # 2. 注册额外节点
    if extra_nodes:
        for node_cls in extra_nodes:
            try:
                instance = node_cls()
                if instance.node_id in registered_ids:
                    continue
                reg.register(instance)
                registered_ids.add(instance.node_id)
                count += 1
            except Exception:
                pass

    return count


def list_available_nodes() -> List[dict]:
    """列出所有可用的节点（不注册，仅发现）

    Returns:
        节点信息字典列表
    """
    return [
        {
            "node_id": cls.node_id,
            "name": getattr(cls, "name", ""),
            "chain": getattr(cls, "chain", ""),
            "description": getattr(cls, "description", ""),
            "class": cls.__name__,
            "module": cls.__module__,
        }
        for cls in get_all_node_classes()
    ]


# 显式导入已实现的节点（向后兼容）
# 使用 try/except 避免循环导入或导入错误

try:
    from .c1_tech_scan import C1TechScanNode
except Exception:
    C1TechScanNode = None  # type: ignore[misc,assignment]

try:
    from .a0_contradiction import A0ContradictionNode
except Exception:
    A0ContradictionNode = None  # type: ignore[misc,assignment]

try:
    from .a1_deep_research import A1DeepResearchNode
except Exception:
    A1DeepResearchNode = None  # type: ignore[misc,assignment]

try:
    from .a2_comprehensive import A2ComprehensiveNode
except Exception:
    A2ComprehensiveNode = None  # type: ignore[misc,assignment]



try:
    from .a3_strategy import A3StrategyNode
except Exception:
    A3StrategyNode = None  # type: ignore[misc,assignment]

try:
    from .a4_gate import A4GateNode
except Exception:
    A4GateNode = None  # type: ignore[misc,assignment]

try:
    from .a5_execution import A5ExecutionNode
except Exception:
    A5ExecutionNode = None  # type: ignore[misc,assignment]

try:
    from .a6_regime_monitor import A6RegimeMonitorNode
except Exception:
    A6RegimeMonitorNode = None  # type: ignore[misc,assignment]

try:
    from .a9_exit_strategy import A9ExitStrategyNode
except Exception:
    A9ExitStrategyNode = None  # type: ignore[misc,assignment]

try:
    from .c2_momentum import C2MomentumNode
except Exception:
    C2MomentumNode = None  # type: ignore[misc,assignment]

try:
    from .c3_volatility import C3VolatilityNode
except Exception:
    C3VolatilityNode = None  # type: ignore[misc,assignment]

try:
    from .f1_news import F1NewsSentimentNode
except Exception:
    F1NewsSentimentNode = None  # type: ignore[misc,assignment]



try:
    from .c5_exit_system import C5ExitSystemNode
except Exception:
    C5ExitSystemNode = None  # type: ignore[misc,assignment]

try:
    from .f2_flow_analysis import F2FlowAnalysisNode
except Exception:
    F2FlowAnalysisNode = None  # type: ignore[misc,assignment]

try:
    from .f3_valuation import F3ValuationNode
except Exception:
    F3ValuationNode = None  # type: ignore[misc,assignment]

try:
    from .f4_onchain_data import F4OnchainDataNode
except Exception:
    F4OnchainDataNode = None  # type: ignore[misc,assignment]

try:
    from .f5_macro_analysis import F5MacroAnalysisNode
except Exception:
    F5MacroAnalysisNode = None  # type: ignore[misc,assignment]

try:
    from .g1_risk_control import G1RiskControlNode
except Exception:
    G1RiskControlNode = None  # type: ignore[misc,assignment]

try:
    from .g2_governance import G2GovernanceNode
except Exception:
    G2GovernanceNode = None  # type: ignore[misc,assignment]

try:
    from .a7_practice_gate import A7PracticeGateNode
except Exception:
    A7PracticeGateNode = None  # type: ignore[misc,assignment]

try:
    from .a8_unity import A8UnityNode
except Exception:
    A8UnityNode = None  # type: ignore[misc,assignment]


__all__ = [
    # 动态注册
    "register_all",
    "register_node",
    "list_available_nodes",
    "get_all_node_classes",
    # A 链节点
    "A0ContradictionNode",
    "A1DeepResearchNode",
    "A2ComprehensiveNode",
    "A3StrategyNode",
    "A4GateNode",
    "A5ExecutionNode",
    "A6RegimeMonitorNode",
    "A7PracticeGateNode",
    "A8UnityNode",
    "A9ExitStrategyNode",
    # C 链节点
    "C1TechScanNode",
    "C2MomentumNode",
    "C3VolatilityNode",
    "C5ExitSystemNode",
    # F 链节点
    "F1NewsSentimentNode",
    "F2FlowAnalysisNode",
    "F3ValuationNode",
    "F4OnchainDataNode",
    "F5MacroAnalysisNode",
    # G 链节点
    "G1RiskControlNode",
    "G2GovernanceNode",
]
