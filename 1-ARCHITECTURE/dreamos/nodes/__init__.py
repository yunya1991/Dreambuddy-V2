"""
DreamOS Nodes — 交易业务节点包 (向后兼容层)

⚠️ 重要: 此包已迁移到 dreamos.capabilities.trading.nodes
    保留此包仅用于向后兼容，新代码请使用新路径。

迁移路径:
    from dreamos.nodes import register_all
    → from dreamos.capabilities.trading.nodes import register_all

    from dreamos.nodes.a4_gate import A4GateNode
    → from dreamos.capabilities.trading.nodes.a4_gate import A4GateNode
"""

from __future__ import annotations

# 从新位置重新导出所有公开 API
from dreamos.capabilities.trading.nodes import (
    register_all,
    register_node,
    list_available_nodes,
    get_all_node_classes,
    # A 链节点
    A0ContradictionNode,
    A1DeepResearchNode,
    A2ComprehensiveNode,
    A3StrategyNode,
    A4GateNode,
    A5ExecutionNode,
    A6RegimeMonitorNode,
    A7PracticeGateNode,
    A8UnityNode,
    A9ExitStrategyNode,
    # C 链节点
    C1TechScanNode,
    C2MomentumNode,
    C3VolatilityNode,
    C5ExitSystemNode,
    # F 链节点
    F1NewsSentimentNode,
    F2FlowAnalysisNode,
    F3ValuationNode,
    F4OnchainDataNode,
    F5MacroAnalysisNode,
    # G 链节点
    G1RiskControlNode,
    G2GovernanceNode,
)

__all__ = [
    "register_all",
    "register_node",
    "list_available_nodes",
    "get_all_node_classes",
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
    "C1TechScanNode",
    "C2MomentumNode",
    "C3VolatilityNode",
    "C5ExitSystemNode",
    "F1NewsSentimentNode",
    "F2FlowAnalysisNode",
    "F3ValuationNode",
    "F4OnchainDataNode",
    "F5MacroAnalysisNode",
    "G1RiskControlNode",
    "G2GovernanceNode",
]
