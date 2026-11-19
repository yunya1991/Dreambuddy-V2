# -*- coding: utf-8 -*-
"""P0-D3C RED: A 层双层验收（规则硬门 + Hermes 语义软门）。

冲突矩阵:
  rule fail → fail
  rule pass + semantic pass(有引用) → pass
  rule pass + semantic pass(无引用) → degraded
  rule pass + semantic fail → degraded
  rule degraded + semantic pass(有引用) → pass
  rule degraded + semantic fail/缺失 → degraded
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.dual_acceptance import (  # noqa: E402
    SemanticReview,
    apply_reviews,
    merge_verdict,
)
from core.okr_acceptance import evaluate_nodes  # noqa: E402
from core.okr_nodes import VERIFY_EVIDENCE  # noqa: E402


def _review(verdict="pass", refs=("artifact:a.md",)):
    return SemanticReview(
        node_id="N1",
        verdict=verdict,
        evidence_refs=tuple(refs),
        confidence=0.8,
        rationale="证据覆盖 criteria",
    )


def test_rule_fail_vetoes_semantic_pass():
    verdict, reason = merge_verdict("fail", _review())
    assert verdict == "fail"
    assert reason == "rule_veto"


def test_rule_pass_semantic_pass_with_citation():
    verdict, reason = merge_verdict("pass", _review())
    assert verdict == "pass"
    assert reason == "semantic_pass"


def test_rule_pass_semantic_pass_without_citation_degrades():
    verdict, reason = merge_verdict("pass", _review(refs=()))
    assert verdict == "degraded"
    assert reason == "semantic_no_citation"


def test_rule_pass_semantic_fail_degrades():
    verdict, reason = merge_verdict("pass", _review(verdict="fail"))
    assert verdict == "degraded"
    assert reason == "semantic_disagreement"


def test_rule_degraded_semantic_pass_can_upgrade():
    verdict, reason = merge_verdict("degraded", _review())
    assert verdict == "pass"
    assert reason == "semantic_upgrade"


def test_rule_degraded_semantic_fail_stays_degraded():
    verdict, reason = merge_verdict("degraded", _review(verdict="fail"))
    assert verdict == "degraded"


def test_missing_semantic_keeps_rule_verdict():
    verdict, reason = merge_verdict("degraded", None)
    assert verdict == "degraded"
    assert reason == "rule_only"


def test_apply_reviews_attaches_semantic_fields():
    nodes = [{"node_id": "N1", "verdict": "degraded", "reason": "evidence_pending"}]
    out = apply_reviews(nodes, [_review()])
    assert out[0]["verdict"] == "pass"
    assert out[0]["semantic_verdict"] == "pass"
    assert out[0]["semantic_confidence"] == 0.8
    assert nodes[0]["verdict"] == "degraded"  # 不改输入


def test_a_layer_integration_evidence_backed_pass():
    nodes = [
        {
            "node_id": "N1",
            "objective": "o",
            "criteria": "c",
            "source": "rea_evidence",
            "verify": VERIFY_EVIDENCE,
            "evidence_id": "EV-1",
        }
    ]
    results = [{"node_id": "N1", "action": "CONTINUE", "detail": {}}]
    out = evaluate_nodes(nodes, results, semantic_reviews={"N1": _review().to_dict()})
    assert out["node_verdicts"][0]["verdict"] == "pass"
    assert out["verdict"] == "pass"


def test_a_layer_integration_default_unchanged():
    nodes = [
        {
            "node_id": "N1",
            "objective": "o",
            "criteria": "c",
            "source": "rea_evidence",
            "verify": VERIFY_EVIDENCE,
            "evidence_id": "EV-1",
        }
    ]
    results = [{"node_id": "N1", "action": "CONTINUE", "detail": {}}]
    out = evaluate_nodes(nodes, results)
    assert out["node_verdicts"][0]["verdict"] == "degraded"
    assert out["node_verdicts"][0]["reason"] == "evidence_pending"
