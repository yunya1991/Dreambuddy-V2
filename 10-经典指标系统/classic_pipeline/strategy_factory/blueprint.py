"""策略工厂 Flask Blueprint。

注册策略工厂路由。路由 URL 与旧路由完全一致（零破坏）。
"""
from __future__ import annotations

import json
import math
import uuid
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

bp = Blueprint("strategy_factory", __name__)


def _dep(name: str):
    """延迟导入大文件依赖，避免循环导入。"""
    import ml_trade_service as _mts
    return getattr(_mts, name)


@bp.route("/agent/api/health", methods=["GET"])
def agent_api_health():
    """系统健康检查（供前端监控页使用）。"""
    _now_ms = _dep("_now_ms")
    _approvals_log_path = _dep("_approvals_log_path")
    _agent_outbox_dir = _dep("_agent_outbox_dir")
    now_ms = int(_now_ms())
    try:
        ap = _approvals_log_path()
        approvals_exists = bool(ap.exists() and ap.is_file())
    except Exception:
        approvals_exists = False
    try:
        rb_dir = _agent_outbox_dir() / "rollback_points"
        rb_count = len(list(rb_dir.glob("*.json"))) if rb_dir.exists() else 0
    except Exception:
        rb_count = 0
    return jsonify({
        "ok": True,
        "ts": now_ms,
        "service": "classic-indicators-ml-system",
        "approvals_log": approvals_exists,
        "rollback_points": rb_count,
    }), 200


@bp.route("/agent/pipeline/state", methods=["GET"])
def agent_pipeline_state():
    _agent_read_auth_ok = _dep("_agent_read_auth_ok")
    _now_ms = _dep("_now_ms")
    _agent_pipeline_state_find_latest = _dep("_agent_pipeline_state_find_latest")
    if not _agent_read_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized", "ts": int(_now_ms())}), 403
    trace_id = str(request.args.get("trace_id") or "").strip()
    if not trace_id:
        return jsonify({"ok": False, "error": "missing_trace_id", "ts": int(_now_ms())}), 400
    st = _agent_pipeline_state_find_latest(trace_id=str(trace_id))
    if not isinstance(st, dict):
        return jsonify({"ok": False, "error": "not_found", "trace_id": trace_id, "ts": int(_now_ms())}), 404
    return jsonify({"ok": True, "trace_id": trace_id, "ts": int(_now_ms()), "pipeline_state": st}), 200


