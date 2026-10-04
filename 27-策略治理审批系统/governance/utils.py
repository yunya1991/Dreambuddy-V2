"""27-策略治理审批系统 本地工具函数。

从 ml_trade_service.py 解耦，提供独立的：
- 时间/文件工具（_now_ms, _tail_lines, _stable_json_dumps, _json_sanitize）
- 配置管理（CONFIG, _config_get, _config_save）
- 治理判断（_governance_env_name, _governance_baseline_judge, _governance_tighten_only, _governance_has_improvement）
- 文档/证据清洗（_doc_refs_default, _doc_refs_sanitize, _evidence_sanitize, _agent_chat_enforce_doc_refs）
- 审计/Outbox（_agent_outbox_dir, _agent_outbox_append_jsonl, _audit_base_payload, _audit_emit_action, _agent_emit_envelope_event）
- 审批日志（_approvals_log_path）
- 变更包工具（_stable_json_dumps, _agent_change_bundle_change_id, _agent_config_diff_*, _agent_change_tags_from_config_diff, _agent_expected_effect_from_delta_metrics, _agent_change_bundle_draft_validate）
- 配置规则（_agent_auto_config_rules, _config_patch_level_info）
- 回滚（_rollback_points_get, _rollback_snapshot_append）
- 运行时（_runtime_config_version）
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 27 模块数据根目录
_MODULE_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _MODULE_ROOT / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# 子目录
_APPROVALS_DIR = _DATA_DIR / "approvals"
_APPROVALS_DIR.mkdir(parents=True, exist_ok=True)
_OUTBOX_DIR = _DATA_DIR / "outbox"
_OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
_CHANGESET_DIR = _DATA_DIR / "changeset"
_CHANGESET_DIR.mkdir(parents=True, exist_ok=True)
_CONFIG_DIR = _DATA_DIR / "config"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

_CONFIG_PATH = _CONFIG_DIR / "governance_config.json"


def _config_get() -> Dict[str, Any]:
    """加载 27 模块本地配置。"""
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _config_save(cfg: Dict[str, Any]) -> bool:
    try:
        _CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


# 全局配置（延迟加载）
CONFIG: Dict[str, Any] = {}


def _ensure_config_loaded() -> None:
    global CONFIG
    if not CONFIG:
        CONFIG = _config_get()


_ensure_config_loaded()


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    return int(time.time() * 1000)


def _tail_lines(path: Path, *, max_lines: int = 2000, max_bytes: int = 2_000_000) -> List[str]:
    try:
        if not path.exists():
            return []
        size = path.stat().st_size
        if size <= max_bytes:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
        with open(path, "rb") as f:
            f.seek(-max_bytes, os.SEEK_END)
            f.readline()
            data = f.read(max_bytes)
        return data.decode("utf-8", errors="replace").splitlines()[-max_lines:]
    except Exception:
        return []


def _json_sanitize(x: Any) -> Any:
    if x is None:
        return None
    if isinstance(x, (str, bool, int)):
        return x
    if isinstance(x, float):
        return (x if math.isfinite(x) else None)
    if isinstance(x, dict):
        return {str(k): _json_sanitize(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_sanitize(v) for v in x]
    try:
        if hasattr(x, "item"):
            return _json_sanitize(x.item())
    except Exception:
        pass
    return x


def _stable_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        try:
            return json.dumps(_json_sanitize(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            return "{}"


# ---------------------------------------------------------------------------
# 治理判断
# ---------------------------------------------------------------------------

def _governance_env_name() -> str:
    try:
        v = str(CONFIG.get("governance_env") or "prod").strip().lower()
    except Exception:
        v = "prod"
    return v if v in ("prod", "explore", "pilot") else "prod"


def _governance_baseline_judge(delta_metrics: Any) -> Dict[str, Any]:
    dm = delta_metrics if isinstance(delta_metrics, dict) else {}
    if not dm:
        return {"ok": False, "decision": "inconclusive", "reasons": ["missing_delta_metrics"]}

    def _get_pair(k: str) -> Optional[Dict[str, float]]:
        v = dm.get(k) if isinstance(dm.get(k), dict) else None
        if not isinstance(v, dict):
            return None
        a, b = None, None
        if v.get("candidate") is not None and v.get("baseline") is not None:
            a, b = v.get("candidate"), v.get("baseline")
        elif v.get("cur") is not None and v.get("base") is not None:
            a, b = v.get("cur"), v.get("base")
        if a is None or b is None:
            return None
        try:
            fa, fb = float(a), float(b)
        except Exception:
            return None
        if not math.isfinite(fa) or not math.isfinite(fb):
            return None
        return {"candidate": fa, "baseline": fb}

    def _ratio(pair: Dict[str, float]) -> Optional[float]:
        b = float(pair.get("baseline") or 0.0)
        if b <= 0:
            return None
        return float(pair.get("candidate") / b)

    try:
        dd_ratio_thr = float(CONFIG.get("governance_baseline_hard_reject_maxdd_ratio", 1.10) or 1.10)
    except Exception:
        dd_ratio_thr = 1.10
    try:
        trades_ratio_thr = float(CONFIG.get("governance_baseline_hard_reject_trades_ratio", 0.80) or 0.80)
    except Exception:
        trades_ratio_thr = 0.80
    try:
        exec_ratio_thr = float(CONFIG.get("governance_baseline_hard_reject_exec_ratio", 1.20) or 1.20)
    except Exception:
        exec_ratio_thr = 1.20
    try:
        improve_rel_thr = float(CONFIG.get("governance_baseline_soft_pass_min_rel_improve", 0.05) or 0.05)
    except Exception:
        improve_rel_thr = 0.05

    hard_reasons: List[str] = []
    soft_warn_reasons: List[str] = []

    ddp = _get_pair("max_drawdown_pct")
    if ddp is not None:
        r = _ratio(ddp)
        if r is not None and r > dd_ratio_thr + 1e-12:
            hard_reasons.append(f"max_drawdown_pct_ratio>{dd_ratio_thr:.3g}")

    tp = dm.get("trades") if isinstance(dm.get("trades"), dict) else None
    if isinstance(tp, dict) and tp.get("candidate") is not None and tp.get("baseline") is not None:
        try:
            tc, tb = int(tp.get("candidate")), int(tp.get("baseline"))
            if tb > 0 and tc < tb * trades_ratio_thr - 1e-12:
                hard_reasons.append(f"trades_ratio<{trades_ratio_thr:.3g}")
        except Exception:
            pass

    for k0 in ("reject_rate", "order_fail_rate", "stoploss_hit_rate", "fat_finger_rate", "exec_risk_trigger_rate"):
        kp = _get_pair(k0)
        if kp is None:
            continue
        r = _ratio(kp)
        if r is not None and r > exec_ratio_thr + 1e-12:
            hard_reasons.append(f"{k0}_ratio>{exec_ratio_thr:.3g}")

    forbid = CONFIG.get("governance_baseline_forbidden_worsen_keys")
    if isinstance(forbid, list):
        for k in [str(x).strip() for x in forbid if str(x or "").strip()][:50]:
            v = dm.get(k) if isinstance(dm.get(k), dict) else None
            if not isinstance(v, dict) or v.get("delta") is None:
                continue
            try:
                if float(v.get("delta")) > 0:
                    hard_reasons.append(f"forbidden_worsen:{k}")
            except Exception:
                continue

    if hard_reasons:
        return {"ok": True, "decision": "hard_reject", "reasons": hard_reasons, "ts": _now_ms()}

    improved = False
    for k in ("profit_factor", "sharpe", "net_sharpe_oos", "calmar"):
        kp = _get_pair(k)
        if kp is None:
            continue
        r = _ratio(kp)
        if r is None:
            continue
        if r >= 1.0 + improve_rel_thr - 1e-12:
            improved = True
            break

    if not improved:
        soft_warn_reasons.append(f"no_metric_rel_improve>={improve_rel_thr:.3g}")
        return {"ok": True, "decision": "soft_warn", "reasons": soft_warn_reasons, "ts": _now_ms()}

    return {"ok": True, "decision": "pass", "reasons": [], "ts": _now_ms()}


def _governance_tighten_only(change_tags: Any) -> bool:
    tags = [str(x).strip() for x in (change_tags if isinstance(change_tags, list) else []) if str(x or "").strip()]
    s = set(tags)
    if "loosen" in s:
        return False
    if "exposure_increase" in s:
        return False
    return "tighten" in s


def _governance_has_improvement(delta_metrics: Any) -> bool:
    j = _governance_baseline_judge(delta_metrics)
    return str((j or {}).get("decision") or "").strip().lower() == "pass"


# ---------------------------------------------------------------------------
# Lookahead 未来函数检测
# ---------------------------------------------------------------------------

import re as _re

# 未来函数模式：在策略代码中引用未来数据的反模式
_LOOKAHEAD_PATTERNS = [
    # shift(-n) 引用未来数据
    (r"shift\(\s*-\d+\s*\)", "shift_negative", "high"),
    # iloc[-1] 或 iloc[1:] 引用未来
    (r"\.iloc\[\s*-1\s*\]", "iloc_last", "high"),
    (r"\.iloc\[\s*-\d+\s*:", "iloc_negative_slice", "high"),
    # rolling + shift(-n)
    (r"rolling\([^)]*\)\.shift\(\s*-\d+\s*\)", "rolling_shift_negative", "high"),
    # 直接用未来价格做判断（在 populate_entry_trend/exit_trend 中引用 shift(-1)）
    (r"shift\(\s*-\d+\s*\)", "lookahead_shift", "medium"),
]


def _lookahead_check(strategy_code: str) -> Dict[str, Any]:
    """检测策略代码中的未来函数（lookahead bias）。

    Args:
        strategy_code: 策略源码字符串

    Returns:
        {
            "ok": True,
            "has_lookahead": bool,
            "findings": [{"pattern": str, "line": int, "severity": str, "snippet": str}],
            "severity": "clean" | "warn" | "critical"
        }
    """
    findings = []
    lines = strategy_code.split("\n")

    for line_no, line in enumerate(lines, 1):
        # 跳过注释行
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pattern, name, severity in _LOOKAHEAD_PATTERNS:
            if _re.search(pattern, line):
                findings.append({
                    "pattern": name,
                    "line": line_no,
                    "severity": severity,
                    "snippet": stripped[:200],
                })
                break  # 每行只报告一次

    has_lookahead = len(findings) > 0
    max_severity = "clean"
    if findings:
        severities = {f["severity"] for f in findings}
        if "high" in severities:
            max_severity = "critical"
        else:
            max_severity = "warn"

    return {
        "ok": True,
        "has_lookahead": has_lookahead,
        "findings": findings,
        "severity": max_severity,
        "total_findings": len(findings),
    }


def _lookahead_check_file(strategy_path: str) -> Dict[str, Any]:
    """从策略文件路径检测未来函数。"""
    try:
        from pathlib import Path as _Path
        code = _Path(strategy_path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "has_lookahead": False, "error": str(e), "findings": [], "severity": "clean"}
    return _lookahead_check(code)


# ---------------------------------------------------------------------------
# 文档/证据清洗
# ---------------------------------------------------------------------------

def _doc_refs_default() -> List[Dict[str, Any]]:
    return [
        {"doc_path": "交易AI Agent 技术文档2.0.md", "section": "4.7.6", "rule": "变更包最小集合"},
        {"doc_path": "技术文档.md", "section": "0.3", "rule": "工程索引（SSoT 入口）"},
    ]


def _doc_refs_sanitize(doc_refs: Any) -> List[Dict[str, Any]]:
    if not isinstance(doc_refs, list):
        return _doc_refs_default()
    out = [x for x in doc_refs if isinstance(x, dict)]
    if not out:
        return _doc_refs_default()
    return out


def _evidence_sanitize(evidence: Any, *, gate_results: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ev = evidence if isinstance(evidence, dict) else {}
    if not ev and isinstance(gate_results, dict) and gate_results:
        ev = {"gate_results": gate_results}
    if not ev:
        ev = {"gate_results": {}}
    return ev


def _agent_chat_enforce_doc_refs(doc_refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    base = _doc_refs_default()
    out: List[Dict[str, Any]] = []

    def _key(x: Dict[str, Any]) -> Tuple[str, str]:
        return (str(x.get("doc_path") or "").strip(), str(x.get("section") or "").strip())

    seen = set()
    for x in doc_refs:
        if not isinstance(x, dict):
            continue
        k = _key(x)
        if not k[0] or k in seen:
            continue
        out.append(x)
        seen.add(k)
    for x in base:
        k = _key(x)
        if not k[0] or k in seen:
            continue
        out.append(x)
        seen.add(k)
    return out


# ---------------------------------------------------------------------------
# Outbox / 审计
# ---------------------------------------------------------------------------

def _agent_outbox_dir() -> Path:
    """27 模块独立的 outbox 目录。"""
    env = _governance_env_name()
    p0 = os.environ.get("GOVERNANCE_OUTBOX_DIR", "").strip()
    if not p0:
        if env == "explore":
            p0 = os.environ.get("GOVERNANCE_OUTBOX_DIR_EXPLORE", "").strip()
        elif env == "pilot":
            p0 = os.environ.get("GOVERNANCE_OUTBOX_DIR_PILOT", "").strip()
    if p0:
        try:
            p = Path(p0).expanduser().resolve()
        except Exception:
            p = _OUTBOX_DIR / env
    else:
        p = _OUTBOX_DIR / env
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def _agent_outbox_append_jsonl(name: str, item: Dict[str, Any]) -> None:
    nm = str(name or "").strip()
    if not nm or "/" in nm or "\\" in nm or ".." in nm:
        return
    out = _agent_outbox_dir() / nm
    try:
        s = json.dumps(item, ensure_ascii=False)
        with open(out, "a", encoding="utf-8") as f:
            f.write(s + "\n")
    except Exception:
        pass


def _approvals_log_path() -> Path:
    return _agent_outbox_dir() / "approvals.jsonl"


def _audit_base_payload(scope: str, action: str, *, trace_id: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构造审计基础 payload。在 Flask 上下文内可用 request 对象。"""
    now_ms = _now_ms()
    actor = source = ip = ua = path = method = None
    try:
        from flask import request as _req
        actor = str(_req.headers.get("X-Actor") or "").strip() or None
        source = str(_req.headers.get("X-Source") or "").strip() or None
        ip = str(_req.remote_addr or "").strip() or None
        ua = str(_req.headers.get("User-Agent") or "").strip() or None
        path = str(_req.path or "").strip() or None
        method = str(_req.method or "").strip().upper() or None
    except Exception:
        pass
    tid = str(trace_id or "").strip() or None if trace_id else None
    if tid is None:
        try:
            from flask import request as _req
            tid = str(_req.headers.get("X-Trace-Id") or "").strip() or None
        except Exception:
            tid = None
    if tid is None:
        tid = uuid.uuid4().hex
    payload: Dict[str, Any] = {
        "trace_id": tid,
        "ts": now_ms,
        "actor": actor,
        "source": source,
        "scope": str(scope or "").strip() or "unknown",
        "action": str(action or "").strip() or "unknown",
        "ip": ip,
        "ua": ua,
        "path": path,
        "method": method,
    }
    if isinstance(extra, dict) and extra:
        payload["extra"] = extra
    return payload


