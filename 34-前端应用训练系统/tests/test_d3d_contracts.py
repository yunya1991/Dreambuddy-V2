# -*- coding: utf-8 -*-
"""P0-D3D Phase 1 RED: 14 个契约模块 + E8/B1/H6/A6/C1 关闭项。

覆盖:
  TierPolicy / BrainstormTicket / ProposalBundle / EvidenceBundle /
  ExperimentPlan / DecisionRecord / AssistRequest / PresentationContract /
  FactLock / FactGate / FeishuBridge / ApprovalBridge / UrgentPolicy / Dispatcher
"""

import os
import sys
from dataclasses import replace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.approval_bridge import ApprovalBridge  # noqa: E402
from core.assist_request import (  # noqa: E402
    AssistInbox,
    AssistLedger,
    AssistRequest,
    AssistResult,
)
from core.brainstorm_dispatcher import dispatch_tasks  # noqa: E402
from core.brainstorm_ticket import create_ticket, transition  # noqa: E402
from core.d3d_evidence_bundle import EvidenceBundle, EvidenceItem  # noqa: E402
from core.decision_record import DecisionRecord, adopt_record, is_consumable  # noqa: E402
from core.experiment_result import ExperimentPlan, validate_plan  # noqa: E402
from core.fact_lock import (  # noqa: E402
    CanonicalFact,
    CaveatManifest,
    ChartData,
    ChartSeries,
    ChartSpec,
    FactUsage,
    FactUsageManifest,
    freeze_facts,
    validate_chart_data,
)
from core.feishu_authorization_bridge import (  # noqa: E402
    ApprovalRequest,
    build_grant,
    verify_grant,
)
from core.presentation_contract import PresentationArtifact, PresentationRequest  # noqa: E402
from core.presentation_gate import evaluate_presentation, extract_facts  # noqa: E402
from core.proposal_bundle import ProposalBundle, ProposalOption  # noqa: E402
from core.runtime_isolation import RuntimeIsolation  # noqa: E402
from core.tier_policy import TierInput, decide_tier  # noqa: E402
from core.urgent_policy import UrgentPolicy, UrgentPolicyRegistry  # noqa: E402

NOW = 1000.0


def _tier_input(**kw):
    data = {
        "risk_level": "low",
        "reversible": True,
        "blast_radius": "single_task",
        "evidence_gap_count": 0,
        "option_count": 1,
        "uncertainty_score": 0.1,
    }
    data.update(kw)
    return TierInput(**data)


def _ticket(**kw):
    data = {
        "ticket_id": "BT-1",
        "gap_key": "gap-1",
        "gap_statement": "回测未达标",
        "source_layer": "A",
        "evidence_refs": ("EV-1",),
        "tier_input": _tier_input(),
    }
    data.update(kw)
    return create_ticket(**data)


def _decision(**kw):
    data = {
        "decision_id": "DR-1",
        "ticket_id": "BT-1",
        "status": "draft",
        "chosen_option": "O-1",
        "rationale": "回测通过",
        "evidence_refs": ("EV-1",),
        "dissent": ("反方：样本不足"),
        "confidence": 0.8,
        "owner": "human",
        "expires_at": 2000.0,
    }
    data.update(kw)
    return DecisionRecord(**data)


def _fact(**kw):
    data = {
        "fact_id": "F-1",
        "name": "BTC 周度收益率",
        "value": 12.3,
        "unit": "%",
        "as_of": "2026-11-19",
        "source_ref": "19-DAL/btc",
        "confidence": 0.8,
        "caveat": "样本外未验证",
    }
    data.update(kw)
    return CanonicalFact(**data)


def _manifest(**kw):
    data = {
        "artifact_id": "PA-1",
        "fact_usages": (
            FactUsage(
                claim_id="C-1",
                fact_id="F-1",
                location="docx:paragraph:12",
                rendered_value="12.3%",
                transform="identity",
            ),
        ),
        "unmapped_claims": (),
        "chart_specs": (
            ChartSpec(
                chart_id="CH-1",
                chart_type="bar",
                source_fact_ids=("F-1",),
                unit="%",
            ),
        ),
        "caveats": (
            CaveatManifest(
                caveat_id="CV-1",
                location="docx:paragraph:30",
                text="样本外未验证",
                source="risks[0]",
            ),
        ),
    }
    data.update(kw)
    return FactUsageManifest(**data)