@bp.route("/agent/pipeline/artifacts", methods=["GET"])
def agent_pipeline_artifacts():
    _agent_read_auth_ok = _dep("_agent_read_auth_ok")
    _now_ms = _dep("_now_ms")
    _agent_outbox_dir = _dep("_agent_outbox_dir")
    if not _agent_read_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized", "ts": int(_now_ms())}), 403
    trace_id = str(request.args.get("trace_id") or "").strip()
    if not trace_id:
        return jsonify({"ok": False, "error": "missing_trace_id", "ts": int(_now_ms())}), 400
    kind = None
    try:
        if request.args.get("kind") is not None:
            kind = str(request.args.get("kind") or "").strip() or None
    except Exception:
        kind = None
    try:
        offset = int(request.args.get("offset") or 0)
    except Exception:
        offset = 0
    try:
        limit = int(request.args.get("limit") or 200)
    except Exception:
        limit = 200
    offset = max(0, offset)
    limit = max(1, min(2000, limit))
    p = _agent_outbox_dir() / "pipeline_artifacts.jsonl"
    if not p.exists():
        return jsonify({"ok": True, "items": [], "next_offset": 0, "ts": int(_now_ms())}), 200
    items: List[Dict[str, Any]] = []
    next_offset = offset
    last_i = -1
    try:
        with open(p, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                last_i = i
                if i < offset:
                    continue
                if len(items) >= limit:
                    break
                s = line.strip("\n")
                if not s.strip():
                    next_offset = i + 1
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    obj = None
                if not isinstance(obj, dict):
                    next_offset = i + 1
                    continue
                if str(obj.get("trace_id") or "").strip() != trace_id:
                    next_offset = i + 1
                    continue
                if kind is not None and str(obj.get("kind") or "").strip() != kind:
                    next_offset = i + 1
                    continue
                items.append({"offset": i, "item": obj})
                next_offset = i + 1
    except Exception:
        items = []
        next_offset = offset
    if last_i >= 0 and len(items) < limit:
        next_offset = int(last_i) + 1
    return jsonify(
        {
            "ok": True,
            "trace_id": trace_id,
            "kind": kind,
            "items": items,
            "next_offset": int(next_offset),
            "count": int(len(items)),
            "ts": int(_now_ms()),
        }
    ), 200


@bp.route("/webhook/freqtrade", methods=["POST"])
def freqtrade_webhook():
    """
    聚合 Webhook 接口：接收所有 Freqtrade 实例的信号，并根据策略分配资金
    """
    CONFIG = _dep("CONFIG")
    LOG = _dep("LOG")
    STRATEGY_ALLOCATION = _dep("STRATEGY_ALLOCATION")
    _check_execute_guard = _dep("_check_execute_guard")
    _hl_coin_from_pair = _dep("_hl_coin_from_pair")
    _system_from_strategy_id = _dep("_system_from_strategy_id")
    aster_market_open_internal = _dep("aster_market_open_internal")
    hyperliquid_market_open_internal = _dep("hyperliquid_market_open_internal")
    aster_market_close_internal = _dep("aster_market_close_internal")
    hyperliquid_market_close_internal = _dep("hyperliquid_market_close_internal")
    try:
        data = request.get_json(force=True) or {}
        strategy = str(data.get("strategy", "")).strip()
        pair = str(data.get("pair", "")).strip()
        type_ = str(data.get("type", "")).lower()
        
        if not strategy or not pair:
            return jsonify({"ok": False, "error": "missing_strategy_or_pair"}), 400

        # 从 pair 中提取 coin (e.g. BTC/USDT -> BTC)
        coin = _hl_coin_from_pair(pair)
        
        base_notional = None
        try:
            for k in ("notional_usdc", "notional_usdt", "notional", "size_usdc", "size"):
                v = data.get(k)
                if v is None:
                    continue
                x = float(v)
                if math.isfinite(float(x)) and float(x) > 0.0:
                    base_notional = float(x)
                    break
        except Exception:
            base_notional = None
        if base_notional is None:
            base_notional = float(CONFIG.get("entry_fixed_notional_usdc", 200.0) or 200.0)

        alloc_pct = None
        try:
            alloc_pct = STRATEGY_ALLOCATION.get(str(strategy))
        except Exception:
            alloc_pct = None
        try:
            if alloc_pct is not None and math.isfinite(float(alloc_pct)) and float(alloc_pct) > 0.0:
                notional = float(base_notional) * float(alloc_pct) / 100.0
            else:
                notional = float(base_notional)
        except Exception:
            notional = float(base_notional)
        execute = bool(data.get("execute", False))
        if execute:
            guard = _check_execute_guard(data)
            if guard is not None:
                return guard
        
        try:
            if alloc_pct is not None and math.isfinite(float(alloc_pct)):
                LOG.info(f"Webhook Received: Strategy={strategy}, Coin={coin}, Type={type_}, Notional={notional}, AllocPct={float(alloc_pct)}")
            else:
                LOG.info(f"Webhook Received: Strategy={strategy}, Coin={coin}, Type={type_}, Notional={notional}")
        except Exception:
            pass

        if type_ == "entry":
            side = str(data.get("side", "long")).lower()
            system_id = _system_from_strategy_id(strategy)
            ab_owner = ("carry" if str(system_id) == "carry" else ("quant" if str(system_id) == "quant" else "strategy"))
            skip_gate = False
            ignore_cooldown = False
            ignore_post_close_freeze = False
            if not bool(execute):
                try:
                    sg_raw = data.get("skip_gate")
                    if sg_raw is not None:
                        skip_gate = str(sg_raw).strip().lower() in ("1", "true", "yes", "y", "on")
                except Exception:
                    skip_gate = False
                try:
                    ic_raw = data.get("ignore_cooldown")
                    if ic_raw is not None:
                        ignore_cooldown = str(ic_raw).strip().lower() in ("1", "true", "yes", "y", "on")
                except Exception:
                    ignore_cooldown = False
                try:
                    ipcf_raw = data.get("ignore_post_close_freeze")
                    if ipcf_raw is not None:
                        ignore_post_close_freeze = str(ipcf_raw).strip().lower() in ("1", "true", "yes", "y", "on")
                except Exception:
                    ignore_post_close_freeze = False

            venue = None
            if str(system_id) == "carry":
                venue = str(CONFIG.get("carry_trade_venue") or "hyperliquid").strip().lower() or "hyperliquid"
            elif str(system_id) == "quant":
                venue = "aster"
            else:
                venue = str(data.get("venue") or CONFIG.get("execution_venue", "hyperliquid") or "hyperliquid").lower()
            if venue not in ("hyperliquid", "hl", "aster"):
                venue = str(CONFIG.get("execution_venue", "hyperliquid") or "hyperliquid").lower()
            if venue == "hl":
                venue = "hyperliquid"
            if str(system_id) == "carry" and venue != "hyperliquid":
                venue = "hyperliquid"
            if str(system_id) == "quant" and venue != "aster":
                venue = "aster"

            if venue == "aster":
                return aster_market_open_internal(
                    coin=coin,
                    side=side,
                    notional_usdc=notional,
                    execute=execute,
                    tag=f"webhook_{strategy}",
                    strategy_id=strategy,
                    ab_owner=ab_owner,
                    skip_gate=bool(skip_gate),
                    ignore_cooldown=bool(ignore_cooldown),
                    ignore_post_close_freeze=bool(ignore_post_close_freeze),
                )
            return hyperliquid_market_open_internal(
                coin=coin,
                side=side,
                notional_usdc=notional,
                execute=execute,
                tag=f"webhook_{strategy}",
                strategy_id=strategy,
                ab_owner=ab_owner,
                skip_gate=bool(skip_gate),
                ignore_cooldown=bool(ignore_cooldown),
                ignore_post_close_freeze=bool(ignore_post_close_freeze),
            )
            
        elif type_ == "exit":
            system_id = _system_from_strategy_id(strategy)
            venue = None
            if str(system_id) == "carry":
                venue = str(CONFIG.get("carry_trade_venue") or "hyperliquid").strip().lower() or "hyperliquid"
            elif str(system_id) == "quant":
                venue = "aster"
            else:
                venue = str(data.get("venue") or CONFIG.get("execution_venue", "hyperliquid") or "hyperliquid").lower()
            if venue not in ("hyperliquid", "hl", "aster"):
                venue = str(CONFIG.get("execution_venue", "hyperliquid") or "hyperliquid").lower()
            if venue == "hl":
                venue = "hyperliquid"
            if str(system_id) == "carry" and venue != "hyperliquid":
                venue = "hyperliquid"
            if str(system_id) == "quant" and venue != "aster":
                venue = "aster"

            exit_owner = "strategy"
            system_id_close = None
            if str(system_id) == "carry":
                exit_owner = "carry_trade"
                system_id_close = "carry"
            elif str(system_id) == "quant":
                exit_owner = "quant"
                system_id_close = "quant"
            if venue == "aster":
                return aster_market_close_internal(
                    coin=coin,
                    execute=execute,
                    tag=f"webhook_{strategy}_exit",
                    sz=None,
                    exit_owner=exit_owner,
                    force=False,
                    system_id=system_id_close,
                )
            return hyperliquid_market_close_internal(
                coin=coin,
                execute=execute,
                tag=f"webhook_{strategy}_exit",
                sz=None,
                exit_owner=exit_owner,
                force=False,
                system_id=system_id_close,
            )
            
        return jsonify({"ok": True, "status": "ignored_type", "type": type_})

    except Exception as e:
        LOG.error(f"Webhook Error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500





@bp.route("/governance/changeset/apply", methods=["POST"])
def governance_changeset_apply():
    CONFIG = _dep("CONFIG")
    _agent_config_patch_validate = _dep("_agent_config_patch_validate")
    _agent_outbox_append_jsonl = _dep("_agent_outbox_append_jsonl")
    _config_set_impl = _dep("_config_set_impl")
    _governance_policy_eval = _dep("_governance_policy_eval")
    _governance_policy_resolve = _dep("_governance_policy_resolve")
    _governance_require_approval_or_error = _dep("_governance_require_approval_or_error")
    _governance_write_auth_ok = _dep("_governance_write_auth_ok")
    _is_local_request = _dep("_is_local_request")
    _json_sanitize = _dep("_json_sanitize")
    _now_ms = _dep("_now_ms")
    _rollback_point_apply = _dep("_rollback_point_apply")
    _rollback_point_make = _dep("_rollback_point_make")
    _rollback_points_get = _dep("_rollback_points_get")
    _rollback_points_put = _dep("_rollback_points_put")
    _sys_monitor_restart_after_apply_maybe = _dep("_sys_monitor_restart_after_apply_maybe")
    if not _governance_write_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    data = request.get_json(force=True) or {}
    trace_id = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
    confirm_live = bool(data.get("confirm_live", False))
    ok_appr, approval_id, err_obj, err_code = _governance_require_approval_or_error(data, trace_id=trace_id, action="governance.changeset.apply")
    if not ok_appr:
        return jsonify(err_obj), int(err_code)
    data.pop("confirm_live", None)
    data.pop("approval_id", None)
    data.pop("trace_id", None)
    ref = str(data.get("policy_ref") or "").strip()
    pol = _governance_policy_resolve(ref)
    if not pol:
        pol = {"ref": (ref or "gov_default")}
    changeset = data.get("changeset") if isinstance(data.get("changeset"), dict) else None
    if changeset is None:
        changeset = data
    try:
        gate_result = None
        if isinstance(data.get("gate_result"), dict):
            gate_result = data.get("gate_result")
        elif isinstance(data.get("draft"), dict) and isinstance((data.get("draft") or {}).get("gate_result"), dict):
            gate_result = (data.get("draft") or {}).get("gate_result")
        if isinstance(gate_result, dict) and (gate_result.get("ok") is False):
            return jsonify({"ok": False, "error": "p3_gate_fail", "gate_result": gate_result, "ts": int(_now_ms())}), 400
    except Exception:
        pass

    decision = _governance_policy_eval(policy=pol, changeset=changeset if isinstance(changeset, dict) else {})
    if not bool(decision.get("ok")):
        return jsonify(decision), 500
    if str(decision.get("decision") or "").strip().lower() != "pass":
        return jsonify(decision), 400
    allowed = decision.get("allowed_actions") if isinstance(decision.get("allowed_actions"), list) else []
    if "config.apply" not in [str(x) for x in allowed]:
        return jsonify({"ok": False, "error": "action_not_allowed", "decision": decision}), 400

    if not _is_local_request():
        if not bool(confirm_live):
            return jsonify({"ok": False, "error": "confirm_live_required", "ts": int(_now_ms())}), 400

    cs = changeset if isinstance(changeset, dict) else {}
    patch = cs.get("config_patch") if isinstance(cs.get("config_patch"), dict) else {}
    if not patch:
        return jsonify({"ok": False, "error": "missing_config_patch", "decision": decision}), 400

    vpatch = _agent_config_patch_validate(patch, allow_unsafe=bool(_is_local_request()))
    if not bool(vpatch.get("ok")):
        return jsonify({"ok": False, "error": "config_patch_rejected", "violations": vpatch.get("violations"), "decision": decision, "ts": int(_now_ms())}), 400
    safe_patch = vpatch.get("patch") if isinstance(vpatch.get("patch"), dict) else {}
    if not safe_patch:
        return jsonify({"ok": False, "error": "empty_patch", "decision": decision, "ts": int(_now_ms())}), 400

    patch_keys = sorted([str(k) for k in safe_patch.keys() if str(k)])

    now_ms = int(_now_ms())
    expires_at_effective_ms = None
    review_after_days = None
    try:
        expires_at_in = cs.get("expires_at")
        if expires_at_in is None:
            expires_at_in = cs.get("expires_at_ms")
        if expires_at_in is not None and str(expires_at_in).strip() != "":
            exp_i = int(float(expires_at_in))
            if exp_i > 0 and exp_i < 10**11:
                exp_i = exp_i * 1000
            expires_at_effective_ms = int(exp_i) if exp_i > 0 else None
    except Exception:
        expires_at_effective_ms = None
    try:
        review_after_days_in = cs.get("review_after_days")
        if review_after_days_in is None:
            review_after_days_in = cs.get("review_after_day")
        if review_after_days_in is None:
            review_after_days_in = cs.get("review_days")
        if review_after_days_in is not None and str(review_after_days_in).strip() != "":
            review_after_days = int(float(review_after_days_in))
    except Exception:
        review_after_days = None
    if expires_at_effective_ms is None:
        if review_after_days is None:
            try:
                review_after_days = int(CONFIG.get("governance_changeset_review_after_days", CONFIG.get("changeset_review_after_days", 7)) or 7)
            except Exception:
                review_after_days = 7
        review_after_days = max(1, min(3650, int(review_after_days)))
        expires_at_effective_ms = int(now_ms + int(review_after_days) * 86400 * 1000)
    if expires_at_effective_ms is not None and int(expires_at_effective_ms) <= int(now_ms):
        return jsonify({"ok": False, "error": "changeset_expired", "ts": int(now_ms), "expires_at": int(expires_at_effective_ms), "decision": decision}), 400

    sid = str(cs.get("strategy_id") or "").strip()
    zip_name = str(cs.get("source_zip") or "").strip()
    label = str(cs.get("label") or f"auto_upgrade:{sid}").strip()
    reason = str(cs.get("reason") or "policy_auto_apply").strip()
    pt = _rollback_point_make(
        now_ms=now_ms,
        label=label,
        reason=reason,
        include_arena=True,
        include_dynamic_thresholds=True,
        include_active_model=True,
        include_tracker_state=True,
        include_arena_state=True,
        include_config_keys=patch_keys,
    )
    if isinstance(pt, dict):
        try:
            pt["trace_id"] = trace_id
            pt["approval_id"] = approval_id
            pt["origin"] = "governance.changeset.apply"
        except Exception:
            pass
    pts = _rollback_points_get()
    pts.append(pt)
    try:
        max_points = int(CONFIG.get("rollback_max_points", 20) or 20)
    except Exception:
        max_points = 20
    max_points = max(1, min(200, int(max_points)))
    pts = sorted(pts, key=lambda x: int(x.get("ts") or 0), reverse=True)[:max_points]
    _rollback_points_put(pts)

    out, code = _config_set_impl(dict(safe_patch), confirm_live=bool(confirm_live), action="governance.changeset.apply")
    ok = bool(out.get("ok")) and int(code) == 200
    audit_payload = {
        "trace_id": trace_id,
        "approval_id": approval_id,
        "policy_ref": str(decision.get("policy_ref") or ""),
        "strategy_id": sid,
        "source_zip": zip_name,
        "rollback_point_id": pt.get("id"),
        "expires_at": (None if expires_at_effective_ms is None else int(expires_at_effective_ms)),
        "review_after_days": (None if review_after_days is None else int(review_after_days)),
        "decision": decision,
        "apply": {"ok": ok, "code": int(code), "out": out},
    }
    try:
        _agent_outbox_append_jsonl("audit_actions.jsonl", {"name": "governance.changeset.apply", "ts": now_ms, "payload": audit_payload})
    except Exception:
        pass

    if not ok:
        try:
            rb_res = _rollback_point_apply(pt, restore_thresholds=True, restore_arena=True, restore_active_model=False, restore_tracker_state=True, restore_config=True)
        except Exception:
            rb_res = {"ok": False, "error": "rollback_failed"}
        try:
            _agent_outbox_append_jsonl("audit_actions.jsonl", {"name": "governance.changeset.rollback", "ts": int(_now_ms()), "payload": {"trace_id": trace_id, "rollback": rb_res, "rollback_point_id": pt.get("id")}})
        except Exception:
            pass
        return jsonify({"ok": False, "error": "apply_failed", "apply": out, "rollback": rb_res, "rollback_point": pt, "decision": decision, "approval_id": approval_id}), 500

    res = {"ok": True, "ts": int(_now_ms()), "rollback_point": pt, "apply": out, "decision": decision}
    if approval_id:
        res["approval_id"] = approval_id
    if expires_at_effective_ms is not None:
        res["expires_at"] = int(expires_at_effective_ms)
    if review_after_days is not None:
        res["review_after_days"] = int(review_after_days)
    try:
        rst = _sys_monitor_restart_after_apply_maybe(
            now_ms=int(now_ms),
            changeset=cs,
            label=str(label),
            reason=str(reason),
            trace_id=str(trace_id),
            approval_id=(str(approval_id) if approval_id else None),
        )
        if isinstance(rst, dict) and rst:
            res["restart_after_apply"] = _json_sanitize(rst)
            try:
                _agent_outbox_append_jsonl(
                    "audit_actions.jsonl",
                    {
                        "name": "sys_monitor.restart_after_apply",
                        "ts": int(now_ms),
                        "payload": {
                            "trace_id": str(trace_id),
                            "approval_id": (str(approval_id) if approval_id else None),
                            "label": str(label or ""),
                            "reason": str(reason or ""),
                            "restart_after_apply": _json_sanitize(rst),
                        },
                    },
                )
            except Exception:
                pass
    except Exception:
        pass
    return jsonify(res)





@bp.route("/agent/changeset/draft", methods=["POST"])
def agent_changeset_draft():
    _agent_changeset_draft_build = _dep("_agent_changeset_draft_build")
    _agent_outbox_append_jsonl = _dep("_agent_outbox_append_jsonl")
    _agent_write_auth_ok = _dep("_agent_write_auth_ok")
    _now_ms = _dep("_now_ms")
    if not _agent_write_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized", "ts": int(_now_ms())}), 403
    data = request.get_json(force=True) or {}
    draft = _agent_changeset_draft_build(data)
    if not bool(draft.get("ok")):
        err = str(draft.get("error") or "bad_request")
        code = 400
        if err == "strategy_registry_entry_not_found":
            code = 404
        return jsonify(draft), int(code)
    trace_id = str(draft.get("trace_id") or "").strip() or uuid.uuid4().hex
    draft_id = uuid.uuid4().hex
    try:
        draft["draft_id"] = str(draft_id)
    except Exception:
        pass
    _agent_outbox_append_jsonl("changeset_drafts.jsonl", {"id": str(draft_id), "trace_id": trace_id, "ts": int(_now_ms()), "type": "changeset.draft", "draft": draft})
    return jsonify(draft), 200





@bp.route("/agent/changeset/draft/get", methods=["GET"])
def agent_changeset_draft_get():
    _agent_changeset_draft_lookup = _dep("_agent_changeset_draft_lookup")
    _agent_read_auth_ok = _dep("_agent_read_auth_ok")
    _json_sanitize = _dep("_json_sanitize")
    _now_ms = _dep("_now_ms")
    if not _agent_read_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized", "ts": int(_now_ms())}), 403
    draft_id = str(request.args.get("id") or request.args.get("draft_id") or "").strip()
    if not draft_id:
        return jsonify({"ok": False, "error": "missing_id", "ts": int(_now_ms())}), 400
    ent = _agent_changeset_draft_lookup(draft_id)
    if not isinstance(ent, dict) or not ent:
        return jsonify({"ok": False, "error": "not_found", "id": draft_id, "ts": int(_now_ms())}), 404
    return jsonify({"ok": True, "id": draft_id, "entry": _json_sanitize(ent), "ts": int(_now_ms())}), 200

# @deprecated
#   此路由属于 AI Agent 辅助层 (Chat/Skills/Pipeline/RCA/Twitter)，
#   核心量化金融治理功能已迁移至 Dreambuddy-V2 提供支持。




@bp.route("/agent/pipeline/run", methods=["POST"])
def agent_pipeline_run():
    CONFIG = _dep("CONFIG")
    TRACKER_STATE = _dep("TRACKER_STATE")
    _agent_changeset_draft_build = _dep("_agent_changeset_draft_build")
    _agent_doc_refs_48_default = _dep("_agent_doc_refs_48_default")
    _agent_outbox_append_jsonl = _dep("_agent_outbox_append_jsonl")
    _agent_pipeline_artifact_common_fields = _dep("_agent_pipeline_artifact_common_fields")
    _agent_pipeline_artifact_emit = _dep("_agent_pipeline_artifact_emit")
    _agent_pipeline_artifact_validate_and_emit = _dep("_agent_pipeline_artifact_validate_and_emit")
    _agent_pipeline_package_write = _dep("_agent_pipeline_package_write")
    _agent_pipeline_state_find_latest = _dep("_agent_pipeline_state_find_latest")
    _agent_sandbox_task_auth_ok = _dep("_agent_sandbox_task_auth_ok")
    _apply_serving_phase = _dep("_apply_serving_phase")
    _approval_ok = _dep("_approval_ok")
    _approval_request_for_changeset_draft = _dep("_approval_request_for_changeset_draft")
    _bt_assumptions_default = _dep("_bt_assumptions_default")
    _bt_assumptions_merge = _dep("_bt_assumptions_merge")
    _is_local_request = _dep("_is_local_request")
    _json_sanitize = _dep("_json_sanitize")
    _now_ms = _dep("_now_ms")
    _pipeline_approval_request_build = _dep("_pipeline_approval_request_build")
    _pipeline_archive_record_build = _dep("_pipeline_archive_record_build")
    _pipeline_archive_writeback = _dep("_pipeline_archive_writeback")
    _pipeline_baseline_report_build = _dep("_pipeline_baseline_report_build")
    _pipeline_candidate_strategies_build = _dep("_pipeline_candidate_strategies_build")
    _pipeline_monitoring_checklist_build = _dep("_pipeline_monitoring_checklist_build")
    _pipeline_regime_report_build = _dep("_pipeline_regime_report_build")
    _pipeline_rollout_plan_build = _dep("_pipeline_rollout_plan_build")
    _pipeline_stage = _dep("_pipeline_stage")
    agent_paramopt_run = _dep("agent_paramopt_run")
    sandbox_queue_submit = _dep("sandbox_queue_submit")
    if not _agent_sandbox_task_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized", "ts": int(_now_ms())}), 403
    data = request.get_json(force=True) or {}
    trace_id = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
    now_ms = int(_now_ms())
    shadow_only = bool(data.get("shadow_only", False))
    if bool(shadow_only):
        try:
            st = TRACKER_STATE.get("shadow_automation") if isinstance(TRACKER_STATE.get("shadow_automation"), dict) else {}
            if not isinstance(st, dict):
                st = {}
            st["active_trace_id"] = str(trace_id)
            TRACKER_STATE["shadow_automation"] = st
        except Exception:
            pass

    force = bool(data.get("force", False))
    idempotent = bool(data.get("idempotent", True))
    if idempotent and (not force):
        prev = _agent_pipeline_state_find_latest(trace_id=str(trace_id))
        if isinstance(prev, dict) and str(prev.get("trace_id") or "").strip() == str(trace_id):
            return jsonify({"ok": True, "trace_id": trace_id, "ts": int(now_ms), "replayed": True, "pipeline_state": prev}), 200

    artifacts: Dict[str, Any] = {}
    stages: List[Dict[str, Any]] = []

    t0 = int(now_ms)
    trigger_record = _agent_pipeline_artifact_common_fields(trace_id=str(trace_id), created_at_ms=int(now_ms), producer_kind="agent")
    trigger_record.update(
        {
            "ts": int(now_ms),
            "trigger_event": (None if data.get("trigger_event") is None else str(data.get("trigger_event") or "").strip() or None),
            "base_trace_id": (None if data.get("base_trace_id") is None else str(data.get("base_trace_id") or "").strip() or None),
            "objective": _json_sanitize(data.get("objective")),
            "risk_budget": _json_sanitize(data.get("risk_budget")),
            "scope": (_json_sanitize(data.get("scope")) if isinstance(data.get("scope"), dict) else {}),
            "inputs": _json_sanitize(data),
        }
    )
    trigger_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="trigger_record.json", obj=trigger_record)
    if trigger_path and isinstance(trigger_record, dict):
        trigger_record["artifact_files"] = {"trigger_record_json": trigger_path}
    artifacts["trigger_record"] = _agent_pipeline_artifact_emit(trace_id=str(trace_id), kind="trigger_record", artifact=trigger_record)
    stages.append(_pipeline_stage("trigger", "success", t0, int(_now_ms()), {"trigger_record": artifacts.get("trigger_record")}))

    t1s = int(_now_ms())
    regime_report = _pipeline_regime_report_build(trace_id=str(trace_id), now_ms=int(now_ms))
    regime_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="regime_report.json", obj=regime_report)
    if regime_path and isinstance(regime_report, dict):
        regime_report["artifact_files"] = {"regime_report_json": regime_path}
    artifacts["regime_report"] = _agent_pipeline_artifact_validate_and_emit(trace_id=str(trace_id), kind="regime_report", artifact=regime_report)
    stages.append(_pipeline_stage("market_regime", "success" if bool((artifacts.get("regime_report") or {}).get("ok", True)) else "fail", t1s, int(_now_ms()), {"regime_report": artifacts.get("regime_report")}))

    try:
        cand_limit = int(data.get("candidate_limit") or 3)
    except Exception:
        cand_limit = 3
    t2s = int(_now_ms())
    candidate_strategies = _pipeline_candidate_strategies_build(trace_id=str(trace_id), now_ms=int(now_ms), limit=int(cand_limit), regime_report=regime_report)
    cand_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="candidate_strategies.json", obj=candidate_strategies)
    if cand_path and isinstance(candidate_strategies, dict):
        candidate_strategies["artifact_files"] = {"candidate_strategies_json": cand_path}
    artifacts["candidate_strategies"] = _agent_pipeline_artifact_validate_and_emit(trace_id=str(trace_id), kind="candidate_strategies", artifact=candidate_strategies)
    stages.append(_pipeline_stage("strategy_screening", "success" if bool((artifacts.get("candidate_strategies") or {}).get("ok", True)) else "fail", t2s, int(_now_ms()), {"candidate_strategies": artifacts.get("candidate_strategies")}))

    chosen = None
    strategy_id = str(data.get("strategy_id") or "").strip()
    source_zip = str(data.get("source_zip") or "").strip()
    if strategy_id and source_zip:
        chosen = {"strategy_id": strategy_id, "source_zip": source_zip}
    else:
        items = candidate_strategies.get("items") if isinstance(candidate_strategies, dict) else None
        if isinstance(items, list) and items:
            it0 = items[0] if isinstance(items[0], dict) else None
            if isinstance(it0, dict):
                chosen = {"strategy_id": str(it0.get("strategy_id") or "").strip(), "source_zip": str(it0.get("source_zip") or "").strip()}

    t3s = int(_now_ms())
    baseline_enabled = bool(data.get("baseline_enabled", True))
    baseline_ref = None
    baseline_ok = None
    baseline_obj_for_changeset = None
    baseline_ref_for_changeset = None
    if baseline_enabled and isinstance(chosen, dict) and chosen.get("strategy_id") and chosen.get("source_zip"):
        try:
            bt_cfg = str(data.get("baseline_config") or "user_data/config_local_backtest.json").strip() or "user_data/config_local_backtest.json"
        except Exception:
            bt_cfg = "user_data/config_local_backtest.json"
        try:
            bt_tr = (None if data.get("baseline_timerange") is None else str(data.get("baseline_timerange") or "").strip() or None)
        except Exception:
            bt_tr = None
        try:
            bt_to = float(data.get("baseline_timeout_sec") or 1200)
        except Exception:
            bt_to = 1200.0
        baseline_report = _pipeline_baseline_report_build(
            trace_id=str(trace_id),
            now_ms=int(now_ms),
            strategy_id=str(chosen.get("strategy_id")),
            source_zip=str(chosen.get("source_zip")),
            config_path=str(bt_cfg),
            timerange=bt_tr,
            timeout_sec=float(bt_to),
        )
        baseline_report_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="baseline_report.json", obj=baseline_report)
        assumptions_obj = None
        baseline_metrics_obj = None
        try:
            cfg_obj = {}
            try:
                p_cfg = Path(str(bt_cfg))
                if not p_cfg.exists():
                    p_cfg = Path(__file__).resolve().parent / str(bt_cfg)
                if p_cfg.exists() and p_cfg.is_file():
                    with open(p_cfg, "r", encoding="utf-8") as f:
                        cfg_obj = json.load(f) or {}
            except Exception:
                cfg_obj = {}
            cfg_assumptions = _bt_assumptions_default(cfg_obj if isinstance(cfg_obj, dict) else {})

            res0 = baseline_report.get("result") if isinstance(baseline_report, dict) else {}
            rep0 = res0.get("report") if isinstance(res0, dict) and isinstance(res0.get("report"), dict) else {}
            aligned0 = rep0.get("aligned_metrics") if isinstance(rep0, dict) and isinstance(rep0.get("aligned_metrics"), dict) else None
            assumptions0 = (aligned0.get("assumptions") if isinstance(aligned0, dict) and isinstance(aligned0.get("assumptions"), dict) else None)
            assumptions_m = _bt_assumptions_merge(cfg_assumptions, assumptions0 if isinstance(assumptions0, dict) else {})
            assumptions_obj = {
                "trace_id": str(trace_id),
                "ts": int(now_ms),
                "strategy_id": str(chosen.get("strategy_id")),
                "source_zip": str(chosen.get("source_zip")),
                "result_zip": (res0.get("result_zip") if isinstance(res0, dict) else None),
                "assumptions": assumptions_m,
            }
            baseline_metrics_obj = {
                "trace_id": str(trace_id),
                "ts": int(now_ms),
                "strategy_id": str(chosen.get("strategy_id")),
                "source_zip": str(chosen.get("source_zip")),
                "result_zip": (res0.get("result_zip") if isinstance(res0, dict) else None),
                "metrics_summary": (res0.get("metrics_summary") if isinstance(res0, dict) and isinstance(res0.get("metrics_summary"), dict) else {}),
                "aligned_metrics": (aligned0 if isinstance(aligned0, dict) else None),
            }
        except Exception:
            assumptions_obj = None
            baseline_metrics_obj = None
        assumptions_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="assumptions.json", obj=(assumptions_obj if assumptions_obj is not None else {"trace_id": str(trace_id), "ts": int(now_ms), "assumptions": {}}))
        baseline_metrics_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="baseline_metrics.json", obj=(baseline_metrics_obj if baseline_metrics_obj is not None else {"trace_id": str(trace_id), "ts": int(now_ms), "metrics_summary": {}}))
        try:
            ms0 = (baseline_metrics_obj.get("metrics_summary") if isinstance(baseline_metrics_obj, dict) else None)
            if isinstance(ms0, dict) and ms0:
                sid0 = str(chosen.get("strategy_id") or "").strip()
                z0 = str(chosen.get("source_zip") or "").strip()
                sk0 = f"{sid0}@{z0}" if sid0 and z0 else None
                baseline_obj_for_changeset = {"metrics_summary": ms0, "strategy_key": sk0, "three_piece": {"strategy_key": sk0}}
                baseline_ref_for_changeset = f"baseline_report:{str(trace_id)}"
        except Exception:
            baseline_obj_for_changeset = None
            baseline_ref_for_changeset = None
        if isinstance(baseline_report, dict):
            files = {}
            if baseline_report_path:
                files["baseline_report_json"] = baseline_report_path
            if assumptions_path:
                files["assumptions_json"] = assumptions_path
            if baseline_metrics_path:
                files["baseline_metrics_json"] = baseline_metrics_path
            if files:
                baseline_report["artifact_files"] = files
        baseline_ref = _agent_pipeline_artifact_validate_and_emit(trace_id=str(trace_id), kind="baseline_report", artifact=baseline_report)
        artifacts["baseline_report"] = baseline_ref
        baseline_ok = bool(baseline_ref.get("ok")) if isinstance(baseline_ref, dict) else None
        stages.append(_pipeline_stage("baseline_reproduction", "success" if baseline_ok else "fail", t3s, int(_now_ms()), {"baseline_report": baseline_ref}))
    else:
        stages.append(_pipeline_stage("baseline_reproduction", "skipped", t3s, int(_now_ms()), {}, {"reason": "disabled_or_missing_choice"}))

    paramopt_rep = None
    selected_patch: Dict[str, Any] = {}
    selected_suggest: Dict[str, Any] = {}
    t4s = int(_now_ms())
    if isinstance(chosen, dict) and chosen.get("strategy_id") and chosen.get("source_zip") and (not bool(data.get("skip_paramopt", False))):
        try:
            req = {
                "trace_id": trace_id,
                "mode": "suggest",
                "eval_mode": "rolling",
                "folds": int(data.get("paramopt_folds") or 3),
                "n_init": int(data.get("paramopt_n_init") or 2),
                "n_iter": int(data.get("paramopt_n_iter") or 4),
                "include_suggest_only": True,
                "skip_robustness": True,
                "context": {"stage": "pipeline", "regime": regime_report, "strategy": chosen},
            }
            with app.test_request_context(
                "/agent/paramopt/run",
                method="POST",
                data=json.dumps(req),
                content_type="application/json",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            ):
                resp = agent_paramopt_run()
            resp0 = resp[0] if isinstance(resp, tuple) and resp else resp
            if hasattr(resp0, "get_json"):
                paramopt_rep = resp0.get_json(force=True) or {}
            if isinstance(paramopt_rep, dict):
                sel = paramopt_rep.get("selected") if isinstance(paramopt_rep.get("selected"), dict) else {}
                selected_patch = sel.get("config_patch") if isinstance(sel.get("config_patch"), dict) else {}
                selected_suggest = sel.get("config_suggest") if isinstance(sel.get("config_suggest"), dict) else {}
        except Exception:
            paramopt_rep = None
            selected_patch = {}
            selected_suggest = {}
    if bool(data.get("skip_paramopt", False)) or (not (isinstance(chosen, dict) and chosen.get("strategy_id") and chosen.get("source_zip"))):
        stages.append(_pipeline_stage("strategy_modification", "skipped", t4s, int(_now_ms()), {}, {"reason": "skip_paramopt_or_missing_choice"}))
    else:
        ok_mod = bool((paramopt_rep or {}).get("ok")) if isinstance(paramopt_rep, dict) else False
        ok_patch = bool(selected_patch) if isinstance(selected_patch, dict) else False
        st = "success" if (ok_mod and ok_patch) else ("fail" if ok_mod else "fail")
        if isinstance(paramopt_rep, dict):
            paramopt_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="paramopt_result.json", obj=paramopt_rep)
            if paramopt_path:
                paramopt_rep["artifact_files"] = {"paramopt_result_json": paramopt_path}
        stages.append(_pipeline_stage("strategy_modification", st, t4s, int(_now_ms()), {"paramopt": _json_sanitize(paramopt_rep), "config_patch": selected_patch}))

    draft = None
    draft_id = None
    approval_id = None
    if isinstance(chosen, dict) and chosen.get("strategy_id") and chosen.get("source_zip") and isinstance(selected_patch, dict) and selected_patch:
        try:
            doc_refs = data.get("doc_refs") if isinstance(data.get("doc_refs"), list) else _agent_doc_refs_48_default()
        except Exception:
            doc_refs = _agent_doc_refs_48_default()
        try:
            draft = _agent_changeset_draft_build(
                {
                    "trace_id": trace_id,
                    "strategy_id": str(chosen.get("strategy_id")),
                    "source_zip": str(chosen.get("source_zip")),
                    "policy_ref": str(data.get("policy_ref") or "gov_default"),
                    "action": str(data.get("action") or "config.apply"),
                    "label": str(data.get("label") or f"pipeline:{chosen.get('strategy_id')}").strip() or f"pipeline:{chosen.get('strategy_id')}",
                    "reason": str(data.get("reason") or "pipeline.auto").strip() or "pipeline.auto",
                    "config_patch": selected_patch,
                    "config_suggest": selected_suggest,
                    "baseline": (baseline_obj_for_changeset if isinstance(baseline_obj_for_changeset, dict) else None),
                    "baseline_ref": (baseline_ref_for_changeset if isinstance(baseline_ref_for_changeset, str) and baseline_ref_for_changeset.strip() else None),
                    "doc_refs": doc_refs,
                }
            )
            if isinstance(draft, dict) and bool(draft.get("ok")):
                draft_id = uuid.uuid4().hex
                _agent_outbox_append_jsonl("changeset_drafts.jsonl", {"id": str(draft_id), "trace_id": trace_id, "ts": int(_now_ms()), "type": "changeset.draft", "draft": draft})
                try:
                    approval_id = _approval_request_for_changeset_draft(trace_id=trace_id, draft_id=str(draft_id), draft=draft, action=str(data.get("action") or "config.apply"))
                except Exception:
                    approval_id = None
        except Exception:
            draft = None
            draft_id = None
            approval_id = None

    change_bundle = (draft.get("change_bundle_draft") if isinstance(draft, dict) else None)
    if isinstance(change_bundle, dict):
        cbd_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="change_bundle_draft.json", obj=change_bundle)
        if cbd_path:
            change_bundle["artifact_files"] = {"change_bundle_draft_json": cbd_path}
        artifacts["change_bundle_draft"] = _agent_pipeline_artifact_validate_and_emit(trace_id=str(trace_id), kind="change_bundle_draft", artifact=change_bundle)

    if approval_id:
        approval_pkg = _pipeline_approval_request_build(
            trace_id=str(trace_id),
            now_ms=int(now_ms),
            approval_id=str(approval_id),
            action=str(data.get("action") or "config.apply"),
            draft_id=(None if draft_id is None else str(draft_id)),
            draft=(draft if isinstance(draft, dict) else {}),
            chosen=(chosen if isinstance(chosen, dict) else None),
        )
        approval_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="approval_request.json", obj=approval_pkg)
        if approval_path:
            approval_pkg["artifact_files"] = {"approval_request_json": approval_path}
        artifacts["approval_request"] = _agent_pipeline_artifact_validate_and_emit(trace_id=str(trace_id), kind="approval_request", artifact=approval_pkg)

    t6s = int(_now_ms())
    sandbox_job = None
    if isinstance(chosen, dict) and chosen.get("strategy_id") and chosen.get("source_zip") and bool(data.get("queue_sandbox", True)):
        try:
            sj_req = {
                "trace_id": trace_id,
                "type": "sandbox.job.request",
                "inputs": {
                    "base_trace_id": (None if data.get("base_trace_id") is None else str(data.get("base_trace_id") or "").strip() or None),
                    "trigger_event": (None if data.get("trigger_event") is None else str(data.get("trigger_event") or "").strip() or None),
                    "candidates": [{"strategy_id": str(chosen.get("strategy_id")), "source_zip": str(chosen.get("source_zip"))}],
                    "data_snapshot": "latest",
                    "config_snapshot": "user_data/config_local_backtest.json",
                    "gates": (data.get("gates") if isinstance(data.get("gates"), list) else ["backtest", "robustness", "stress"]),
                },
            }
            with app.test_request_context(
                "/agent/sandbox/queue/submit",
                method="POST",
                data=json.dumps(sj_req),
                content_type="application/json",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            ):
                resp2 = sandbox_queue_submit()
            resp2_0 = resp2[0] if isinstance(resp2, tuple) and resp2 else resp2
            if hasattr(resp2_0, "get_json"):
                sandbox_job = resp2_0.get_json(force=True) or {}
        except Exception:
            sandbox_job = None
    if sandbox_job is not None:
        sandbox_job_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="sandbox_job.json", obj=sandbox_job)
        if sandbox_job_path and isinstance(sandbox_job, dict):
            sandbox_job["artifact_files"] = {"sandbox_job_json": sandbox_job_path}
        stages.append(_pipeline_stage("sandbox_validation", "running", t6s, int(_now_ms()), {"sandbox_job": _json_sanitize(sandbox_job)}))
    else:
        stages.append(_pipeline_stage("sandbox_validation", "skipped", t6s, int(_now_ms()), {}, {"reason": "queue_sandbox_disabled_or_missing_choice"}))

    t7s = int(_now_ms())
    gov_obj = None
    try:
        gov_obj = (change_bundle.get("governance") if isinstance(change_bundle, dict) else None)
    except Exception:
        gov_obj = None
    gov_decision = None
    try:
        gov_decision = str((gov_obj or {}).get("decision") or "").strip() if isinstance(gov_obj, dict) else None
        if not gov_decision:
            gov_decision = None
    except Exception:
        gov_decision = None

    if gov_decision == "auto_reject":
        stages.append(_pipeline_stage("audit_approval", "fail", t7s, int(_now_ms()), {}, {"reason": "auto_reject", "detail": _json_sanitize(gov_obj)}))
    elif approval_id:
        try:
            ap_ok = _approval_ok(str(approval_id), max_age_ms=int(86400_000))
        except Exception:
            ap_ok = False
        stages.append(_pipeline_stage("audit_approval", ("success" if ap_ok else "running"), t7s, int(_now_ms()), {"approval_request": artifacts.get("approval_request")}, {"approval_id": str(approval_id), "approved": bool(ap_ok)}))
    else:
        stages.append(_pipeline_stage("audit_approval", "skipped", t7s, int(_now_ms()), {}, {"reason": (gov_decision or "no_approval_created"), "detail": _json_sanitize(gov_obj)}))

    change_id = None
    try:
        change_id = str((change_bundle or {}).get("change_id") or "").strip() if isinstance(change_bundle, dict) else None
        if not change_id:
            change_id = None
    except Exception:
        change_id = None
    rollout_plan = _pipeline_rollout_plan_build(trace_id=str(trace_id), now_ms=int(now_ms), change_id=change_id)
    rollout_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="rollout_plan.json", obj=rollout_plan)
    if rollout_path and isinstance(rollout_plan, dict):
        rollout_plan["artifact_files"] = {"rollout_plan_json": rollout_path}
    artifacts["rollout_plan"] = _agent_pipeline_artifact_validate_and_emit(trace_id=str(trace_id), kind="rollout_plan", artifact=rollout_plan)

    monitoring_checklist = _pipeline_monitoring_checklist_build(trace_id=str(trace_id), now_ms=int(now_ms), change_id=change_id)
    checklist_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="monitoring_checklist.json", obj=monitoring_checklist)
    if checklist_path and isinstance(monitoring_checklist, dict):
        monitoring_checklist["artifact_files"] = {"monitoring_checklist_json": checklist_path}
    artifacts["monitoring_checklist"] = _agent_pipeline_artifact_validate_and_emit(trace_id=str(trace_id), kind="monitoring_checklist", artifact=monitoring_checklist)

    t8s = int(_now_ms())
    stages.append(
        _pipeline_stage(
            "rollout_preparation",
            "success" if bool((artifacts.get("rollout_plan") or {}).get("ok", True)) and bool((artifacts.get("monitoring_checklist") or {}).get("ok", True)) else "fail",
            t8s,
            int(_now_ms()),
            {"rollout_plan": artifacts.get("rollout_plan"), "monitoring_checklist": artifacts.get("monitoring_checklist")},
        )
    )
    t9s = int(_now_ms())
    try:
        gray_mode = str(data.get("gray_rollout_mode") or data.get("gray_rollout") or data.get("mode") or "plan_only").strip().lower()
    except Exception:
        gray_mode = "plan_only"
    if gray_mode not in ("plan_only", "execute"):
        gray_mode = "plan_only"
    try:
        execute_allowed = bool(_is_local_request()) or bool(data.get("confirm_live", False)) or bool(shadow_only)
    except Exception:
        execute_allowed = False
    if gray_mode == "execute" and execute_allowed:
        if bool(shadow_only):
            try:
                CONFIG["dry_run"] = True
            except Exception:
                pass
        try:
            _apply_serving_phase("shadow")
        except Exception:
            pass
        stages.append(
            _pipeline_stage(
                "gray_rollout",
                "pending",
                t9s,
                int(_now_ms()),
                {"rollout_plan": artifacts.get("rollout_plan"), "monitoring_checklist": artifacts.get("monitoring_checklist")},
                {"mode": ("shadow_only" if bool(shadow_only) else "execute"), "phase": "shadow", "execute_allowed": True, "executed": False, "shadow_only": bool(shadow_only)},
            )
        )
    elif gray_mode == "execute" and (not execute_allowed):
        stages.append(_pipeline_stage("gray_rollout", "skipped", t9s, int(_now_ms()), {"rollout_plan": artifacts.get("rollout_plan"), "monitoring_checklist": artifacts.get("monitoring_checklist")}, {"mode": "execute", "reason": "confirm_live_required", "execute_allowed": False}))
    else:
        stages.append(_pipeline_stage("gray_rollout", "skipped", t9s, int(_now_ms()), {"rollout_plan": artifacts.get("rollout_plan"), "monitoring_checklist": artifacts.get("monitoring_checklist")}, {"mode": "plan_only", "reason": "plan_only"}))

    archive = _pipeline_archive_record_build(trace_id=str(trace_id), now_ms=int(now_ms), artifacts=artifacts)
    artifacts["archive_record"] = _agent_pipeline_artifact_validate_and_emit(trace_id=str(trace_id), kind="archive_record", artifact=archive)
    archive_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="archive_record.json", obj=archive)
    writeback = _pipeline_archive_writeback(trace_id=str(trace_id), now_ms=int(now_ms), chosen=chosen, change_bundle=change_bundle, approval_id=approval_id, artifacts=artifacts)
    stages.append(_pipeline_stage("archive", "success" if bool((artifacts.get("archive_record") or {}).get("ok", True)) else "fail", int(_now_ms()), int(_now_ms()), {"archive_record": artifacts.get("archive_record")}, {"archive_record_path": archive_path, "writeback": writeback}))

    status = "success"
    if any(str(s.get("status") or "").lower() == "fail" for s in stages if isinstance(s, dict)):
        status = "fail"
    elif any(str(s.get("status") or "").lower() == "running" for s in stages if isinstance(s, dict)):
        status = "running"
    elif any(str(s.get("status") or "").lower() in ("skipped", "pending") for s in stages if isinstance(s, dict)):
        status = "partial"
    pipeline_state = _agent_pipeline_artifact_common_fields(trace_id=str(trace_id), created_at_ms=int(now_ms), producer_kind="agent")
    pipeline_state.update({"ts": int(now_ms), "status": status, "stages": stages, "chosen": chosen, "shadow_only": bool(shadow_only)})
    pipeline_state_path = _agent_pipeline_package_write(trace_id=str(trace_id), filename="pipeline_state.json", obj=pipeline_state)
    if pipeline_state_path and isinstance(pipeline_state, dict):
        pipeline_state["artifact_files"] = {"pipeline_state_json": pipeline_state_path}
    artifacts["pipeline_state"] = _agent_pipeline_artifact_validate_and_emit(trace_id=str(trace_id), kind="pipeline_state", artifact=pipeline_state)

    out = {
        "ok": True,
        "trace_id": trace_id,
        "ts": int(now_ms),
        "regime_report": regime_report,
        "candidate_strategies": candidate_strategies,
        "chosen": chosen,
        "paramopt": paramopt_rep,
        "changeset_draft": (draft if isinstance(draft, dict) else None),
        "draft_id": draft_id,
        "approval_id": approval_id,
        "sandbox_job": sandbox_job,
        "artifacts": artifacts,
        "pipeline_state": pipeline_state,
    }
    return jsonify(out), 200