def _audit_emit_action(name: str, payload: Dict[str, Any]) -> None:
    nm = str(name or "").strip() or "audit"
    now_ms = _now_ms()
    pl = payload if isinstance(payload, dict) else {"trace_id": uuid.uuid4().hex}
    _agent_outbox_append_jsonl("audit_actions.jsonl", {"name": nm, "ts": now_ms, "payload": pl})


def _agent_emit_envelope_event(
    *,
    event: str,
    trace_id: str,
    severity: str,
    intent_level: str,
    ts_ms: int,
    inputs: Dict[str, Any],
    evidence: List[Dict[str, Any]],
    outputs: Dict[str, Any],
    doc_refs: List[Dict[str, str]],
) -> Dict[str, Any]:
    ev = str(event or "event").strip() or "event"
    tid = str(trace_id or "").strip() or uuid.uuid4().hex
    sev = str(severity or "info").strip().lower() or "info"
    il = str(intent_level or "L1").strip().upper() or "L1"
    ts0 = int(ts_ms or _now_ms())
    try:
        stable = json.dumps({"event": ev, "trace_id": tid, "ts": ts0, "inputs": inputs}, sort_keys=True, ensure_ascii=False)
    except Exception:
        stable = f"{ev}|{tid}|{ts0}"
    try:
        eid = hashlib.sha256(str(stable).encode("utf-8")).hexdigest()[:32]
    except Exception:
        eid = uuid.uuid4().hex

    env = {
        "event": ev,
        "event_id": eid,
        "trace_id": tid,
        "ts": int(ts0),
        "severity": sev,
        "intent_level": il,
        "inputs": (inputs if isinstance(inputs, dict) else {}),
        "evidence": (evidence if isinstance(evidence, list) else []),
        "outputs": (outputs if isinstance(outputs, dict) else {}),
        "doc_refs": (doc_refs if isinstance(doc_refs, list) else []),
    }
    try:
        _agent_outbox_append_jsonl("chat.jsonl", {"id": eid, "trace_id": tid, "ts": int(ts0), "type": ev, "envelope": env})
    except Exception:
        pass
    return env


