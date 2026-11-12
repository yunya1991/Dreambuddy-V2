"""T-G14 三层分级器 + 研发流水线 — RED 测试

SPEC-33-G §2.11.1 / §2.11.2 / §2.11.4 / §2.11.5：
  - 分级由 classify 确定性判定，LLM 不得自定级：
      ≥2 编号目录 / 改公共契约 / 改 schema / 改依赖方向 / >3 文件或 >200 行 → L3
      单模块内 ≤3 文件 ≤200 行且不改对外契约 → L2
      只改规则/权重/SKILL → L1
      无法判定 → 默认 L3（保守）
  - 五段流水线：路由(DreamOS) → 脑暴(双链) → 研发(DSH 子 Agent) → 取证(L0) → 门禁
  - 产物契约：research_artifact.json + dev_artifact.json + evidence_refs 三者缺一不得进门禁
  - L2：新增外部依赖降级 L3；stateful 禁止自动（L2-9）；自动合入未开启（L2-7）
  - L3：只出 ADR + SPEC，禁止代码变更

RED 契约：core.evolution.research_pipeline 不存在。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from core.evolution.research_pipeline import (
    ChangeClassifier,
    PipelineError,
    ResearchPipeline,
    classify_change,
)

BASE = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=BASE):
        self.now = now

    def __call__(self):
        return self.now


# ---------------------------------------------------------------- 分级器


def _scope(**overrides):
    payload = {
        "files": ["33-REA逆向解析工程/core/evolution/demo.py"],
        "lines_changed": 40,
    }
    payload.update(overrides)
    return payload


def test_classify_single_module_small_change_is_l2():
    result = classify_change(
        **_scope(
            files=[
                "33-REA逆向解析工程/core/evolution/a.py",
                "33-REA逆向解析工程/core/evolution/b.py",
            ]
        )
    )
    assert result["level"] == "L2"
    assert result["module"] == "33-REA逆向解析工程"


def test_classify_two_numbered_dirs_is_l3():
    result = classify_change(
        **_scope(
            files=[
                "33-REA逆向解析工程/core/evolution/a.py",
                "4-MEMORY/9-工具与接口/b.py",
            ]
        )
    )
    assert result["level"] == "L3"
    assert any("编号目录" in reason for reason in result["reasons"])


@pytest.mark.parametrize(
    "flag,keyword",
    [
        ("changes_contract", "公共契约"),
        ("changes_schema", "schema"),
        ("changes_dependency_direction", "依赖方向"),
    ],
)
def test_classify_architecture_triggers_are_l3(flag, keyword):
    result = classify_change(**_scope(**{flag: True}))
    assert result["level"] == "L3"
    assert any(keyword in reason for reason in result["reasons"])


def test_classify_new_dependency_downgrades_to_l3():
    result = classify_change(**_scope(adds_dependency=True))
    assert result["level"] == "L3"
    assert any("依赖" in reason for reason in result["reasons"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"files": [f"33-REA逆向解析工程/core/evolution/m{i}.py" for i in range(4)]},
        {"lines_changed": 201},
    ],
)
def test_classify_size_limits_are_l3(overrides):
    result = classify_change(**_scope(**overrides))
    assert result["level"] == "L3"
    assert any("文件" in reason or "行" in reason for reason in result["reasons"])


def test_classify_rule_only_is_l1():
    result = classify_change(
        **_scope(
            files=["33-REA逆向解析工程/policy/rea_rules.yaml"],
            lines_changed=5,
            rule_only=True,
        )
    )
    assert result["level"] == "L1"
    assert result["module"] == "33-REA逆向解析工程"


def test_classify_rule_only_with_code_is_l3():
    result = classify_change(
        **_scope(
            rule_only=True,
            files=[
                "33-REA逆向解析工程/policy/rea_rules.yaml",
                "33-REA逆向解析工程/core/evolution/a.py",
            ],
        )
    )
    assert result["level"] == "L3"
    assert any("代码" in reason for reason in result["reasons"])


def test_classify_unknown_module_defaults_to_l3():
    result = classify_change(**_scope(files=["scratch/demo.py"]))
    assert result["level"] == "L3"
    assert any("保守" in reason or "无法判定" in reason for reason in result["reasons"])


def test_classifier_is_reusable_instance():
    classifier = ChangeClassifier(max_files=3, max_lines=200)
    assert classifier.classify(**_scope())["level"] == "L2"


# ---------------------------------------------------------------- 流水线


def _proposal(**overrides):
    payload = {
        "proposal_id": "P-20261111-01",
        "level": "L2",
        "trigger": "capability_gap",
        "claim": "把取证步骤前移可减少无证据改动",
        "falsifier": "若取证后仍出现无证据改动则证伪",
        "change": {
            "files": ["33-REA逆向解析工程/core/evolution/demo.py"],
            "lines_changed": 30,
        },
    }
    payload.update(overrides)
    return payload


def _route(_proposal):
    return {"route": "workers", "reason": "evolution 研发", "matched": ["evolution"]}


def _brainstorm(_proposal):
    return {
        "plan_cards": [{"card_id": "A-1"}, {"card_id": "B-1"}],
        "sides": [
            {"side": "A", "model": "model-a", "evidence_path": "unified_search+recall"},
            {"side": "B", "model": "model-b", "evidence_path": "dreamos.intent+registry"},
        ],
    }


def _develop(_proposal, _route_result):
    return [
        {
            "module": "technical",
            "summary": "实现取证前移",
            "signals": [{"type": "code", "title": "diff"}],
            "charts": [],
            "evidence_refs": ["EV-DEV-1"],
            "artifact_uri": "artifact://dev-1",
            "code_changes": ["33-REA逆向解析工程/core/evolution/demo.py"],
        }
    ]


def _evidence(_proposal, _dev_outputs):
    return ["EV-L0-REA-1", "EV-L0-DATA-2"]


def _gate_pass(_proposal, _artifacts):
    return {"overall": "pass", "gates": [{"gate": 1, "status": "pass"}]}


def _pipeline(tmp_path, **overrides):
    kwargs = {
        "root": tmp_path / "research",
        "clock": Clock(),
        "max_explorations_per_week": 2,
        "max_l2_changes_per_week": 2,
    }
    kwargs.update(overrides)
    return ResearchPipeline(**kwargs)


def _run(pipeline, proposal=None, **overrides):
    kwargs = {
        "route": _route,
        "brainstorm": _brainstorm,
        "develop": _develop,
        "collect_evidence": _evidence,
        "gate": _gate_pass,
    }
    kwargs.update(overrides)
    return pipeline.run(proposal or _proposal(), **kwargs)


def test_pipeline_happy_path_writes_three_artifacts(tmp_path):
    pipeline = _pipeline(tmp_path)
    result = _run(pipeline)

    assert result["level"] == "L2"
    assert result["state"] == "qualified"
    assert result["evidence_refs"] == ["EV-L0-REA-1", "EV-L0-DATA-2"]

    artifact_dir = tmp_path / "research" / "P-20261111-01"
    assert (artifact_dir / "research_artifact.json").is_file()
    assert (artifact_dir / "dev_artifact.json").is_file()
    assert (artifact_dir / "evidence_refs.json").is_file()
    assert (tmp_path / "research" / "pipeline_runs.jsonl").is_file()


def test_pipeline_overrides_llm_declared_level(tmp_path):
    """LLM 自报 L1，但改动跨两个编号目录 → 必须按 L3 处理。"""
    proposal = _proposal(
        level="L1",
        change={
            "files": [
                "33-REA逆向解析工程/core/evolution/a.py",
                "4-MEMORY/9-工具与接口/b.py",
            ],
            "lines_changed": 20,
        },
    )
    result = _run(
        _pipeline(tmp_path),
        proposal=proposal,
        develop=lambda _p, _r: [
            {
                "module": "arch",
                "summary": "ADR 草案",
                "kind": "adr",
                "signals": [],
                "charts": [],
                "evidence_refs": ["EV-1"],
                "artifact_uri": "artifact://adr",
            }
        ],
    )

    assert result["level"] == "L3"
    assert result["declared_level"] == "L1"
    assert result["level_source"] == "classifier"


def test_pipeline_rejects_brainstorm_without_distinct_sides(tmp_path):
    def same_chain(_proposal):
        return {
            "plan_cards": [{"card_id": "A-1"}, {"card_id": "B-1"}],
            "sides": [
                {"side": "A", "model": "same", "evidence_path": "same"},
                {"side": "B", "model": "same", "evidence_path": "same"},
            ],
        }

    with pytest.raises(PipelineError) as excinfo:
        _run(_pipeline(tmp_path), brainstorm=same_chain)
    assert "两链" in str(excinfo.value) or "不同" in str(excinfo.value)


def test_pipeline_rejects_change_without_l0_evidence(tmp_path):
    with pytest.raises(PipelineError) as excinfo:
        _run(_pipeline(tmp_path), collect_evidence=lambda _p, _d: [])
    assert "Evidence" in str(excinfo.value) or "取证" in str(excinfo.value)


def test_pipeline_rejects_l3_code_changes(tmp_path):
    proposal = _proposal(
        change={
            "files": [
                "33-REA逆向解析工程/core/a.py",
                "4-MEMORY/9-工具与接口/b.py",
            ],
            "lines_changed": 10,
        }
    )

    def code_dev(_proposal, _route_result):
        return [
            {
                "module": "technical",
                "summary": "直接改代码",
                "signals": [{"type": "code"}],
                "charts": [],
                "evidence_refs": ["EV-1"],
                "artifact_uri": "artifact://dev",
                "code_changes": ["33-REA逆向解析工程/core/a.py"],
            }
        ]

    with pytest.raises(PipelineError) as excinfo:
        _run(_pipeline(tmp_path), proposal=proposal, develop=code_dev)
    assert "L3" in str(excinfo.value) and "ADR" in str(excinfo.value)


def test_pipeline_stateful_l2_never_auto_merges(tmp_path):
    result = _run(
        _pipeline(tmp_path),
        proposal=_proposal(
            change={
                "files": ["33-REA逆向解析工程/core/evolution/demo.py"],
                "lines_changed": 30,
                "stateful": True,
            }
        ),
    )
    assert result["level"] == "L2"
    assert result["auto_merge"]["allowed"] is False
    assert "L2-9" in result["auto_merge"]["reason"]


def test_pipeline_l2_auto_merge_stays_closed(tmp_path):
    result = _run(_pipeline(tmp_path))
    assert result["auto_merge"]["allowed"] is False
    assert "L2-7" in result["auto_merge"]["reason"]


def test_pipeline_weekly_exploration_budget(tmp_path):
    pipeline = _pipeline(tmp_path, max_explorations_per_week=2)
    _run(pipeline, _proposal(proposal_id="P-1"))
    _run(pipeline, _proposal(proposal_id="P-2"))

    with pytest.raises(PipelineError) as excinfo:
        _run(pipeline, _proposal(proposal_id="P-3"))
    assert "预算" in str(excinfo.value) or "配额" in str(excinfo.value)


def test_pipeline_records_gate_failure(tmp_path):
    result = _run(
        _pipeline(tmp_path),
        gate=lambda _p, _a: {"overall": "fail", "gates": []},
    )
    assert result["state"] == "gates_failed"


def test_completion_rate_counts_deliverables(tmp_path):
    pipeline = _pipeline(tmp_path, max_explorations_per_week=5)
    _run(pipeline, _proposal(proposal_id="P-1"))
    _run(
        pipeline, _proposal(proposal_id="P-2"), gate=lambda _p, _a: {"overall": "fail", "gates": []}
    )

    rate = pipeline.completion_rate(window_days=28)
    assert rate["total"] == 2
    assert rate["deliverable"] == 1
    assert rate["rate"] == 0.5
