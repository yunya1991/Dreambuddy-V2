"""策略工厂流水线编排模块。

trigger → regime → candidate → baseline → paramopt → changeset → approval 全链路。
依赖大文件中的策略库、回测、审批、审计等函数。
"""
from __future__ import annotations

import json
import math
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# 延迟导入依赖
def _dep(name):
    import ml_trade_service as _mts
    return getattr(_mts, name)

# 全局变量（懒加载代理，避免循环导入）
class _LazyProxy:
    def __init__(self, name): self._name = name; self._t = None
    def _r(self):
        if self._t is None: self._t = _dep(self._name)
        return self._t
    def get(self, *a, **k): return self._r().get(*a, **k)
    def __getitem__(self, k): return self._r()[k]
    def __contains__(self, k): return k in self._r()
    def __iter__(self): return iter(self._r())

CONFIG = _LazyProxy("CONFIG")

def _agent_approval_request_validate(*a, **k): return _dep("_agent_approval_request_validate")(*a, **k)
def _agent_archive_record_validate(*a, **k): return _dep("_agent_archive_record_validate")(*a, **k)
def _agent_artifact_sha256(*a, **k): return _dep("_agent_artifact_sha256")(*a, **k)
def _agent_baseline_report_validate(*a, **k): return _dep("_agent_baseline_report_validate")(*a, **k)
def _agent_candidate_strategies_validate(*a, **k): return _dep("_agent_candidate_strategies_validate")(*a, **k)
def _agent_change_bundle_draft_validate(*a, **k): return _dep("_agent_change_bundle_draft_validate")(*a, **k)
def _agent_gating_report_validate(*a, **k): return _dep("_agent_gating_report_validate")(*a, **k)
def _agent_gtw_decision_package_validate(*a, **k): return _dep("_agent_gtw_decision_package_validate")(*a, **k)
def _agent_jsonl_tail(*a, **k): return _dep("_agent_jsonl_tail")(*a, **k)
def _agent_monitoring_checklist_validate(*a, **k): return _dep("_agent_monitoring_checklist_validate")(*a, **k)
def _agent_outbox_append_jsonl(*a, **k): return _dep("_agent_outbox_append_jsonl")(*a, **k)
def _agent_outbox_dir(*a, **k): return _dep("_agent_outbox_dir")(*a, **k)
def _agent_regime_report_validate(*a, **k): return _dep("_agent_regime_report_validate")(*a, **k)
def _agent_rollout_plan_validate(*a, **k): return _dep("_agent_rollout_plan_validate")(*a, **k)
def _append_jsonl(*a, **k): return _dep("_append_jsonl")(*a, **k)
def _apply_serving_phase(*a, **k): return _dep("_apply_serving_phase")(*a, **k)
def _backtest_zip_metrics(*a, **k): return _dep("_backtest_zip_metrics")(*a, **k)
def _backtests_dir(*a, **k): return _dep("_backtests_dir")(*a, **k)
def _clip(*a, **k): return _dep("_clip")(*a, **k)
def _doc_refs_sanitize(*a, **k): return _dep("_doc_refs_sanitize")(*a, **k)
def _entry_macro_btc_regime_at(*a, **k): return _dep("_entry_macro_btc_regime_at")(*a, **k)
def _json_sanitize(*a, **k): return _dep("_json_sanitize")(*a, **k)
def _macro_gate_state_get(*a, **k): return _dep("_macro_gate_state_get")(*a, **k)
def _mts(*a, **k): return _dep("_mts")(*a, **k)
def _now_ms(*a, **k): return _dep("_now_ms")(*a, **k)
def _p1_exec_gate_status(*a, **k): return _dep("_p1_exec_gate_status")(*a, **k)
def _p2_health_gate_status(*a, **k): return _dep("_p2_health_gate_status")(*a, **k)
def _rank(*a, **k): return _dep("_rank")(*a, **k)
def _rollback_point_apply(*a, **k): return _dep("_rollback_point_apply")(*a, **k)
def _rollback_snapshot_append(*a, **k): return _dep("_rollback_snapshot_append")(*a, **k)
def _shadow_automation_apply_shadow_patch(*a, **k): return _dep("_shadow_automation_apply_shadow_patch")(*a, **k)
def _shadow_observation_emit(*a, **k): return _dep("_shadow_observation_emit")(*a, **k)
def _strategy_registry_events_path(*a, **k): return _dep("_strategy_registry_events_path")(*a, **k)
def _strategy_registry_key(*a, **k): return _dep("_strategy_registry_key")(*a, **k)
def _strategy_registry_load(*a, **k): return _dep("_strategy_registry_load")(*a, **k)
def _strategy_registry_save(*a, **k): return _dep("_strategy_registry_save")(*a, **k)
def _strategy_sandbox_dir(*a, **k): return _dep("_strategy_sandbox_dir")(*a, **k)
def _write_json_atomic(*a, **k): return _dep("_write_json_atomic")(*a, **k)

def _outbox_dir() -> Path:
    return _dep("_agent_outbox_dir")()

def _agent_pipeline_producer(kind: str) -> Dict[str, Any]:
    return {
        "kind": str(kind or "").strip() or "agent",
        "name": "ml_trade_service",
        "version": str(os.environ.get("ML_TRADE_SERVICE_VERSION") or "").strip() or "unknown",
    }


def _agent_pipeline_artifact_common_fields(*, trace_id: str, created_at_ms: int, producer_kind: str = "agent") -> Dict[str, Any]:
    return {
        "schema_version": str(PIPELINE_ARTIFACT_SCHEMA_VERSION),
        "trace_id": str(trace_id),
        "created_at_ms": int(created_at_ms),
        "producer": _agent_pipeline_producer(str(producer_kind or "agent")),
        "scope": {},
        "inputs": {},
        "references": {},
    }