# ---------------------------------------------------------------------------
# 变更包工具
# ---------------------------------------------------------------------------

def _agent_change_bundle_change_id(*, strategy_key: str, action: str, policy_ref: str, config_patch: Dict[str, Any], baseline_ref: Optional[str]) -> str:
    stable = _stable_json_dumps({
        "strategy_key": str(strategy_key),
        "action": str(action),
        "policy_ref": str(policy_ref),
        "baseline_ref": (baseline_ref or None),
        "config_patch": (config_patch if isinstance(config_patch, dict) else {}),
    })
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32]


def _agent_config_diff_direction(*, key: str, from_v: Any, to_v: Any, rule: Optional[Dict[str, Any]]) -> str:
    tr = str((rule or {}).get("tighten_rule") or "").strip().lower()
    tp = str((rule or {}).get("type") or "").strip().lower()
    if from_v == to_v:
        return "neutral"
    if tr == "disable_only":
        return "tighten" if (tp == "bool" and bool(from_v) and not bool(to_v)) else "loosen"
    if tr == "enable_only":
        return "tighten" if (tp == "bool" and not bool(from_v) and bool(to_v)) else "loosen"
    if tr == "restrict_only":
        if tp != "list_str":
            return "neutral"
        a = {str(x).strip().upper() for x in (from_v if isinstance(from_v, list) else []) if str(x or "").strip()}
        b = {str(x).strip().upper() for x in (to_v if isinstance(to_v, list) else []) if str(x or "").strip()}
        if b.issubset(a) and a != b:
            return "tighten"
        if a.issubset(b) and a != b:
            return "loosen"
        return "neutral"
    if tr in ("increase", "decrease", "toward_zero"):
        if tp not in ("int", "float"):
            return "neutral"
        try:
            af, bf = float(from_v), float(to_v)
        except Exception:
            return "neutral"
        if not (math.isfinite(af) and math.isfinite(bf)):
            return "neutral"
        if tr == "increase":
            return "tighten" if bf > af else "loosen"
        if tr == "decrease":
            return "tighten" if bf < af else "loosen"
        if tr == "toward_zero":
            aa, bb = abs(af), abs(bf)
            if bb < aa:
                return "tighten"
            if bb > aa:
                return "loosen"
            return "neutral"
    return "neutral"