@bp.route("/evaluation/gate/check", methods=["GET", "POST"])
def evaluation_gate_check():
    CONFIG = _dep("CONFIG")
    _audit_base_payload = _dep("_audit_base_payload")
    _audit_emit_action = _dep("_audit_emit_action")
    _backtest_pick_latest_zip_path = _dep("_backtest_pick_latest_zip_path")
    _backtest_report_from_zip = _dep("_backtest_report_from_zip")
    _now_ms = _dep("_now_ms")
    thr = CONFIG.get("gate_thresholds") or {}
    p = _backtest_pick_latest_zip_path()
    rep = _backtest_report_from_zip(p, strategy=None)
    if not isinstance(rep, dict) or not bool(rep.get("ok")):
        return jsonify({"ok": False, "error": "backtest_unavailable"}), 404
    ms = rep.get("metrics_summary") or {}
    baseline = {}  # could be extended to load baseline
    checks = {
        "pf": (ms.get("pf") is not None) and (float(ms.get("pf")) >= float(thr.get("pf", 1.05))),
        "dd": (ms.get("maxdd") is not None) and (float(ms.get("maxdd")) <= float(thr.get("dd", 0.95))),
        "trades": (ms.get("trades") is not None) and (float(ms.get("trades")) >= float(thr.get("trades", 0.7)) * float((baseline.get("trades") or ms.get("trades") or 1))),
        "winrate": (ms.get("winrate") is not None) and (float(ms.get("winrate")) >= float(thr.get("winrate", 0.95))),
    }
    passed = all(bool(v) for v in checks.values())
    # POST 时记录审计
    if request.method == "POST":
        try:
            data = request.get_json(force=True, silent=True) or {}
            tid = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
            _audit_emit_action("gate.check", _audit_base_payload(scope="evaluation", action="gate.check", trace_id=tid, extra={"passed": bool(passed), "checks": checks}))
        except Exception:
            pass
    return jsonify({"ok": True, "passed": bool(passed), "checks": checks, "thresholds": thr, "metrics": ms, "ts": int(_now_ms())})





