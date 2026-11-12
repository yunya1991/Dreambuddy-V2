"""T-G12 Case 结构化契约 + 完成硬门禁 — RED 测试

SPEC-33-G §2.12 / §3 T-G12 / G-G11：
  - Case 为结构化三元组，字段完整率 100%，缺字段即失败
  - Case 不入库不算完成（硬门禁，非 FAIL-OPEN）
  - 写入后立即触发 verify(outcome=...)

RED 契约：core.evolution.case_ledger 模块不存在。
"""

from __future__ import annotations

import pytest
from core.evolution.case_ledger import (
    CaseContractError,
    CaseStore,
    case_to_outcome,
    require_case,
)

VALID_CASE = {
    "case_id": "C-20261111-01",
    "iteration_id": "SPEC-33-G/T-G12",
    "goal": "落地 Case 契约",
    "hypotheses": [{"claim": "结构化 Case 可计算", "falsifier": "无法聚类"}],
    "changes": {"files": 2, "loc": 80, "modules": ["33-REA"], "level": "L2"},
    "verification": {"tests": 10, "passed": 10, "duration_s": 3, "gates": ["sandbox"]},
    "outcome": {"accepted": True, "reverted": False, "reviewer": "auto"},
    "defects": [],
    "lessons": ["Case 必须结构化"],
    "policy_id": None,
    "evidence_refs": ["E-1"],
    "created_at": "2026-11-11T10:00:00+00:00",
}


def test_case_store_rejects_missing_field(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    broken = dict(VALID_CASE)
    broken.pop("lessons")
    with pytest.raises(CaseContractError, match="lessons"):
        store.add(broken)


def test_case_store_rejects_hypothesis_without_falsifier(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    bad = {**VALID_CASE, "hypotheses": [{"claim": "x"}]}
    with pytest.raises(CaseContractError, match="falsifier"):
        store.add(bad)


def test_case_store_persists_and_reads(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    store.add(VALID_CASE)
    assert store.exists("SPEC-33-G/T-G12")
    assert store.get("SPEC-33-G/T-G12")["case_id"] == "C-20261111-01"


def test_require_case_is_hard_gate(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    with pytest.raises(CaseContractError, match="未产生结构化 Case"):
        require_case("SPEC-33-G/NOT-DONE", store)

    store.add(VALID_CASE)
    assert require_case("SPEC-33-G/T-G12", store)["case_id"] == "C-20261111-01"


def test_case_to_outcome_feeds_verify(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    case = store.add(VALID_CASE)
    outcome = case_to_outcome(case)
    assert outcome == {"accepted": True, "tests_pass": True, "reverted": False}
