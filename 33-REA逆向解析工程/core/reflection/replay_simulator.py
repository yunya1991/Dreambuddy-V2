# -*- coding: utf-8 -*-
"""回放模拟器 — SPEC-33-反思层 v0.3 P1（对齐 Dream-RSI）

Dream-RSI 核心洞察：累积发现历史可作为回放模拟器（replay simulator），
在模拟器内『做梦』获得即时低成本的离线反馈，评估候选探索策略。

发现树（Discovery Tree，对齐 Dream-RSI §3）：
  - 根节点 r：初始工作区状态（s_r = 0）
  - 非根节点：唯一 primary parent，继承父节点快照与累积观测
  - 节点带评估分数 s_v（poe_score，固定协议生成，越大越好）
  - 决策接口：可选节点集 A(T) = {根} ∪ {叶节点}

确定性重放（对齐 Dream-RSI 做梦阶段）：
  - 给定候选策略与历史树，重放返回已记录的 children_record
  - 不调用分析器重新生成（零成本、确定性）

回放池（Replay Pool）：
  - reflection_data/replay_pool/internal/  内部发现树
  - reflection_data/replay_pool/external/  外部成熟项目解析树
  - 内部树数量低于阈值时降级为『仅记录不评估』模式

关联：SPEC-33-反思层.md v0.3 §4.1；core/evidence.py；arXiv 2609.14858v2
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 内部发现树数量低于该阈值时，做梦评估降级为『仅记录不评估』
MIN_TREES_FOR_EVAL = 10
# 外部树动态权重（SPEC §5.4，控制自举循环风险）
EXTERNAL_TREE_INIT_WEIGHT = 0.5
EXTERNAL_TREE_WEIGHT_MIN = 0.1
EXTERNAL_TREE_WEIGHT_MAX = 1.0


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class DiscoveryNode:
    """发现树节点：一次分析器调用及其记录结果。

    对齐 Dream-RSI：非根节点有唯一 primary parent，
    children_record 是确定性重放的数据源。
    """

    node_id: str
    parent_id: Optional[str]
    action: Dict[str, Any]
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    poe_score: float = 0.0
    cost_calls: int = 1
    cost_tokens: int = 0
    children_record: List[Dict[str, Any]] = field(default_factory=list)
    created_at: int = field(default_factory=_now_ms)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "action": self.action,
            "evidence_refs": self.evidence_refs,
            "poe_score": self.poe_score,
            "cost": {"calls": self.cost_calls, "tokens": self.cost_tokens},
            "children_record": self.children_record,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscoveryNode":
        cost = data.get("cost") or {}
        return cls(
            node_id=str(data["node_id"]),
            parent_id=data.get("parent_id"),
            action=dict(data.get("action") or {}),
            evidence_refs=list(data.get("evidence_refs") or []),
            poe_score=float(data.get("poe_score") or 0.0),
            cost_calls=int(cost.get("calls") or 1),
            cost_tokens=int(cost.get("tokens") or 0),
            children_record=list(data.get("children_record") or []),
            created_at=int(data.get("created_at") or _now_ms()),
        )


@dataclass
class DiscoveryTree:
    """发现树：一次分析任务的完整路径记录。

    对齐 Dream-RSI：根节点为初始工作区状态（s_r=0），
    provenance 区分 internal（本系统分析）/ external（成熟项目解析）。
    """

    tree_id: str
    task: Dict[str, Any]
    nodes: List[DiscoveryNode] = field(default_factory=list)
    provenance: str = "internal"
    source_label: str = ""
    weight: float = 1.0
    created_at: int = field(default_factory=_now_ms)
    # 外部源元数据（SPEC-33-外部真实源接入 §9-5，A2 验收要求）
    source_id: str = ""
    repo_url: str = ""
    commit: str = ""
    license: str = ""
    collected_at: int = 0

    def __post_init__(self) -> None:
        if self.provenance == "external" and self.weight == 1.0:
            self.weight = EXTERNAL_TREE_INIT_WEIGHT

    def get_node(self, node_id: str) -> Optional[DiscoveryNode]:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None

    @property
    def root(self) -> Optional[DiscoveryNode]:
        for n in self.nodes:
            if n.parent_id is None:
                return n
        return None

    def children_of(self, node_id: str) -> List[DiscoveryNode]:
        return [n for n in self.nodes if n.parent_id == node_id]

    def leaves(self) -> List[DiscoveryNode]:
        parent_ids = {n.parent_id for n in self.nodes if n.parent_id}
        return [n for n in self.nodes if n.node_id not in parent_ids]

    def action_set(self) -> List[str]:
        """决策接口 A(T) = {根} ∪ {叶节点}（对齐 Dream-RSI）。"""
        ids: List[str] = []
        r = self.root
        if r is not None:
            ids.append(r.node_id)
        ids.extend(n.node_id for n in self.leaves() if n.node_id not in ids)
        return ids

    def add_node(self, node: DiscoveryNode) -> None:
        """追加节点并登记到父节点 children_record（确定性重放数据源）。"""
        if node.parent_id is not None:
            parent = self.get_node(node.parent_id)
            if parent is None:
                raise ValueError(f"parent node not found: {node.parent_id}")
            parent.children_record.append(node.to_dict())
        self.nodes.append(node)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tree_id": self.tree_id,
            "task": self.task,
            "nodes": [n.to_dict() for n in self.nodes],
            "provenance": self.provenance,
            "source_label": self.source_label,
            "weight": self.weight,
            "created_at": self.created_at,
            "source_id": self.source_id,
            "repo_url": self.repo_url,
            "commit": self.commit,
            "license": self.license,
            "collected_at": self.collected_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscoveryTree":
        return cls(
            tree_id=str(data["tree_id"]),
            task=dict(data.get("task") or {}),
            nodes=[DiscoveryNode.from_dict(n) for n in data.get("nodes") or []],
            provenance=str(data.get("provenance") or "internal"),
            source_label=str(data.get("source_label") or ""),
            weight=float(data.get("weight") or 1.0),
            created_at=int(data.get("created_at") or _now_ms()),
            source_id=str(data.get("source_id") or ""),
            repo_url=str(data.get("repo_url") or ""),
            commit=str(data.get("commit") or ""),
            license=str(data.get("license") or ""),
            collected_at=int(data.get("collected_at") or 0),
        )

    @classmethod
    def new_tree(
        cls,
        task: Dict[str, Any],
        provenance: str = "internal",
        source_label: str = "",
    ) -> "DiscoveryTree":
        """创建新发现树：自动生成根节点（初始状态，s_r=0）。"""
        tree = cls(
            tree_id=f"dt_{uuid.uuid4().hex[:16]}",
            task=task,
            provenance=provenance,
            source_label=source_label,
        )
        root = DiscoveryNode(
            node_id=f"dn_{uuid.uuid4().hex[:16]}",
            parent_id=None,
            action={"analyzer": "init", "params": {"target": task.get("target", "")}},
            poe_score=0.0,
            cost_calls=0,
        )
        tree.nodes.append(root)
        return tree


class ReplayPool:
    """回放池：发现树的持久化存储与检索。

    目录结构（SPEC §4.1）：
        reflection_data/replay_pool/
        ├── internal/   内部发现树（本系统分析历史）
        └── external/   外部解析树（成熟项目）
    """

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.internal_dir = os.path.join(base_dir, "internal")
        self.external_dir = os.path.join(base_dir, "external")
        os.makedirs(self.internal_dir, exist_ok=True)
        os.makedirs(self.external_dir, exist_ok=True)

    def _dir_for(self, provenance: str) -> str:
        return self.external_dir if provenance == "external" else self.internal_dir

    def save(self, tree: DiscoveryTree) -> str:
        path = os.path.join(self._dir_for(tree.provenance), f"{tree.tree_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(tree.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    def load(self, tree_id: str) -> Optional[DiscoveryTree]:
        for d in (self.internal_dir, self.external_dir):
            path = os.path.join(d, f"{tree_id}.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return DiscoveryTree.from_dict(json.load(f))
        return None

    def list_trees(self, provenance: Optional[str] = None) -> List[DiscoveryTree]:
        dirs = (
            [self._dir_for(provenance)]
            if provenance in ("internal", "external")
            else [self.internal_dir, self.external_dir]
        )
        trees: List[DiscoveryTree] = []
        for d in dirs:
            for name in sorted(os.listdir(d)):
                if not name.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(d, name), "r", encoding="utf-8") as f:
                        trees.append(DiscoveryTree.from_dict(json.load(f)))
                except (json.JSONDecodeError, KeyError):
                    continue
        return trees

    def count(self, provenance: Optional[str] = None) -> int:
        return len(self.list_trees(provenance))

    def eval_ready(self) -> bool:
        """做梦评估就绪判定：内部发现树达到阈值（冷启动降级）。"""
        return self.count("internal") >= MIN_TREES_FOR_EVAL

    def update_external_weight(self, tree_id: str, verify_pass_rate: float) -> bool:
        """更新外部树动态权重（SPEC §5.4：随验证通过率线性调整）。"""
        tree = self.load(tree_id)
        if tree is None or tree.provenance != "external":
            return False
        rate = max(0.0, min(1.0, verify_pass_rate))
        tree.weight = max(
            EXTERNAL_TREE_WEIGHT_MIN,
            min(EXTERNAL_TREE_WEIGHT_MAX, EXTERNAL_TREE_INIT_WEIGHT * rate * 2),
        )
        self.save(tree)
        return True


class ReplaySimulator:
    """确定性重放引擎：在历史发现树上回放候选策略。

    对齐 Dream-RSI 做梦阶段：重放返回已记录的 children_record，
    不调用分析器重新生成——零成本、确定性、可重复。
    """

    def __init__(self, pool: ReplayPool):
        self.pool = pool

    def replay(
        self,
        tree: DiscoveryTree,
        strategy: Dict[str, Any],
        max_rounds: int = 10,
    ) -> Dict[str, Any]:
        """在单棵发现树上确定性回放策略。

        策略（SPEC §4.2 编排配置）按 analyzer_sequence 顺序选择动作，
        每轮从当前节点已记录的 children_record 中匹配策略动作：
          - 匹配到：转移到该子节点（确定性重放）
          - 未匹配：重放终止（历史中该策略未探索过此分支）
        """
        sequence = list(strategy.get("analyzer_sequence") or [])
        budget = int((strategy.get("budget") or {}).get("max_calls") or 0)
        current = tree.root
        if current is None:
            return {"path": [], "total_score": 0.0, "total_cost_calls": 0,
                    "rounds": 0, "terminated_reason": "no_root"}
        path = [current.node_id]
        total_score = 0.0
        total_cost = 0
        reason = "sequence_exhausted"
        for round_idx in range(max_rounds):
            if round_idx >= len(sequence):
                reason = "sequence_exhausted"
                break
            if budget and total_cost >= budget:
                reason = "budget_exhausted"
                break
            action = sequence[round_idx]
            matched = self._match_child(current, action)
            if matched is None:
                reason = "no_recorded_child"
                break
            total_score += matched.poe_score
            total_cost += max(1, matched.cost_calls)
            current = matched
            path.append(current.node_id)
        return {
            "path": path,
            "total_score": total_score,
            "total_cost_calls": total_cost,
            "rounds": len(path) - 1,
            "terminated_reason": reason,
        }

    @staticmethod
    def _match_child(node: DiscoveryNode, action: Any) -> Optional[DiscoveryNode]:
        """从 children_record 中匹配策略动作对应的子节点。"""
        action_name = action if isinstance(action, str) else str((action or {}).get("analyzer", ""))
        best: Optional[DiscoveryNode] = None
        for rec in node.children_record:
            rec_analyzer = str((rec.get("action") or {}).get("analyzer", ""))
            if rec_analyzer == action_name:
                child = DiscoveryNode.from_dict(rec)
                if best is None or child.poe_score > best.poe_score:
                    best = child
        return best

    def replay_all(
        self,
        strategy: Dict[str, Any],
        max_rounds: int = 10,
    ) -> Dict[str, Any]:
        """在回放池全部发现树上回放策略，返回加权汇总结果。

        外部树按动态权重折算贡献（SPEC §5.4）。
        """
        results = []
        for tree in self.pool.list_trees():
            r = self.replay(tree, strategy, max_rounds)
            r["tree_id"] = tree.tree_id
            r["provenance"] = tree.provenance
            r["weight"] = tree.weight
            results.append(r)
        weighted_score = sum(r["total_score"] * r["weight"] for r in results)
        total_weight = sum(r["weight"] for r in results) or 1.0
        return {
            "results": results,
            "weighted_avg_score": weighted_score / total_weight,
            "tree_count": len(results),
            "eval_ready": self.pool.eval_ready(),
        }