@bp.route("/agent/approvals/request", methods=["POST"])
def agent_approvals_request():
    """创建审批请求（写入 approvals.jsonl，decision=pending）。"""
    _agent_write_auth_ok = _dep("_agent_write_auth_ok")
    _approval_append = _dep("_approval_append")
    _audit_base_payload = _dep("_audit_base_payload")
    _audit_emit_action = _dep("_audit_emit_action")
    _doc_refs_sanitize = _dep("_doc_refs_sanitize")
    _now_ms = _dep("_now_ms")
    if not _agent_write_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized", "ts": int(_now_ms())}), 403
    data = request.get_json(force=True) or {}
    trace_id = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
    draft_id = str(data.get("draft_id") or "").strip()
    action = str(data.get("action") or "config.apply").strip() or "config.apply"
    reason = str(data.get("reason") or "").strip() or "agent_request"
    changeset = data.get("changeset") if isinstance(data.get("changeset"), dict) else {}
    gate_results = data.get("gate_result") if isinstance(data.get("gate_result"), dict) else {}
    doc_refs = _doc_refs_sanitize(data.get("doc_refs"))
    evidence = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
    ent = {
        "trace_id": trace_id,
        "decision": "pending",
        "reason": reason,
        "action": action,
        "draft_id": draft_id,
        "changeset": changeset,
        "gate_results": gate_results,
        "doc_refs": doc_refs,
        "evidence": evidence,
        "ts": int(_now_ms()),
        "scope": "governance",
    }
    rid = _approval_append(ent)
    if not rid:
        return jsonify({"ok": False, "error": "write_failed", "ts": int(_now_ms())}), 500
    try:
        _audit_emit_action("approval.requested", _audit_base_payload(scope="governance", action="approval.requested", trace_id=trace_id, extra={"approval_id": rid, "draft_id": draft_id, "action": action}))
    except Exception:
        pass
    return jsonify({"ok": True, "approval_id": rid, "trace_id": trace_id, "decision": "pending", "ts": int(_now_ms())}), 200






