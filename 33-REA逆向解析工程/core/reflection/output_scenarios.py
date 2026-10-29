"""输出场景核心 — SPEC-33-输出场景-意图系统.md §4/§5。

Q1/Q2 Spec 增强管线（A 层）：
- 第一段 证据提取（规则驱动，零 LLM）：解析任务特征 → 检索外部池 →
  规则抽取证据包（设计决策/架构模式/演化叙事，全部带证据引用）
- 第二段 Spec 组装（单次生成，token 预算 ≤8K）：草案 + 证据包 →
  engineering_okr 格式增强 Spec
- Spec 质量门禁：PoE 三级门禁 + 纸上谈兵检测（约束证据必须真实存在）

Q3/Q4 最优路径驱动（C 层）：
- 轻量层（默认触发，<100ms）：关键词匹配回放池索引 + 置信度阈值
- 重量层（条件触发，<5s）：回放池检索 + V 值排序候选策略
- 降级链路：无信号时 FAIL-OPEN 不阻断 C-Drive
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .replay_simulator import ReplayPool
from .dreaming import DreamingLoop

# token 预算上限（第二段组装）
TOKEN_BUDGET = 8000
# 轻量层延迟预算（ms）
LIGHT_LAYER_BUDGET_MS = 100
# 重量层延迟预算（ms）
HEAVY_LAYER_BUDGET_MS = 5000
# 重量层触发条件阈值
CONFIDENCE_TRIGGER = 0.6
# 决策阈值语义（对接 decision_deriver）
DECISION_REDO = 0.3
DECISION_INSERT = 0.6


def _now_ms() -> int:
    return int(time.time() * 1000)


# ----------------------------------------------------------------------
# Q1/Q2：Spec 增强管线（两段式）
# ----------------------------------------------------------------------

@dataclass
class EvidencePack:
    """第一段产物：规则抽取的证据包（零 LLM）。"""

    task_features: Dict[str, Any] = field(default_factory=dict)
    design_decisions: List[Dict[str, Any]] = field(default_factory=list)
    architecture_patterns: List[Dict[str, Any]] = field(default_factory=list)
    evolution_notes: List[Dict[str, Any]] = field(default_factory=list)
    matched_trees: List[str] = field(default_factory=list)
    llm_calls: int = 0  # 第一段必须为 0

    def total_items(self) -> int:
        return (len(self.design_decisions)
                + len(self.architecture_patterns)
                + len(self.evolution_notes))


class SpecEnhancer:
    """两段式 Spec 增强器（SPEC §4.1）。"""

    def __init__(self, pool: Optional[ReplayPool] = None):
        self.pool = pool

    # ---- 第一段：证据提取（规则驱动，零 LLM）----
    def extract_evidence(self, spec_draft: str) -> EvidencePack:
        """规则抽取证据包：任务特征解析 + 外部池检索 + 证据规则抽取。

        全程零 LLM 调用（对齐 rea_cdrive_adapter 零 token 原则）。
        """
        pack = EvidencePack()
        pack.task_features = self._parse_task_features(spec_draft)
        # 外部池检索（无匹配时仅用内部能力，FAIL-OPEN）
        if self.pool is not None:
            for tree in self.pool.list_trees("external"):
                pack.matched_trees.append(tree.tree_id)
                for node in tree.nodes:
                    if node.action.get("analyzer") == "architecture_pattern_detector":
                        pack.architecture_patterns.append({
                            "pattern": node.action.get("params", {}).get("path", ""),
                            "evidence_ref": {
                                "source": f"replay_pool:{tree.tree_id}",
                                "node": node.node_id,
                                "confidence": node.poe_score,
                            },
                            "applicable_condition": tree.source_label,
                        })
                    if node.evidence_refs:
                        pack.design_decisions.append({
                            "decision": node.action.get("analyzer", ""),
                            "evidence_ref": {
                                "source": f"replay_pool:{tree.tree_id}",
                                "node": node.node_id,
                                "confidence": node.poe_score,
                            },
                            "applicable_condition": tree.source_label,
                        })
        return pack

    def _parse_task_features(self, spec_draft: str) -> Dict[str, Any]:
        """规则解析任务特征（语言/领域/架构类型关键词匹配）。"""
        text = spec_draft.lower()
        features: Dict[str, Any] = {"raw_length": len(spec_draft)}
        langs = ["python", "typescript", "javascript", "rust", "go"]
        features["language"] = next((l for l in langs if l in text), "unknown")
        domains = ["web", "cli", "data", "training", "trading"]
        features["domain"] = next((d for d in domains if d in text), "unknown")
        archs = ["mvc", "pipeline", "event-driven", "layered"]
        features["architecture"] = next((a for a in archs if a in text), "unknown")
        return features

    # ---- 第二段：Spec 组装（单次生成，token 预算控制）----
    def assemble_spec(
        self,
        spec_draft: str,
        pack: EvidencePack,
    ) -> Dict[str, Any]:
        """组装增强 Spec（engineering_okr 格式）。

        模拟单次 LLM 生成：确定性模板组装（测试环境零 LLM 依赖），
        token 预算超限时按置信度排序截断证据包。
        """
        # token 预算控制：按置信度排序保留高置信项
        kept = self._budget_trim(pack)
        constraints = []
        for dd in kept["design_decisions"]:
            constraints.append({
                "constraint": f"参考设计决策: {dd['decision']}",
                "evidence_ref": dd["evidence_ref"],
                "applicable_condition": dd["applicable_condition"],
            })
        for ap in kept["architecture_patterns"]:
            constraints.append({
                "constraint": f"架构模式参考: {ap['pattern']}",
                "evidence_ref": ap["evidence_ref"],
                "applicable_condition": ap["applicable_condition"],
            })
        okr_nodes = [
            {
                "node_id": f"okr_{i + 1}",
                "objective": f"落实约束 {i + 1}",
                "acceptance": {
                    "criteria": c["constraint"],
                    "verify": "okr_nodes",
                },
                "evidence_ref": c["evidence_ref"],
            }
            for i, c in enumerate(constraints)
        ]
        return {
            "spec_draft": spec_draft,
            "task_features": pack.task_features,
            "engineering_constraints": constraints,
            "okr_nodes": okr_nodes,
            "tech_selection_basis": [
                {"basis": dd["decision"], "applicable_condition": dd["applicable_condition"]}
                for dd in kept["design_decisions"]
            ],
            "token_usage": {
                "budget": TOKEN_BUDGET,
                "trimmed": pack.total_items() - (len(kept["design_decisions"]) + len(kept["architecture_patterns"])),
            },
        }

    def _budget_trim(self, pack: EvidencePack) -> Dict[str, List[Dict[str, Any]]]:
        """token 预算超限时按置信度排序保留高置信项。"""
        def conf(item: Dict[str, Any]) -> float:
            return float(item.get("evidence_ref", {}).get("confidence", 0.0))
        dds = sorted(pack.design_decisions, key=conf, reverse=True)
        aps = sorted(pack.architecture_patterns, key=conf, reverse=True)
        # 粗略 token 估算：每项约 200 token
        max_items = TOKEN_BUDGET // 200
        total = len(dds) + len(aps)
        if total <= max_items:
            return {"design_decisions": dds, "architecture_patterns": aps}
        keep_dd = dds[: max_items // 2]
        keep_ap = aps[: max(0, max_items - len(keep_dd))]
        return {"design_decisions": keep_dd, "architecture_patterns": keep_ap}

    # ---- Spec 质量门禁（Q2）----
    def quality_gate(self, enhanced_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Spec 质量门禁：约束证据真实存在（纸上谈兵检测）+ PoE 评分。"""
        constraints = enhanced_spec.get("engineering_constraints", [])
        missing = [
            c for c in constraints
            if not c.get("evidence_ref") or not c["evidence_ref"].get("source")
        ]
        all_evidenced = len(constraints) > 0 and not missing
        # PoE 评分：证据覆盖率（复用 ai_audit 语义的简化实现）
        poe = 1.0 if all_evidenced else (0.5 if constraints else 0.0)
        return {
            "passed": all_evidenced and poe >= 0.6,
            "poe_score": poe,
            "constraint_count": len(constraints),
            "missing_evidence": len(missing),
            "paper_talk_detected": bool(missing),
        }

    # ---- 全链路 ----
    def enhance(self, spec_draft: str) -> Dict[str, Any]:
        """两段式全链路：证据提取（零 LLM）→ 组装 → 质量门禁。"""
        t0 = _now_ms()
        pack = self.extract_evidence(spec_draft)
        extract_ms = _now_ms() - t0
        enhanced = self.assemble_spec(spec_draft, pack)
        gate = self.quality_gate(enhanced)
        return {
            "enhanced_spec": enhanced,
            "quality_gate": gate,
            "evidence_pack_stats": {
                "design_decisions": len(pack.design_decisions),
                "architecture_patterns": len(pack.architecture_patterns),
                "matched_trees": len(pack.matched_trees),
                "llm_calls_segment1": pack.llm_calls,
            },
            "extract_ms": extract_ms,
        }