def _agent_pipeline_artifact_apply_common_fields(*, trace_id: str, created_at_ms: int, artifact: Any, producer_kind: str = "agent") -> Dict[str, Any]:
    art = artifact if isinstance(artifact, dict) else {}
    out: Dict[str, Any] = dict(art)
    out["trace_id"] = str(trace_id)

    if not str(out.get("schema_version") or "").strip():
        out["schema_version"] = str(PIPELINE_ARTIFACT_SCHEMA_VERSION)

    ca = out.get("created_at_ms")
    if ca is None:
        out["created_at_ms"] = int(created_at_ms)
    else:
        try:
            out["created_at_ms"] = int(ca)
        except Exception:
            out["created_at_ms"] = int(created_at_ms)

    prod = out.get("producer")
    if not isinstance(prod, dict):
        out["producer"] = _agent_pipeline_producer(str(producer_kind or "agent"))
    else:
        pk = str(prod.get("kind") or "").strip()
        pn = str(prod.get("name") or "").strip()
        if not pk or not pn:
            out["producer"] = _agent_pipeline_producer(str(producer_kind or "agent"))

    if not isinstance(out.get("scope"), dict):
        out["scope"] = {}
    if not isinstance(out.get("inputs"), dict):
        out["inputs"] = {}
    if not isinstance(out.get("references"), dict):
        out["references"] = {}
    return out


def _agent_pipeline_state_validate(obj: Any) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    if not isinstance(obj, dict):
        return {"ok": False, "errors": [{"path": "$", "error": "not_object"}]}
    if not str(obj.get("trace_id") or "").strip():
        errors.append({"path": "$.trace_id", "error": "missing"})
    if obj.get("ts") is None:
        errors.append({"path": "$.ts", "error": "missing"})
    status = str(obj.get("status") or "").strip().lower()
    if status not in ("running", "success", "fail", "partial"):
        errors.append({"path": "$.status", "error": "bad_value"})
    stages = obj.get("stages")
    if not isinstance(stages, list) or not stages:
        errors.append({"path": "$.stages", "error": "bad_type"})
    else:
        for i, st in enumerate(stages[:50]):
            if not isinstance(st, dict):
                errors.append({"path": f"$.stages[{i}]", "error": "not_object"})
                continue
            if not str(st.get("name") or "").strip():
                errors.append({"path": f"$.stages[{i}].name", "error": "missing"})
            s = str(st.get("status") or "").strip().lower()
            if s not in ("pending", "running", "success", "fail", "skipped"):
                errors.append({"path": f"$.stages[{i}].status", "error": "bad_value"})
    return {"ok": (not errors), "errors": errors}


def _agent_pipeline_artifact_emit(*, trace_id: str, kind: str, artifact: Dict[str, Any]) -> Dict[str, Any]:
    ts = int(_now_ms())
    art = _agent_pipeline_artifact_apply_common_fields(trace_id=str(trace_id), created_at_ms=int(ts), artifact=artifact, producer_kind="agent")
    sha = _agent_artifact_sha256(art)
    ent = {"id": uuid.uuid4().hex, "trace_id": str(trace_id), "ts": int(ts), "type": "pipeline.artifact", "kind": str(kind), "sha256": sha, "artifact": art}
    _agent_outbox_append_jsonl("pipeline_artifacts.jsonl", ent)
    return {"kind": str(kind), "source": "agent_outbox/pipeline_artifacts.jsonl", "id": str(ent.get("id")), "sha256": sha}


def _agent_pipeline_artifact_validate_and_emit(*, trace_id: str, kind: str, artifact: Any) -> Dict[str, Any]:
    k = str(kind or "").strip()
    art = _agent_pipeline_artifact_apply_common_fields(trace_id=str(trace_id), created_at_ms=int(_now_ms()), artifact=artifact, producer_kind="agent")
    v = {"ok": True, "errors": []}
    try:
        if k == "regime_report":
            v = _agent_regime_report_validate(art)
        elif k == "candidate_strategies":
            v = _agent_candidate_strategies_validate(art)
        elif k == "gating_report":
            v = _agent_gating_report_validate(art)
        elif k == "approval_request":
            v = _agent_approval_request_validate(art)
        elif k == "monitoring_checklist":
            v = _agent_monitoring_checklist_validate(art)
        elif k == "rollout_plan":
            v = _agent_rollout_plan_validate(art)
        elif k == "archive_record":
            v = _agent_archive_record_validate(art)
        elif k == "change_bundle_draft":
            v = _agent_change_bundle_draft_validate(art)
        elif k == "baseline_report":
            v = _agent_baseline_report_validate(art)
        elif k == "pipeline_state":
            v = _agent_pipeline_state_validate(art)
        elif k == "gtw.decision_package":
            v = _agent_gtw_decision_package_validate(art)
    except Exception:
        v = {"ok": False, "errors": [{"path": "$", "error": "validator_exception"}]}
    ref = _agent_pipeline_artifact_emit(trace_id=str(trace_id), kind=k, artifact=art)
    return {"ok": bool(v.get("ok")), "errors": (v.get("errors") if isinstance(v.get("errors"), list) else []), "ref": ref}


def _agent_pipeline_package_dir(trace_id: str) -> Path:
    tid = str(trace_id or "").strip() or "unknown_trace"
    tid = re.sub(r"[^a-zA-Z0-9_.-]+", "_", tid)[:120]
    return _outbox_dir() / "pipeline_packages" / tid


def _agent_pipeline_package_write(*, trace_id: str, filename: str, obj: Any) -> Optional[str]:
    name = str(filename or "").strip()
    if (not name) or ("/" in name) or ("\\" in name) or (".." in name):
        return None
    try:
        p = _agent_pipeline_package_dir(trace_id) / name
        ok = _write_json_atomic(p, _json_sanitize(obj))
        return (str(p) if ok else None)
    except Exception:
        return None


def _pipeline_regime_report_build(*, trace_id: str, now_ms: int) -> Dict[str, Any]:
    ts_ms = int(now_ms or _now_ms())
    snap = _entry_macro_btc_regime_at(ts_ms)
    tw = int(snap.get("trend_w_dir") or 0)
    td = int(snap.get("trend_d_dir") or 0)
    tr = "sideways"
    if tw == 1 and td == 1:
        tr = "up"
    elif tw == -1 and td == -1:
        tr = "down"
    atr = float(snap.get("atr_pct") or 0.0)
    try:
        atr_p80 = float(CONFIG.get("entry_macro_atr_p80", 0.0) or 0.0)
    except Exception:
        atr_p80 = 0.0
    try:
        atr_p95 = float(CONFIG.get("entry_macro_atr_p95", 0.0) or 0.0)
    except Exception:
        atr_p95 = 0.0
    vol = "normal"
    if atr_p95 > 0.0 and atr >= atr_p95:
        vol = "high"
    elif atr_p80 > 0.0 and atr >= atr_p80:
        vol = "elevated"
    try:
        mg = _macro_gate_state_get(int(ts_ms))
    except Exception:
        mg = {}
    conf = 0.65 if bool(snap.get("valid", True)) else 0.40
    try:
        if isinstance(mg, dict) and isinstance(mg.get("eval"), dict):
            if bool((mg.get("eval") or {}).get("pass")):
                conf = min(0.85, conf + 0.10)
            else:
                conf = max(0.30, conf - 0.10)
    except Exception:
        pass
    out = _agent_pipeline_artifact_common_fields(trace_id=str(trace_id), created_at_ms=int(ts_ms), producer_kind="agent")
    out.update(
        {
            "ts": int(ts_ms),
            "trend": tr,
            "volatility": vol,
            "confidence": float(_clip(conf, 0.0, 1.0)),
            "evidence": {
                "btc_regime": snap,
                "thresholds": {"entry_macro_atr_p80": float(atr_p80), "entry_macro_atr_p95": float(atr_p95)},
            },
            "macro_gate": (mg.get("eval") if isinstance(mg, dict) else {}),
            "applicable_timeframes": ["1h", "4h", "1d"],
        }
    )
    return out


