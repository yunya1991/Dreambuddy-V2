"""ASIL Pipeline Schema 构造 — 含 bootstrap + fallback。

SPEC v0.2 §3.1 + P0-2：Step③ bootstrap fallback（E6 gaps 空时用预注册模板）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# SPEC v0.2 P0-2 D2-B 预注册模板（bootstrap fallback）
# ---------------------------------------------------------------------------
D2_BOOTSTRAP_TEMPLATES: List[str] = [
    "architecture_gap",
    "doc_debt",
    "interface_mismatch",
]


@dataclass
class PipelineBuilder:
    """Pipeline Schema 构造器。"""

    llm_budget_tokens_remaining: int = 0  # Phase 1 默认 0

    def build(
        self,
        trigger_type: str,
        trigger_evidence: Dict[str, Any],
        e6_gaps_empty: bool = False,
        low_confidence_seeds: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """构造完整 Pipeline Schema。

        Args:
            trigger_type: 触发源类型
            trigger_evidence: 触发证据
            e6_gaps_empty: E6 gaps 是否为空（决定是否走 bootstrap）
            low_confidence_seeds: 低置信记忆 seed 列表（用于 bootstrap 伪 gap）
        """
        trace_id = f"asil-{int(time.time())}-{uuid.uuid4().hex[:8]}"

        steps = self._build_steps(bootstrap=e6_gaps_empty)

        return {
            "pipeline_id": trace_id,
            "trigger": {
                "type": trigger_type,
                "source": trigger_evidence.get("source", trigger_type),
                "evidence": trigger_evidence,
                "timestamp": time.time(),
            },
            "bootstrap_source": {
                "e6_gaps_empty": e6_gaps_empty,
                "fallback_templates": D2_BOOTSTRAP_TEMPLATES if e6_gaps_empty else [],
                "low_confidence_seeds": low_confidence_seeds or [],
            },
            "steps": steps,
            "trace_id": trace_id,
            "run_mode": "shadow",
            "provenance": "ASIL-Orchestrator v0.2",
            "llm_budget_tokens_remaining": self.llm_budget_tokens_remaining,
        }

    def _build_steps(self, bootstrap: bool) -> List[Dict[str, Any]]:
        """构造 8 步 pipeline。"""
        steps: List[Dict[str, Any]] = [
            {
                "seq": 1,
                "name": "cognitive_recall",
                "input": "低置信记忆列表",
                "output": "poe_evidence_chain",
                "ok": True,
            },
            {
                "seq": 2,
                "name": "intent_prediction",
                "input": "recall_result",
                "output": "intent_prediction + knowledge_combo",
                "domain": "D3",
                "optional": True,
                "ok": True,
            },
            {
                "seq": 3,
                "name": "architecture_solution",
                "input": "e6_gaps + [optional: intent]",
                "output": "architecture_graph + build_plan",
                "domain": "D2",
                "mode": "shadow",
                "bootstrap": bootstrap,
                "ok": True,
            },
            {
                "seq": 4,
                "name": "test_verify",
                "input": "build_plan",
                "output": "coverage + pass_rate",
                "gate": "45 E-H1~H5",
                "survival_checkpoint": "build_plan_nonempty",
                "ok": False,
            },
            {
                "seq": 5,
                "name": "oracle_review",
                "input": "test_result + 45 judge",
                "output": "oracle_confidence + verdict",
                "survival_checkpoint": "verdict_exists",
                "ok": False,
            },
            {
                "seq": 6,
                "name": "feedback_write",
                "input": "verdict",
                "output": "gap_router_update",
                "policy": "FAIL-OPEN",
                "ok": False,
            },
            {
                "seq": 7,
                "name": "bayesian_verify",
                "input": "verdict + evidence",
                "output": "memory_confidence_update",
                "policy": "OOD_隔离_PHASE1_SKIP",
                "ok": False,
            },
            {
                "seq": 8,
                "name": "distill",
                "input": "A/S级记忆",
                "output": "skill / pattern / 40_training_suggestion",
                "gate": "脚手架披露",
                "ok": False,
            },
        ]
        return steps
