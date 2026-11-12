"""T-G3 涌现回灌 — RED 测试

SPEC-33-G G-G3 / §2.12.3：
  - 方法论模板 + 同类 Case（≥5 条、跨 ≥3 次迭代）→ 候选规则
  - C 级记忆不进候选池（硬约束 13）
  - 候选规则必须过八门禁（全 pass）才能写入 `rea_rules.yaml`
  - 回灌后规则带来源候选、Evidence、晋级时间

RED 契约：core.evolution.emergence 不存在。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from core.evolution.emergence import (
    CandidateError,
    EmergenceEngine,
)

BASE = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=BASE):
        self.now = now

    def __call__(self):
        return self.now


def _template(**overrides):
    payload = {
        "template_id": "MT-001",
        "name": "取证前移模板",
        "when": "研发改动缺少 L0 Evidence",
        "then": "在门禁前强制补取证",
        "evidence_refs": ["EV-1", "EV-2"],
    }
    payload.update(overrides)
    return payload


def _cases(count=5, iterations=3, quality="B"):
    return [
        {
            "case_id": f"C-{index}",
            "iteration_id": f"ITER-{index % iterations}",
            "quality_level": quality,
            "module": "33-REA逆向解析工程",
        }
        for index in range(count)
    ]


def _engine(tmp_path, **overrides):
    kwargs = {"root": tmp_path / "evolution", "clock": Clock()}
    kwargs.update(overrides)
    return EmergenceEngine(**kwargs)


def _gate_pass():
    return {
        "overall": "pass",
        "gates": [{"gate": index, "status": "pass"} for index in range(1, 9)],
    }


def test_candidates_from_template_happy_path(tmp_path):
    engine = _engine(tmp_path)
    candidates = engine.candidates_from_template(_template(), _cases())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["status"] == "candidate"
    assert candidate["source_template"] == "MT-001"
    assert candidate["when"] == "研发改动缺少 L0 Evidence"

    path = tmp_path / "evolution" / "candidates" / "rules.jsonl"
    assert path.is_file()
    assert (
        json.loads(path.read_text(encoding="utf-8").splitlines()[0])["candidate_id"]
        == candidate["candidate_id"]
    )


def test_candidates_require_five_cases(tmp_path):
    with pytest.raises(CandidateError) as excinfo:
        _engine(tmp_path).candidates_from_template(_template(), _cases(count=4))
    assert "5" in str(excinfo.value) or "案例" in str(excinfo.value)


def test_candidates_require_three_iterations(tmp_path):
    with pytest.raises(CandidateError) as excinfo:
        _engine(tmp_path).candidates_from_template(_template(), _cases(count=6, iterations=2))
    assert "迭代" in str(excinfo.value)


def test_candidates_reject_c_level_memories(tmp_path):
    with pytest.raises(CandidateError) as excinfo:
        _engine(tmp_path).candidates_from_template(_template(), _cases(quality="C"))
    assert "C 级" in str(excinfo.value) or "候选池" in str(excinfo.value)


def test_candidates_require_two_evidences(tmp_path):
    with pytest.raises(CandidateError) as excinfo:
        _engine(tmp_path).candidates_from_template(_template(evidence_refs=["EV-1"]), _cases())
    assert "Evidence" in str(excinfo.value) or "证据" in str(excinfo.value)


def test_promote_writes_rea_rules_yaml(tmp_path):
    engine = _engine(tmp_path)
    candidate = engine.candidates_from_template(_template(), _cases())[0]

    result = engine.promote(candidate["candidate_id"], gate_summary=_gate_pass())

    assert result["rule_id"] == "RULE-0001"
    rules_path = tmp_path / "evolution" / "rea_rules.yaml"
    content = rules_path.read_text(encoding="utf-8")
    assert "RULE-0001" in content
    assert "取证前移模板" in content
    assert "MT-001" in content

    registry = json.loads(
        (tmp_path / "evolution" / "rules_registry.json").read_text(encoding="utf-8")
    )
    assert registry["rules"][0]["rule_id"] == "RULE-0001"
    assert engine.candidates() == []


def test_promote_rejects_incomplete_gates(tmp_path):
    engine = _engine(tmp_path)
    candidate = engine.candidates_from_template(_template(), _cases())[0]
    bad_gate = {"overall": "fail", "gates": [{"gate": 1, "status": "fail"}]}

    with pytest.raises(CandidateError) as excinfo:
        engine.promote(candidate["candidate_id"], gate_summary=bad_gate)
    assert "八门禁" in str(excinfo.value) or "门禁" in str(excinfo.value)


def test_promote_unknown_candidate(tmp_path):
    with pytest.raises(CandidateError) as excinfo:
        _engine(tmp_path).promote("RULE-C-999", gate_summary=_gate_pass())
    assert "不存在" in str(excinfo.value) or "未找到" in str(excinfo.value)


def test_promote_numbers_increment(tmp_path):
    engine = _engine(tmp_path)
    first = engine.candidates_from_template(_template(), _cases())[0]
    second = engine.candidates_from_template(
        _template(template_id="MT-002", name="第二个模板"), _cases()
    )[0]

    assert (
        engine.promote(first["candidate_id"], gate_summary=_gate_pass())["rule_id"] == "RULE-0001"
    )
    assert (
        engine.promote(second["candidate_id"], gate_summary=_gate_pass())["rule_id"] == "RULE-0002"
    )