def _pipeline_candidate_strategies_build(*, trace_id: str, now_ms: int, limit: int = 3, regime_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lim = max(1, min(50, int(limit)))
    out_items: List[Dict[str, Any]] = []
    try:
        regime = regime_report if isinstance(regime_report, dict) else {}
        trend = str(regime.get("trend") or "").strip().lower()
        vol = str(regime.get("volatility") or "").strip().lower()

        reg = _strategy_registry_load()
        entries = reg.get("entries") if isinstance(reg, dict) else None
        if isinstance(entries, dict):
            items = [v for v in entries.values() if isinstance(v, dict)]

            def _rank(x: Dict[str, Any]) -> Tuple[int, int, int, str]:
                fam = str(x.get("family") or "").strip().lower()
                regime_fit = 0
                if trend == "up" and fam in ("trend", "breakout"):
                    regime_fit = 2
                elif trend == "down" and fam in ("mean_reversion", "carry"):
                    regime_fit = 2
                elif trend == "sideways" and fam == "mean_reversion":
                    regime_fit = 2

                robust = str(x.get("robustness") or "").strip().lower()
                robust_score = 0
                if robust in ("pass", "good"):
                    robust_score = 1

                vol_penalty = 0
                if vol in ("high", "elevated") and fam in ("breakout",):
                    vol_penalty = -1

                t0 = str(x.get("tier") or "").strip().upper()
                tr = 0
                if t0 == "A":
                    tr = 3
                elif t0 == "B":
                    tr = 2
                elif t0 == "C":
                    tr = 1
                upd = str(x.get("updated_at") or "")
                return regime_fit, robust_score, (tr + vol_penalty), upd

            items.sort(key=_rank, reverse=True)
            for it in items:
                sid = str(it.get("strategy_id") or "").strip()
                z = str(it.get("source_zip") or "").strip()
                if sid and z:
                    out_items.append({"strategy_id": sid, "source_zip": z, "tier": it.get("tier"), "meta": {"updated_at": it.get("updated_at")}})
                if len(out_items) >= lim:
                    break
    except Exception:
        out_items = []
    if not out_items:
        try:
            p = _backtests_dir()
            if p.exists():
                zips = list(p.glob("*.zip"))
                zips.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                for z in zips[:200]:
                    mt = None
                    try:
                        mt = int(float(z.stat().st_mtime) * 1000.0)
                    except Exception:
                        mt = None
                    m = _backtest_zip_metrics(z)
                    ss = m.get("strategies") if isinstance(m, dict) else None
                    if not isinstance(ss, list) or not ss:
                        continue
                    s0 = ss[0] if isinstance(ss[0], dict) else None
                    sid = str((s0 or {}).get("key") or "").strip()
                    if not sid:
                        continue
                    out_items.append({"strategy_id": sid, "source_zip": str(z.name), "tier": None, "meta": {"source": "backtest_results", "mtime_ms": mt}})
                    if len(out_items) >= lim:
                        break
        except Exception:
            pass
    ts = int(now_ms or _now_ms())
    out = _agent_pipeline_artifact_common_fields(trace_id=str(trace_id), created_at_ms=int(ts), producer_kind="agent")
    out.update({"ts": int(ts), "items": out_items})
    return out


def _pipeline_rollout_plan_build(*, trace_id: str, now_ms: int, change_id: Optional[str]) -> Dict[str, Any]:
    cid = (None if change_id is None else str(change_id).strip() or None)
    ts = int(now_ms or _now_ms())
    sp = AUTOMATION.get("serving_pipeline") if isinstance(AUTOMATION.get("serving_pipeline"), dict) else {}
    try:
        canary_frac = float(sp.get("canary_frac") or 0.10)
    except Exception:
        canary_frac = 0.10
    canary_frac = float(max(0.0, min(1.0, float(canary_frac))))
    pairs = sp.get("pairs") if isinstance(sp.get("pairs"), list) else []
    phases = [
        {"phase": "shadow", "duration_min": 30, "traffic_pct": 0, "requires": ["monitoring_ok"]},
        {"phase": "canary", "duration_min": 120, "traffic_pct": int(round(canary_frac * 100.0)), "requires": ["monitoring_ok", "p3_gates_pass"]},
        {"phase": "full", "duration_min": 0, "traffic_pct": 100, "requires": ["manual_approve"]},
    ]
    stages = [
        {"name": "shadow", "duration_min": 30, "scope_overrides": {"serving_phase": "shadow"}, "success_criteria": {"monitoring_ok": True}, "rollback_triggers": {"p0": "any", "p1": "consecutive_windows"}},
        {"name": "canary_1", "duration_min": 120, "scope_overrides": {"serving_phase": "canary", "pairs": pairs, "canary_frac": float(canary_frac)}, "success_criteria": {"p0": "zero_breach", "p1": "exec_safe", "p2": "no_drift"}, "rollback_triggers": {"p0": "any", "p1": "consecutive_windows", "p2": "pf_below_floor"}},
        {"name": "full", "duration_min": 0, "scope_overrides": {"serving_phase": "full"}, "success_criteria": {"manual_approve": True}, "rollback_triggers": {"p0": "any"}},
    ]
    out = _agent_pipeline_artifact_common_fields(trace_id=str(trace_id), created_at_ms=int(ts), producer_kind="agent")
    out.update(
        {
            "ts": int(ts),
            "change_id": cid,
            "execution_mode": "progressive",
            "rollback_to": {"change_id": cid, "kind": "rollback_point", "id": None},
            "phases": phases,
            "stages": stages,
        }
    )
    return out


def _pipeline_monitoring_checklist_build(*, trace_id: str, now_ms: int, change_id: Optional[str]) -> Dict[str, Any]:
    ts = int(now_ms or _now_ms())
    cid = (None if change_id is None else str(change_id).strip() or None)

    try:
        max_daily_loss = float(CONFIG.get("max_daily_loss", CONFIG.get("account_max_daily_loss", -0.05)) or -0.05)
    except Exception:
        max_daily_loss = -0.05
    try:
        max_weekly_loss = float(CONFIG.get("max_weekly_loss", CONFIG.get("account_max_weekly_loss", -0.12)) or -0.12)
    except Exception:
        max_weekly_loss = -0.12

    p1 = _p1_exec_gate_status(now_ms=int(ts))
    p2 = _p2_health_gate_status(now_ms=int(ts))

    items: List[Dict[str, Any]] = []
    items.append(
        {
            "priority": "P0",
            "name": "capital_protection",
            "signals": [
                {"metric": "daily_loss", "threshold": float(max_daily_loss), "direction": "min"},
                {"metric": "weekly_loss", "threshold": float(max_weekly_loss), "direction": "min"},
            ],
            "actions": ["halt_trading", "force_exit", "rollback"],
        }
    )
    items.append(
        {
            "priority": "P1",
            "name": "execution_safety",
            "signals": [
                {
                    "metric": "order_fail_rate",
                    "threshold": ((p1.get("thresholds") or {}).get("order_fail_rate_thr") if isinstance(p1, dict) else None),
                    "window_sec": ((p1.get("metrics") or {}).get("order_window_sec") if isinstance(p1, dict) else None),
                },
                {
                    "metric": "order_consecutive_failures",
                    "threshold": ((p1.get("thresholds") or {}).get("order_consecutive_failures_thr") if isinstance(p1, dict) else None),
                },
                {
                    "metric": "order_reject_reason_distribution",
                    "source": "signals.reject_stats",
                },
            ],
            "endpoints": ["/audit/execution-quality", "/signals/reject_stats"],
            "actions": ["reduce_risk", "pause_new_entries", "investigate"],
        }
    )
    items.append(
        {
            "priority": "P2",
            "name": "strategy_drift",
            "signals": [
                {"metric": "feature_drift", "threshold": (p2.get("drift_warn") if isinstance(p2, dict) else None)},
                {"metric": "holding_period_shift", "source": "positions/holding_period"},
                {"metric": "pnl_distribution_shift", "source": "arena/attrib"},
            ],
            "endpoints": ["/audit/alerts/evaluate", "/metrics"],
            "actions": ["attribution", "sandbox_reproduce", "draft_changeset"],
        }
    )

    try:
        poll_sec = int(CONFIG.get("agent_monitor_poll_sec", 120) or 120)
    except Exception:
        poll_sec = 120
    poll_sec = int(max(10, min(3600, poll_sec)))
    try:
        summary_window_min = int(CONFIG.get("agent_monitor_summary_window_min", 120) or 120)
    except Exception:
        summary_window_min = 120
    summary_window_sec = int(max(60, min(24 * 3600, summary_window_min * 60)))

    metrics: List[Dict[str, Any]] = []
    for it in items[:50]:
        if not isinstance(it, dict):
            continue
        lvl = str(it.get("priority") or "").strip() or "P2"
        actions = it.get("actions") if isinstance(it.get("actions"), list) else []
        sigs = it.get("signals") if isinstance(it.get("signals"), list) else []
        for s in sigs[:50]:
            if not isinstance(s, dict):
                continue
            name = str(s.get("metric") or s.get("name") or "").strip()
            if not name:
                continue
            metrics.append({"level": lvl, "name": name, "threshold": s.get("threshold"), "action_on_breach": actions})

    out = _agent_pipeline_artifact_common_fields(trace_id=str(trace_id), created_at_ms=int(ts), producer_kind="agent")
    out.update(
        {
            "ts": int(ts),
            "change_id": cid,
            "intervals_sec": {"poll": int(poll_sec), "summary_window": int(summary_window_sec)},
            "metrics": metrics,
            "dashboards_refs": [],
            "items": items,
        }
    )
    return out


def _pipeline_approval_request_build(
    *,
    trace_id: str,
    now_ms: int,
    approval_id: str,
    action: str,
    draft_id: Optional[str],
    draft: Dict[str, Any],
    chosen: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    ts = int(now_ms or _now_ms())
    appr = str(approval_id or "").strip()
    act = str(action or "").strip() or "config.apply"

    chg = draft.get("changeset") if isinstance(draft.get("changeset"), dict) else {}
    cbd = draft.get("change_bundle_draft") if isinstance(draft.get("change_bundle_draft"), dict) else {}
    candidate = draft.get("candidate") if isinstance(draft.get("candidate"), dict) else {}

    venues: Dict[str, Any] = {}
    for k in (
        "execution_venue",
        "universe_venue",
        "carry_trade_venue",
        "carry_universe_venue",
        "three_screen_5m_venue",
        "perp_5m_autofill_exchange",
    ):
        try:
            v = CONFIG.get(k)
        except Exception:
            v = None
        if v is not None and str(v).strip():
            venues[k] = str(v).strip()

    target = candidate.get("target") if isinstance(candidate.get("target"), dict) else {}
    impact = {
        "strategies": [
            {
                "strategy_id": str((chosen or {}).get("strategy_id") or chg.get("strategy_id") or "").strip() or None,
                "source_zip": str((chosen or {}).get("source_zip") or chg.get("source_zip") or "").strip() or None,
                "strategy_key": str(chg.get("strategy_key") or cbd.get("strategy_key") or "").strip() or None,
            }
        ],
        "accounts": [{"account_id_hash": target.get("account_id_hash"), "env": target.get("env")}],
        "venues": venues,
    }

    config_diff = cbd.get("config_diff") if isinstance(cbd.get("config_diff"), dict) else {}
    changes = config_diff.get("changes") if isinstance(config_diff.get("changes"), list) else []
    loosen_keys: List[str] = []
    exposure_increase_keys: List[str] = []
    for c in changes:
        if not isinstance(c, dict):
            continue
        k = str(c.get("key") or "").strip()
        if not k:
            continue
        if str(c.get("direction") or "") == "loosen":
            loosen_keys.append(k)
        try:
            if k in ("entry_max_notional_usdc", "entry_fixed_notional_usdc", "entry_min_notional_usdc", "hl_default_leverage", "aster_default_leverage"):
                if float(c.get("to")) > float(c.get("from")):
                    exposure_increase_keys.append(k)
        except Exception:
            pass

    try:
        max_daily_loss = float(CONFIG.get("max_daily_loss", CONFIG.get("account_max_daily_loss", -0.05)) or -0.05)
    except Exception:
        max_daily_loss = -0.05
    try:
        max_weekly_loss = float(CONFIG.get("max_weekly_loss", CONFIG.get("account_max_weekly_loss", -0.12)) or -0.12)
    except Exception:
        max_weekly_loss = -0.12
    p1_thr = _p1_exec_gate_status(now_ms=int(ts)).get("thresholds")
    p2_thr = {"drift_warn": _p2_health_gate_status(now_ms=int(ts)).get("drift_warn")}

    out = _agent_pipeline_artifact_common_fields(trace_id=str(trace_id), created_at_ms=int(ts), producer_kind="agent")
    out.update(
        {
            "ts": int(ts),
            "approval_id": appr,
            "action": act,
            "draft_id": (None if draft_id is None else str(draft_id)),
            "change_bundle_summary": {
                "change_id": (cbd.get("change_id") if isinstance(cbd, dict) else None),
                "diff_ref": (cbd.get("diff_ref") if isinstance(cbd.get("diff_ref"), dict) else None),
                "config_diff": config_diff,
                "expected_effect": (cbd.get("expected_effect") if isinstance(cbd.get("expected_effect"), dict) else None),
                "required_gates": (cbd.get("required_gates") if isinstance(cbd.get("required_gates"), dict) else None),
            },
            "gate_summary": {
                "gate_result": (draft.get("gate_result") if isinstance(draft.get("gate_result"), dict) else {}),
                "required_gates": (cbd.get("required_gates") if isinstance(cbd.get("required_gates"), dict) else None),
            },
            "risk_points": {
                "risk_checks": (cbd.get("risk_checks") if isinstance(cbd.get("risk_checks"), dict) else {}),
                "loosen_keys": sorted(list(set(loosen_keys)))[:200],
                "exposure_increase_keys": sorted(list(set(exposure_increase_keys)))[:50],
            },
            "impact": impact,
            "rollback": {
                "rollback_point": (cbd.get("rollback_point") if isinstance(cbd.get("rollback_point"), dict) else None),
                "rollback_plan": (cbd.get("rollback_plan") if isinstance(cbd.get("rollback_plan"), dict) else None),
                "triggers": (cbd.get("rollback_plan") or {}).get("triggers") if isinstance(cbd.get("rollback_plan"), dict) else None,
                "trigger_thresholds": {
                    "P0": {"max_daily_loss": float(max_daily_loss), "max_weekly_loss": float(max_weekly_loss)},
                    "P1": (p1_thr if isinstance(p1_thr, dict) else {}),
                    "P2": (p2_thr if isinstance(p2_thr, dict) else {}),
                },
            },
            "doc_refs": _doc_refs_sanitize(draft.get("doc_refs")),
        }
    )
    return out


def _pipeline_archive_record_build(*, trace_id: str, now_ms: int, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    ts = int(now_ms or _now_ms())
    out = _agent_pipeline_artifact_common_fields(trace_id=str(trace_id), created_at_ms=int(ts), producer_kind="agent")
    out.update({"ts": int(ts), "artifacts": (artifacts if isinstance(artifacts, dict) else {})})
    return out


def _pipeline_archive_writeback(
    *,
    trace_id: str,
    now_ms: int,
    chosen: Optional[Dict[str, Any]],
    change_bundle: Optional[Dict[str, Any]],
    approval_id: Optional[str],
    artifacts: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(chosen, dict):
        return {"ok": True, "skipped": "missing_chosen"}
    sid = str(chosen.get("strategy_id") or "").strip()
    z = str(chosen.get("source_zip") or "").strip()
    if (not sid) or (not z):
        return {"ok": True, "skipped": "missing_key"}
    if (not z.lower().endswith(".zip")) or (".." in z) or ("/" in z) or ("\\" in z):
        return {"ok": True, "skipped": "bad_source_zip"}

    try:
        reg = _strategy_registry_load()
        entries = reg.get("entries") if isinstance(reg.get("entries"), dict) else {}
        k_exact = _strategy_registry_key(sid, z)
        k_any = _strategy_registry_key(sid, "*")
        key = (k_exact if isinstance(entries.get(k_exact), dict) else (k_any if isinstance(entries.get(k_any), dict) else None))
        if not key:
            return {"ok": True, "skipped": "entry_not_found"}

        existing = entries.get(key) if isinstance(entries.get(key), dict) else {}
        before = {"pipeline_last": (existing.get("pipeline_last") if isinstance(existing.get("pipeline_last"), dict) else None)}

        change_id = None
        if isinstance(change_bundle, dict):
            try:
                change_id = str(change_bundle.get("change_id") or "").strip() or None
            except Exception:
                change_id = None

        out = dict(existing)
        out["pipeline_last"] = {
            "trace_id": str(trace_id),
            "ts": int(now_ms),
            "approval_id": (None if approval_id is None else str(approval_id)),
            "change_id": change_id,
            "artifact_refs": {
                "approval_request": (artifacts.get("approval_request") if isinstance(artifacts.get("approval_request"), dict) else None),
                "rollout_plan": (artifacts.get("rollout_plan") if isinstance(artifacts.get("rollout_plan"), dict) else None),
                "monitoring_checklist": (artifacts.get("monitoring_checklist") if isinstance(artifacts.get("monitoring_checklist"), dict) else None),
                "archive_record": (artifacts.get("archive_record") if isinstance(artifacts.get("archive_record"), dict) else None),
                "gating_report": (artifacts.get("gating_report") if isinstance(artifacts.get("gating_report"), dict) else None),
                "shadow_config_apply": (artifacts.get("shadow_config_apply") if isinstance(artifacts.get("shadow_config_apply"), dict) else None),
                "shadow_observation_initial": (artifacts.get("shadow_observation_initial") if isinstance(artifacts.get("shadow_observation_initial"), dict) else None),
                "shadow_observation_after_gate": (artifacts.get("shadow_observation_after_gate") if isinstance(artifacts.get("shadow_observation_after_gate"), dict) else None),
                "shadow_daily_report": (artifacts.get("shadow_daily_report") if isinstance(artifacts.get("shadow_daily_report"), dict) else None),
                "pipeline_state": (artifacts.get("pipeline_state") if isinstance(artifacts.get("pipeline_state"), dict) else None),
            },
        }
        out["updated_at"] = datetime.now(timezone.utc).isoformat()
        entries[key] = out
        reg["entries"] = entries
        ok = _strategy_registry_save(reg)
        if not bool(ok):
            return {"ok": False, "error": "registry_save_failed"}

        evt = {
            "id": str(uuid.uuid4()),
            "ts": int(_now_ms()),
            "trace_id": str(trace_id),
            "actor": "agent.pipeline",
            "kind": "note",
            "strategy_id": sid,
            "source_zip": z,
            "note": "pipeline_archive_writeback",
            "payload": {"approval_id": (None if approval_id is None else str(approval_id)), "change_id": change_id, "pipeline_last": out.get("pipeline_last")},
            "before": before,
            "after": {"pipeline_last": out.get("pipeline_last")},
        }
        _append_jsonl(_strategy_registry_events_path(), evt)
        return {"ok": True, "key": key, "event_id": evt.get("id")}
    except Exception:
        return {"ok": False, "error": "exception"}


def _pipeline_stage(name: str, status: str, started_ms: int, ended_ms: int, refs: Dict[str, Any], detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    st = str(status or "").strip().lower()
    if st not in ("pending", "running", "success", "fail", "skipped"):
        st = "pending"
    out = {"name": str(name or "").strip(), "status": st, "started_ms": int(started_ms), "ended_ms": int(ended_ms), "refs": (refs if isinstance(refs, dict) else {})}
    if detail is not None and isinstance(detail, dict):
        out["detail"] = detail
    return out


def _pipeline_baseline_report_build(*, trace_id: str, now_ms: int, strategy_id: str, source_zip: str, config_path: str, timerange: Optional[str], timeout_sec: float) -> Dict[str, Any]:
    ts_ms = int(now_ms or _now_ms())
    sandbox_path = None
    try:
        sp = str(source_zip or "").strip()
        if sp:
            p = Path(sp)
            if p.exists() and p.is_dir():
                sandbox_path = sp
            else:
                if (not p.is_absolute()) and (not str(sp).lower().endswith(".zip")):
                    p2 = (_strategy_sandbox_dir() / sp)
                    if p2.exists() and p2.is_dir():
                        sandbox_path = str(p2)
    except Exception:
        sandbox_path = None
    req = {
        "trace_id": trace_id,
        "config": config_path,
        "timerange": (None if timerange is None else str(timerange)),
        "strategy": str(strategy_id),
        "strategy_name": str(strategy_id),
        "sandbox_path": sandbox_path,
        "timeout_sec": float(timeout_sec),
    }
    rep = None
    try:
        with app.test_request_context(
            "/automation/backtest/run",
            method="POST",
            data=json.dumps(req),
            content_type="application/json",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ):
            resp = automation_backtest_run()
        resp0 = resp[0] if isinstance(resp, tuple) and resp else resp
        if hasattr(resp0, "get_json"):
            rep = resp0.get_json(force=True) or {}
    except Exception:
        rep = None
    out = _agent_pipeline_artifact_common_fields(trace_id=str(trace_id), created_at_ms=int(ts_ms), producer_kind="sandbox")
    out.update({"ts": int(ts_ms), "ok": bool((rep or {}).get("ok"))})
    if isinstance(rep, dict):
        out["result"] = {
            "result_zip": rep.get("result_zip"),
            "metrics_summary": (rep.get("metrics_summary") if isinstance(rep.get("metrics_summary"), dict) else None),
            "report": (rep.get("report") if isinstance(rep.get("report"), dict) else None),
            "error": rep.get("error"),
        }
    return out


def _agent_pipeline_state_find_latest(*, trace_id: str) -> Optional[Dict[str, Any]]:
    tid = str(trace_id or "").strip()
    if not tid:
        return None
    p = _outbox_dir() / "pipeline_artifacts.jsonl"
    if not p.exists():
        return None
    latest = None
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    obj = None
                if not isinstance(obj, dict):
                    continue
                if str(obj.get("trace_id") or "").strip() != tid:
                    continue
                if str(obj.get("kind") or "").strip() != "pipeline_state":
                    continue
                art = obj.get("artifact") if isinstance(obj.get("artifact"), dict) else None
                if isinstance(art, dict):
                    latest = art
    except Exception:
        latest = None
    return latest


def _agent_pipeline_artifact_find_latest(*, trace_id: str, kind: str) -> Optional[Dict[str, Any]]:
    tid = str(trace_id or "").strip()
    k = str(kind or "").strip()
    if not tid or not k:
        return None
    p = _outbox_dir() / "pipeline_artifacts.jsonl"
    if not p.exists():
        return None
    latest = None
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    obj = None
                if not isinstance(obj, dict):
                    continue
                if str(obj.get("trace_id") or "").strip() != tid:
                    continue
                if str(obj.get("kind") or "").strip() != k:
                    continue
                art = obj.get("artifact") if isinstance(obj.get("artifact"), dict) else None
                if isinstance(art, dict):
                    latest = art
    except Exception:
        latest = None
    return latest


def _agent_pipeline_state_update_stage(
    *,
    trace_id: str,
    now_ms: int,
    stage_name: str,
    stage_status: str,
    detail_update: Optional[Dict[str, Any]] = None,
    refs_update: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    st0 = _agent_pipeline_state_find_latest(trace_id=str(trace_id))
    if not isinstance(st0, dict):
        return None
    stages0 = st0.get("stages") if isinstance(st0.get("stages"), list) else []
    nm = str(stage_name or "").strip()
    ss = str(stage_status or "").strip().lower()
    if ss not in ("pending", "running", "success", "fail", "skipped"):
        ss = "pending"
    updated = False
    stages1: List[Dict[str, Any]] = []
    for st in stages0:
        if not isinstance(st, dict):
            continue
        if str(st.get("name") or "").strip() != nm:
            stages1.append(st)
            continue
        out_st = dict(st)
        out_st["status"] = ss
        out_st["ended_ms"] = int(now_ms)
        if out_st.get("started_ms") is None:
            out_st["started_ms"] = int(now_ms)
        if refs_update is not None and isinstance(refs_update, dict):
            rr = out_st.get("refs") if isinstance(out_st.get("refs"), dict) else {}
            rr2 = dict(rr)
            rr2.update(refs_update)
            out_st["refs"] = rr2
        if detail_update is not None and isinstance(detail_update, dict):
            dd = out_st.get("detail") if isinstance(out_st.get("detail"), dict) else {}
            dd2 = dict(dd)
            dd2.update(detail_update)
            out_st["detail"] = dd2
        stages1.append(out_st)
        updated = True
    if not updated:
        stages1.append(
            _pipeline_stage(
                nm,
                ss,
                int(now_ms),
                int(now_ms),
                (refs_update if isinstance(refs_update, dict) else {}),
                (detail_update if isinstance(detail_update, dict) else None),
            )
        )
    out = dict(st0)
    out["ts"] = int(now_ms)
    out["stages"] = stages1
    if any(str(s.get("status") or "").lower() == "fail" for s in stages1 if isinstance(s, dict)):
        out["status"] = "fail"
    elif any(str(s.get("status") or "").lower() == "running" for s in stages1 if isinstance(s, dict)):
        out["status"] = "running"
    elif any(str(s.get("status") or "").lower() in ("skipped", "pending") for s in stages1 if isinstance(s, dict)):
        out["status"] = "partial"
    else:
        out["status"] = "success"
    try:
        _agent_pipeline_artifact_validate_and_emit(trace_id=str(trace_id), kind="pipeline_state", artifact=out)
    except Exception:
        pass
    return out


def _agent_pipeline_gray_rollout_execute(*, trace_id: str, now_ms: int, target_phase: str, reason: str) -> Dict[str, Any]:
    tid = str(trace_id or "").strip()
    ph = str(target_phase or "shadow").strip().lower()
    rsn = str(reason or "").strip() or "pipeline.gray_rollout"
    if not tid:
        return {"ok": False, "error": "missing_trace_id"}
    if ph not in ("shadow", "canary", "full"):
        return {"ok": False, "error": "invalid_phase"}
    st0 = _agent_pipeline_state_find_latest(trace_id=tid)
    if not isinstance(st0, dict):
        return {"ok": False, "error": "pipeline_state_not_found"}
    stages0 = st0.get("stages") if isinstance(st0.get("stages"), list) else []
    gray = None
    for s in stages0:
        if isinstance(s, dict) and str(s.get("name") or "").strip() == "gray_rollout":
            gray = s
            break
    if isinstance(gray, dict):
        det0 = gray.get("detail") if isinstance(gray.get("detail"), dict) else {}
        if bool(det0.get("executed", False)) and str(gray.get("status") or "").strip().lower() in ("success", "fail"):
            return {"ok": True, "replayed": True, "phase": det0.get("phase")}

    canary_frac = 0.10
    try:
        rp = _agent_pipeline_artifact_find_latest(trace_id=tid, kind="rollout_plan") or {}
        phases = rp.get("phases") if isinstance(rp.get("phases"), list) else []
        for it in phases:
            if isinstance(it, dict) and str(it.get("phase") or "").strip().lower() == "canary":
                canary_frac = float(it.get("traffic_pct") or 10.0) / 100.0
                break
    except Exception:
        canary_frac = 0.10
    canary_frac = float(max(0.0, min(1.0, float(canary_frac))))

    rb_pt = None
    try:
        rb_pt = _rollback_snapshot_append(label="agent.pipeline.gray_rollout", reason=rsn, config_keys=["automation", "universe_core"])
    except Exception:
        rb_pt = None

    try:
        pairs = CONFIG.get("serving_canary_pairs")
    except Exception:
        pairs = None
    try:
        if ph == "canary":
            _apply_serving_phase("canary", canary_frac=canary_frac, pairs=(pairs if isinstance(pairs, list) else []))
        else:
            _apply_serving_phase(ph)
        applied_ok = True
    except Exception as e:
        applied_ok = False
        err = str(e)

    guard_eval = None
    try:
        with app.test_request_context(
            "/automation/serving/pipeline/guard/eval",
            method="GET",
            content_type="application/json",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ):
            resp = automation_serving_pipeline_guard_eval()
        resp0 = resp[0] if isinstance(resp, tuple) and resp else resp
        if hasattr(resp0, "get_json"):
            guard_eval = resp0.get_json(force=True) or {}
    except Exception:
        guard_eval = None

    rolled_back = False
    rollback_out = None
    if applied_ok and isinstance(guard_eval, dict) and bool(guard_eval.get("rollback_recommended", False)):
        if isinstance(rb_pt, dict):
            try:
                rollback_out = _rollback_point_apply(rb_pt, restore_thresholds=True, restore_arena=True, restore_active_model=False, restore_tracker_state=True, restore_config=True)
                rolled_back = True
            except Exception as e:
                rollback_out = {"ok": False, "error": str(e)}
                rolled_back = True
        try:
            _apply_serving_phase("shadow")
        except Exception:
            pass

    detail = {
        "mode": "execute",
        "phase": ph,
        "executed": bool(applied_ok),
        "reason": rsn,
        "rollback_point_id": ((rb_pt or {}).get("id") if isinstance(rb_pt, dict) else None),
        "guard_eval": guard_eval,
        "rolled_back": bool(rolled_back),
        "rollback": rollback_out,
        "canary_frac": (float(canary_frac) if ph == "canary" else None),
    }
    if not applied_ok:
        detail["error"] = (None if 'err' not in locals() else err)
    stage_status = "success" if (applied_ok and (not rolled_back)) else "fail"
    _agent_pipeline_state_update_stage(trace_id=tid, now_ms=int(now_ms), stage_name="gray_rollout", stage_status=stage_status, detail_update=detail, refs_update=None)
    return {"ok": True, "applied": bool(applied_ok), "rolled_back": bool(rolled_back), "phase": ph, "guard_eval": guard_eval, "rollback_point": rb_pt, "rollback": rollback_out}


def _agent_pipeline_on_sandbox_gate_result(*, trace_id: str, now_ms: int, gate_result: Dict[str, Any], gating_report_ref: Optional[Dict[str, Any]]) -> None:
    tid = str(trace_id or "").strip()
    if not tid:
        return
    gr = gate_result if isinstance(gate_result, dict) else {}
    dec = str(gr.get("decision") or "").strip().lower()
    if dec not in ("pass", "fail", "blocked", "inconclusive"):
        dec = "inconclusive"
    sb_status = "success" if dec == "pass" else "fail"
    refs = {"gating_report": gating_report_ref} if isinstance(gating_report_ref, dict) else {}
    st1 = _agent_pipeline_state_update_stage(
        trace_id=tid,
        now_ms=int(now_ms),
        stage_name="sandbox_validation",
        stage_status=sb_status,
        detail_update={"decision": dec, "reasons": (gr.get("reasons") if isinstance(gr.get("reasons"), list) else None)},
        refs_update=refs,
    )
    if not isinstance(st1, dict):
        return
    if dec != "pass":
        try:
            _agent_pipeline_state_update_stage(
                trace_id=tid,
                now_ms=int(now_ms),
                stage_name="gray_rollout",
                stage_status="skipped",
                detail_update={"reason": "sandbox_gate_not_pass", "decision": dec},
                refs_update=None,
            )
        except Exception:
            pass
        return

    if bool(st1.get("shadow_only", False)):
        try:
            CONFIG["dry_run"] = True
        except Exception:
            pass
        try:
            _agent_pipeline_gray_rollout_execute(trace_id=tid, now_ms=int(now_ms), target_phase="shadow", reason="sandbox_gate_pass_shadow_only")
        except Exception:
            pass
        apply_rep = None
        try:
            apply_rep = _shadow_automation_apply_shadow_patch(trace_id=tid, now_ms=int(now_ms))
        except Exception:
            apply_rep = None
        try:
            _agent_pipeline_state_update_stage(
                trace_id=tid,
                now_ms=int(now_ms),
                stage_name="gray_rollout",
                stage_status="success",
                detail_update={"shadow_only": True, "shadow_config_apply": _json_sanitize(apply_rep)},
                refs_update=None,
            )
        except Exception:
            pass
        try:
            _shadow_observation_emit(trace_id=str(tid), now_ms=int(now_ms), kind="shadow_observation_after_gate", monitor_out=None)
        except Exception:
            pass
        try:
            chosen0 = st1.get("chosen") if isinstance(st1.get("chosen"), dict) else None
            art_map = {
                "gating_report": (gating_report_ref if isinstance(gating_report_ref, dict) else _agent_pipeline_artifact_find_latest(trace_id=str(tid), kind="gating_report")),
                "rollout_plan": _agent_pipeline_artifact_find_latest(trace_id=str(tid), kind="rollout_plan"),
                "monitoring_checklist": _agent_pipeline_artifact_find_latest(trace_id=str(tid), kind="monitoring_checklist"),
                "archive_record": _agent_pipeline_artifact_find_latest(trace_id=str(tid), kind="archive_record"),
                "shadow_config_apply": _agent_pipeline_artifact_find_latest(trace_id=str(tid), kind="shadow_config_apply"),
                "shadow_observation_initial": _agent_pipeline_artifact_find_latest(trace_id=str(tid), kind="shadow_observation_initial"),
                "shadow_observation_after_gate": _agent_pipeline_artifact_find_latest(trace_id=str(tid), kind="shadow_observation_after_gate"),
                "shadow_daily_report": _agent_pipeline_artifact_find_latest(trace_id=str(tid), kind="shadow_daily_report"),
                "pipeline_state": _agent_pipeline_artifact_find_latest(trace_id=str(tid), kind="pipeline_state"),
            }
            _pipeline_archive_writeback(trace_id=str(tid), now_ms=int(now_ms), chosen=chosen0, change_bundle=None, approval_id=None, artifacts=art_map)
        except Exception:
            pass
        return
    stages = st1.get("stages") if isinstance(st1.get("stages"), list) else []
    g = None
    for s in stages:
        if isinstance(s, dict) and str(s.get("name") or "").strip() == "gray_rollout":
            g = s
            break
    if not isinstance(g, dict):
        return
    det = g.get("detail") if isinstance(g.get("detail"), dict) else {}
    if str(det.get("mode") or "").strip().lower() != "execute":
        return
    if not bool(det.get("execute_allowed", False)):
        return
    if bool(det.get("executed", False)) and str(g.get("status") or "").strip().lower() in ("success", "fail"):
        return
    _agent_pipeline_gray_rollout_execute(trace_id=tid, now_ms=int(now_ms), target_phase="canary", reason="sandbox_gate_pass")


def _pipeline_artifacts_tail(*, tail_bytes: int = 2_000_000, max_lines: int = 20_000) -> List[Dict[str, Any]]:
    try:
        p = _outbox_dir() / "pipeline_artifacts.jsonl"
    except Exception:
        return []
    return _agent_jsonl_tail(p, tail_bytes=int(tail_bytes), max_lines=int(max_lines))


def _pipeline_artifacts_for_trace(rows: List[Dict[str, Any]], trace_id: str) -> List[Dict[str, Any]]:
    tid = str(trace_id or "").strip()
    if not tid:
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("trace_id") or "").strip() != tid:
            continue
        out.append(r)
    return out


def _pipeline_latest_trace_for_kinds(rows: List[Dict[str, Any]], kinds: List[str]) -> Optional[str]:
    ks = set([str(k).strip() for k in (kinds or []) if str(k).strip()])
    if not ks:
        return None
    best_ts = 0
    best_tid = None
    for r in rows:
        if not isinstance(r, dict):
            continue
        k = str(r.get("kind") or "").strip()
        if k not in ks:
            continue
        try:
            ts = int(r.get("ts") or 0)
        except Exception:
            ts = 0
        if ts <= 0:
            continue
        if ts >= best_ts:
            tid = str(r.get("trace_id") or "").strip()
            if tid:
                best_ts = ts
                best_tid = tid
    return best_tid



__all__ = ['_agent_pipeline_producer', '_agent_pipeline_artifact_common_fields', '_agent_pipeline_artifact_apply_common_fields', '_agent_pipeline_state_validate', '_agent_pipeline_artifact_emit', '_agent_pipeline_artifact_validate_and_emit', '_agent_pipeline_package_dir', '_agent_pipeline_package_write', '_pipeline_regime_report_build', '_pipeline_candidate_strategies_build', '_pipeline_rollout_plan_build', '_pipeline_monitoring_checklist_build', '_pipeline_approval_request_build', '_pipeline_archive_record_build', '_pipeline_archive_writeback', '_pipeline_stage', '_pipeline_baseline_report_build', '_agent_pipeline_state_find_latest', '_agent_pipeline_artifact_find_latest', '_agent_pipeline_state_update_stage', '_agent_pipeline_gray_rollout_execute', '_agent_pipeline_on_sandbox_gate_result', '_pipeline_artifacts_tail', '_pipeline_artifacts_for_trace', '_pipeline_latest_trace_for_kinds']