@bp.route("/agent/approvals/list", methods=["GET"])
def agent_approvals_list():
    """返回审批列表（默认 pending，可按 status 过滤）。"""
    _agent_read_auth_ok = _dep("_agent_read_auth_ok")
    _approvals_log_path = _dep("_approvals_log_path")
    _json_sanitize = _dep("_json_sanitize")
    _now_ms = _dep("_now_ms")
    _tail_lines = _dep("_tail_lines")
    if not _agent_read_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized", "ts": int(_now_ms())}), 403
    status = str(request.args.get("status") or "pending").strip().lower()
    try:
        max_lines = int(request.args.get("max_lines") or 2000)
    except Exception:
        max_lines = 2000
    max_lines = max(50, min(50000, int(max_lines)))
    items: List[Dict[str, Any]] = []
    try:
        p = _approvals_log_path()
        if p.exists() and p.is_file():
            lines = _tail_lines(p, max_lines=max_lines, max_bytes=20_000_000)
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
                dec = str(obj.get("decision") or "").strip().lower()
                if status == "all" or dec == status:
                    items.append(_json_sanitize(obj))
    except Exception:
        pass
    return jsonify({"ok": True, "status": status, "count": len(items), "items": items, "ts": int(_now_ms())}), 200






@bp.route("/agent/approvals/action", methods=["POST"])
def agent_approvals_action():
    """审批动作：approve / reject，更新 decision 字段（追加新记录）。"""
    _approval_append = _dep("_approval_append")
    _approval_lookup = _dep("_approval_lookup")
    _audit_base_payload = _dep("_audit_base_payload")
    _audit_emit_action = _dep("_audit_emit_action")
    _doc_refs_sanitize = _dep("_doc_refs_sanitize")
    _governance_write_auth_ok = _dep("_governance_write_auth_ok")
    _now_ms = _dep("_now_ms")
    if not _governance_write_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized", "ts": int(_now_ms())}), 403
    data = request.get_json(force=True) or {}
    approval_id = str(data.get("approval_id") or data.get("id") or "").strip()
    if not approval_id:
        return jsonify({"ok": False, "error": "missing_approval_id", "ts": int(_now_ms())}), 400
    decision = str(data.get("decision") or data.get("action") or "").strip().lower()
    if decision not in ("approve", "approved", "reject", "rejected"):
        return jsonify({"ok": False, "error": "invalid_decision", "ts": int(_now_ms())}), 400
    norm_decision = "approved" if decision in ("approve", "approved") else "reject"
    approver = str(data.get("approver") or "").strip() or "manual"
    reason = str(data.get("reason") or "").strip() or f"manual_{norm_decision}"
    trace_id = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
    # 查找原审批记录以保留上下文
    prev = _approval_lookup(approval_id, max_lines=20000, max_bytes=20_000_000)
    chg = (prev.get("changeset") if isinstance(prev, dict) else {}) or {}
    gate = (prev.get("gate_results") if isinstance(prev, dict) else {}) or {}
    doc_refs = _doc_refs_sanitize(prev.get("doc_refs") if isinstance(prev, dict) else None)
    ent = {
        "id": approval_id,
        "trace_id": trace_id,
        "approver": approver,
        "decision": norm_decision,
        "reason": reason,
        "action": str(prev.get("action") if isinstance(prev, dict) else "config.apply") or "config.apply",
        "draft_id": str(prev.get("draft_id") if isinstance(prev, dict) else "") or "",
        "changeset": chg,
        "gate_results": gate,
        "doc_refs": doc_refs,
        "evidence": data.get("evidence") if isinstance(data.get("evidence"), dict) else {},
        "ts": int(_now_ms()),
        "scope": "governance",
    }
    rid = _approval_append(ent)
    try:
        _audit_emit_action(f"approval.{norm_decision}", _audit_base_payload(scope="governance", action=f"approval.{norm_decision}", trace_id=trace_id, extra={"approval_id": approval_id, "approver": approver, "reason": reason}))
    except Exception:
        pass
    return jsonify({"ok": True, "approval_id": rid or approval_id, "decision": norm_decision, "ts": int(_now_ms())}), 200






@bp.route("/agent/audit/record", methods=["POST"])
def agent_audit_record():
    """记录审计事件（追加写入 audit_actions.jsonl）。"""
    _agent_write_auth_ok = _dep("_agent_write_auth_ok")
    _audit_base_payload = _dep("_audit_base_payload")
    _audit_emit_action = _dep("_audit_emit_action")
    _now_ms = _dep("_now_ms")
    if not _agent_write_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized", "ts": int(_now_ms())}), 403
    data = request.get_json(force=True) or {}
    name = str(data.get("name") or data.get("action") or "audit.record").strip() or "audit.record"
    trace_id = str(data.get("trace_id") or "").strip() or None
    stage = str(data.get("stage") or "").strip() or None
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    if stage:
        extra["stage"] = stage
    payload = _audit_base_payload(scope=str(data.get("scope") or "governance"), action=name, trace_id=trace_id, extra=extra if extra else None)
    _audit_emit_action(name, payload)
    return jsonify({"ok": True, "name": name, "ts": int(_now_ms())}), 200




@bp.route("/strategy/registry", methods=["GET"])
def strategy_registry_get():
    _github_asset_reconcile_for_entry = _dep("_github_asset_reconcile_for_entry")
    _now_ms = _dep("_now_ms")
    _strategy_registry_load = _dep("_strategy_registry_load")
    _strategy_registry_save = _dep("_strategy_registry_save")
    reg = _strategy_registry_load()
    entries = reg.get("entries") if isinstance(reg.get("entries"), dict) else {}
    items: List[Dict[str, Any]] = []
    for v in entries.values():
        if isinstance(v, dict):
            items.append(v)
    items.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    changed = False
    checked = 0
    for it in items:
        try:
            src = it.get("source") if isinstance(it.get("source"), dict) else {}
            if str(src.get("kind") or "").strip().lower() != "github":
                continue
            checked += 1
            need = (not str(src.get("asset_mirror_path") or "").strip()) or (not isinstance(src.get("asset_links"), list))
            if not need:
                try:
                    sid = str(it.get("strategy_id") or "").strip()
                    mp = str(src.get("asset_mirror_path") or "").strip()
                    if sid and mp:
                        p = Path(mp)
                        if p.exists() and p.is_file():
                            try:
                                txt = p.read_text(encoding="utf-8", errors="ignore")
                            except Exception:
                                txt = p.read_text(errors="ignore")
                            low = txt.lower()
                            sid_low = sid.lower()
                            if sid_low and (f"class {sid_low}" not in low and f"class\t{sid_low}" not in low):
                                need = True
                        else:
                            need = True
                except Exception:
                    pass
            if not need:
                continue
            rep = _github_asset_reconcile_for_entry(it)
            if isinstance(rep, dict) and bool(rep.get("ok")) and (not bool(rep.get("skipped"))):
                changed = True
        except Exception:
            continue
        if checked >= 50:
            break
    if changed:
        try:
            _strategy_registry_save(reg)
        except Exception:
            pass
    return jsonify({"ok": True, "ts": int(_now_ms()), "entries": items})





