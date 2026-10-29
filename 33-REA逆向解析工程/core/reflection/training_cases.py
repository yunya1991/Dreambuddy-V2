"""输出训练闭环 — 训练案例生成与历史案例转换。

SPEC-33-输出场景-意图系统.md §6.2：
- Spec 增强案例：草案 vs 增强 Spec + OKR 验收结果（正/负样本）
- 策略评估案例：节点完成情境 + 候选策略 + 实际执行结果
- 质量门控：无证据引用不入库；负样本 100% 入库
- 历史案例冷启动：系统已开发项目案例作为初始训练语料，
  新增案例走增量训练（用户确认的推进策略）
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .replay_simulator import ReplayPool

# 训练案例 JSON Schema 字段（SPEC §6.2）
CASE_TYPES = ("spec_enhance", "optimal_path")


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


@dataclass
class TrainingCaseRecord:
    """训练案例记录（JSON Schema 对齐 SPEC §6.2）。"""

    case_type: str
    intent: str
    payload: Dict[str, Any]
    label: str  # positive / negative
    poe_score: float
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def passes_gate(self) -> bool:
        """质量门控：无证据引用不入库（对齐纸上谈兵检测）。"""
        return bool(self.evidence_refs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_type": self.case_type,
            "intent": self.intent,
            "payload": self.payload,
            "label": self.label,
            "poe_score": self.poe_score,
            "evidence_refs": self.evidence_refs,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingCaseRecord":
        return cls(
            case_type=str(data["case_type"]),
            intent=str(data["intent"]),
            payload=dict(data.get("payload") or {}),
            label=str(data.get("label") or "positive"),
            poe_score=float(data.get("poe_score") or 0.0),
            evidence_refs=list(data.get("evidence_refs") or []),
            created_at=str(data.get("created_at") or _now_iso()),
        )


class TrainingCaseGenerator:
    """训练案例生成器：从输出场景执行产物生成两类训练案例。"""

    def spec_enhance_case(
        self,
        spec_draft: str,
        enhanced_spec: str,
        okr_acceptance: Dict[str, Any],
        poe_score: float,
        evidence_refs: List[Dict[str, Any]],
    ) -> TrainingCaseRecord:
        """Spec 增强案例：验收通过=正样本；REDO/回滚=负样本。"""
        passed = bool(okr_acceptance.get("passed"))
        return TrainingCaseRecord(
            case_type="spec_enhance",
            intent=str(okr_acceptance.get("intent") or "spec_enhance"),
            payload={
                "spec_draft": spec_draft,
                "enhanced_spec": enhanced_spec,
                "okr_acceptance_results": okr_acceptance,
            },
            label="positive" if passed else "negative",
            poe_score=poe_score,
            evidence_refs=evidence_refs,
        )

    def optimal_path_case(
        self,
        node_context: Dict[str, Any],
        candidate_strategies: List[Dict[str, Any]],
        chosen_decision: Dict[str, Any],
        execution_outcome: Dict[str, Any],
        v_value: float,
        evidence_refs: List[Dict[str, Any]],
    ) -> TrainingCaseRecord:
        """策略评估案例：执行结果与预期一致=正样本；偏差=负样本。"""
        as_expected = bool(execution_outcome.get("as_expected"))
        return TrainingCaseRecord(
            case_type="optimal_path",
            intent=str(node_context.get("intent") or "optimal_path"),
            payload={
                "node_context": node_context,
                "candidate_strategies": candidate_strategies,
                "chosen_decision": chosen_decision,
                "execution_outcome": execution_outcome,
                "v_value": v_value,
            },
            label="positive" if as_expected else "negative",
            poe_score=float(execution_outcome.get("poe_score") or 0.0),
            evidence_refs=evidence_refs,
        )


class HistoricalCaseConverter:
    """历史项目案例转换器（冷启动语料）。

    数据源：
    - 验收包（acceptance_bundles/*/wrapup_report.md）
    - 反思层回放池发现树（reflection_data/replay_pool/）
    - 34 系统 l1 案例库（l1_case_store.jsonl）
    """

    def __init__(self, project_root: str):
        self.project_root = project_root

    def from_acceptance_bundles(self) -> List[TrainingCaseRecord]:
        """验收包 → spec_enhance 案例（步骤矩阵即增强路径）。"""
        cases: List[TrainingCaseRecord] = []
        bundles_dir = os.path.join(self.project_root, "acceptance_bundles")
        if not os.path.isdir(bundles_dir):
            return cases
        for bundle in sorted(os.listdir(bundles_dir)):
            report = os.path.join(bundles_dir, bundle, "wrapup_report.md")
            if not os.path.isfile(report):
                continue
            try:
                with open(report, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            passed = "收尾完成" in text
            cases.append(TrainingCaseRecord(
                case_type="spec_enhance",
                intent=f"acceptance:{bundle}",
                payload={
                    "spec_draft": bundle,
                    "enhanced_spec": text[:2000],
                    "okr_acceptance_results": {"passed": passed, "bundle": bundle},
                },
                label="positive" if passed else "negative",
                poe_score=0.8 if passed else 0.4,
                evidence_refs=[{
                    "type": "acceptance_bundle",
                    "path": f"acceptance_bundles/{bundle}/wrapup_report.md",
                }],
            ))
        return cases

    def from_replay_pool(self, pool: ReplayPool) -> List[TrainingCaseRecord]:
        """回放池发现树 → optimal_path 案例（树路径即策略评估历史）。"""
        cases: List[TrainingCaseRecord] = []
        for tree in pool.list_trees():
            path_actions = [n.action.get("analyzer", "") for n in tree.nodes]
            avg_poe = (
                sum(n.poe_score for n in tree.nodes) / len(tree.nodes)
                if tree.nodes else 0.0
            )
            cases.append(TrainingCaseRecord(
                case_type="optimal_path",
                intent=str(tree.task.get("target") or tree.tree_id),
                payload={
                    "node_context": {"tree_id": tree.tree_id, "task": tree.task},
                    "candidate_strategies": [{
                        "analyzer_sequence": path_actions,
                        "source": tree.provenance,
                    }],
                    "chosen_decision": {"analyzer_sequence": path_actions},
                    "execution_outcome": {
                        "as_expected": avg_poe >= 0.5,
                        "poe_score": avg_poe,
                    },
                    "v_value": avg_poe,
                },
                label="positive" if avg_poe >= 0.5 else "negative",
                poe_score=avg_poe,
                evidence_refs=[{
                    "type": "replay_pool_tree",
                    "tree_id": tree.tree_id,
                    "provenance": tree.provenance,
                }],
            ))
        return cases

    def from_l1_store(self, l1_path: str) -> List[TrainingCaseRecord]:
        """34 系统 l1 案例库 → optimal_path 案例（意图-应答即执行路径）。"""
        cases: List[TrainingCaseRecord] = []
        if not os.path.isfile(l1_path):
            return cases
        try:
            with open(l1_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    data = rec.get("data") or {}
                    has_answer = bool(rec.get("answer"))
                    cases.append(TrainingCaseRecord(
                        case_type="optimal_path",
                        intent=str(rec.get("intent") or "data_query"),
                        payload={
                            "node_context": {"message": rec.get("message", "")},
                            "candidate_strategies": [{
                                "source": str(data.get("source") or "unknown"),
                            }],
                            "chosen_decision": {"source": data.get("source")},
                            "execution_outcome": {
                                "as_expected": has_answer,
                                "answer": str(rec.get("answer", ""))[:500],
                            },
                            "v_value": 0.6 if has_answer else 0.2,
                        },
                        label="positive" if has_answer else "negative",
                        poe_score=0.6 if has_answer else 0.2,
                        evidence_refs=[{
                            "type": "l1_case",
                            "ts": rec.get("ts", ""),
                            "source": data.get("source"),
                        }],
                    ))
        except OSError:
            pass
        return cases


class TrainingCaseStore:
    """训练案例存储：JSONL 持久化 + 质量门控 + 负样本入库保证。"""

    def __init__(self, store_path: str):
        self.store_path = store_path
        os.makedirs(os.path.dirname(store_path) or ".", exist_ok=True)

    def save(self, case: TrainingCaseRecord) -> Optional[str]:
        """入库单条案例：质量门控（无证据不入库），负样本不静默丢弃。"""
        if not case.passes_gate():
            return None
        with open(self.store_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(case.to_dict(), ensure_ascii=False) + "\n")
        return case.case_type

    def load_all(self) -> List[TrainingCaseRecord]:
        cases: List[TrainingCaseRecord] = []
        if not os.path.isfile(self.store_path):
            return cases
        with open(self.store_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    cases.append(TrainingCaseRecord.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError):
                    continue
        return cases

    def stats(self) -> Dict[str, Any]:
        cases = self.load_all()
        by_type: Dict[str, int] = {}
        by_label: Dict[str, int] = {}
        for c in cases:
            by_type[c.case_type] = by_type.get(c.case_type, 0) + 1
            by_label[c.label] = by_label.get(c.label, 0) + 1
        return {
            "total": len(cases),
            "by_type": by_type,
            "by_label": by_label,
            "negative_ratio": by_label.get("negative", 0) / len(cases) if cases else 0.0,
        }
