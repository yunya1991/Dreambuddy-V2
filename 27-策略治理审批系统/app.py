"""
27-策略治理审批系统 - Flask 服务（端口 8094）

提供完整的治理审批能力链：
- C0-C8 流水线状态管理
- 变更包草稿构建与查询
- 审批请求创建、查询、状态校验
- 审计哈希链查询与完整性验证
- 评估门控（gate）评估
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, request

# 确保模块可导入
_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from governance.approval import engine as approval_engine
from governance.audit.chain import (
    audit_query,
    audit_verify_chain,
    strategy_factory_audit,
)
from governance.changeset.builder import (
    _agent_changeset_draft_build,
    _agent_changeset_draft_lookup,
    _agent_config_patch_validate,
)
from governance.pipeline.state import (
    PIPELINE_STAGES,
    VALID_STATES,
    _pipeline_create_state,
    _pipeline_list,
    _pipeline_load,
    _pipeline_save,
    _pipeline_update_stage,
)
from governance.utils import (
    CONFIG,
    _audit_emit_action,
    _audit_base_payload,
    _config_save,
    _governance_env_name,
    _now_ms,
)

app = Flask(__name__)


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Token, X-User-Id"
    return resp


# Admin token
ADMIN_TOKEN = os.environ.get("GOVERNANCE_ADMIN_TOKEN", "dev-governance-token-2026")


def _require_admin() -> bool:
    token = request.headers.get("X-Admin-Token", "")
    return token == ADMIN_TOKEN


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    env = _governance_env_name()
    chain_status = audit_verify_chain()
    return jsonify({
        "ok": True,
        "module": "27-策略治理审批系统",
        "port": int(os.environ.get("GOVERNANCE_PORT", "8094")),
        "governance_env": env,
        "audit_chain": chain_status,
        "config_keys": len(CONFIG),
    })


# ---------------------------------------------------------------------------
# 流水线 API（C0-C8）
# ---------------------------------------------------------------------------

@app.route("/api/v1/pipeline/create", methods=["POST"])
def pipeline_create():
    """创建新的流水线状态。"""
    body = request.get_json(force=True) or {}
    trace_id = str(body.get("trace_id") or f"trace_{uuid.uuid4().hex[:12]}").strip()
    strategy_id = str(body.get("strategy_id") or "").strip()
    source_zip = str(body.get("source_zip") or "").strip()
    state = _pipeline_create_state(trace_id, strategy_id, source_zip)
    _pipeline_save(state)
    try:
        _audit_emit_action("pipeline.create", _audit_base_payload(
            scope="governance", action="pipeline.create", trace_id=trace_id,
            extra={"strategy_id": strategy_id, "source_zip": source_zip}))
    except Exception:
        pass
    return jsonify({"ok": True, "state": state})


@app.route("/api/v1/pipeline/state/<trace_id>", methods=["GET"])
def pipeline_get_state(trace_id):
    """获取流水线状态。"""
    state = _pipeline_load(trace_id)
    if state is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "state": state})


@app.route("/api/v1/pipeline/stage/<trace_id>/<stage>", methods=["PUT"])
def pipeline_update_stage(trace_id, stage):
    """更新流水线阶段状态。"""
    if not _require_admin():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    if stage not in PIPELINE_STAGES:
        return jsonify({"ok": False, "error": f"invalid_stage: {stage}", "valid_stages": PIPELINE_STAGES}), 400
    body = request.get_json(force=True) or {}
    new_state = str(body.get("state") or "").strip().lower()
    if new_state not in VALID_STATES:
        return jsonify({"ok": False, "error": f"invalid_state: {new_state}", "valid_states": list(VALID_STATES)}), 400
    result = body.get("result")
    error = body.get("error")
    updated = _pipeline_update_stage(trace_id, stage, new_state, result=result, error=error)
    if updated is None:
        return jsonify({"ok": False, "error": "update_failed"}), 500
    try:
        _audit_emit_action(f"pipeline.stage.{new_state}", _audit_base_payload(
            scope="governance", action=f"pipeline.{stage}.{new_state}", trace_id=trace_id,
            extra={"stage": stage, "state": new_state}))
    except Exception:
        pass
    return jsonify({"ok": True, "state": updated})


@app.route("/api/v1/pipeline/list", methods=["GET"])
def pipeline_list():
    """列出流水线状态。"""
    strategy_id = request.args.get("strategy_id")
    overall_state = request.args.get("overall_state")
    limit = int(request.args.get("limit", "50"))
    items = _pipeline_list(strategy_id=strategy_id, overall_state=overall_state, limit=limit)
    return jsonify({"ok": True, "count": len(items), "items": items})


# ---------------------------------------------------------------------------
# 变更包 API
# ---------------------------------------------------------------------------

@app.route("/api/v1/changeset/draft", methods=["POST"])
def changeset_build_draft():
    """构建变更包草稿。"""
    if not _require_admin():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    body = request.get_json(force=True) or {}
    draft = _agent_changeset_draft_build(body)
    if not draft.get("ok"):
        return jsonify(draft), 400
    # 写入草稿日志
    try:
        from governance.utils import _agent_outbox_append_jsonl
        draft_id = hashlib_sha256(f"{draft.get('trace_id')}|{_now_ms()}")
        draft["id"] = draft_id
        _agent_outbox_append_jsonl("changeset_drafts.jsonl", draft)
    except Exception:
        pass
    try:
        _audit_emit_action("changeset.draft_build", _audit_base_payload(
            scope="governance", action="changeset.draft_build",
            trace_id=str(draft.get("trace_id") or ""),
            extra={"ok": True, "draft_id": draft.get("id")}))
    except Exception:
        pass
    return jsonify(draft)


@app.route("/api/v1/changeset/draft/<draft_id>", methods=["GET"])
def changeset_lookup_draft(draft_id):
    """查询变更包草稿。"""
    draft = _agent_changeset_draft_lookup(draft_id)
    if draft is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "draft": draft})


@app.route("/api/v1/changeset/validate", methods=["POST"])
def changeset_validate_patch():
    """校验 config_patch。"""
    body = request.get_json(force=True) or {}
    patch = body.get("config_patch") if isinstance(body.get("config_patch"), dict) else {}
    result = _agent_config_patch_validate(patch, allow_suggest_only=True)
    return jsonify(result)


# ---------------------------------------------------------------------------
# 审批 API
# ---------------------------------------------------------------------------

@app.route("/api/v1/approvals", methods=["POST"])
def approval_create():
    """创建审批请求。"""
    if not _require_admin():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    body = request.get_json(force=True) or {}
    rid = approval_engine._approval_append(body)
    if rid is None:
        return jsonify({"ok": False, "error": "append_failed"}), 500
    return jsonify({"ok": True, "approval_id": rid})


@app.route("/api/v1/approvals/<approval_id>", methods=["GET"])
def approval_lookup(approval_id):
    """查询审批请求。"""
    obj = approval_engine._approval_lookup(approval_id)
    if obj is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "approval": obj})


@app.route("/api/v1/approvals/<approval_id>/ok", methods=["GET"])
def approval_check_ok(approval_id):
    """检查审批是否有效。"""
    ok = approval_engine._approval_ok(approval_id)
    return jsonify({"ok": ok, "approval_id": approval_id})


# ---------------------------------------------------------------------------
# 审计 API
# ---------------------------------------------------------------------------

@app.route("/api/v1/audit/query", methods=["GET"])
def audit_query_api():
    """查询审计事件。"""
    trace_id = request.args.get("trace_id")
    stage = request.args.get("stage")
    action = request.args.get("action")
    strategy_id = request.args.get("strategy_id")
    limit = int(request.args.get("limit", "100"))
    events = audit_query(
        trace_id=trace_id,
        stage=stage,
        action=action,
        strategy_id=strategy_id,
        limit=limit,
    )
    return jsonify({"ok": True, "count": len(events), "events": events})


@app.route("/api/v1/audit/verify", methods=["GET"])
def audit_verify_api():
    """验证审计哈希链完整性。"""
    result = audit_verify_chain()
    return jsonify(result)


@app.route("/api/v1/audit/event", methods=["POST"])
def audit_record_event():
    """记录审计事件。"""
    if not _require_admin():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    body = request.get_json(force=True) or {}
    trace_id = str(body.get("trace_id") or uuid.uuid4().hex).strip()
    stage = str(body.get("stage") or "").strip()
    action = str(body.get("action") or "").strip()
    actor = str(body.get("actor") or "governance_api").strip()
    result_data = body.get("result") if isinstance(body.get("result"), dict) else None
    strategy_id = body.get("strategy_id")
    source_zip = body.get("source_zip")
    event = strategy_factory_audit(
        trace_id=trace_id,
        stage=stage,
        action=action,
        actor=actor,
        result=result_data,
        strategy_id=strategy_id,
        source_zip=source_zip,
    )
    return jsonify({"ok": True, "event": event})


# ---------------------------------------------------------------------------
# Gate 评估 API
# ---------------------------------------------------------------------------

@app.route("/api/v1/gate/evaluate", methods=["POST"])
def gate_evaluate():
    """评估 Gate 结果（基于 delta_metrics + lookahead 检测）。"""
    body = request.get_json(force=True) or {}
    delta_metrics = body.get("delta_metrics")
    change_tags = body.get("change_tags", [])
    strategy_code = body.get("strategy_code")
    strategy_path = body.get("strategy_path")

    from governance.utils import (
        _governance_baseline_judge,
        _governance_env_name,
        _governance_has_improvement,
        _governance_tighten_only,
        _lookahead_check,
        _lookahead_check_file,
    )
    env = _governance_env_name()
    judge = _governance_baseline_judge(delta_metrics)
    tighten_only = _governance_tighten_only(change_tags)
    has_improvement = _governance_has_improvement(delta_metrics)

    # Lookahead 未来函数检测
    lookahead_result = None
    if strategy_code:
        lookahead_result = _lookahead_check(str(strategy_code))
    elif strategy_path:
        lookahead_result = _lookahead_check_file(str(strategy_path))

    # 如果 lookahead 检测到 high 级别问题，覆盖为 hard_reject
    final_decision = judge.get("decision", "inconclusive")
    final_reasons = list(judge.get("reasons", []))
    if lookahead_result and lookahead_result.get("severity") == "critical":
        final_decision = "hard_reject"
        final_reasons.append("lookahead_critical")
    elif lookahead_result and lookahead_result.get("severity") == "warn":
        if final_decision == "pass":
            final_decision = "soft_warn"
        final_reasons.append("lookahead_warn")

    return jsonify({
        "ok": True,
        "env": env,
        "baseline_judge": {**judge, "decision": final_decision, "reasons": final_reasons},
        "tighten_only": tighten_only,
        "has_improvement": has_improvement,
        "delta_metrics": delta_metrics,
        "change_tags": change_tags,
        "lookahead": lookahead_result,
    })


# ---------------------------------------------------------------------------
# 配置 API
# ---------------------------------------------------------------------------

@app.route("/api/v1/config", methods=["GET"])
def config_get():
    """获取治理配置。"""
    return jsonify({"ok": True, "config": dict(CONFIG)})


@app.route("/api/v1/config", methods=["PUT"])
def config_update():
    """更新治理配置。"""
    if not _require_admin():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    body = request.get_json(force=True) or {}
    for k, v in body.items():
        CONFIG[str(k)] = v
    _config_save(CONFIG)
    return jsonify({"ok": True, "updated_keys": list(body.keys())})


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def hashlib_sha256(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    port = int(os.environ.get("GOVERNANCE_PORT", "8094"))
    app.run(host="127.0.0.1", port=port, debug=False)