@bp.route("/strategy/registry/upsert", methods=["POST"])
def strategy_registry_upsert():
    _audit_base_payload = _dep("_audit_base_payload")
    _audit_emit_action = _dep("_audit_emit_action")
    _governance_require_approval_or_error = _dep("_governance_require_approval_or_error")
    _governance_write_auth_ok = _dep("_governance_write_auth_ok")
    _now_ms = _dep("_now_ms")
    _strategy_registry_upsert_impl = _dep("_strategy_registry_upsert_impl")
    if not _governance_write_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    data = request.get_json(force=True) or {}
    trace_id = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
    ok_appr, approval_id, err_obj, err_code = _governance_require_approval_or_error(data, trace_id=trace_id, action="strategy.registry.upsert")
    if not ok_appr:
        return jsonify(err_obj), int(err_code)
    items = data.get("items") if isinstance(data.get("items"), list) else []
    ok, saved, err = _strategy_registry_upsert_impl(items=items, trace_id=trace_id, approval_id=approval_id)
    if err:
        return jsonify(err), 400
    try:
        _audit_emit_action(
            "strategy.registry.upsert",
            _audit_base_payload(scope="governance", action="strategy.registry.upsert", trace_id=trace_id, extra={"ok": bool(ok), "saved": int(saved), "approval_id": approval_id}),
        )
    except Exception:
        pass
    return jsonify({"ok": bool(ok), "saved": int(saved), "trace_id": trace_id, "approval_id": approval_id, "ts": int(_now_ms())})





@bp.route("/strategy/registry/import_active", methods=["POST"])
def strategy_registry_import_active():
    CONFIG = _dep("CONFIG")
    _audit_base_payload = _dep("_audit_base_payload")
    _audit_emit_action = _dep("_audit_emit_action")
    _governance_require_approval_or_error = _dep("_governance_require_approval_or_error")
    _governance_write_auth_ok = _dep("_governance_write_auth_ok")
    _infer_strategy_family_from_id = _dep("_infer_strategy_family_from_id")
    _now_ms = _dep("_now_ms")
    _strategy_family_normalize = _dep("_strategy_family_normalize")
    _strategy_registry_upsert_impl = _dep("_strategy_registry_upsert_impl")
    _strategy_stage_normalize = _dep("_strategy_stage_normalize")
    if not _governance_write_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    data = request.get_json(force=True) or {}
    trace_id = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
    ok_appr, approval_id, err_obj, err_code = _governance_require_approval_or_error(data, trace_id=trace_id, action="strategy.registry.import_active")
    if not ok_appr:
        return jsonify(err_obj), int(err_code)

    source_zip = str(data.get("source_zip") or "*").strip() or "*"
    if source_zip != "*":
        if (not source_zip.lower().endswith(".zip")) or (".." in source_zip) or ("/" in source_zip) or ("\\" in source_zip):
            return jsonify({"ok": False, "error": "bad_source_zip"}), 400

    stage_default = str(data.get("stage") or "deployment").strip() or "deployment"
    stage_n = _strategy_stage_normalize(stage_default)
    if stage_n is None:
        return jsonify({"ok": False, "error": "invalid_stage"}), 400

    cfg = CONFIG or {}
    sm = cfg.get("strategy_meta") or {}
    ids: List[str] = []
    if isinstance(sm, dict):
        for k in sm.keys():
            s = str(k or "").strip()
            if s:
                ids.append(s)
    for sid0 in ("RegimeHybridStrategy", "Strategy005", "MultiGroupStrategy", "BreakoutStrategy"):
        if sid0 not in ids:
            ids.append(sid0)
    ids = sorted({str(x).strip() for x in ids if str(x).strip()})

    items: List[Dict[str, Any]] = []
    for sid in ids:
        fam = _infer_strategy_family_from_id(sid)
        fam_n = _strategy_family_normalize(fam) or "trend"
        feats = sm.get(sid) if isinstance(sm, dict) else None
        group_id = str((feats or {}).get("group_id") or "").strip() if isinstance(feats, dict) else ""
        feature_set_id = str((feats or {}).get("feature_set_id") or "").strip() if isinstance(feats, dict) else ""
        tags = ["active", "in_use"]
        if group_id:
            tags.append(f"gid:{group_id}")
        if feature_set_id:
            tags.append(f"fs:{feature_set_id}")
        items.append(
            {
                "strategy_id": sid,
                "source_zip": source_zip,
                "family": fam_n,
                "stage": stage_n,
                "tags": tags,
                "robustness": "unknown",
                "features": {"group_id": group_id or None, "feature_set_id": feature_set_id or None},
                "source": {"kind": "import_active", "ts": int(_now_ms())},
            }
        )

    ok, saved, err = _strategy_registry_upsert_impl(items=items, trace_id=trace_id, approval_id=approval_id)
    if err:
        return jsonify(err), 400
    try:
        _audit_emit_action(
            "strategy.registry.import_active",
            _audit_base_payload(scope="governance", action="strategy.registry.import_active", trace_id=trace_id, extra={"ok": bool(ok), "saved": int(saved), "approval_id": approval_id, "source_zip": source_zip}),
        )
    except Exception:
        pass
    return jsonify({"ok": bool(ok), "saved": int(saved), "trace_id": trace_id, "approval_id": approval_id, "source_zip": source_zip, "ts": int(_now_ms())}), 200





@bp.route("/strategy/registry/sync_from_zip", methods=["POST"])
def strategy_registry_sync_from_zip():
    _audit_base_payload = _dep("_audit_base_payload")
    _audit_emit_action = _dep("_audit_emit_action")
    _backtests_dir = _dep("_backtests_dir")
    _characterization_gate_check_or_error = _dep("_characterization_gate_check_or_error")
    _governance_require_approval_or_error = _dep("_governance_require_approval_or_error")
    _governance_write_auth_ok = _dep("_governance_write_auth_ok")
    _json_sanitize = _dep("_json_sanitize")
    _strategy_registry_sync_from_zip_impl = _dep("_strategy_registry_sync_from_zip_impl")
    if not _governance_write_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    data = request.get_json(force=True) or {}
    trace_id = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
    ok_appr, approval_id, err_obj, err_code = _governance_require_approval_or_error(data, trace_id=trace_id, action="strategy.registry.sync_from_zip")
    if not ok_appr:
        return jsonify(err_obj), int(err_code)
    name = data.get("zip")
    s = "" if name is None else str(name).strip()
    if (not s) or (not s.lower().endswith(".zip")) or (".." in s) or ("/" in s) or ("\\" in s):
        return jsonify({"ok": False, "error": "bad_zip"}), 400
    zip_path = _backtests_dir() / s
    if (not zip_path.exists()) or (not zip_path.is_file()):
        return jsonify({"ok": False, "error": "backtest_zip_not_found"}), 404

    gate_err, gate_code = _characterization_gate_check_or_error(action="strategy.registry.sync_from_zip", config_keys=None)
    if gate_err is not None and gate_code is not None:
        gate_err["trace_id"] = trace_id
        gate_err["approval_id"] = approval_id
        return jsonify(_json_sanitize(gate_err)), int(gate_code)

    out, code = _strategy_registry_sync_from_zip_impl(data=data, zip_path=Path(zip_path))
    try:
        _audit_emit_action(
            "strategy.registry.sync_from_zip",
            _audit_base_payload(scope="governance", action="strategy.registry.sync_from_zip", trace_id=trace_id, extra={"ok": (bool(out.get("ok")) if isinstance(out, dict) else None), "http": int(code), "zip": str(s), "approval_id": approval_id}),
        )
    except Exception:
        pass
    if isinstance(out, dict):
        out["trace_id"] = trace_id
        out["approval_id"] = approval_id
    return jsonify(out), int(code)





@bp.route("/strategy/registry/run_and_sync", methods=["POST"])
def strategy_registry_run_and_sync():
    _audit_base_payload = _dep("_audit_base_payload")
    _audit_emit_action = _dep("_audit_emit_action")
    _backtests_dir = _dep("_backtests_dir")
    _characterization_gate_check_or_error = _dep("_characterization_gate_check_or_error")
    _governance_require_approval_or_error = _dep("_governance_require_approval_or_error")
    _governance_write_auth_ok = _dep("_governance_write_auth_ok")
    _json_sanitize = _dep("_json_sanitize")
    _now_ms = _dep("_now_ms")
    _run_backtest = _dep("_run_backtest")
    _strategy_registry_sync_from_zip_impl = _dep("_strategy_registry_sync_from_zip_impl")
    if not _governance_write_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    data = request.get_json(force=True) or {}
    trace_id = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
    ok_appr, approval_id, err_obj, err_code = _governance_require_approval_or_error(data, trace_id=trace_id, action="strategy.registry.run_and_sync")
    if not ok_appr:
        return jsonify(err_obj), int(err_code)
    sid = str(data.get("strategy_id") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "missing_strategy_id"}), 400
    config_path = str(data.get("config") or "user_data/config_local_backtest.json").strip() or "user_data/config_local_backtest.json"
    if (".." in config_path) or config_path.startswith("/") or config_path.startswith("\\") or (not config_path.startswith("user_data/")) or (not config_path.lower().endswith(".json")):
        return jsonify({"ok": False, "error": "bad_config"}), 400
    timerange = data.get("timerange")
    timerange_s = None if timerange is None else str(timerange).strip()
    if timerange_s == "":
        timerange_s = None
    try:
        timeout_sec = float(data.get("timeout_sec", 1800) or 1800)
    except Exception:
        timeout_sec = 1800.0
    timeout_sec = float(max(30.0, min(6 * 3600.0, timeout_sec)))

    bt = _run_backtest(config_path, timerange_s, strategy=sid, timeout_sec=timeout_sec)
    if not bool(bt.get("ok")):
        return (
            jsonify({"ok": False, "error": "backtest_failed", "trace_id": trace_id, "approval_id": approval_id, "backtest": bt}),
            200,
        )
    zip_name = str(bt.get("result_zip") or "").strip()
    if (not zip_name) or (not zip_name.lower().endswith(".zip")) or (".." in zip_name) or ("/" in zip_name) or ("\\" in zip_name):
        return (
            jsonify({"ok": False, "error": "bad_result_zip", "trace_id": trace_id, "approval_id": approval_id, "backtest": bt}),
            200,
        )
    zip_path = _backtests_dir() / zip_name
    if (not zip_path.exists()) or (not zip_path.is_file()):
        return (
            jsonify({"ok": False, "error": "backtest_zip_not_found", "trace_id": trace_id, "approval_id": approval_id, "backtest": bt}),
            200,
        )

    payload = dict(data)
    payload["zip"] = zip_name
    if payload.get("n_bootstrap") is None and payload.get("n_shuffle") is None:
        deep = bool(payload.get("deep_robustness", False))
        if deep:
            payload["n_bootstrap"] = 200
            payload["n_shuffle"] = 200
        else:
            payload["n_bootstrap"] = 0
            payload["n_shuffle"] = 0
    if payload.get("n_slices") is None:
        payload["n_slices"] = 6

    gate_err, gate_code = _characterization_gate_check_or_error(action="strategy.registry.run_and_sync", config_keys=None)
    if gate_err is not None and gate_code is not None:
        gate_err["trace_id"] = trace_id
        gate_err["approval_id"] = approval_id
        return jsonify(_json_sanitize(gate_err)), int(gate_code)

    out, code = _strategy_registry_sync_from_zip_impl(data=payload, zip_path=Path(zip_path))
    if int(code) != 200 or not bool(out.get("ok")):
        try:
            _audit_emit_action(
                "strategy.registry.run_and_sync",
                _audit_base_payload(scope="governance", action="strategy.registry.run_and_sync", trace_id=trace_id, extra={"ok": False, "http": int(code), "strategy_id": sid, "approval_id": approval_id, "error": out.get("error") if isinstance(out, dict) else None}),
            )
        except Exception:
            pass
        return jsonify({"ok": False, "error": out.get("error") or "sync_failed", "trace_id": trace_id, "approval_id": approval_id, "backtest": bt, "sync": out}), int(code)
    try:
        _audit_emit_action(
            "strategy.registry.run_and_sync",
            _audit_base_payload(scope="governance", action="strategy.registry.run_and_sync", trace_id=trace_id, extra={"ok": True, "strategy_id": sid, "approval_id": approval_id, "zip": str(zip_name)}),
        )
    except Exception:
        pass
    return jsonify({"ok": True, "ts": int(_now_ms()), "trace_id": trace_id, "approval_id": approval_id, "backtest": bt, "sync": out}), 200





