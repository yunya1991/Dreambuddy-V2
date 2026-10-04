"""策略工厂变更包模块。

变更包构建、查询、config_patch 安全校验。
依赖大文件中的策略库、配置规则、回滚快照等函数。
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from governance.utils import (
    CONFIG,
    _agent_auto_config_rules,
    _agent_change_bundle_change_id,
    _agent_change_bundle_draft_validate,
    _agent_change_tags_from_config_diff,
    _agent_chat_enforce_doc_refs,
    _agent_config_diff_build,
    _agent_expected_effect_from_delta_metrics,
    _agent_outbox_dir,
    _behavior_summary_autogen_style_mutation,
    _config_patch_level_info,
    _now_ms,
    _rollback_points_get,
    _rollback_snapshot_append,
    _runtime_config_version,
    _stable_json_dumps,
    _tail_lines,
)


def _outbox_dir() -> Path:
    return _agent_outbox_dir()


def _registry_get_entry(strategy_id: str, source_zip: str):
    """从 26-策略管理模块 加载策略注册表条目。"""
    try:
        import sys
        _26_PATH = str(Path(__file__).resolve().parent.parent.parent.parent / "26-策略管理模块")
        if _26_PATH not in sys.path:
            sys.path.insert(0, _26_PATH)
        from strategy_lib.services.registry import _strategy_registry_get_entry as _get
        return _get(strategy_id, source_zip)
    except Exception:
        return None

def _agent_changeset_draft_build(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    trace_id = str(data.get("trace_id") or "").strip() or uuid.uuid4().hex
    strategy_id = str(data.get("strategy_id") or "").strip()
    source_zip = str(data.get("source_zip") or "").strip()
    if not strategy_id or not source_zip:
        return {"ok": False, "error": "missing_strategy_ref", "ts": int(_now_ms()), "trace_id": trace_id}

    strategy_key = f"{strategy_id}@{source_zip}"
    strategy_key_in = data.get("strategy_key")
    if strategy_key_in is not None and str(strategy_key_in).strip() and str(strategy_key_in).strip() != strategy_key:
        return {"ok": False, "error": "strategy_key_mismatch", "strategy_key": strategy_key, "ts": int(_now_ms()), "trace_id": trace_id}

    ent = _registry_get_entry(strategy_id, source_zip)
    if not isinstance(ent, dict) or not ent:
        return {"ok": False, "error": "strategy_registry_entry_not_found", "ts": int(_now_ms()), "trace_id": trace_id}

    config_patch = data.get("config_patch") if isinstance(data.get("config_patch"), dict) else {}
    config_suggest: Dict[str, Any] = {}
    if config_patch:
        val = _agent_config_patch_validate(config_patch, allow_suggest_only=True)
        if not bool(val.get("ok")):
            return {"ok": False, "error": "config_patch_rejected", "violations": val.get("violations"), "ts": int(_now_ms()), "trace_id": trace_id}
        config_patch = val.get("patch") if isinstance(val.get("patch"), dict) else {}
        config_suggest = val.get("suggest") if isinstance(val.get("suggest"), dict) else {}

    config_suggest_in = data.get("config_suggest") if isinstance(data.get("config_suggest"), dict) else {}
    if config_suggest_in:
        rules = _agent_auto_config_rules()
        extra: Dict[str, Any] = {}
        for k, v in config_suggest_in.items():
            kk = str(k or "").strip()
            if not kk:
                continue
            r = rules.get(kk) if isinstance(rules, dict) else None
            if not isinstance(r, dict) or str(r.get("mode") or "").strip().lower() != "suggest-only":
                continue
            tp = str(r.get("type") or "").strip().lower()
            try:
                if tp == "bool":
                    extra[kk] = bool(v)
                elif tp == "int":
                    extra[kk] = int(v)
                elif tp == "float":
                    extra[kk] = float(v)
                elif tp == "str":
                    extra[kk] = str(v)
                elif tp == "list_str":
                    if isinstance(v, list):
                        extra[kk] = [str(x) for x in v if str(x or "").strip()]
            except Exception:
                continue
        if extra:
            config_suggest.update(extra)

    doc_refs = data.get("doc_refs") if isinstance(data.get("doc_refs"), list) else []
    if not doc_refs:
        doc_refs = [
            {"doc_path": "交易AI Agent 技术文档2.0.md", "section": "4.7.6", "rule": "变更包最小集合"},
            {"doc_path": "技术文档.md", "section": "0.3", "rule": "工程索引（SSoT 入口）"},
        ]
    else:
        doc_refs = [x for x in doc_refs if isinstance(x, dict)]
    doc_refs = _agent_chat_enforce_doc_refs(doc_refs)
    label = str(data.get("label") or f"draft:{strategy_id}").strip()
    reason = str(data.get("reason") or "").strip() or "draft"
    baseline = data.get("baseline") if isinstance(data.get("baseline"), dict) else None
    baseline_ref_in = (None if data.get("baseline_ref") is None else str(data.get("baseline_ref") or "").strip()) or None
    baseline_key = None
    if baseline_ref_in:
        baseline_key = baseline_ref_in
    elif isinstance(baseline, dict):
        baseline_key = (None if baseline.get("strategy_key") is None else str(baseline.get("strategy_key") or "").strip()) or None
        if not baseline_key:
            tp = baseline.get("three_piece") if isinstance(baseline.get("three_piece"), dict) else {}
            baseline_key = (None if tp.get("strategy_key") is None else str(tp.get("strategy_key") or "").strip()) or None
    rollback_point_id = (None if data.get("rollback_point_id") is None else str(data.get("rollback_point_id") or "").strip())
    param_optimization = data.get("param_optimization") if isinstance(data.get("param_optimization"), dict) else {}
    gate_result = ent.get("gate_result") if isinstance(ent.get("gate_result"), dict) else {}
    backtest_spec = ent.get("backtest_spec") if isinstance(ent.get("backtest_spec"), dict) else {}
    policy_ref = str(data.get("policy_ref") or "").strip() or "gov_default"
    action = str(data.get("action") or "").strip() or "config.apply"
    direction = (None if data.get("direction") is None else str(data.get("direction") or "").strip()) or None
    objective_profile = (None if data.get("objective_profile") is None else str(data.get("objective_profile") or "").strip()) or None
    behavior_summary = (None if data.get("behavior_summary") is None else str(data.get("behavior_summary") or "").strip()) or None

    cost_profile_id = (None if backtest_spec.get("cost_profile_id") is None else str(backtest_spec.get("cost_profile_id") or "").strip()) or None
    fees_bps = backtest_spec.get("fees_bps")
    slippage_bps = backtest_spec.get("slippage_bps")
    cost_assumptions = None
    try:
        fb = (None if fees_bps is None else float(fees_bps))
        sb = (None if slippage_bps is None else float(slippage_bps))
        if fb is not None and sb is not None and math.isfinite(float(fb)) and math.isfinite(float(sb)):
            cost_assumptions = {"fees_bps": float(fb), "slippage_bps": float(sb), "cost_profile_id": (cost_profile_id or None)}
    except Exception:
        cost_assumptions = None

    level_info = _config_patch_level_info(config_patch, base_cfg=CONFIG)
    change_level = str(level_info.get("level") or "B").strip().upper() or "B"
    if direction:
        dnorm = str(direction).strip().lower()
        if dnorm in ("segment", "rebalance", "segment/rebalance"):
            change_level = "B"
            if not behavior_summary:
                cand_obj = {"metrics_summary": (ent.get("metrics_summary") if isinstance(ent.get("metrics_summary"), dict) else {}), "aligned_metrics": (ent.get("aligned_metrics") if isinstance(ent.get("aligned_metrics"), dict) else {})}
                summ = _behavior_summary_autogen_style_mutation(candidate=cand_obj, baseline=(baseline if isinstance(baseline, dict) else None))
                if isinstance(summ, dict) and summ:
                    try:
                        behavior_summary = json.dumps(summ, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    except Exception:
                        behavior_summary = None

    rollback_point = None
    if not rollback_point_id:
        try:
            cfg_keys = [str(k) for k in (config_patch or {}).keys() if str(k or "").strip()]
        except Exception:
            cfg_keys = []
        try:
            rp = _rollback_snapshot_append(label=str(label or "rollback").strip() or "rollback", reason=str(reason or "").strip() or None, config_keys=(cfg_keys if cfg_keys else None))
            if isinstance(rp, dict) and rp.get("id") is not None:
                rollback_point = rp
                rollback_point_id = str(rp.get("id"))
        except Exception:
            rollback_point = None
    if rollback_point is None and rollback_point_id:
        try:
            pts = _rollback_points_get()
            for pt in pts:
                if isinstance(pt, dict) and str(pt.get("id") or "").strip() == str(rollback_point_id):
                    rollback_point = pt
                    break
        except Exception:
            rollback_point = None

    backtest_summary = data.get("backtest_summary") if isinstance(data.get("backtest_summary"), dict) else (ent.get("metrics_summary") if isinstance(ent.get("metrics_summary"), dict) else {})
    risk_checks = data.get("risk_checks") if isinstance(data.get("risk_checks"), dict) else {"gate_result": gate_result, "hard_fails": (ent.get("hard_fails") if isinstance(ent.get("hard_fails"), list) else [])}
    robustness = data.get("robustness") if isinstance(data.get("robustness"), dict) else {"robustness": ent.get("robustness"), "oos_summary": (ent.get("oos_summary") if isinstance(ent.get("oos_summary"), dict) else {})}

    data_snapshot_id = backtest_spec.get("data_snapshot_id")
    config_version = backtest_spec.get("config_version")
    if config_version is None:
        try:
            config_version = _runtime_config_version(CONFIG)
        except Exception:
            config_version = None

    now_ms = int(_now_ms())
    try:
        review_after_days_in = data.get("review_after_days")
        if review_after_days_in is None:
            review_after_days_in = data.get("review_after_day")
        if review_after_days_in is None:
            review_after_days_in = data.get("review_days")
        review_after_days = int(review_after_days_in) if review_after_days_in is not None and str(review_after_days_in).strip() != "" else None
    except Exception:
        review_after_days = None
    if review_after_days is None:
        try:
            review_after_days = int(CONFIG.get("governance_changeset_review_after_days", CONFIG.get("changeset_review_after_days", 7)) or 7)
        except Exception:
            review_after_days = 7
    review_after_days = max(1, min(3650, int(review_after_days)))
    expires_at_ms = None
    expires_at_in = data.get("expires_at")
    if expires_at_in is None:
        expires_at_in = data.get("expires_at_ms")
    if expires_at_in is not None and str(expires_at_in).strip() != "":
        try:
            exp_i = int(float(expires_at_in))
            if exp_i > 0 and exp_i < 10**11:
                exp_i = exp_i * 1000
            expires_at_ms = int(exp_i) if exp_i > 0 else None
        except Exception:
            expires_at_ms = None
    if expires_at_ms is None:
        expires_at_ms = int(now_ms + int(review_after_days) * 86400 * 1000)

    delta_metrics = None
    try:
        cand_ms = ent.get("metrics_summary") if isinstance(ent.get("metrics_summary"), dict) else {}
        base_ms = None
        if isinstance(baseline, dict):
            base_ms = baseline.get("metrics_summary") if isinstance(baseline.get("metrics_summary"), dict) else None
        if isinstance(cand_ms, dict) and isinstance(base_ms, dict) and cand_ms and base_ms:
            keys = ["profit_factor", "max_drawdown_pct", "trades", "winrate", "stoploss_hit_rate", "fat_finger_rate", "exec_risk_trigger_rate"]
            dm: Dict[str, Any] = {}
            for k in keys:
                a = cand_ms.get(k)
                b = base_ms.get(k)
                if a is None or b is None:
                    continue
                try:
                    if k == "trades":
                        dm[k] = {"candidate": int(a), "baseline": int(b), "delta": int(a) - int(b)}
                    else:
                        fa = float(a)
                        fb = float(b)
                        if math.isfinite(float(fa)) and math.isfinite(float(fb)):
                            dm[k] = {"candidate": float(fa), "baseline": float(fb), "delta": float(fa) - float(fb)}
                except Exception:
                    continue
            delta_metrics = dm if dm else None
    except Exception:
        delta_metrics = None

    rules = _agent_auto_config_rules()
    config_diff_obj = _agent_config_diff_build(config_patch=config_patch, base_cfg=CONFIG, rules=rules)
    config_diff_sha = hashlib.sha256(_stable_json_dumps(config_diff_obj).encode("utf-8")).hexdigest()
    change_id = _agent_change_bundle_change_id(strategy_key=strategy_key, action=action, policy_ref=policy_ref, config_patch=config_patch, baseline_ref=baseline_key)
    change_tags = _agent_change_tags_from_config_diff(config_diff_obj)
    expected_effect = _agent_expected_effect_from_delta_metrics(delta_metrics)
    required_gates = {"P3": True, "items": ["rolling_verify", "monte_carlo", "stress"]}

    draft = {
        "ok": True,
        "ts": now_ms,
        "trace_id": trace_id,
        "evidence": {
            "rca": (data.get("rca") if isinstance(data.get("rca"), dict) else None),
            "online": (data.get("online") if isinstance(data.get("online"), dict) else None),
            "sandbox": (data.get("sandbox") if isinstance(data.get("sandbox"), dict) else None),
        },
        "candidate": {
            "strategy_id": strategy_id,
            "source_zip": source_zip,
            "baseline": baseline,
            "three_piece": {
                "data_snapshot_id": data_snapshot_id,
                "config_version": config_version,
                "strategy_key": strategy_key,
                "strategy_version": source_zip,
            },
            "metrics_summary": (ent.get("metrics_summary") if isinstance(ent.get("metrics_summary"), dict) else {}),
            "oos_summary": (ent.get("oos_summary") if isinstance(ent.get("oos_summary"), dict) else {}),
        },
        "gate_result": gate_result,
        "rollback_plan": {
            "rollback_point_id": (rollback_point_id or None),
            "trigger": (data.get("rollback_trigger") if isinstance(data.get("rollback_trigger"), dict) else None),
        },
        "doc_refs": doc_refs,
        "changeset": {
            "policy_ref": policy_ref,
            "action": action,
            "strategy_id": strategy_id,
            "source_zip": source_zip,
            "strategy_key": strategy_key,
            "label": label,
            "reason": reason,
            "baseline_ref": (baseline_key or None),
            "baseline_version": (None if config_version is None else str(config_version)),
            "rollback_point_id": (rollback_point_id or None),
            "review_after_days": int(review_after_days),
            "expires_at": (None if expires_at_ms is None else int(expires_at_ms)),
            "config_patch": config_patch,
            "config_suggest": config_suggest,
            "direction": (direction or None),
            "objective_profile": (objective_profile or None),
            "behavior_summary": (behavior_summary or None),
            "change_level": str(change_level),
            "level_info": level_info,
            "delta_metrics": delta_metrics,
            "cost_profile_id": (cost_profile_id or None),
            "cost_assumptions": cost_assumptions,
            "doc_refs": doc_refs,
        },
    }
    draft["change_bundle_draft"] = {
        "ok": True,
        "ts": int(draft.get("ts") or _now_ms()),
        "trace_id": trace_id,
        "change_type": "param",
        "change_id": change_id,
        "change_tags": change_tags,
        "diff_ref": {"kind": "config_diff", "source": "embedded", "sha256": config_diff_sha},
        "expected_effect": expected_effect,
        "required_gates": required_gates,
        "evidence": draft.get("evidence"),
        "candidate": draft.get("candidate"),
        "gate_result": draft.get("gate_result"),
        "rollback_plan": {
            "rollback_to": (rollback_point_id or None),
            "rollback_point_id": (rollback_point_id or None),
            "triggers": (draft.get("rollback_plan") or {}).get("trigger") if isinstance(draft.get("rollback_plan"), dict) else None,
            "max_time_to_decide_min": 60,
        },
        "rollback_point": rollback_point,
        "doc_refs": doc_refs,
        "strategy_key": strategy_key,
        "config_diff": config_diff_obj,
        "config_patch": config_patch,
        "config_suggest": config_suggest,
        "backtest_summary": backtest_summary,
        "risk_checks": risk_checks,
        "robustness": robustness,
        "param_optimization": param_optimization,
        "policy_ref": policy_ref,
        "action": action,
        "label": label,
        "reason": reason,
        "baseline_ref": (baseline_key or None),
        "baseline_version": (None if config_version is None else str(config_version)),
        "rollback_point_id": (rollback_point_id or None),
        "change_level": str(change_level),
        "direction": (direction or None),
        "objective_profile": (objective_profile or None),
        "behavior_summary": (behavior_summary or None),
        "delta_metrics": delta_metrics,
        "cost_profile_id": (cost_profile_id or None),
        "cost_assumptions": cost_assumptions,
        "review_after_days": int(review_after_days),
        "expires_at": (None if expires_at_ms is None else int(expires_at_ms)),
    }
    v = _agent_change_bundle_draft_validate(draft.get("change_bundle_draft"))
    if not bool(v.get("ok")):
        return {"ok": False, "error": "change_bundle_draft_invalid", "violations": v.get("errors"), "ts": int(_now_ms()), "trace_id": trace_id}
    return draft


def _agent_config_patch_validate(
    patch: Dict[str, Any],
    *,
    base_cfg: Optional[Dict[str, Any]] = None,
    allow_suggest_only: bool = False,
    allow_unsafe: bool = False,
) -> Dict[str, Any]:
    rules = _agent_auto_config_rules()
    base = base_cfg if isinstance(base_cfg, dict) else CONFIG
    allowed: Dict[str, Any] = {}
    suggest: Dict[str, Any] = {}
    violations: List[Dict[str, Any]] = []
    unsafe = bool(allow_unsafe)
    def _coerce_bool(v0: Any) -> bool:
        if isinstance(v0, bool):
            return bool(v0)
        if isinstance(v0, (int, float)):
            try:
                return bool(int(v0))
            except Exception:
                return bool(v0)
        s0 = str(v0).strip().lower()
        if s0 in ("1", "true", "yes", "y", "on"):
            return True
        if s0 in ("0", "false", "no", "n", "off", ""):
            return False
        return True

    def _infer_rule_from_cur(cur0: Any, v0: Any) -> Dict[str, Any]:
        t = cur0
        if t is None:
            t = v0
        if isinstance(t, bool):
            return {"mode": "auto", "type": "bool"}
        if isinstance(t, int) and (not isinstance(t, bool)):
            return {"mode": "auto", "type": "int"}
        if isinstance(t, float):
            return {"mode": "auto", "type": "float"}
        if isinstance(t, str):
            return {"mode": "auto", "type": "str"}
        if isinstance(t, list):
            return {"mode": "auto", "type": "json", "json_writable": True}
        if isinstance(t, dict):
            return {"mode": "auto", "type": "json", "json_writable": True}
        return {"mode": "auto", "type": "json", "json_writable": True}

    def _json_value_ok(v0: Any) -> bool:
        max_depth = 10
        max_nodes = 5000
        nodes = 0
        stack: List[Tuple[int, Any]] = [(0, v0)]
        while stack:
            depth, v1 = stack.pop()
            nodes += 1
            if nodes > max_nodes:
                return False
            if depth > max_depth:
                return False
            if v1 is None:
                continue
            if isinstance(v1, (bool, int, float, str)):
                if isinstance(v1, str) and len(v1) > 20000:
                    return False
                continue
            if isinstance(v1, list):
                if len(v1) > 2000:
                    return False
                for it0 in v1:
                    stack.append((depth + 1, it0))
                continue
            if isinstance(v1, dict):
                if len(v1) > 2000:
                    return False
                for k0, vv0 in v1.items():
                    if not isinstance(k0, str) or not k0.strip():
                        return False
                    if len(k0) > 256:
                        return False
                    stack.append((depth + 1, vv0))
                continue
            return False
        return True
    for k, v in (patch or {}).items():
        kk = str(k)
        if not kk:
            continue
        try:
            cur = base.get(kk)
        except Exception:
            cur = None
        r = rules.get(kk)
        if not isinstance(r, dict):
            if unsafe:
                r = _infer_rule_from_cur(cur, v)
            else:
                violations.append({"key": kk, "error": "not_allowed"})
                continue
        tp = str(r.get("type") or "").strip()

        vv = v
        if tp == "bool":
            vv = _coerce_bool(v)
        elif tp == "int":
            try:
                vv = int(v)
            except Exception:
                violations.append({"key": kk, "error": "bad_int"})
                continue
            if not unsafe:
                mn = r.get("min")
                mx = r.get("max")
                if mn is not None and int(vv) < int(mn):
                    violations.append({"key": kk, "error": "below_min", "min": mn})
                    continue
                if mx is not None and int(vv) > int(mx):
                    violations.append({"key": kk, "error": "above_max", "max": mx})
                    continue
        elif tp == "float":
            try:
                vv = float(v)
            except Exception:
                violations.append({"key": kk, "error": "bad_float"})
                continue
            if not math.isfinite(float(vv)):
                violations.append({"key": kk, "error": "nan"})
                continue
            if not unsafe:
                mn = r.get("min")
                mx = r.get("max")
                if mn is not None and float(vv) < float(mn):
                    violations.append({"key": kk, "error": "below_min", "min": mn})
                    continue
                if mx is not None and float(vv) > float(mx):
                    violations.append({"key": kk, "error": "above_max", "max": mx})
                    continue
        elif tp == "list_str":
            if not isinstance(v, list):
                violations.append({"key": kk, "error": "bad_list"})
                continue
            out_list = []
            for it in v:
                s = str(it).strip()
                if not s:
                    continue
                out_list.append(s)
            if not unsafe:
                choices = r.get("choices")
                if isinstance(choices, list) and choices:
                    allowed_set = {str(x).strip() for x in choices if str(x).strip()}
                    out_list = [x for x in out_list if x in allowed_set]
            max_len = int(r.get("max_len") or 2000)
            if len(out_list) > max_len:
                out_list = out_list[:max_len]
            vv = out_list
        elif tp == "str":
            vv = str(v).strip()
            if not unsafe:
                choices = r.get("choices")
                if isinstance(choices, list) and choices:
                    allowed_set = {str(x).strip() for x in choices if str(x).strip()}
                    if vv not in allowed_set:
                        violations.append({"key": kk, "error": "invalid_choice", "choices": sorted(list(allowed_set))[:50]})
                        continue
        elif tp == "json":
            if not _json_value_ok(v):
                violations.append({"key": kk, "error": "bad_json_value"})
                continue
            vv = v
        else:
            violations.append({"key": kk, "error": "unknown_type"})
            continue

        mode = str(r.get("mode") or "auto").strip().lower()
        tighten_rule = str(r.get("tighten_rule") or "").strip().lower()
        if unsafe:
            mode = "auto"
            tighten_rule = ""
        if tp == "json" and mode != "suggest-only":
            if (not unsafe) and (not bool(r.get("json_writable", False))):
                violations.append({"key": kk, "error": "json_not_applicable", "mode": mode})
                continue
        if mode == "suggest-only":
            if allow_suggest_only:
                suggest[kk] = vv
                continue
            violations.append({"key": kk, "error": "suggest_only"})
            continue
        if mode == "auto-tighten-only":
            if not tighten_rule:
                if tp == "bool":
                    cur_b = bool(cur) if cur is not None else False
                    if bool(vv) and (not cur_b):
                        violations.append({"key": kk, "error": "cannot_enable"})
                        continue
                elif tp in ("int", "float"):
                    try:
                        if cur is not None and float(vv) < float(cur):
                            violations.append({"key": kk, "error": "cannot_loosen", "current": cur})
                            continue
                    except Exception:
                        pass

        if tighten_rule:
            if tighten_rule == "disable_only":
                if tp != "bool":
                    violations.append({"key": kk, "error": "tighten_rule_type_mismatch", "tighten_rule": tighten_rule})
                    continue
                cur_b = bool(cur) if cur is not None else False
                if bool(vv) and (not cur_b):
                    violations.append({"key": kk, "error": "cannot_enable"})
                    continue
            elif tighten_rule == "enable_only":
                if tp != "bool":
                    violations.append({"key": kk, "error": "tighten_rule_type_mismatch", "tighten_rule": tighten_rule})
                    continue
                cur_b = bool(cur) if cur is not None else False
                if (not bool(vv)) and cur_b:
                    violations.append({"key": kk, "error": "cannot_disable"})
                    continue
            elif tighten_rule == "restrict_only":
                if tp != "list_str":
                    violations.append({"key": kk, "error": "tighten_rule_type_mismatch", "tighten_rule": tighten_rule})
                    continue
                cur_list = cur if isinstance(cur, list) else []
                cur_norm = {str(x).strip().upper() for x in cur_list if str(x).strip()}
                new_norm = {str(x).strip().upper() for x in (vv if isinstance(vv, list) else []) if str(x).strip()}
                if not new_norm.issubset(cur_norm):
                    violations.append({"key": kk, "error": "tighten_restrict_only", "current": cur})
                    continue
            elif tighten_rule in ("increase", "decrease", "toward_zero"):
                if tp not in ("int", "float"):
                    violations.append({"key": kk, "error": "tighten_rule_type_mismatch", "tighten_rule": tighten_rule})
                    continue
                try:
                    cur_f = None if cur is None else float(cur)
                except Exception:
                    cur_f = None
                if cur_f is not None and math.isfinite(float(cur_f)):
                    if tighten_rule == "increase":
                        try:
                            if float(vv) < float(cur_f):
                                violations.append({"key": kk, "error": "tighten_increase_only", "current": cur})
                                continue
                        except Exception:
                            pass
                    elif tighten_rule == "decrease":
                        try:
                            if float(vv) > float(cur_f):
                                violations.append({"key": kk, "error": "tighten_decrease_only", "current": cur})
                                continue
                        except Exception:
                            pass
                    elif tighten_rule == "toward_zero":
                        try:
                            if float(cur_f) > 0 and float(vv) > float(cur_f):
                                violations.append({"key": kk, "error": "tighten_toward_zero_only", "current": cur})
                                continue
                            if float(cur_f) < 0 and float(vv) < float(cur_f):
                                violations.append({"key": kk, "error": "tighten_toward_zero_only", "current": cur})
                                continue
                            if float(cur_f) == 0 and float(vv) != 0:
                                violations.append({"key": kk, "error": "tighten_toward_zero_only", "current": cur})
                                continue
                        except Exception:
                            pass
            else:
                violations.append({"key": kk, "error": "unknown_tighten_rule", "tighten_rule": tighten_rule})
                continue

        allowed[kk] = vv

    return {"ok": (not violations), "patch": allowed, "suggest": suggest, "violations": violations, "rules": rules}


def _agent_changeset_draft_lookup(draft_id: str, *, max_lines: int = 5000, max_bytes: int = 3_000_000) -> Optional[Dict[str, Any]]:
    did = str(draft_id or "").strip()
    if not did:
        return None
    p = _outbox_dir() / "changeset_drafts.jsonl"
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
        if str(obj.get("id") or "").strip() != did:
            continue
        return obj
    return None



__all__ = ["_agent_changeset_draft_build", "_agent_config_patch_validate", "_agent_changeset_draft_lookup"]
