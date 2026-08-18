"""
DreamOS A层 — 执行图实现

提供 Graph 接口的具体实现:
    - SequentialGraph: 顺序执行图（默认）
    - ConditionalGraph: 条件执行图（支持节点间条件跳转）
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional
from collections import OrderedDict

from dreamos.shared.interfaces import Node, Graph, Edge
from dreamos.shared.state import State


# ============================================================
# 顺序执行图
# ============================================================

class SequentialGraph(Graph):
    """顺序执行图 — 按添加顺序执行节点

    最简单的 Graph 实现:
        graph = SequentialGraph()
        graph.add_node(node_a).add_node(node_b).add_node(node_c)
        # 执行顺序: A → B → C

    支持条件跳转:
        graph.add_edge("A", "C", condition=lambda s: s.get_confidence("A") > 0.8)
        # A 置信度 > 0.8 时跳过 B 直接到 C
    """

    def __init__(self):
        self._nodes: OrderedDict[str, Node] = OrderedDict()
        self._edges: List[Edge] = []
        self._entry_id: Optional[str] = None

    def add_node(self, node: Node) -> "SequentialGraph":
        if not node.node_id:
            raise ValueError("节点 node_id 不能为空")
        self._nodes[node.node_id] = node
        if self._entry_id is None:
            self._entry_id = node.node_id
        return self

    def add_edge(self, source: str, target: str,
                 condition: Optional[Callable[[State], bool]] = None,
                 label: str = "") -> "SequentialGraph":
        self._edges.append(Edge(source=source, target=target,
                                condition=condition, label=label))
        return self

    def get_entry(self) -> Optional[Node]:
        if self._entry_id:
            return self._nodes.get(self._entry_id)
        return None

    def get_next(self, current_id: str, state: State) -> Optional[Node]:
        """获取下一个节点

        优先检查条件边:
            - 如果有从 current_id 出发的条件边，且条件满足，跳转到 target
            - 否则按顺序取下一个节点
        """
        # 检查条件边
        for edge in self._edges:
            if edge.source != current_id:
                continue
            if edge.condition is None:
                # 无条件跳转
                if edge.target in self._nodes:
                    return self._nodes[edge.target]
            else:
                try:
                    if edge.condition(state) and edge.target in self._nodes:
                        return self._nodes[edge.target]
                except Exception:
                    pass

        # 顺序取下一个
        keys = list(self._nodes.keys())
        if current_id in keys:
            idx = keys.index(current_id)
            if idx + 1 < len(keys):
                return self._nodes[keys[idx + 1]]
        return None

    def topological_order(self) -> List[str]:
        """拓扑排序（顺序图就是添加顺序）"""
        return list(self._nodes.keys())

    def all_nodes(self) -> List[Node]:
        return list(self._nodes.values())

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    def insert_before(self, before_node_id: str, new_node: Node) -> bool:
        """在指定节点前插入新节点（保持顺序）

        如果 before_node_id 不存在，返回 False。
        插入后，新节点位于 before_node_id 之前。
        """
        if not new_node.node_id:
            return False
        if before_node_id not in self._nodes:
            return False
        if new_node.node_id in self._nodes:
            return False

        keys = list(self._nodes.keys())
        idx = keys.index(before_node_id)

        new_ordered = OrderedDict()
        for i, k in enumerate(keys):
            if i == idx:
                new_ordered[new_node.node_id] = new_node
            new_ordered[k] = self._nodes[k]

        self._nodes = new_ordered

        if idx == 0:
            self._entry_id = new_node.node_id

        return True

    def __len__(self) -> int:
        return len(self._nodes)

    def __repr__(self) -> str:
        return f"<SequentialGraph nodes={list(self._nodes.keys())}>"


# ============================================================
# 条件执行图
# ============================================================

class ConditionalGraph(Graph):
    """条件执行图 — 支持复杂的条件跳转

    节点间通过边连接，支持:
        - 无条件边: A → B (总是执行 B)
        - 条件边: A → B (when state.confidence > 0.6)
        - 多出边: A 有多个条件边，第一个满足的生效

    用法:
        graph = ConditionalGraph()
        graph.add_node(node_a)
        graph.add_node(node_b)
        graph.add_node(node_c)
        graph.add_edge("A", "B", condition=lambda s: s.get_confidence("A") < 0.5, label="低置信度→B")
        graph.add_edge("A", "C", condition=lambda s: s.get_confidence("A") >= 0.5, label="高置信度→C")
    """

    def __init__(self, entry_id: Optional[str] = None):
        self._nodes: Dict[str, Node] = {}
        self._edges: List[Edge] = []
        self._entry_id = entry_id
        self._default_next: Dict[str, str] = {}  # 无条件默认下一个

    def add_node(self, node: Node) -> "ConditionalGraph":
        if not node.node_id:
            raise ValueError("节点 node_id 不能为空")
        self._nodes[node.node_id] = node
        if self._entry_id is None:
            self._entry_id = node.node_id
        return self

    def add_edge(self, source: str, target: str,
                 condition: Optional[Callable[[State], bool]] = None,
                 label: str = "") -> "ConditionalGraph":
        if condition is None:
            self._default_next[source] = target
        self._edges.append(Edge(source=source, target=target,
                                condition=condition, label=label))
        return self

    def get_entry(self) -> Optional[Node]:
        if self._entry_id:
            return self._nodes.get(self._entry_id)
        return None

    def get_next(self, current_id: str, state: State) -> Optional[Node]:
        """获取下一个节点

        优先级:
            1. 检查条件边（按添加顺序），第一个满足的生效
            2. 无条件默认边
            3. None（结束）
        """
        # 检查条件边
        for edge in self._edges:
            if edge.source != current_id:
                continue
            if edge.condition is None:
                continue
            try:
                if edge.condition(state) and edge.target in self._nodes:
                    return self._nodes[edge.target]
            except Exception:
                pass

        # 无条件默认边
        default_target = self._default_next.get(current_id)
        if default_target and default_target in self._nodes:
            return self._nodes[default_target]

        return None

    def topological_order(self) -> List[str]:
        """拓扑排序（BFS 从入口开始）"""
        if not self._entry_id:
            return []
        visited = []
        queue = [self._entry_id]
        seen = set()
        while queue:
            nid = queue.pop(0)
            if nid in seen or nid not in self._nodes:
                continue
            seen.add(nid)
            visited.append(nid)
            # 找所有出边
            for edge in self._edges:
                if edge.source == nid and edge.target not in seen:
                    queue.append(edge.target)
            if self._default_next.get(nid) and self._default_next[nid] not in seen:
                queue.append(self._default_next[nid])
        return visited

    def all_nodes(self) -> List[Node]:
        return list(self._nodes.values())

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    def insert_before(self, before_node_id: str, new_node: Node) -> bool:
        """在指定节点前插入新节点

        对于 ConditionalGraph，插入逻辑：
        1. 添加新节点
        2. 将所有指向 before_node_id 的入边改指向新节点
        3. 添加新节点 → before_node_id 的默认边
        """
        if not new_node.node_id:
            return False
        if before_node_id not in self._nodes:
            return False
        if new_node.node_id in self._nodes:
            return False

        self._nodes[new_node.node_id] = new_node

        # 重定向所有入边和默认路径
        new_edges = []
        for edge in self._edges:
            if edge.target == before_node_id:
                new_edges.append(Edge(
                    source=edge.source,
                    target=new_node.node_id,
                    condition=edge.condition,
                    label=edge.label,
                ))
            else:
                new_edges.append(edge)

        # 重定向 _default_next 中指向 before_node_id 的条目
        for src, tgt in list(self._default_next.items()):
            if tgt == before_node_id:
                self._default_next[src] = new_node.node_id

        # 添加新节点 → before_node_id 的默认边
        new_edges.append(Edge(
            source=new_node.node_id,
            target=before_node_id,
            condition=None,
            label="insert_before_default",
        ))
        self._default_next[new_node.node_id] = before_node_id

        self._edges = new_edges

        # 如果 before_node_id 是入口，更新入口
        if self._entry_id == before_node_id:
            self._entry_id = new_node.node_id

        return True

    def __len__(self) -> int:
        return len(self._nodes)

    def __repr__(self) -> str:
        return f"<ConditionalGraph nodes={len(self._nodes)} edges={len(self._edges)}>"