@bp.route("/strategy/registry/event", methods=["POST"])
def strategy_registry_event_append():
    _append_jsonl = _dep("_append_jsonl")
    _audit_base_payload = _dep("_audit_base_payload")
    _audit_emit_action = _dep("_audit_emit_action")
    _governance_require_approval_or_error = _dep("_governance_require_approval_or_error")
    _governance_write_auth_ok = _dep("_governance_write_auth_ok")
    _iso_from_any = _dep("_iso_from_any")
    _now_ms = _dep("_now_ms")
    _strategy_lifecycle_expected_stage = _dep("_strategy_lifecycle_expected_stage")
    _strategy_lifecycle_normalize = _dep("_strategy_lifecycle_normalize")
    _strategy_lifecycle_prereq_ok = _dep("_strategy_lifecycle_prereq_ok")
    _strategy_lifecycle_transition_ok = _dep("_strategy_lifecycle_transition_ok")
    _strategy_registry_events_path = _dep("_strategy_registry_events_path")
    _strategy_registry_key = _dep("_strategy_registry_key")
    _strategy_registry_load = _dep("_strategy_registry_load")
    _strategy_registry_save = _dep("_strategy_registry_save")
    if not _governance_write_auth_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    data = request.get_json(force=True) or {}
    trace_id_in = str(data.get("trace_id") or "").strip() or None
    trace_id_appr = trace_id_in or uuid.uuid4().hex
    ok_appr, approval_id, err_obj, err_code = _governance_require_approval_or_error(data, trace_id=trace_id_appr, action="strategy.registry.event")
    if not ok_appr:
        return jsonify(err_obj), int(err_code)
    sid = str(data.get("strategy_id") or "").strip()
    source_zip = str(data.get("source_zip") or "").strip()
    if (not sid) or (not source_zip):
        return jsonify({"ok": False, "error": "missing_key"}), 400
    if (not source_zip.lower().endswith(".zip")) or (".." in source_zip) or ("/" in source_zip) or ("\\" in source_zip):
        return jsonify({"ok": False, "error": "bad_source_zip"}), 400

    kind = str(data.get("kind") or "").strip().lower()
    allowed = {"rollout", "rollback", "tier_change", "deprecate", "note", "lifecycle"}
    if kind not in allowed:
        return jsonify({"ok": False, "error": "invalid_kind"}), 400

    trace_id = trace_id_in
    actor = str(data.get("actor") or "").strip() or None
    note = str(data.get("note") or "").strip() or None
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}

    if kind != "note" and not trace_id:
        return jsonify({"ok": False, "error": "missing_trace_id"}), 400

    reg = _strategy_registry_load()
    entries = reg.get("entries") if isinstance(reg.get("entries"), dict) else {}
    key = _strategy_registry_key(sid, source_zip)
    existing = entries.get(key) if isinstance(entries.get(key), dict) else {}
    if not existing:
        return jsonify({"ok": False, "error": "entry_not_found"}), 404

    before = {
        "tier": existing.get("tier"),
        "tier_reason": existing.get("tier_reason"),
        "baseline_ref": existing.get("baseline_ref"),
        "stage": existing.get("stage"),
        "lifecycle_state": existing.get("lifecycle_state"),
        "rollout": existing.get("rollout"),
        "rollback": existing.get("rollback"),
        "deprecated_reason": existing.get("deprecated_reason"),
        "replacement_candidates": existing.get("replacement_candidates"),
        "robustness": existing.get("robustness"),
        "approved_by": existing.get("approved_by"),
        "approved_at": existing.get("approved_at"),
    }

    out = dict(existing)
    now_iso = datetime.now(timezone.utc).isoformat()
    if kind == "rollout":
        status = str(payload.get("status") or "").strip().lower()
        if status not in {"planned", "canary", "full", "paused", "completed", "failed"}:
            return jsonify({"ok": False, "error": "invalid_rollout_status"}), 400
        if "lifecycle_state" in payload and payload.get("lifecycle_state") is not None:
            if _strategy_lifecycle_normalize(payload.get("lifecycle_state")) is None:
                return jsonify({"ok": False, "error": "invalid_lifecycle_state"}), 400
        out["rollout"] = {
            "status": status,
            "metrics": payload.get("metrics") if isinstance(payload.get("metrics"), dict) else None,
            "since_ts": payload.get("since_ts"),
            "trace_id": trace_id,
            "note": note,
        }
        if "lifecycle_state" in payload and payload.get("lifecycle_state") is not None:
            nxt = _strategy_lifecycle_normalize(payload.get("lifecycle_state"))
            if nxt is None:
                return jsonify({"ok": False, "error": "invalid_lifecycle_state"}), 400
            if not _strategy_lifecycle_transition_ok(existing.get("lifecycle_state"), nxt):
                return jsonify({"ok": False, "error": "invalid_lifecycle_transition"}), 400
            out["lifecycle_state"] = nxt
            exp = _strategy_lifecycle_expected_stage(nxt)
            if exp is not None:
                out["stage"] = exp
            ok2, reason2 = _strategy_lifecycle_prereq_ok(to_state=nxt, entry=out)
            if not ok2:
                return jsonify({"ok": False, "error": f"lifecycle_prereq_failed:{reason2}"}), 400
    elif kind == "rollback":
        to_bundle_id = str(payload.get("to_bundle_id") or "").strip() or None
        if not to_bundle_id:
            return jsonify({"ok": False, "error": "missing_to_bundle_id"}), 400
        out["rollback"] = {
            "to_bundle_id": to_bundle_id,
            "reason": str(payload.get("reason") or "").strip() or None,
            "trace_id": trace_id,
            "note": note,
        }
        if not _strategy_lifecycle_transition_ok(existing.get("lifecycle_state"), "rolled_back"):
            return jsonify({"ok": False, "error": "invalid_lifecycle_transition"}), 400
        out["lifecycle_state"] = "rolled_back"
        exp = _strategy_lifecycle_expected_stage("rolled_back")
        if exp is not None:
            out["stage"] = exp
        ok2, reason2 = _strategy_lifecycle_prereq_ok(to_state="rolled_back", entry=out)
        if not ok2:
            return jsonify({"ok": False, "error": f"lifecycle_prereq_failed:{reason2}"}), 400
    elif kind == "tier_change":
        t = str(payload.get("tier") or "").strip().upper()
        if t not in {"A", "B", "C", "UNRATED"}:
            return jsonify({"ok": False, "error": "invalid_tier"}), 400
        old_t = str(existing.get("tier") or "unrated").strip().upper()
        rank = {"A": 3, "B": 2, "C": 1, "UNRATED": 0}
        old_rank = rank.get(old_t, 0)
        new_rank = rank.get(t, 0)
        if new_rank < old_rank:
            reason = str(payload.get("tier_reason") or "").strip()
            if not reason and not note:
                return jsonify({"ok": False, "error": "missing_tier_reason"}), 400
        out["tier"] = ("unrated" if t == "UNRATED" else t)
        if payload.get("tier_reason") is not None:
            out["tier_reason"] = str(payload.get("tier_reason") or "").strip()
        if payload.get("baseline_ref") is not None:
            out["baseline_ref"] = str(payload.get("baseline_ref") or "").strip()
    elif kind == "deprecate":
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            return jsonify({"ok": False, "error": "missing_deprecate_reason"}), 400
        if not _strategy_lifecycle_transition_ok(existing.get("lifecycle_state"), "deprecated"):
            return jsonify({"ok": False, "error": "invalid_lifecycle_transition"}), 400
        out["lifecycle_state"] = "deprecated"
        out["deprecated_reason"] = reason

        rollback_to = str(payload.get("rollback_to_bundle_id") or "").strip() or None
        if rollback_to:
            out["rollback"] = {
                "to_bundle_id": rollback_to,
                "reason": str(payload.get("rollback_reason") or "").strip() or reason,
                "trace_id": trace_id,
                "note": note,
            }

        repl_raw = payload.get("replacement_candidates")
        repl: List[str] = []
        if isinstance(repl_raw, list):
            for x in repl_raw:
                s = str(x or "").strip()
                if s:
                    repl.append(s)
        elif isinstance(repl_raw, str):
            for x in repl_raw.split(","):
                s = str(x or "").strip()
                if s:
                    repl.append(s)
        if repl:
            out["replacement_candidates"] = repl
        exp = _strategy_lifecycle_expected_stage("deprecated")
        if exp is not None:
            out["stage"] = exp
    elif kind == "lifecycle":
        nxt = _strategy_lifecycle_normalize(payload.get("lifecycle_state"))
        if nxt is None:
            return jsonify({"ok": False, "error": "missing_lifecycle_state"}), 400
        if not _strategy_lifecycle_transition_ok(existing.get("lifecycle_state"), nxt):
            return jsonify({"ok": False, "error": "invalid_lifecycle_transition"}), 400
        out["lifecycle_state"] = nxt
        exp = _strategy_lifecycle_expected_stage(nxt)
        if exp is not None:
            out["stage"] = exp

        ab = payload.get("approved_by")
        aa = payload.get("approved_at")
        if nxt == "approved" and (ab is None or str(ab or "").strip() == ""):
            ab = actor
        if ab is not None:
            out["approved_by"] = str(ab or "").strip()
        if aa is not None:
            out["approved_at"] = _iso_from_any(aa)
        if nxt == "approved":
            if not str(out.get("approved_by") or "").strip():
                return jsonify({"ok": False, "error": "approval_required"}), 400
            if not _iso_from_any(out.get("approved_at")):
                out["approved_at"] = datetime.now(timezone.utc).isoformat()

        ok2, reason2 = _strategy_lifecycle_prereq_ok(to_state=nxt, entry=out)
        if not ok2:
            return jsonify({"ok": False, "error": f"lifecycle_prereq_failed:{reason2}"}), 400
    elif kind == "note":
        pass

    out["updated_at"] = now_iso
    entries[key] = out
    reg["entries"] = entries
    ok = _strategy_registry_save(reg)
    if not bool(ok):
        return jsonify({"ok": False, "error": "registry_save_failed"}), 500

    evt_id = str(uuid.uuid4())
    evt = {
        "id": evt_id,
        "ts": int(_now_ms()),
        "trace_id": trace_id,
        "actor": actor,
        "kind": kind,
        "strategy_id": sid,
        "source_zip": source_zip,
        "note": note,
        "payload": payload,
        "before": before,
        "after": {
            "tier": out.get("tier"),
            "tier_reason": out.get("tier_reason"),
            "baseline_ref": out.get("baseline_ref"),
            "stage": out.get("stage"),
            "lifecycle_state": out.get("lifecycle_state"),
            "rollout": out.get("rollout"),
            "rollback": out.get("rollback"),
            "deprecated_reason": out.get("deprecated_reason"),
            "replacement_candidates": out.get("replacement_candidates"),
            "robustness": out.get("robustness"),
            "approved_by": out.get("approved_by"),
            "approved_at": out.get("approved_at"),
        },
    }
    _append_jsonl(_strategy_registry_events_path(), evt)
    try:
        _audit_emit_action(
            "strategy.registry.event",
            _audit_base_payload(scope="governance", action="strategy.registry.event", trace_id=trace_id_appr, extra={"ok": True, "kind": kind, "strategy_id": sid, "source_zip": source_zip, "approval_id": approval_id, "trace_id": trace_id}),
        )
    except Exception:
        pass
    return jsonify({"ok": True, "ts": int(_now_ms()), "event": evt, "entry": out, "approval_id": approval_id, "trace_id": trace_id_appr})