def _agent_config_diff_build(*, config_patch: Dict[str, Any], base_cfg: Optional[Dict[str, Any]], rules: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    patch = config_patch if isinstance(config_patch, dict) else {}
    base = base_cfg if isinstance(base_cfg, dict) else {}
    changes: List[Dict[str, Any]] = []
    for k in sorted([str(x).strip() for x in patch.keys() if str(x).strip()]):
        rule = rules.get(k) if isinstance(rules, dict) else None
        try:
            frm = base.get(k)
        except Exception:
            frm = None
        to = patch.get(k)
        direction = _agent_config_diff_direction(key=k, from_v=frm, to_v=to, rule=rule if isinstance(rule, dict) else None)
        changes.append({"key": k, "from": frm, "to": to, "direction": direction, "reason": None, "allowlist_ref": f"agent_auto_config_rules_v1:{k}"})
    return {"changes": changes}


def _agent_change_tags_from_config_diff(config_diff: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    changes = config_diff.get("changes") if isinstance(config_diff, dict) else None
    if not isinstance(changes, list) or not changes:
        return ["neutral"]
    if any(isinstance(c, dict) and str(c.get("direction") or "") == "tighten" for c in changes):
        tags.append("tighten")
    if any(isinstance(c, dict) and str(c.get("direction") or "") == "loosen" for c in changes):
        tags.append("loosen")
    risk_keys = {"max_open_trades", "max_orders_per_minute", "entry_max_notional_usdc", "entry_fixed_notional_usdc", "entry_min_notional_usdc", "hl_default_leverage", "aster_default_leverage"}
    exposure_increase_keys = {"entry_max_notional_usdc", "entry_fixed_notional_usdc", "entry_min_notional_usdc", "hl_default_leverage", "aster_default_leverage"}
    try:
        for c in changes:
            if not isinstance(c, dict):
                continue
            k = str(c.get("key") or "").strip()
            if k in exposure_increase_keys:
                try:
                    if float(c.get("to")) > float(c.get("from")):
                        tags.append("exposure_increase")
                        break
                except Exception:
                    continue
    except Exception:
        pass
    if any(isinstance(c, dict) and str(c.get("key") or "").strip() in risk_keys for c in changes):
        tags.append("risk_controls")
    uniq: List[str] = []
    seen = set()
    for t in tags:
        s = str(t).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq if uniq else ["neutral"]


def _agent_expected_effect_from_delta_metrics(delta_metrics: Any) -> Dict[str, Any]:
    dm = delta_metrics if isinstance(delta_metrics, dict) else {}
    primary_metrics_up: List[str] = []
    tradeoffs: List[str] = []
    try:
        for k in ("profit_factor", "winrate", "trades"):
            d = dm.get(k) if isinstance(dm.get(k), dict) else None
            if not isinstance(d, dict):
                continue
            dv = d.get("delta")
            if dv is None:
                continue
            try:
                if float(dv) > 0:
                    primary_metrics_up.append(k)
            except Exception:
                continue
        ddd = dm.get("max_drawdown_pct") if isinstance(dm.get("max_drawdown_pct"), dict) else None
        if isinstance(ddd, dict):
            dv = ddd.get("delta")
            if dv is not None:
                try:
                    if float(dv) < 0:
                        primary_metrics_up.append("max_drawdown_pct")
                except Exception:
                    pass
    except Exception:
        pass
    if not primary_metrics_up and dm:
        tradeoffs.append("metrics_delta_unclear")
    return {"primary_metrics_up": primary_metrics_up, "possible_tradeoffs": tradeoffs, "regime_assumptions": []}


def _agent_change_bundle_draft_validate(obj: Any) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    if not isinstance(obj, dict):
        return {"ok": False, "errors": [{"path": "$", "error": "not_object"}]}
    ct = str(obj.get("change_type") or "").strip()
    if ct not in ("param", "code"):
        errors.append({"path": "$.change_type", "error": "bad_value"})
    cid = str(obj.get("change_id") or "").strip()
    if not cid:
        errors.append({"path": "$.change_id", "error": "missing"})
    tags = obj.get("change_tags")
    if not (isinstance(tags, list) and all(isinstance(x, str) and x.strip() for x in tags) and len(tags) <= 50):
        errors.append({"path": "$.change_tags", "error": "bad_type"})
    diff_ref = obj.get("diff_ref")
    if not isinstance(diff_ref, dict):
        errors.append({"path": "$.diff_ref", "error": "bad_type"})
    exp = obj.get("expected_effect")
    if not isinstance(exp, dict):
        errors.append({"path": "$.expected_effect", "error": "bad_type"})
    rb = obj.get("rollback_plan")
    if not isinstance(rb, dict) or (rb.get("rollback_to") is None and rb.get("rollback_point_id") is None):
        errors.append({"path": "$.rollback_plan", "error": "bad_type"})
    req = obj.get("required_gates")
    if not isinstance(req, dict):
        errors.append({"path": "$.required_gates", "error": "bad_type"})
    return {"ok": (not errors), "errors": errors}


# ---------------------------------------------------------------------------
# 自动配置规则
# ---------------------------------------------------------------------------

_AGENT_AUTO_CONFIG_RULES_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def _agent_auto_config_rules() -> Dict[str, Dict[str, Any]]:
    global _AGENT_AUTO_CONFIG_RULES_CACHE
    if isinstance(_AGENT_AUTO_CONFIG_RULES_CACHE, dict) and _AGENT_AUTO_CONFIG_RULES_CACHE:
        return _AGENT_AUTO_CONFIG_RULES_CACHE

    out: Dict[str, Dict[str, Any]] = {}
    # 从本地配置加载自定义规则
    custom_rules = CONFIG.get("agent_auto_config_rules_custom", {})
    if isinstance(custom_rules, dict):
        for k, v in custom_rules.items():
            if isinstance(v, dict):
                out[str(k).strip()] = v

    # 默认规则集
    out.update({
        "dry_run": {"mode": "auto", "type": "bool"},
        "arena_enabled": {"mode": "auto", "type": "bool"},
        "three_screen_use_ml_vote": {"mode": "auto", "type": "bool"},
        "elastic_vote_rule": {"mode": "auto", "type": "json", "json_writable": True},
        "entry_inflight_cooldown_sec": {"mode": "auto-tighten-only", "type": "int", "min": 0, "max": 86400, "tighten_rule": "increase"},
        "paramopt_fast_apply_enabled": {"mode": "auto", "type": "bool"},
        "paramopt_fast_apply_allowed_keys": {"mode": "auto", "type": "json", "json_writable": True},
        "paramopt_fast_apply_delta_caps": {"mode": "auto", "type": "json", "json_writable": True},
        "paramopt_fast_apply_max_keys": {"mode": "auto", "type": "int", "min": 1, "max": 50},
        "paramopt_fast_apply_daily_limit": {"mode": "auto", "type": "int", "min": 0, "max": 200},
        "paramopt_fast_apply_min_interval_sec": {"mode": "auto", "type": "int", "min": 0, "max": 86400},
        "paramopt_fast_apply_monitor_window_sec": {"mode": "auto", "type": "int", "min": 0, "max": 86400},
        "paramopt_fast_apply_auto_rollback_enabled": {"mode": "auto", "type": "bool"},
        "paramopt_fast_apply_rollback_on_p0": {"mode": "auto", "type": "bool"},
        "paramopt_fast_apply_state": {"mode": "auto", "type": "json", "json_writable": True},
        "paramopt_fast_apply_triggers": {"mode": "auto", "type": "json", "json_writable": True},
        "execution_venue": {"mode": "suggest-only", "type": "str"},
        "aster_trading_enabled": {"mode": "suggest-only", "type": "bool"},
        "hl_trading_enabled": {"mode": "suggest-only", "type": "bool"},
        "entry_fixed_notional_usdc": {"mode": "suggest-only", "type": "float", "min": 1.0, "max": 1_000_000.0},
        "entry_min_notional_usdc": {"mode": "suggest-only", "type": "float", "min": 0.0, "max": 1_000_000.0},
        "entry_max_notional_usdc": {"mode": "suggest-only", "type": "float", "min": 0.0, "max": 1_000_000.0},
        "hl_min_notional_usdc": {"mode": "suggest-only", "type": "float", "min": 0.0, "max": 1_000_000.0},
        "hl_max_notional_usdc": {"mode": "suggest-only", "type": "float", "min": 0.0, "max": 1_000_000.0},
        "aster_min_notional_usdc": {"mode": "suggest-only", "type": "float", "min": 0.0, "max": 1_000_000.0},
        "aster_max_notional_usdc": {"mode": "suggest-only", "type": "float", "min": 0.0, "max": 1_000_000.0},
        "hl_default_leverage": {"mode": "suggest-only", "type": "int", "min": 1, "max": 50},
        "aster_default_leverage": {"mode": "suggest-only", "type": "int", "min": 1, "max": 50},
        "trade_whitelist": {"mode": "suggest-only", "type": "list_str", "max_len": 200},
        "universe_core_enforcement": {"mode": "suggest-only", "type": "str"},
        "config_allow_remote": {"mode": "suggest-only", "type": "bool"},
        "live_execute_allow_remote": {"mode": "suggest-only", "type": "bool"},
        "repo_fetch_enabled": {"mode": "suggest-only", "type": "bool"},
        "repo_whitelist": {"mode": "suggest-only", "type": "list_str", "max_len": 200},
    })
    _AGENT_AUTO_CONFIG_RULES_CACHE = out
    return out


def _config_patch_level_info(patch: Dict[str, Any], *, base_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(patch, dict) or not patch:
        return {"ok": True, "level": "B", "reasons": ["empty_patch"], "keys": []}
    rules = _agent_auto_config_rules()
    keys = [str(k).strip() for k in patch.keys() if str(k).strip()]
    modes: Dict[str, str] = {}
    unknown_keys: List[str] = []
    for k in keys:
        r = rules.get(k) if isinstance(rules, dict) else None
        if not isinstance(r, dict):
            unknown_keys.append(k)
            continue
        modes[k] = str(r.get("mode") or "").strip().lower() or "auto"
    if unknown_keys:
        return {"ok": True, "level": "B", "reasons": ["unknown_keys"], "keys": keys, "unknown_keys": unknown_keys, "modes": modes}
    tighten_only_keys = [k for k in keys if str(modes.get(k) or "").strip().lower() == "auto-tighten-only"]
    all_tighten_only_mode = (len(tighten_only_keys) == len(keys)) and bool(keys)
    level = "A" if all_tighten_only_mode else "B"
    reasons: List[str] = []
    if not all_tighten_only_mode:
        reasons.append("contains_non_tighten_only_keys")
    out: Dict[str, Any] = {"ok": True, "level": level, "keys": keys, "modes": modes, "all_tighten_only_mode": bool(all_tighten_only_mode)}
    if reasons:
        out["reasons"] = reasons
    return out


# ---------------------------------------------------------------------------
# 回滚
# ---------------------------------------------------------------------------

def _rollback_points_get() -> List[Dict[str, Any]]:
    raw = CONFIG.get("rollback_points")
    if not isinstance(raw, list):
        return []
    return [it for it in raw if isinstance(it, dict)]


def _rollback_snapshot_append(*, label: str, reason: str, config_keys: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """创建回滚快照（简化版，27模块独立存储）。"""
    try:
        now_ms = _now_ms()
        pt = {
            "id": hashlib.sha256(f"rb|{now_ms}|{uuid.uuid4().hex}".encode("utf-8")).hexdigest()[:16],
            "ts": now_ms,
            "label": str(label or "rollback").strip() or "rollback",
            "reason": str(reason or "").strip() or None,
            "config_keys": (config_keys if isinstance(config_keys, list) else None),
        }
        pts = _rollback_points_get()
        pts.append(pt)
        max_points = max(1, min(200, int(CONFIG.get("rollback_max_points", 20) or 20)))
        pts = sorted(pts, key=lambda x: int(x.get("ts") or 0), reverse=True)[:max_points]
        CONFIG["rollback_points"] = pts
        _config_save(CONFIG)
        return pt
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 运行时
# ---------------------------------------------------------------------------

def _runtime_config_version(cfg: Dict[str, Any]) -> Optional[str]:
    try:
        cfg_norm = json.dumps(cfg, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(cfg_norm).hexdigest()
    except Exception:
        return None


def _behavior_summary_autogen_style_mutation(*, candidate: Dict[str, Any], baseline: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """生成行为摘要（简化版）。"""
    if not isinstance(candidate, dict) or not candidate:
        return None
    cm = candidate.get("metrics_summary") if isinstance(candidate.get("metrics_summary"), dict) else {}
    ca = candidate.get("aligned_metrics") if isinstance(candidate.get("aligned_metrics"), dict) else {}

    def _trades_per_day(m: Dict[str, Any]) -> Optional[float]:
        try:
            n, d = m.get("trades"), m.get("backtest_days")
            if n is None or d is None:
                return None
            nf, df = float(n), float(d)
            if not math.isfinite(nf) or not math.isfinite(df) or df <= 0.0:
                return None
            return nf / df
        except Exception:
            return None

    def _dd_recovery_days(a: Dict[str, Any]) -> Optional[float]:
        try:
            v = a.get("dd_recovery_ms_max")
            if v is None:
                return None
            ms = float(v)
            if not math.isfinite(ms) or ms < 0.0:
                return None
            return ms / 86400_000.0
        except Exception:
            return None

    tpd = _trades_per_day(cm)
    ddr = _dd_recovery_days(ca)
    out: Dict[str, Any] = {}
    if tpd is not None:
        out["trades_per_day"] = round(tpd, 4)
    if ddr is not None:
        out["dd_recovery_days"] = round(ddr, 2)
    pf = cm.get("profit_factor")
    if pf is not None:
        try:
            out["profit_factor"] = float(pf)
        except Exception:
            pass
    mdd = cm.get("max_drawdown_pct")
    if mdd is not None:
        try:
            out["max_drawdown_pct"] = float(mdd)
        except Exception:
            pass
    return out if out else None


__all__ = [
    # 基础
    "CONFIG", "_now_ms", "_tail_lines", "_json_sanitize", "_stable_json_dumps",
    # 治理
    "_governance_env_name", "_governance_baseline_judge", "_governance_tighten_only", "_governance_has_improvement",
    # Lookahead 检测
    "_lookahead_check", "_lookahead_check_file",
    # 文档
    "_doc_refs_default", "_doc_refs_sanitize", "_evidence_sanitize", "_agent_chat_enforce_doc_refs",
    # Outbox/审计
    "_agent_outbox_dir", "_agent_outbox_append_jsonl", "_approvals_log_path",
    "_audit_base_payload", "_audit_emit_action", "_agent_emit_envelope_event",
    # 变更包
    "_agent_change_bundle_change_id", "_agent_config_diff_build", "_agent_config_diff_direction",
    "_agent_change_tags_from_config_diff", "_agent_expected_effect_from_delta_metrics",
    "_agent_change_bundle_draft_validate",
    # 配置规则
    "_agent_auto_config_rules", "_config_patch_level_info",
    # 回滚
    "_rollback_points_get", "_rollback_snapshot_append",
    # 运行时
    "_runtime_config_version", "_behavior_summary_autogen_style_mutation",
    # 配置管理
    "_config_get", "_config_save",
]
