"""
DreamOS A层 — Arrange 编排层类型定义

核心数据结构:
    - ExecutionPlan:    A 层产出的执行计划
    - NodeMeta:         节点元信息（选中后的节点描述）
    - BudgetAllocation: 预算分配方案
    - ChainSpec:        链路规格定义

三大核心闭环:
    🔵 执行环: A1→A2→A3→A4→A5→A9  (A0 内置于 A1/A2/A3)
    🟠 情报环: A6 (每1H运行, 5级放射驱动执行环)
    🟣 治理环: 两个独立维度的治理逻辑
        维度1 gap_score路由: A9→A7→A8(gap_score)→A1/A2/A3
        维度2 做梦部: 独立潜意识分析, 连败≥3/置信度55-64%时触发

A0 矛盾论内嵌说明:
    A0 内嵌到 A1→A2→A3 全链路, 三节点各自调用 A0 做不同维度的矛盾分析:
    A1 = 发现主要矛盾 (Tavily+LLM调研, 调用A0识别市场主要矛盾)
    A2 = 辩证看待矛盾 (第一性原理, 调用A0辩证分析矛盾主次关系)
    A3 = 推演解决矛盾 (策略设计, 调用A0围绕主要矛盾推演解决方案)

节点说明:
    A0 = 矛盾论 (内部方法论, 内置于 A1/A2/A3, 不独立执行)
    A1 = 深度调研 (发现主要矛盾, Tavily + LLM)
    A2 = 第一性原理 (辩证看待矛盾, 阻力最小路径)
    A3 = 策略设计 (推演解决矛盾, 大师研讨 + 沙盘推演)
    A4 = 门禁 (置信度门禁, 风险过滤)
    A5 = 战术执行 (仓位/杠杆/止损止盈)
    A6 = 情报监控 (每小时, 5级放射)
    A7 = 实践论门禁 (INDEPENDENT_AUTO 独立验证)
    A8 = 知行合一 (gap_score 路由: ≥0.5→A1, 0.3-0.5→A2, <0.3→A3)
    A9 = 离场评估 (四层离场决策链)
    做梦部 = 梦境分析 (弗洛伊德潜意识, 独立治理维度)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================
# 链路规格
# ============================================================

@dataclass
class ChainSpec:
    """链路规格 — 定义一条执行链的节点序列

    三大闭环:
        执行环: A1 → A2 → A3 → A4 → A5 → A9
            (A0 内置于 A1/A2/A3, 不在链路中独立出现)
        情报环: A6 (每小时运行, 独立调度)
        治理环: 两个独立维度的治理逻辑
            维度1 gap_score路由: A9→A7→A8→A1/A2/A3 (知行合一闭环)
            维度2 做梦部: 独立潜意识分析 (不串入 gap_score 链)
    """
    chain_id: str                          # A / C / F / G(治理) / I(情报)
    name: str = ""
    description: str = ""
    node_ids: List[str] = field(default_factory=list)
    optional_nodes: List[str] = field(default_factory=list)  # 可选扩展节点
    scenario_nodes: Dict[str, List[str]] = field(default_factory=dict)  # 场景→节点映射

    def total_count(self) -> int:
        return len(self.node_ids)

    def get_scenario_nodes(self, scenario_id: str) -> List[str]:
        """根据场景获取推荐的额外节点

        支持精确匹配和通配符匹配（如 "BULL_*" 匹配所有 BULL 开头的场景）。
        优先精确匹配，未命中则按通配符匹配。
        """
        # 精确匹配
        nodes = self.scenario_nodes.get(scenario_id)
        if nodes:
            return nodes

        # 通配符匹配（如 "BULL_*"）
        import fnmatch
        for pattern, pattern_nodes in self.scenario_nodes.items():
            if "*" in pattern and fnmatch.fnmatch(scenario_id, pattern):
                return pattern_nodes

        return []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "name": self.name,
            "description": self.description,
            "node_ids": self.node_ids,
            "optional_nodes": self.optional_nodes,
            "scenario_nodes": self.scenario_nodes,
        }


# 预定义标准链路
# A0 是内部方法论节点, 内嵌到 A1/A2/A3, 不出现在链路中
# A0 在三个节点中的不同作用:
#   A1 发现主要矛盾 — 调用A0识别市场主要矛盾
#   A2 辩证看待矛盾 — 调用A0辩证分析矛盾主次关系
#   A3 推演解决矛盾 — 调用A0围绕主要矛盾推演解决方案
STANDARD_CHAINS: Dict[str, ChainSpec] = {
    # 🔵 执行环 — A 链 (技术分析主线)
    "A": ChainSpec(
        chain_id="A",
        name="执行环·技术分析主线",
        description="C1技术面→C2动量→C3波动率→A1发现矛盾(含A0)→A2辩证矛盾(含C/F信号)→A3解决矛盾→A4门禁→A5执行→A9离场",
        node_ids=["C1", "C2", "C3", "A1", "A2", "A3", "A4", "A5", "A9"],
        optional_nodes=["A6"],  # A6 情报可作为可选扩展
        scenario_nodes={
            # 牛市趋势场景 — 三屏趋势信号优先
            "BULL_LOW_ACCELERATING": ["C_S3_TREND"],
            "BULL_LOW_DECELERATING": ["C_S3_TREND"],
            "BULL_LOW_EXHAUSTION": ["C_S3_TREND", "A_YJ_INFER"],
            "BULL_NORMAL_ACCELERATING": ["C_S3_TREND"],
            "BULL_NORMAL_DECELERATING": ["C_S3_TREND"],
            "BULL_NORMAL_EXHAUSTION": ["C_S3_TREND", "A_YJ_INFER"],
            "BULL_HIGH_ACCELERATING": ["C_S3_TREND"],
            "BULL_HIGH_DECELERATING": ["C_S3_TREND"],
            "BULL_HIGH_EXHAUSTION": ["C_S3_TREND", "A_YJ_INFER"],
            "BULL_EXTREME_ACCELERATING": ["C_S3_TREND"],
            "BULL_EXTREME_DECELERATING": ["C_S3_TREND"],
            "BULL_EXTREME_EXHAUSTION": ["C_S3_TREND", "A_YJ_INFER"],
            # 熊市趋势场景 — 三屏趋势信号优先
            "BEAR_LOW_ACCELERATING": ["C_S3_TREND"],
            "BEAR_LOW_DECELERATING": ["C_S3_TREND"],
            "BEAR_LOW_EXHAUSTION": ["C_S3_TREND", "A_YJ_INFER"],
            "BEAR_NORMAL_ACCELERATING": ["C_S3_TREND"],
            "BEAR_NORMAL_DECELERATING": ["C_S3_TREND"],
            "BEAR_NORMAL_EXHAUSTION": ["C_S3_TREND", "A_YJ_INFER"],
            "BEAR_HIGH_ACCELERATING": ["C_S3_TREND"],
            "BEAR_HIGH_DECELERATING": ["C_S3_TREND"],
            "BEAR_HIGH_EXHAUSTION": ["C_S3_TREND", "A_YJ_INFER"],
            "BEAR_EXTREME_ACCELERATING": ["C_S3_TREND"],
            "BEAR_EXTREME_DECELERATING": ["C_S3_TREND"],
            "BEAR_EXTREME_EXHAUSTION": ["C_S3_TREND", "A_YJ_INFER"],
            # 震荡/中性场景 — 马丁策略和易经推理
            "NEUTRAL_LOW_ACCELERATING": ["C_MARTIN_V15"],
            "NEUTRAL_LOW_DECELERATING": ["C_MARTIN_V15"],
            "NEUTRAL_LOW_EXHAUSTION": ["C_MARTIN_V15", "A_YJ_INFER"],
            "NEUTRAL_NORMAL_ACCELERATING": ["C_MARTIN_V15"],
            "NEUTRAL_NORMAL_DECELERATING": ["C_MARTIN_V15"],
            "NEUTRAL_NORMAL_EXHAUSTION": ["C_MARTIN_V15", "A_YJ_INFER"],
            "NEUTRAL_HIGH_ACCELERATING": ["C_MARTIN_V15", "A_YJ_INFER"],
            "NEUTRAL_HIGH_DECELERATING": ["C_MARTIN_V15", "A_YJ_INFER"],
            "NEUTRAL_HIGH_EXHAUSTION": ["C_MARTIN_V15", "A_YJ_INFER"],
            "NEUTRAL_EXTREME_ACCELERATING": ["C_MARTIN_V15", "A_YJ_INFER"],
            "NEUTRAL_EXTREME_DECELERATING": ["C_MARTIN_V15", "A_YJ_INFER"],
            "NEUTRAL_EXTREME_EXHAUSTION": ["C_MARTIN_V15", "A_YJ_INFER"],
        },
    ),
    # C 链 (短线/突破)
    "C": ChainSpec(
        chain_id="C",
        name="短线/突破链",
        description="C1技术→A2辩证→C3策略匹配→A4门禁",
        node_ids=["C1", "A2", "C3", "A4"],
        scenario_nodes={
            "BULL_*": ["C_S3_TREND"],
            "BEAR_*": ["C_S3_TREND"],
            "NEUTRAL_*": ["C_MARTIN_V15"],
        },
    ),
    # F 链 (基本面)
    "F": ChainSpec(
        chain_id="F",
        name="基本面链",
        description="A1发现矛盾→F1新闻→F5宏观→A2辩证→A4门禁",
        node_ids=["A1", "F1", "F5", "A2", "A4"],
        scenario_nodes={
            "BULL_*": ["A_YJ_INFER"],
            "BEAR_*": ["A_YJ_INFER"],
        },
    ),
    # 🟣 治理环 维度1 — gap_score 路由闭环 (知行合一)
    "G1": ChainSpec(
        chain_id="G1",
        name="治理环·gap_score路由闭环",
        description="A9离场→A7实践记录→A8知行合一(gap_score)→路由修正A1/A2/A3",
        node_ids=["A9", "A7", "A8"],
    ),
    # 🟣 治理环 维度2 — 做梦部 (独立潜意识分析, 不串入 gap_score 链)
    "G2": ChainSpec(
        chain_id="G2",
        name="治理环·做梦部潜意识分析",
        description="做梦部: 弗洛伊德潜意识分析, 连败≥3/置信度55-64%时触发, 独立维度",
        node_ids=["ONEIROLOGY"],
    ),
    # 🟠 情报环 — I 链 (独立调度, 每小时运行)
    "I": ChainSpec(
        chain_id="I",
        name="情报环·市场雷达",
        description="A6情报监控, 每小时运行, 5级放射驱动执行环",
        node_ids=["A6"],
    ),
}


# 意图类型到执行链路的映射 (对应规范中的六种意图)
INTENT_CHAIN_MAP: Dict[str, str] = {
    "TREND_FOLLOWING":   "A",    # C1→F2/F3→A2→A4 (趋势跟随, 走A链精简)
    "MEAN_REVERSION":    "A",    # C1→F2/F3→A2→A4 (均值回归, 走A链精简)
    "FUNDAMENTAL_PLAY":  "F",    # A1→F1→F5→A2→A4 (基本面驱动, 走F链)
    "BREAKOUT":          "C",    # C1→A2→C3→A4 (突破, 走C链)
    "KNOWLEDGE_MATCH":   "C",    # C3→A4 (知识库快捷路径)
    "UNCERTAIN":         "A",    # C1→A1→A2→A4 (不确定, 走A链完整)
}


# ============================================================
# 节点元信息
# ============================================================

@dataclass
class NodeMeta:
    """节点元信息 — A 层选中节点后的描述

    包含节点执行所需的全部信息:
        - 节点基本信息 (id / name / chain)
        - 预算分配 (tokens / priority)
        - 依赖关系 (depends_on)
        - 执行条件 (condition)
    """
    node_id: str
    name: str = ""
    chain: str = ""
    priority: int = 0                       # 0=必须, 1=高优, 2=可选
    estimated_tokens: int = 0              # 预估 Token 消耗
    allocated_tokens: int = 0               # 分配的 Token 预算
    estimated_latency_ms: int = 0
    depends_on: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    condition: Optional[str] = None         # 执行条件描述（调试用）

    @property
    def is_required(self) -> bool:
        return self.priority == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "chain": self.chain,
            "priority": self.priority,
            "allocated_tokens": self.allocated_tokens,
            "estimated_latency_ms": self.estimated_latency_ms,
            "depends_on": self.depends_on,
            "tags": self.tags,
            "condition": self.condition,
        }


# ============================================================
# 预算分配
# ============================================================

@dataclass
class BudgetAllocation:
    """预算分配方案 — A 层对 Token 预算的分配

    将总预算分配到各节点:
        - 必须节点 (priority=0): 优先分配
        - 高优节点 (priority=1): 按权重分配
        - 可选节点 (priority=2): 剩余分配
    """
    total_budget: int = 0
    allocated: Dict[str, int] = field(default_factory=dict)   # node_id → tokens
    reserved: int = 0                                        # 预留给反射/重试
    mode: str = "standard"                                    # lean / standard / full

    @property
    def total_allocated(self) -> int:
        return sum(self.allocated.values())

    @property
    def remaining(self) -> int:
        return self.total_budget - self.total_allocated - self.reserved

    def get(self, node_id: str) -> int:
        """获取某节点的预算"""
        return self.allocated.get(node_id, 0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_budget": self.total_budget,
            "allocated": dict(self.allocated),
            "reserved": self.reserved,
            "mode": self.mode,
            "total_allocated": self.total_allocated,
            "remaining": self.remaining,
        }


# ============================================================
# 执行计划 (A层最终输出)
# ============================================================

@dataclass
class ExecutionPlan:
    """A 层最终输出 — 执行计划

    包含:
        - 选中的节点列表
        - 执行顺序
        - 预算分配
        - 链路信息
    """
    planned_chain: str = ""                 # 选中的主链 (A/C/F)
    selected_nodes: List[NodeMeta] = field(default_factory=list)
    budget: BudgetAllocation = field(default_factory=BudgetAllocation)
    chain_spec: Optional[ChainSpec] = None
    conditions: Dict[str, str] = field(default_factory=dict)  # 节点执行条件
    rationale: str = ""                     # 编排理由
    estimated_total_tokens: int = 0
    estimated_total_latency_ms: int = 0
    capability_id: str = ""                # 能力域 ID（用于追溯路由结果）

    @property
    def node_ids(self) -> List[str]:
        """执行顺序的节点 ID 列表"""
        return [n.node_id for n in self.selected_nodes]

    @property
    def required_nodes(self) -> List[NodeMeta]:
        """必须执行的节点"""
        return [n for n in self.selected_nodes if n.is_required]

    @property
    def optional_nodes(self) -> List[NodeMeta]:
        """可选节点"""
        return [n for n in self.selected_nodes if not n.is_required]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "planned_chain": self.planned_chain,
            "selected_nodes": [n.to_dict() for n in self.selected_nodes],
            "budget": self.budget.to_dict(),
            "chain_spec": self.chain_spec.to_dict() if self.chain_spec else None,
            "conditions": self.conditions,
            "rationale": self.rationale,
            "estimated_total_tokens": self.estimated_total_tokens,
            "estimated_total_latency_ms": self.estimated_total_latency_ms,
            "capability_id": self.capability_id,
        }