@bp.route("/strategy/registry/events", methods=["GET"])
def strategy_registry_events_get():
    _now_ms = _dep("_now_ms")
    _strategy_registry_events_path = _dep("_strategy_registry_events_path")
    _tail_lines = _dep("_tail_lines")
    sid = str(request.args.get("strategy_id") or "").strip()
    source_zip = str(request.args.get("source_zip") or "").strip()
    if (not sid) or (not source_zip):
        return jsonify({"ok": False, "error": "missing_key"}), 400
    if (not source_zip.lower().endswith(".zip")) or (".." in source_zip) or ("/" in source_zip) or ("\\" in source_zip):
        return jsonify({"ok": False, "error": "bad_source_zip"}), 400
    try:
        limit = int(request.args.get("limit") or 200)
    except Exception:
        limit = 200
    limit = max(1, min(2000, int(limit)))
    p = _strategy_registry_events_path()
    if (not p.exists()) or (not p.is_file()):
        return jsonify({"ok": True, "ts": int(_now_ms()), "events": []})
    lines = _tail_lines(p, max_lines=max(2000, limit * 10), max_bytes=2000000)
    out: List[Dict[str, Any]] = []
    for ln in reversed(lines):
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("strategy_id") or "").strip() != sid:
            continue
        if str(obj.get("source_zip") or "").strip() != source_zip:
            continue
        out.append(obj)
        if len(out) >= limit:
            break
    out.reverse()
    return jsonify({"ok": True, "ts": int(_now_ms()), "events": out})





@bp.route("/strategy/registry/import_from_github", methods=["POST"])
def strategy_registry_import_from_github():
    _agent_outbox_append_jsonl = _dep("_agent_outbox_append_jsonl")
    _agent_sandbox_task_auth_ok = _dep("_agent_sandbox_task_auth_ok")
    _backtests_dir = _dep("_backtests_dir")
    _governance_require_approval_or_error = _dep("_governance_require_approval_or_error")
    _governance_write_auth_ok = _dep("_governance_write_auth_ok")
    _is_local_request = _dep("_is_local_request")
    _normalize_repo_url = _dep("_normalize_repo_url")
    _now_ms = _dep("_now_ms")
    _parse_github_tree_url = _dep("_parse_github_tree_url")
    _repo_ensure_cached = _dep("_repo_ensure_cached")
    _repo_fetch_enabled = _dep("_repo_fetch_enabled")
    _repo_id_from_url = _dep("_repo_id_from_url")
    _repo_update_registry = _dep("_repo_update_registry")
    _repo_url_allowed = _dep("_repo_url_allowed")
    _run_backtest = _dep("_run_backtest")
    _strategy_pick_files = _dep("_strategy_pick_files")
    _strategy_registry_sync_from_zip_impl = _dep("_strategy_registry_sync_from_zip_impl")
    _strategy_sandbox_stage = _dep("_strategy_sandbox_stage")
    _strategy_scan_forbidden = _dep("_strategy_scan_forbidden")
    if not (_governance_write_auth_ok() or _agent_sandbox_task_auth_ok()):
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    if not _repo_fetch_enabled():
        return jsonify({"ok": False, "error": "repo_fetch_disabled"}), 400

    data = request.get_json(force=True) or {}
    trace_id = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
    confirm_live = bool(data.get("confirm_live", False))
    data.pop("confirm_live", None)
    ok_appr, approval_id, err_obj, err_code = _governance_require_approval_or_error(data, trace_id=trace_id, action="strategy.registry.import_from_github")
    if not ok_appr:
        return jsonify(err_obj), int(err_code)
    if (not _is_local_request()) and (not bool(confirm_live)):
        return jsonify({"ok": False, "error": "confirm_live_required", "ts": int(_now_ms())}), 400
    ts0 = int(_now_ms())
    url = str(data.get("url") or data.get("repo_url") or "").strip()

    family = str(data.get("family") or "trend").strip() or "trend"
    stage = str(data.get("stage") or "research").strip() or "research"
    timerange = (None if data.get("timerange") is None else str(data.get("timerange")).strip()) or None
    config_path = str(data.get("config") or "user_data/config_local_backtest.json").strip() or "user_data/config_local_backtest.json"
    if (".." in config_path) or config_path.startswith("/") or config_path.startswith("\\") or (not config_path.startswith("user_data/")) or (not config_path.lower().endswith(".json")):
        return jsonify({"ok": False, "error": "bad_config"}), 400
    try:
        timeout_sec = float(data.get("timeout_sec", 1800) or 1800)
    except Exception:
        timeout_sec = 1800.0
    timeout_sec = float(max(30.0, min(6 * 3600.0, timeout_sec)))

    _agent_outbox_append_jsonl(
        "chat.jsonl",
        {
            "id": uuid.uuid4().hex,
            "trace_id": trace_id,
            "ts": ts0,
            "type": "strategy.import.start",
            "channel": "chat",
            "url": url,
            "family": family,
            "stage": stage,
        },
    )

    repo_url_raw = data.get("repo_url")
    branch = data.get("branch")
    commit = data.get("commit")
    subpath = data.get("path")
    strategy_name = data.get("strategy_name")

    repo_from_tree, tree_branch, tree_subpath = _parse_github_tree_url(str(url or repo_url_raw or ""))
    if repo_from_tree:
        repo_url_raw = repo_from_tree
        if (not branch) and tree_branch:
            branch = tree_branch
        if (not subpath) and tree_subpath:
            subpath = tree_subpath

    repo_url = _normalize_repo_url(repo_url_raw)
    if not repo_url:
        _agent_outbox_append_jsonl("chat.jsonl", {"id": uuid.uuid4().hex, "trace_id": trace_id, "ts": int(_now_ms()), "type": "strategy.import.error", "error": "missing_repo_url"})
        return jsonify({"ok": False, "error": "missing_repo_url", "trace_id": trace_id}), 400
    if not _repo_url_allowed(repo_url):
        _agent_outbox_append_jsonl("chat.jsonl", {"id": uuid.uuid4().hex, "trace_id": trace_id, "ts": int(_now_ms()), "type": "strategy.import.error", "error": "repo_not_whitelisted", "repo_url": repo_url})
        return jsonify({"ok": False, "error": "repo_not_whitelisted", "trace_id": trace_id, "repo_url": repo_url}), 403

    if subpath and str(subpath).strip().lower().endswith(".py"):
        try:
            pp = Path(str(subpath).strip())
            if not strategy_name:
                strategy_name = pp.stem
            parent = str(pp.parent).strip()
            subpath = (None if (not parent) or parent == "." else parent)
        except Exception:
            pass

    ok, head, repo_path, err = _repo_ensure_cached(repo_url, branch=branch, commit=commit)
    if (not ok) or repo_path is None:
        _agent_outbox_append_jsonl("chat.jsonl", {"id": uuid.uuid4().hex, "trace_id": trace_id, "ts": int(_now_ms()), "type": "strategy.import.error", "error": "repo_fetch_failed", "detail": err})
        return jsonify({"ok": False, "error": "repo_fetch_failed", "detail": err, "trace_id": trace_id}), 500

    repo_id = _repo_id_from_url(repo_url)
    commit_id = str(head or "")
    if not commit_id:
        _agent_outbox_append_jsonl("chat.jsonl", {"id": uuid.uuid4().hex, "trace_id": trace_id, "ts": int(_now_ms()), "type": "strategy.import.error", "error": "commit_not_found"})
        return jsonify({"ok": False, "error": "commit_not_found", "trace_id": trace_id}), 500

    stage_ok, sandbox_path, files, stage_err, diff_summary = _strategy_sandbox_stage(repo_path, subpath, repo_id, commit_id, strategy_name=strategy_name)
    if not stage_ok:
        _agent_outbox_append_jsonl("chat.jsonl", {"id": uuid.uuid4().hex, "trace_id": trace_id, "ts": int(_now_ms()), "type": "strategy.import.error", "error": stage_err})
        return jsonify({"ok": False, "error": stage_err, "trace_id": trace_id}), 400

    if not strategy_name:
        try:
            stems = sorted({Path(x).stem for x in (files or []) if str(x).lower().endswith(".py")})
        except Exception:
            stems = []
        if len(stems) == 1:
            strategy_name = stems[0]
        else:
            return jsonify({"ok": False, "error": "missing_strategy_name", "trace_id": trace_id, "candidates": stems}), 400

    _repo_update_registry(repo_id, repo_url, repo_path, commit_id)
    _agent_outbox_append_jsonl(
        "chat.jsonl",
        {
            "id": uuid.uuid4().hex,
            "trace_id": trace_id,
            "ts": int(_now_ms()),
            "type": "strategy.import.stage",
            "ok": True,
            "repo_url": repo_url,
            "repo_id": repo_id,
            "commit": commit_id,
            "sandbox_path": sandbox_path,
            "files": files,
        },
    )

    files2 = _strategy_pick_files(Path(str(sandbox_path)), strategy_name=str(strategy_name))
    hits2 = _strategy_scan_forbidden(files2) if files2 else [{"file": "(none)", "rule": "missing"}]
    if hits2:
        _agent_outbox_append_jsonl("chat.jsonl", {"id": uuid.uuid4().hex, "trace_id": trace_id, "ts": int(_now_ms()), "type": "strategy.import.scan", "ok": False, "hits": hits2})
        return jsonify({"ok": False, "error": "strategy_forbidden_tokens", "hits": hits2, "trace_id": trace_id}), 400
    _agent_outbox_append_jsonl("chat.jsonl", {"id": uuid.uuid4().hex, "trace_id": trace_id, "ts": int(_now_ms()), "type": "strategy.import.scan", "ok": True, "files": [str(x.name) for x in (files2 or [])]})

    bt = _run_backtest(config_path, timerange, strategy=strategy_name, strategy_path=str(sandbox_path), timeout_sec=timeout_sec)
    if not bool(bt.get("ok")):
        _agent_outbox_append_jsonl("chat.jsonl", {"id": uuid.uuid4().hex, "trace_id": trace_id, "ts": int(_now_ms()), "type": "strategy.import.backtest", "ok": False, "backtest": bt})
        return jsonify({"ok": False, "error": "backtest_failed", "backtest": bt, "trace_id": trace_id}), 500

    zip_name = str(bt.get("result_zip") or "").strip()
    if (not zip_name) or (not zip_name.lower().endswith(".zip")) or (".." in zip_name) or ("/" in zip_name) or ("\\" in zip_name):
        return jsonify({"ok": False, "error": "bad_result_zip", "backtest": bt, "trace_id": trace_id}), 500
    zip_path = _backtests_dir() / zip_name
    if (not zip_path.exists()) or (not zip_path.is_file()):
        return jsonify({"ok": False, "error": "backtest_zip_not_found", "backtest": bt, "trace_id": trace_id}), 500

    _agent_outbox_append_jsonl("chat.jsonl", {"id": uuid.uuid4().hex, "trace_id": trace_id, "ts": int(_now_ms()), "type": "strategy.import.backtest", "ok": True, "zip": zip_name, "metrics_summary": bt.get("metrics_summary")})

    tags = data.get("tags") if isinstance(data.get("tags"), list) else None
    sync_payload: Dict[str, Any] = {
        "trace_id": trace_id,
        "zip": zip_name,
        "strategy_id": strategy_name,
        "family": family,
        "stage": stage,
        "eval_policy_ref": (str(data.get("eval_policy_ref") or "").strip() or "p3_default"),
    }
    if tags is not None:
        sync_payload["tags"] = [str(x) for x in tags if str(x or "").strip()]
    if data.get("robustness") is not None:
        sync_payload["robustness"] = data.get("robustness")
    if data.get("econ_driver") is not None:
        sync_payload["econ_driver"] = data.get("econ_driver")
    if data.get("owner") is not None:
        sync_payload["owner"] = data.get("owner")

    sync_payload["source"] = {
        "kind": "github",
        "repo_url": repo_url,
        "repo_id": repo_id,
        "commit": commit_id,
        "branch": (None if branch is None else str(branch)),
        "path": (None if subpath is None else str(subpath)),
        "sandbox_path": sandbox_path,
        "diff_summary": diff_summary,
        "ts": int(_now_ms()),
    }

    out, code = _strategy_registry_sync_from_zip_impl(data=sync_payload, zip_path=Path(zip_path))
    _agent_outbox_append_jsonl("chat.jsonl", {"id": uuid.uuid4().hex, "trace_id": trace_id, "ts": int(_now_ms()), "type": "strategy.import.sync", "ok": bool(out.get("ok")), "sync": out})

    if int(code) != 200 or (not bool(out.get("ok"))):
        return jsonify({"ok": False, "error": out.get("error") or "sync_failed", "trace_id": trace_id, "backtest": bt, "sync": out}), int(code)

    resp = {"ok": True, "ts": int(_now_ms()), "trace_id": trace_id, "approval_id": approval_id, "repo": {"repo_url": repo_url, "repo_id": repo_id, "commit": commit_id, "sandbox_path": sandbox_path, "files": files}, "backtest": bt, "sync": out}
    return jsonify(resp), 200





__all__ = ["bp"]
