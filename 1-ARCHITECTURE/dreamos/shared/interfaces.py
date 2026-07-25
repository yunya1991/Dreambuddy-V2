"""
Dreambuddy OS — 核心接口定义

五大核心抽象:
    1. State      — 全局状态 (见 state.py)
    2. Node       — 节点接口 (最小执行单元)
    3. Graph      — 执行图 (节点 + 边)
    4. Registry   — 注册表接口
    5. Adapter    — 适配器接口

设计原则:
    - 接口优于实现: 所有抽象都是 Protocol/ABC，可有多套实现
    - 单一职责: 每个接口只做一件事
    - 可替换: 实现可替换，不影响上层
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Iterable
from dataclasses import dataclass, field

from .state import State, NodeResult, NodeStatus


# ============================================================
# 1. Node 节点接口
# ============================================================

class Node(ABC):
    """节点接口 — 最小执行单元的统一抽象

    所有可执行单元（A0-A9节点、技术指标、基本面分析、外部 API 等）
    都实现此接口。节点读取 State，返回 NodeResult。

    实现方式:
        class MyNode(Node):
            node_id = "A0_矛盾论"
            name = "A0 矛盾论分析"
            chain = "A"

            def execute(self, state: State) -> NodeResult:
                # 读取 state.market / state.intent ...
                # 执行分析
                return NodeResult(
                    node_id=self.node_id,
                    confidence=0.72,
                    direction="LONG",
                    outputs={"conflict_count": 3, ...},
                )

    生命周期:
        1. validate(state)  — 校验输入
        2. execute(state)   — 执行
        3. (失败时) fallback(state) — 降级
    """

    # ── 元信息（子类重写） ──────────────────────────────
    node_id: str = ""
    name: str = ""
    description: str = ""
    chain: str = ""                # A / C / F / G / T
    tags: List[str] = []

    # ── 资源与优先级元信息 ──────────────────────────────
    required_tokens: int = 0       # 文档标准字段：预计消耗 token
    priority: int = 0              # 文档标准字段：节点优先级（越大越高）
    estimated_latency_ms: int = 0

    # ── 兼容别名（旧代码可继续用） ─────────────────────
    @property
    def estimated_tokens(self) -> int:
        return self.required_tokens

    @estimated_tokens.setter
    def estimated_tokens(self, val: int) -> None:
        self.required_tokens = val

    # ── 核心方法 ────────────────────────────────────────

    @abstractmethod
    def execute(self, state: State) -> NodeResult:
        """执行节点

        Args:
            state: 当前全局状态

        Returns:
            NodeResult: 执行结果，框架会合并到 state
        """
        ...

    # ── 可选方法（子类可重写） ──────────────────────────

    def validate(self, state: State) -> Optional[str]:
        """校验输入是否满足

        Returns:
            None 表示通过，否则返回错误信息
        """
        return None

    def fallback(self, state: State) -> NodeResult:
        """降级执行（默认标记为 DEGRADED，子类可重写）"""
        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.DEGRADED,
            confidence=0.0,
            error=f"{self.node_id} 降级执行（无具体实现）",
        )

    def __repr__(self) -> str:
        return f"<Node {self.node_id} [{self.chain}]>"


# ============================================================
# 2. Graph 图接口
# ============================================================

@dataclass
class Edge:
    """图的边 — 定义节点间的跳转关系

    支持条件边:
        edge = Edge(source="A0", target="A1", condition=lambda s: s.get_confidence("A0") > 0.6)
    """
    source: str                                            # 源节点 ID
    target: str                                            # 目标节点 ID
    condition: Optional[Callable[[State], bool]] = None    # 条件 (None=无条件)
    label: str = ""                                        # 标签（调试用）


class Graph(ABC):
    """执行图接口 — 定义节点的执行流程

    实现可参考:
        - SequentialGraph: 顺序执行
        - DAGGraph: 有向无环图（支持并行）
        - ConditionalGraph: 条件跳转
    """

    @abstractmethod
    def add_node(self, node: Node) -> "Graph":
        """添加节点（链式）"""
        ...

    @abstractmethod
    def add_edge(self, source: str, target: str,
                 condition: Optional[Callable[[State], bool]] = None,
                 label: str = "") -> "Graph":
        """添加边（链式）"""
        ...

    @abstractmethod
    def get_entry(self) -> Optional[Node]:
        """获取入口节点"""
        ...

    @abstractmethod
    def get_next(self, current_id: str, state: State) -> Optional[Node]:
        """根据当前节点和状态，获取下一个要执行的节点"""
        ...

    @abstractmethod
    def topological_order(self) -> List[str]:
        """拓扑排序（用于顺序执行）"""
        ...

    @abstractmethod
    def all_nodes(self) -> List[Node]:
        """所有节点"""
        ...

    def get_node(self, node_id: str) -> Optional[Node]:
        """根据 ID 获取节点（默认实现，子类可重写）"""
        for n in self.all_nodes():
            if n.node_id == node_id:
                return n
        return None

    def insert_before(self, before_node_id: str, new_node: Node) -> bool:
        """在指定节点前插入新节点

        Args:
            before_node_id: 插入位置（在此节点之前）
            new_node: 要插入的新节点

        Returns:
            True 插入成功，False 失败（如 before_node_id 不存在）
        """
        return False


# ============================================================
# 3. Registry 注册表接口
# ============================================================

class Registry(ABC):
    """注册表接口 — 节点/能力的唯一真相源

    职责:
        - 注册节点
        - 按 ID / chain / tag 查询
        - 支持动态注册和注销
    """

    @abstractmethod
    def register(self, node: Node) -> None:
        """注册节点"""
        ...

    @abstractmethod
    def get(self, node_id: str) -> Optional[Node]:
        """按 ID 获取节点"""
        ...

    @abstractmethod
    def list_nodes(self, chain: Optional[str] = None,
                   tag: Optional[str] = None) -> List[Node]:
        """列出节点（可过滤）"""
        ...

    @abstractmethod
    def unregister(self, node_id: str) -> bool:
        """注销节点"""
        ...

    @abstractmethod
    def exists(self, node_id: str) -> bool:
        """节点是否存在"""
        ...


# ============================================================
# 4. Adapter 适配器接口
# ============================================================

class Adapter(ABC):
    """适配器接口 — 外部能力接入 OS 的标准接口

    适配器将不同类型的能力（SKILL / API / 本地函数）包装成 Node，
    使 OS 内核无需关心能力的具体实现方式。

    适配器类型:
        - SkillAdapter:   将 6-TRADING/skills/ 下的 SKILL 包装为 Node
        - APIAdapter:     将外部 HTTP API 包装为 Node
        - FunctionAdapter: 将本地 Python 函数包装为 Node
    """

    @abstractmethod
    def to_node(self, config: Dict[str, Any]) -> Node:
        """将外部能力配置转换为 Node

        Args:
            config: 能力配置 (type / path / endpoint / handler / ...)

        Returns:
            Node: 包装后的节点
        """
        ...

    @abstractmethod
    def can_handle(self, config: Dict[str, Any]) -> bool:
        """是否能处理此配置"""
        ...