def _artifact(**kw):
    data = {
        "artifact_id": "PA-1",
        "uri": "outputs/report.docx",
        "format": "docx",
        "renderer": "hermes",
        "fact_bundle_hash": "sha256:placeholder",
        "fact_refs": ("F-1",),
        "supplementary_refs": (),
        "fact_usage_manifest": "outputs/report.fact-usage.json",
        "status": "VERIFIED",
        "consistency_report": "CR-1",
    }
    data.update(kw)
    return PresentationArtifact(**data)


# ---------- C1 TierPolicy ----------


def test_tier_critical_is_t3():
    assert decide_tier(_tier_input(risk_level="critical")).tier == "T3"


def test_tier_irreversible_is_t3():
    assert decide_tier(_tier_input(reversible=False)).tier == "T3"


def test_tier_cross_domain_is_t2():
    assert decide_tier(_tier_input(blast_radius="cross_domain")).tier == "T2"


def test_tier_evidence_gap_two_is_t2():
    assert decide_tier(_tier_input(evidence_gap_count=2)).tier == "T2"


def test_tier_uncertainty_high_is_t2():
    assert decide_tier(_tier_input(uncertainty_score=0.7)).tier == "T2"


def test_tier_two_options_is_t1():
    assert decide_tier(_tier_input(option_count=2)).tier == "T1"


def test_tier_uncertainty_medium_is_t1():
    assert decide_tier(_tier_input(uncertainty_score=0.4)).tier == "T1"


def test_tier_low_is_t0_and_has_reason():
    decision = decide_tier(_tier_input())
    assert decision.tier == "T0"
    assert decision.tier_reason
    assert decision.policy_version


# ---------- BrainstormTicket ----------


def test_ticket_created_with_tier_and_reason():
    ticket = _ticket(tier_input=_tier_input(option_count=2))
    assert ticket.tier == "T1"
    assert ticket.tier_reason
    assert ticket.status == "open"


def test_ticket_invalid_transition_returns_none():
    ticket = _ticket()
    assert transition(ticket, "decided") is None
    assert transition(ticket, "proposing").status == "proposing"


# ---------- ProposalBundle ----------


def test_proposal_requires_option_and_preserves_dissent():
    opt = ProposalOption(
        option_id="O-1",
        title="方案 A",
        assumptions=("流动性正常",),
        risks=("样本不足",),
        expected_effect="提升夏普",
        evidence_refs=("EV-1",),
    )
    bundle = ProposalBundle(
        bundle_id="PB-1",
        ticket_id="BT-1",
        options=(opt,),
        dissent=("反方：成本过高",),
    )
    assert bundle.validate() == []
    assert bundle.dissent == ("反方：成本过高",)


def test_proposal_empty_options_invalid():
    bundle = ProposalBundle(bundle_id="PB-1", ticket_id="BT-1", options=())
    assert "option_required" in bundle.validate()


# ---------- EvidenceBundle ----------


def test_evidence_requires_hash_and_replay():
    item = EvidenceItem(
        ref_id="EV-1",
        source_type="data",
        uri="s3://bucket/x",
        content_hash="sha256:abc",
        collected_at=NOW,
        replay_cmd="python run.py",
    )
    bundle = EvidenceBundle(bundle_id="EB-1", trace_id="rp-1", items=(item,))
    assert bundle.validate() == []


def test_evidence_missing_hash_invalid():
    item = EvidenceItem(
        ref_id="EV-1",
        source_type="data",
        uri="s3://bucket/x",
        content_hash="",
        collected_at=NOW,
        replay_cmd="",
    )
    bundle = EvidenceBundle(bundle_id="EB-1", trace_id="rp-1", items=(item,))
    errors = bundle.validate()
    assert "content_hash_required" in errors
    assert "replay_cmd_required" in errors


# ---------- ExperimentPlan ----------


def test_experiment_judgment_requires_human_signoff():
    plan = ExperimentPlan(
        experiment_id="EXP-1",
        decision_id="DR-1",
        hypothesis="A 优于 B",
        control="baseline",
        treatment="A",
        sample_size=0,
        metrics=(),
        thresholds={},
        run_id="",
        judgment=True,
        human_signoff=None,
    )
    errors = validate_plan(plan, tier="T2")
    assert "sample_size_required" in errors
    assert "human_signoff_required" in errors


# ---------- DecisionRecord ----------


def test_decision_adopt_and_consumable():
    record = adopt_record(_decision(), now=NOW)
    assert record.status == "adopted"
    assert record.decision_hash
    assert is_consumable(record, now=NOW + 1)


def test_decision_expired_not_consumable():
    record = adopt_record(_decision(), now=NOW)
    assert not is_consumable(record, now=3000)