# ----------------------------------------------------------------------
# Q3/Q4：最优路径驱动（双层延迟）
# ----------------------------------------------------------------------

@dataclass
class CandidateStrategy:
    """候选下一步策略（100% 带证据与来源标注）。"""

    strategy: Dict[str, Any]
    evidence_ref: Dict[str, Any]
    source: str  # internal / external
    confidence: float
    v_value: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "evidence_ref": self.evidence_ref,
            "source": self.source,
            "confidence": self.confidence,
            "v_value": self.v_value,
        }


class OptimalPathEvaluator:
    """双层延迟策略评估器（SPEC §5.1）。"""

    def __init__(self, pool: Optional[ReplayPool] = None):
        self.pool = pool

    def evaluate(
        self,
        completed_node: Dict[str, Any],
        task_context: Optional[Dict[str, Any]] = None,
        force_heavy: bool = False,
    ) -> Dict[str, Any]:
        """节点完成后策略评估：轻量层默认，条件触发重量层。

        降级链路（FAIL-OPEN）：无回放池/无匹配时返回空候选，
        不阻断 C-Drive（由现有 P4 问题触发式反思接管）。
        """
        t0 = _now_ms()
        acceptance = completed_node.get("acceptance", {})
        passed = bool(acceptance.get("passed"))
        confidence = float(acceptance.get("confidence", 1.0))
        # 重量层触发条件：验收失败 / 置信度 <0.6 / 显式调用
        heavy = force_heavy or (not passed) or (confidence < CONFIDENCE_TRIGGER)
        layer = "heavy" if heavy else "light"
        candidates: List[CandidateStrategy] = []
        if heavy:
            candidates = self._heavy_evaluate(completed_node)
        else:
            candidates = self._light_evaluate(completed_node)
        elapsed = _now_ms() - t0
        # V 值排序（重量层）
        if heavy and candidates:
            candidates.sort(key=lambda c: c.v_value, reverse=True)
        # expected_decision 建议（对接 decision_deriver 阈值语义）
        best_conf = candidates[0].confidence if candidates else 0.0
        if not passed:
            decision = "REDO"
        elif best_conf < DECISION_REDO:
            decision = "REDO"
        elif best_conf < DECISION_INSERT:
            decision = "INSERT_BEFORE"
        else:
            decision = "CONTINUE"
        return {
            "layer": layer,
            "elapsed_ms": elapsed,
            "budget_ms": HEAVY_LAYER_BUDGET_MS if heavy else LIGHT_LAYER_BUDGET_MS,
            "within_budget": elapsed <= (HEAVY_LAYER_BUDGET_MS if heavy else LIGHT_LAYER_BUDGET_MS),
            "candidates": [c.to_dict() for c in candidates],
            "expected_decision": decision,
            "degraded": not candidates,  # 无候选 → 降级（FAIL-OPEN）
        }

    def _light_evaluate(self, completed_node: Dict[str, Any]) -> List[CandidateStrategy]:
        """轻量层：关键词匹配回放池索引 + 置信度阈值（<100ms）。"""
        if self.pool is None:
            return []
        analyzer = str(completed_node.get("analyzer", ""))
        candidates: List[CandidateStrategy] = []
        for tree in self.pool.list_trees():
            for node in tree.nodes:
                if node.action.get("analyzer") == analyzer and node.evidence_refs:
                    candidates.append(CandidateStrategy(
                        strategy={
                            "next_analyzer": analyzer,
                            "action": "reuse_recorded_path",
                        },
                        evidence_ref={
                            "source": f"replay_pool:{tree.tree_id}",
                            "node": node.node_id,
                        },
                        source=tree.provenance,
                        confidence=node.poe_score,
                    ))
                    if len(candidates) >= 5:  # 轻量层限量
                        return candidates
        return candidates

    def _heavy_evaluate(self, completed_node: Dict[str, Any]) -> List[CandidateStrategy]:
        """重量层：回放池检索 + V 值排序（<5s）。"""
        if self.pool is None:
            return []
        candidates = self._light_evaluate(completed_node)
        # V 值评估（复用做梦循环的回放目标函数语义）
        if self.pool.eval_ready():
            seq = [str(completed_node.get("analyzer", ""))]
            strategy = {
                "budget": {"max_calls": 10},
                "parallelism": 1,
                "analyzer_sequence": seq,
                "transform": "current",
            }
            loop = DreamingLoop(self.pool)
            result = loop.evaluate_strategy(strategy)
            for c in candidates:
                c.v_value = result.get("avg_v", 0.0)
        return candidates
