"""
Dreambuddy OS — State 全局状态抽象

设计借鉴 LangGraph 的 StateGraph:
- State 是执行图的全局状态
- 所有节点读写同一份 State
- 节点返回 NodeResult，由框架合并到 State

核心概念:
    State       — 完整执行状态
    NodeResult  — 节点执行结果
    NodeStatus  — 节点状态枚举

依赖关系:
    本文件是 OS 最底层，不依赖任何其他 OS 模块
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ============================================================
# 节点状态枚举
# ============================================================

class NodeStatus(Enum):
    """节点执行状态"""
    PENDING = "pending"          # 等待执行
    RUNNING = "running"          # 执行中
    SUCCESS = "success"          # 成功
    FAILED = "failed"            # 失败
    SKIPPED = "skipped"          # 跳过
    DEGRADED = "degraded"        # 降级执行


# ============================================================
# 节点执行结果
# ============================================================

@dataclass
class NodeResult:
    """节点执行结果

    每个节点执行后产出 NodeResult，框架将其合并到 State。
    所有字段都有合理默认值，节点只需填写关心的字段。
    """
    node_id: str
    status: NodeStatus = NodeStatus.SUCCESS
    outputs: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0                          # 0-1
    direction: Optional[str] = None                  # LONG / SHORT / HOLD / NEUTRAL
    error: Optional[str] = None
    error_code: Optional[str] = None
    latency_ms: float = 0.0
    tokens_used: int = 0
    retries: int = 0
    degraded: bool = False
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """是否成功（含降级）"""
        return self.status in (NodeStatus.SUCCESS, NodeStatus.DEGRADED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status.value,
            "outputs": self.outputs,
            "confidence": self.confidence,
            "direction": self.direction,
            "error": self.error,
            "error_code": self.error_code,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "retries": self.retries,
            "degraded": self.degraded,
        }


# ============================================================
# State — 执行图的全局状态
# ============================================================

@dataclass
class State:
    """执行图的全局状态 — 所有节点读写同一份 State

    设计原则:
        1. 节点不直接互相调用，通过 State 通信
        2. 节点执行后返回 NodeResult，框架更新 State
        3. State 可序列化，支持 checkpoint 和 replay
        4. State 不可变性: 节点不应直接修改其他节点的结果

    字段分组:
        - 输入层: intent / market / memory / config
        - 编排层: blueprint / plan
        - 执行层: results / trace
        - 决策输出: final_action / final_confidence
        - 元信息: cycle_id / session_id / timestamps
    """

    # ── 输入层 ──────────────────────────────────────────
    intent: Optional[Dict[str, Any]] = None
    """S层产出的意图结果 (intent_type / confidence / recommended_chain / ...)"""

    market: Optional[Dict[str, Any]] = None
    """市场数据快照 (symbol / price / candles / regime / ...)"""

    memory: Optional[Dict[str, Any]] = None
    """跨周期记忆 (lessons / recent_decisions / win_streaks / ...)"""

    config: Optional[Dict[str, Any]] = None
    """执行配置 (budget_mode / max_tokens / risk_params / ...)"""

    # ── 编排层（A层产出） ──────────────────────────────
    blueprint: Optional[Dict[str, Any]] = None
    """S层三层递进产出的执行蓝图 (objective / okr / execution_plan)"""

    plan: Optional[Dict[str, Any]] = None
    """A层产出的执行图规划 (planned_chain / node_meta / budget_mode / ...)"""

    # ── 执行层 ──────────────────────────────────────────
    results: Dict[str, NodeResult] = field(default_factory=dict)
    """各节点的执行结果, key=node_id"""

    trace: List[Dict[str, Any]] = field(default_factory=list)
    """执行轨迹，按时间顺序记录每步"""

    # ── 决策输出 ────────────────────────────────────────
    final_action: Optional[str] = None
    """最终决策: LONG / SHORT / HOLD"""

    final_confidence: float = 0.0
    """最终置信度 0-1"""

    # ── 元信息 ──────────────────────────────────────────
    cycle_id: str = ""
    session_id: str = ""
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # ── 扩展字段（节点可自由使用） ─────────────────────
    extra: Dict[str, Any] = field(default_factory=dict)

    # ──────────────────────────────────────────────────
    # 状态操作方法
    # ──────────────────────────────────────────────────

    def update(self, node_id: str, result: NodeResult) -> "State":
        """节点执行后更新状态（链式调用）"""
        self.results[node_id] = result
        self.trace.append({
            "node_id": node_id,
            "status": result.status.value,
            "confidence": result.confidence,
            "direction": result.direction,
            "ts": datetime.utcnow().isoformat(),
        })
        self.updated_at = datetime.utcnow()
        return self

    def get_result(self, node_id: str) -> Optional[NodeResult]:
        """获取某节点的执行结果"""
        return self.results.get(node_id)

    def get_confidence(self, node_id: str) -> float:
        """获取某节点的置信度"""
        r = self.results.get(node_id)
        return r.confidence if r else 0.0

    def get_direction(self, node_id: str) -> Optional[str]:
        """获取某节点的方向判断"""
        r = self.results.get(node_id)
        return r.direction if r else None

    def aggregate_confidence(self, node_ids: Optional[List[str]] = None) -> float:
        """聚合多个节点的置信度（算术平均）"""
        ids = node_ids or list(self.results.keys())
        if not ids:
            return 0.0
        confs = [self.results[i].confidence for i in ids if i in self.results]
        return sum(confs) / len(confs) if confs else 0.0

    def has_node(self, node_id: str) -> bool:
        """某节点是否已执行"""
        return node_id in self.results

    def is_all_success(self, node_ids: Optional[List[str]] = None) -> bool:
        """指定节点是否全部成功"""
        ids = node_ids or list(self.results.keys())
        return all(self.results[i].success for i in ids if i in self.results)

    # ──────────────────────────────────────────────────
    # 序列化（用于 checkpoint 和回放）
    # ──────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict"""
        return {
            "intent": self.intent,
            "market": self.market,
            "memory": self.memory,
            "config": self.config,
            "blueprint": self.blueprint,
            "plan": self.plan,
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "trace": self.trace,
            "final_action": self.final_action,
            "final_confidence": self.final_confidence,
            "cycle_id": self.cycle_id,
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "State":
        """从 dict 反序列化"""
        s = cls()
        s.intent = data.get("intent")
        s.market = data.get("market")
        s.memory = data.get("memory")
        s.config = data.get("config")
        s.blueprint = data.get("blueprint")
        s.plan = data.get("plan")
        s.trace = data.get("trace", [])
        s.final_action = data.get("final_action")
        s.final_confidence = data.get("final_confidence", 0.0)
        s.cycle_id = data.get("cycle_id", "")
        s.session_id = data.get("session_id", "")
        s.extra = data.get("extra", {})
        # results 反序列化
        for nid, r in (data.get("results") or {}).items():
            s.results[nid] = NodeResult(
                node_id=nid,
                status=NodeStatus(r.get("status", "success")),
                outputs=r.get("outputs", {}),
                confidence=r.get("confidence", 0.0),
                direction=r.get("direction"),
                error=r.get("error"),
                error_code=r.get("error_code"),
                latency_ms=r.get("latency_ms", 0.0),
                tokens_used=r.get("tokens_used", 0),
                retries=r.get("retries", 0),
                degraded=r.get("degraded", False),
            )
        return s

    def snapshot(self) -> "State":
        """创建当前状态的深拷贝快照"""
        return copy.deepcopy(self)


# ============================================================
# 工厂函数
# ============================================================

def new_state(cycle_id: str = "", **kwargs) -> State:
    """创建新的 State 实例"""
    s = State(cycle_id=cycle_id, started_at=datetime.utcnow(), **kwargs)
    s.updated_at = s.started_at
    return s