def test_decision_tampered_not_consumable():
    record = adopt_record(_decision(), now=NOW)
    assert not is_consumable(replace(record, decision_hash="sha256:bad"), now=NOW + 1)


# ---------- AssistRequest ----------


def test_assist_default_non_blocking():
    request = AssistRequest(
        assist_id="A-1",
        ticket_id="TK-1",
        trace_id="rp-1",
        need="补充数据",
        allowed_tools=("recall",),
        budget={"max_attempts": 1},
    )
    assert request.blocking is False
    assert request.deadline_s == 300


def test_assist_ledger_dedup_and_limit():
    ledger = AssistLedger()
    assert ledger.allow("TK-1", "h1")
    assert not ledger.allow("TK-1", "h1")
    assert ledger.allow("TK-1", "h2")
    assert not ledger.allow("TK-1", "h3")


# ---------- PresentationContract ----------


def test_presentation_request_and_artifact_valid():
    request = PresentationRequest(
        request_id="PR-1",
        ticket_id="TK-1",
        format="docx",
        audience="internal",
        template="research-v1",
        language="zh-CN",
        length="8-12 pages",
        required_sections=("结论", "风险"),
        allow_supplementary_research=True,
        fact_bundle_id="FB-1",
    )
    assert request.validate() == []
    assert _artifact().validate() == []


def test_presentation_unsupported_format_invalid():
    request = PresentationRequest(
        request_id="PR-1",
        ticket_id="TK-1",
        format="exe",
        audience="internal",
        template="t",
        language="zh-CN",
        length="1",
        required_sections=(),
        allow_supplementary_research=False,
        fact_bundle_id="FB-1",
    )
    assert "unsupported_format" in request.validate()


def test_presentation_artifact_requires_manifest_and_status():
    artifact = replace(_artifact(), fact_usage_manifest="", status="UNKNOWN")
    errors = artifact.validate()
    assert "fact_usage_manifest_required" in errors
    assert "invalid_status" in errors


# ---------- FactLock ----------


def test_fact_bundle_hash_is_stable():
    bundle = freeze_facts((_fact(),))
    assert bundle.bundle_hash.startswith("sha256:")
    assert freeze_facts((_fact(),)).bundle_hash == bundle.bundle_hash


def test_manifest_unmapped_claims_invalid():
    manifest = replace(_manifest(), unmapped_claims=("C-2",))
    assert "unmapped_claims" in manifest.validate()


# ---------- FactGate ----------


def test_fact_gate_pass():
    bundle = freeze_facts((_fact(),))
    report = evaluate_presentation(_artifact(), _manifest(), bundle)
    assert report.verdict == "pass"
    assert report.changed == 0


def test_fact_gate_changed_value_fails():
    bundle = freeze_facts((_fact(),))
    manifest = _manifest(
        fact_usages=(
            FactUsage(
                claim_id="C-1",
                fact_id="F-1",
                location="docx:paragraph:12",
                rendered_value="12.5%",
                transform="identity",
            ),
        )
    )
    report = evaluate_presentation(_artifact(), manifest, bundle)
    assert report.verdict == "fail"
    assert report.changed == 1


def test_extract_docx_and_reject_scanned_pdf():
    assert extract_facts("docx", {"paragraphs": ["收益 12.3%"], "tables": []}) == ["12.3%"]
    with pytest.raises(ValueError):
        extract_facts("pdf", {"scanned": True})


# ---------- Feishu / ApprovalBridge ----------


def _approval_request(**kw):
    data = {
        "request_id": "AR-1",
        "gate_run_id": "GR-1",
        "node_id": "N1",
        "action": "rework.dispatch",
        "scope": ("rework.dispatch",),
        "ttl_s": 3600,
        "requested_by": "hermes_secretary",
        "reason": "驳回后重做",
        "high_risk": False,
    }
    data.update(kw)
    return ApprovalRequest(**data)


def test_grant_verify_and_nonce_replay():
    grant = build_grant(_approval_request(), subject="u1", secret="s", issued_at=NOW, nonce="n-1")
    assert verify_grant(grant, secret="s", used_nonces=set(), now=NOW + 1)
    assert not verify_grant(grant, secret="s", used_nonces={"n-1"}, now=NOW + 1)


def test_approval_bridge_idempotent_and_rejects_direct_write():
    grant = build_grant(_approval_request(), subject="u1", secret="s", issued_at=NOW, nonce="n-1")
    sink = []
    bridge = ApprovalBridge(secret="s", gateflow_sink=sink)
    assert bridge.write_grant(grant, now=NOW + 1)
    assert bridge.write_grant(grant, now=NOW + 2)
    assert len(sink) == 1
    assert not bridge.write_grant(replace(grant, signature="bad"), now=NOW + 3)
    assert not bridge.reject_direct_write("hermes")


