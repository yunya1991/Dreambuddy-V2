"""策略工厂审批对接模块。

审批请求创建、查询、状态校验。
不含 LLM 审批分析师（保留在大文件，随通用审批能力拆分）。
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any, Dict, Optional

# 延迟导入依赖
def _dep(name):
    import ml_trade_service as _mts
    return getattr(_mts, name)

def _agent_emit_envelope_event(*a, **k): return _dep("_agent_emit_envelope_event")(*a, **k)
def _agent_outbox_append_jsonl(*a, **k): return _dep("_agent_outbox_append_jsonl")(*a, **k)
def _approvals_log_path(*a, **k): return _dep("_approvals_log_path")(*a, **k)
def _audit_base_payload(*a, **k): return _dep("_audit_base_payload")(*a, **k)
def _audit_emit_action(*a, **k): return _dep("_audit_emit_action")(*a, **k)
def _doc_refs_default(*a, **k): return _dep("_doc_refs_default")(*a, **k)
def _doc_refs_sanitize(*a, **k): return _dep("_doc_refs_sanitize")(*a, **k)
def _evidence_sanitize(*a, **k): return _dep("_evidence_sanitize")(*a, **k)
def _governance_baseline_judge(*a, **k): return _dep("_governance_baseline_judge")(*a, **k)
def _governance_env_name(*a, **k): return _dep("_governance_env_name")(*a, **k)
def _governance_has_improvement(*a, **k): return _dep("_governance_has_improvement")(*a, **k)
def _governance_tighten_only(*a, **k): return _dep("_governance_tighten_only")(*a, **k)
def _json_sanitize(*a, **k): return _dep("_json_sanitize")(*a, **k)
def _mts(*a, **k): return _dep("_mts")(*a, **k)
def _now_ms(*a, **k): return _dep("_now_ms")(*a, **k)
def _tail_lines(*a, **k): return _dep("_tail_lines")(*a, **k)

def _approval_request_for_changeset_draft(*, trace_id: str, draft_id: str, draft: Dict[str, Any], action: str) -> Optional[str]:
    did = str(draft_id or "").strip()
    if not did:
        return None
    chg = draft.get("changeset") if isinstance(draft.get("changeset"), dict) else {}
    gate = draft.get("gate_result") if isinstance(draft.get("gate_result"), dict) else {}
    doc_refs = _doc_refs_sanitize(draft.get("doc_refs"))
    evidence = draft.get("evidence") if isinstance(draft.get("evidence"), dict) else {}
    reason = str(chg.get("reason") or action).strip() or str(action or "config.apply")
    cbd = draft.get("change_bundle_draft") if isinstance(draft.get("change_bundle_draft"), dict) else {}
    env = _governance_env_name()
    if isinstance(cbd, dict):
        gov_obj = cbd.get("governance") if isinstance(cbd.get("governance"), dict) else {}
        gov_obj = dict(gov_obj)
        gov_obj["env"] = env
        cbd["governance"] = gov_obj
        draft["change_bundle_draft"] = cbd

    if env == "explore":
        if isinstance(cbd, dict):
            gov_obj = cbd.get("governance") if isinstance(cbd.get("governance"), dict) else {}
            gov_obj = dict(gov_obj)
            gov_obj.update({"decision": "no_approval_explore", "approval_required": False})
            cbd["governance"] = gov_obj
            draft["change_bundle_draft"] = cbd
        return None

    delta_metrics = (cbd.get("delta_metrics") if isinstance(cbd, dict) else None)
    baseline_ref = (cbd.get("baseline_ref") if isinstance(cbd, dict) else None)
    has_baseline = bool(str(baseline_ref or "").strip()) and isinstance(delta_metrics, dict) and bool(delta_metrics)
    baseline_judge = (_governance_baseline_judge(delta_metrics) if bool(has_baseline) else {"ok": False, "decision": "inconclusive", "reasons": ["missing_baseline"]})
    baseline_decision = str((baseline_judge or {}).get("decision") or "").strip().lower()
    baseline_worse = bool(has_baseline) and baseline_decision == "hard_reject"
    baseline_soft_warn = bool(has_baseline) and baseline_decision == "soft_warn"
    if baseline_worse:
        try:
            rid0 = _approval_append(
                {
                    "trace_id": str(trace_id),
                    "approver": "system",
                    "decision": "reject",
                    "reason": "baseline_worse_auto_reject",
                    "action": str(action or "config.apply").strip() or "config.apply",
                    "draft_id": did,
                    "changeset": chg,
                    "gate_results": gate,
                    "doc_refs": doc_refs,
                    "evidence": {"baseline_ref": baseline_ref, "delta_metrics": _json_sanitize(delta_metrics), "baseline_judge": _json_sanitize(baseline_judge)},
                    "ts": int(_now_ms()),
                    "scope": "governance",
                }
            )
        except Exception:
            rid0 = None
        try:
            _agent_emit_envelope_event(
                event="governance.auto_reject",
                trace_id=str(trace_id),
                severity="warning",
                intent_level="L2",
                ts_ms=int(_now_ms()),
                inputs={"action": str(action), "draft_id": did, "baseline_ref": baseline_ref},
                evidence=[{"type": "approvals_log", "id": rid0, "path": str(_approvals_log_path())}],
                outputs={"ok": False, "error": "baseline_worse_auto_reject", "approval_id": rid0},
                doc_refs=_doc_refs_default(),
            )
        except Exception:
            pass
        if isinstance(cbd, dict):
            gov_obj = cbd.get("governance") if isinstance(cbd.get("governance"), dict) else {}
            gov_obj = dict(gov_obj)
            gov_obj.update({"decision": "auto_reject", "approval_required": False, "reason": "baseline_worse", "baseline_judge": baseline_judge})
            cbd["governance"] = gov_obj
            draft["change_bundle_draft"] = cbd
        return None

    change_tags = (cbd.get("change_tags") if isinstance(cbd, dict) else None)
    tighten_only = _governance_tighten_only(change_tags)
    improved = bool(has_baseline) and _governance_has_improvement(delta_metrics)
    if tighten_only and improved and (not baseline_soft_warn):
        ent2 = {
            "trace_id": str(trace_id),
            "approver": "system",
            "decision": "approved",
            "reason": "auto_approved_tighten_only",
            "action": str(action or "config.apply").strip() or "config.apply",
            "draft_id": did,
            "changeset": chg,
            "gate_results": gate,
            "doc_refs": doc_refs,
            "evidence": evidence,
            "ts": int(_now_ms()),
            "scope": "governance",
        }
        rid2 = _approval_append(ent2)
        if rid2 and isinstance(cbd, dict):
            gov_obj = cbd.get("governance") if isinstance(cbd.get("governance"), dict) else {}
            gov_obj = dict(gov_obj)
            gov_obj.update({"decision": "auto_approved", "approval_required": False, "approval_id": rid2, "reason": "tighten_only_improved", "baseline_judge": baseline_judge})
            cbd["governance"] = gov_obj
            draft["change_bundle_draft"] = cbd
        return rid2

    ent = {
        "trace_id": str(trace_id),
        "decision": "pending",
        "reason": reason,
        "action": str(action or "config.apply").strip() or "config.apply",
        "draft_id": did,
        "changeset": chg,
        "gate_results": gate,
        "doc_refs": doc_refs,
        "evidence": evidence,
        "ts": int(_now_ms()),
        "scope": "governance",
    }
    rid = _approval_append(ent)
    if not rid:
        return None
    if isinstance(cbd, dict):
        gov_obj = cbd.get("governance") if isinstance(cbd.get("governance"), dict) else {}
        gov_obj = dict(gov_obj)
        gov_obj.update({"decision": ("soft_warn" if baseline_soft_warn else "approval_required"), "approval_required": True, "approval_id": rid, "baseline_judge": baseline_judge})
        cbd["governance"] = gov_obj
        draft["change_bundle_draft"] = cbd
    try:
        _agent_outbox_append_jsonl(
            "chat.jsonl",
            {
                "id": rid,
                "trace_id": str(trace_id),
                "ts": int(_now_ms()),
                "type": "approval.requested",
                "channel": "skills",
                "reason": reason,
                "input": _json_sanitize({"action": str(action), "draft_id": did}),
            },
        )
    except Exception:
        pass
    try:
        _audit_emit_action(
            "approval.requested",
            _audit_base_payload(scope="governance", action="approval.requested", trace_id=str(trace_id), extra={"ok": True, "approval_id": rid, "draft_id": did, "action": str(action)}),
        )
    except Exception:
        pass
    return rid


def _approval_append(entry: Dict[str, Any]) -> Optional[str]:
    now_ms = int(_now_ms())
    obj = dict(entry) if isinstance(entry, dict) else {}
    rid = str(obj.get("id") or "").strip()
    if not rid:
        rid = hashlib.sha256(f"approval|{now_ms}|{uuid.uuid4().hex}".encode("utf-8")).hexdigest()[:16]
        obj["id"] = rid
    if obj.get("ts") is None or str(obj.get("ts")).strip() == "":
        obj["ts"] = now_ms

    gate_results = obj.get("gate_results") if isinstance(obj.get("gate_results"), dict) else {}
    obj["doc_refs"] = _doc_refs_sanitize(obj.get("doc_refs"))
    obj["evidence"] = _evidence_sanitize(obj.get("evidence"), gate_results=gate_results)
    try:
        q = _approvals_log_path()
        with open(q, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception:
        return None
    return rid


def _approval_lookup(approval_id: str, *, max_lines: int = 4000, max_bytes: int = 2_000_000) -> Optional[Dict[str, Any]]:
    aid = str(approval_id or "").strip()
    if not aid:
        return None
    p = _approvals_log_path()
    if not p.exists() or (not p.is_file()):
        return None
    lines = _tail_lines(p, max_lines=int(max_lines), max_bytes=int(max_bytes))
    for ln in reversed(lines):
        s = str(ln or "").strip("\n")
        if not s.strip():
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("id") or "").strip() != aid:
            continue
        return obj
    return None


def _approval_ok(approval_id: str, *, max_age_ms: int = 86400_000) -> bool:
    obj = _approval_lookup(approval_id)
    if not isinstance(obj, dict) or not obj:
        return False
    dec = str(obj.get("decision") or "").strip().lower()
    if dec not in ("approve", "approved", "ok", "pass", "yes"):
        return False
    try:
        ts = int(obj.get("ts") or 0)
    except Exception:
        ts = 0
    if ts <= 0:
        return False
    now_ms = int(_now_ms())
    return (now_ms - ts) <= int(max_age_ms)



__all__ = ["_approval_request_for_changeset_draft", "_approval_append", "_approval_lookup", "_approval_ok"]
