"""
Dreambuddy OS 节点模块

每个节点独立实现，支持 Trae 直接调用和 SKILL.md 规范调用

设计原则:
- 调用的不重复建设：优先调用已有模块/SKILL，不重新实现
- 高度模块化：每个节点独立，支持图架构动态编排
- 统一接口：所有节点遵循相同的 (mkt, memory, data) → result 协议
- 降级容错：外部依赖不可用时自动降级到本地规则

架构层次:
  粗粒度: 链 (A/C/F/G/T)
  中粒度: 模块 (module_id)
  细粒度: 节点 (node_id) — 实际执行单元

节点分类:
- C 链（技术/量化层）: C1_技术扫描, C2_Regime识别, ...
- A 链（分析/决策层）: A0_矛盾论, A1_调研, A2_分析, A3_策略, A4_门禁, A9_离场
- F 链（基本面层）: F1_新闻, F2_资金流, F3_情绪, F5_宏观
- 其他: 做梦部（潜意识层）
"""

from .node_registry import (
    NodeRegistry,
    NodeInfo,
    IOSchema,
    NodeRetryPolicy,
    NodeFallbackPolicy,
    get_node_registry,
    register_node,
    get_node,
    get_node_handler,
)

from .node_definitions import (
    get_all_node_definitions,
    LEGACY_TO_NEW_ID,
    NEW_TO_LEGACY_ID,
    map_legacy_id,
    map_new_id,
)

from .c1_tech_scan import execute as c1_execute
from .a0_contradiction import execute as a0_execute
from .a1_research import execute as a1_execute
from .a2_analysis import execute as a2_execute
from .a9_exit import execute as a9_execute
from .a4_gate import execute as a4_execute
from .a3_strategy import execute as a3_execute
from .f1_news import execute as f1_execute
from .f2_fund_flow import execute as f2_execute
from .f3_sentiment import execute as f3_execute
from .oneirology import execute as oneirology_execute


# ============================================================
# 执行函数映射（旧版 NODE_HANDLERS，保留向后兼容）
# ============================================================

_NODE_EXECUTORS = {
    "classic-indicator-scan": c1_execute,
    "dream-contradiction-theory": a0_execute,
    "dream-research-v2": a1_execute,
    "dream-first-principles": a2_execute,
    "dream-strategy-engine": a3_execute,
    "dream-gate-v2": a4_execute,
    "dream-exit-skill-v2": a9_execute,
    "fundamental-news-analysis": f1_execute,
    "fundamental-fund-flow": f2_execute,
    "fundamental-sentiment": f3_execute,
    "dream-oneirology": oneirology_execute,
}

# 旧版节点ID → 执行函数（向后兼容）
NODE_HANDLERS = {}
for new_id, handler in _NODE_EXECUTORS.items():
    legacy_id = map_new_id(new_id)
    NODE_HANDLERS[legacy_id] = handler


# ============================================================
# 初始化全局节点注册表
# ============================================================

def _init_node_registry():
    """初始化全局节点注册表

    将所有节点定义和执行函数注册到全局注册表
    """
    registry = get_node_registry()
    definitions = get_all_node_definitions()

    for def_data in definitions:
        node = NodeInfo.from_dict(def_data)
        handler = _NODE_EXECUTORS.get(node.node_id)
        if handler:
            node.handler = handler
            node.handler_name = handler.__name__
        registry.register(node)

    return registry


# 立即初始化
_init_node_registry()


# ============================================================
# 对外接口（向后兼容 + 新接口）
# ============================================================

def get_node_handler(node_id: str):
    """获取节点处理器

    同时支持新ID和旧ID（自动转换）

    Args:
        node_id: 节点ID（新格式如 classic-indicator-scan 或旧格式如 C1_技术扫描）

    Returns:
        节点执行函数，未找到返回 None
    """
    # 先尝试新ID
    handler = _NODE_EXECUTORS.get(node_id)
    if handler:
        return handler

    # 再尝试旧ID转换
    new_id = map_legacy_id(node_id)
    if new_id != node_id:
        handler = _NODE_EXECUTORS.get(new_id)
        if handler:
            return handler

    # 最后从全局注册表获取
    registry = get_node_registry()
    return registry.get_handler(node_id)


def list_nodes() -> list:
    """列出所有可用节点（新ID）"""
    registry = get_node_registry()
    return [n.node_id for n in registry.get_all()]


def node_exists(node_id: str) -> bool:
    """检查节点是否存在（支持新旧ID）"""
    return get_node_handler(node_id) is not None


def list_legacy_nodes() -> list:
    """列出所有可用节点（旧ID）"""
    return list(NODE_HANDLERS.keys())


__all__ = [
    # 注册表核心
    "NodeRegistry",
    "NodeInfo",
    "IOSchema",
    "NodeRetryPolicy",
    "NodeFallbackPolicy",
    "get_node_registry",
    "register_node",
    "get_node",
    "get_node_handler",
    # 节点定义
    "get_all_node_definitions",
    "LEGACY_TO_NEW_ID",
    "NEW_TO_LEGACY_ID",
    "map_legacy_id",
    "map_new_id",
    # 执行函数（旧版兼容）
    "c1_execute",
    "a0_execute", "a1_execute", "a2_execute",
    "a9_execute", "a4_execute", "a3_execute",
    "f1_execute", "f2_execute", "f3_execute",
    "oneirology_execute",
    # 注册表（旧版兼容）
    "NODE_HANDLERS",
    "list_nodes",
    "node_exists",
    "list_legacy_nodes",
]
