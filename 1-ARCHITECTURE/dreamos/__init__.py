"""
Dreambuddy OS — AI 驱动操作系统内核

Dreambuddy OS 是意图驱动的 AI 操作系统内核，管理:
    - 意图进程 (Intent Process)
    - 能力模块 (Capability Modules)
    - 记忆资源 (Memory Resources)
    - 治理约束 (Governance Constraints)

核心原则: 纯编排层，不重复建设能力——通过调用已有 SKILL / API / 本地函数完成工作。

SACG 四层架构:
    S层 Sense      — 感知/意图识别
    A层 Arrange    — 图编排
    C层 Compute    — 执行
    G层 GraphStore — 图存储

横切关注点:
    - registry:   节点注册表（唯一真相源）
    - adapters:   适配器框架（SKILL/API/Function → Node）
    - evolution:  自我进化
    - budget:     预算管理

快速上手:
    from os import State, NodeResult, Node, BaseNode, NodeRegistry

    registry = NodeRegistry()

    class A0Node(BaseNode):
        node_id = "A0"
        name = "矛盾论分析"
        chain = "A"

        def execute_core(self, state: State) -> NodeResult:
            return NodeResult(node_id="A0", confidence=0.7, direction="LONG")

    registry.register(A0Node())

    # 执行
    state = State()
    result = registry.get("A0").execute(state)
    state.update("A0", result)

版本: v2.0.0
"""

__version__ = "2.4.0"

# ── shared 层: 核心抽象 ─────────────────────────────
from .shared.state import State, NodeResult, NodeStatus, new_state
from .shared.interfaces import Node, Graph, Edge, Registry, Adapter
from .shared.errors import ErrorCode, OSError
from .shared.llm_client import (
    LLMClient, LLMMessage, LLMResponse,
    get_default_client, set_default_client, make_messages,
)
from .shared.utils import (
    Timer, timed, gen_cycle_id, gen_session_id,
    safe_json, safe_get, retry, chunk, dedupe,
)

# ── registry 层: 节点管理 ───────────────────────────
from .registry.base import BaseNode
from .registry.node_registry import (
    NodeRegistry, get_default_registry, set_default_registry,
)
from .registry.decorators import register_node, node_metadata

# ── adapters 层: 适配器框架 ─────────────────────────
from .adapters.base import BaseAdapter, AdapterRegistry, get_default_adapter_registry
from .adapters.function_adapter import FunctionAdapter, FunctionNode
from .adapters.skill_adapter import SkillAdapter, SkillNode, parse_skill_metadata
from .adapters.api_adapter import APIAdapter, APINode

# ── core 四层（占位，P1-P4 实现） ───────────────────
from .core import sense, arrange, compute, graph_store

# ── 能力域层 ────────────────────────────────────────
from . import capabilities

# ── 横切关注点（占位，P6 实现） ─────────────────────
from . import evolution, budget
from . import apps

__all__ = [
    # 版本
    "__version__",
    # shared - state
    "State", "NodeResult", "NodeStatus", "new_state",
    # shared - interfaces
    "Node", "Graph", "Edge", "Registry", "Adapter",
    # shared - errors
    "ErrorCode", "OSError",
    # shared - llm
    "LLMClient", "LLMMessage", "LLMResponse",
    "get_default_client", "set_default_client", "make_messages",
    # shared - utils
    "Timer", "timed", "gen_cycle_id", "gen_session_id",
    "safe_json", "safe_get", "retry", "chunk", "dedupe",
    # registry
    "BaseNode", "NodeRegistry", "register_node", "node_metadata",
    "get_default_registry", "set_default_registry",
    # adapters
    "BaseAdapter", "AdapterRegistry", "get_default_adapter_registry",
    "FunctionAdapter", "FunctionNode",
    "SkillAdapter", "SkillNode", "parse_skill_metadata",
    "APIAdapter", "APINode",
    # core layers
    "sense", "arrange", "compute", "graph_store",
    # capability layers
    "capabilities",
    # cross-cutting
    "evolution", "budget", "apps",
]