# ---------- UrgentPolicy ----------


def test_urgent_policy_valid_and_gate_rejected():
    policy = UrgentPolicy(
        policy_id="UP-1",
        task_class="restart_service",
        risk="low",
        reversible=True,
        max_scope="single_service",
        max_budget=1.0,
        ttl_s=600,
        audit=True,
    )
    registry = UrgentPolicyRegistry()
    assert registry.register(policy) == []
    assert registry.can_auto_approve("UP-1", "restart_service")

    bad = replace(policy, task_class="gate_approval")
    assert "hard_exclusion" in registry.register(bad)


# ---------- Dispatcher ----------


def test_dispatcher_only_consumes_adopted_and_not_expired():
    record = adopt_record(_decision(), now=NOW)
    tasks = dispatch_tasks(
        record,
        ticket_id="BT-1",
        tasks=({"title": "t1"}, {"title": "t2"}),
        now=NOW + 1,
    )
    assert len(tasks) == 2
    assert tasks[0].source == "brainstorm"
    assert tasks[0].decision_id == "DR-1"
    assert dispatch_tasks(record, ticket_id="BT-1", tasks=({"title": "t1"},), now=3000) is None


# ---------- E8 四格式 + chart_data ----------


def test_extract_four_formats():
    assert "12.3%" in extract_facts("docx", {"paragraphs": ["收益 12.3%"], "tables": []})
    assert "12.3%" in extract_facts("pptx", {"slides": ["收益 12.3%"]})
    assert "12.3%" in extract_facts("xlsx", {"cells": {"A1": "12.3%"}})
    assert "12.3%" in extract_facts("pdf", {"text": "收益 12.3%"})


def test_chart_data_matches_spec_and_rejects_mismatch():
    data = ChartData(
        chart_id="CH-1",
        series=(ChartSeries(name="收益", x=("2026-11-19",), y=(12.3,)),),
        source_fact_ids=("F-1",),
    )
    assert validate_chart_data((data,), _manifest().chart_specs) == []
    bad = replace(data, source_fact_ids=("F-2",))
    assert "chart_source_mismatch:CH-1" in validate_chart_data((bad,), _manifest().chart_specs)


# ---------- A6 异步结果投递 ----------


def test_assist_inbox_delivers_partial_once():
    inbox = AssistInbox()
    partial = AssistResult(
        assist_id="A-1",
        status="partial",
        output="已补一半",
        partial_reason="timeout",
    )
    assert inbox.deliver(partial)
    assert not inbox.deliver(partial)
    assert inbox.get("A-1") == partial
    assert len(inbox.drain()) == 1


# ---------- H6 紧急策略边界 ----------


def test_urgent_policy_rejects_live_and_irreversible():
    base = UrgentPolicy(
        policy_id="UP-1",
        task_class="restart_service",
        risk="low",
        reversible=True,
        max_scope="single_service",
        max_budget=1.0,
        ttl_s=600,
        audit=True,
    )
    registry = UrgentPolicyRegistry()
    assert "hard_exclusion" in registry.register(
        replace(base, policy_id="UP-2", task_class="live_trade")
    )
    assert "irreversible" in registry.register(replace(base, policy_id="UP-3", reversible=False))


def test_urgent_policy_auto_only_whitelist():
    policy = UrgentPolicy(
        policy_id="UP-1",
        task_class="restart_service",
        risk="low",
        reversible=True,
        max_scope="single_service",
        max_budget=1.0,
        ttl_s=600,
        audit=True,
    )
    registry = UrgentPolicyRegistry()
    registry.register(policy)
    assert not registry.can_auto_approve("UP-1", "other_task")
    assert not registry.can_auto_approve("UP-X", "restart_service")


# ---------- B1 运行时隔离 ----------


def test_runtime_isolation_valid_and_rejects_credentials():
    valid = RuntimeIsolation(
        allowed_egress=("47-mcp", "approval-bridge"),
        writable_paths=("workspace", "tmp"),
    )
    assert valid.validate() == []

    bad = replace(valid, dsh_credentials=True, dsh_internal_reachable=True, allowed_egress=())
    errors = bad.validate()
    assert "dsh_credentials_forbidden" in errors
    assert "dsh_internal_network_forbidden" in errors
    assert "egress_allowlist_required" in errors
