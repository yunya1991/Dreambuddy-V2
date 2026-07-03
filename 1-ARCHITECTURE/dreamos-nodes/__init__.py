"""
Dreambuddy OS — Nodes 节点库

OS 节点的具体实现，按域组织:
    - a_domain/  AI 交易节点 (A0-A9 + 做梦部)
    - c_domain/  经典量化节点 (C1-C2)
    - f_domain/  基本面节点 (F1-F3)

每个节点都是 BaseNode 的子类，通过 register_node 装饰器注册。

P0 状态: 占位，P5 阶段实现
"""

# P5 阶段将导入:
# from .a_domain import A0Node, A1Node, ..., A9Node
# from .c_domain import C1Node, C2Node
# from .f_domain import F1Node, F2Node, F3Node
