from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SyncRule:
    source_rel: str
    target_rel: str
    patterns: Tuple[str, ...]
    max_files: int


def _now_ms() -> int:
    return int(time.time() * 1000)


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _json_hash(v: Any) -> str:
    s = json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _find_latest(base: Path, patterns: Tuple[str, ...]) -> Optional[Path]:
    rows: List[Path] = []
    for pat in patterns:
        rows.extend([p for p in base.glob(pat) if p.is_file()])
    if not rows:
        return None
    rows.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return rows[0]


def _pick_narrative_dir(root: Path) -> Path:
    p1 = root / "ops" / "nanoclaw" / "core_task1" / "narrative" / "narrative" / "outputs"
    p2 = root / "ops" / "nanoclaw" / "core_task1" / "narrative" / "outputs"
    if p1.exists():
        return p1
    return p2


def _glob_latest(base: Path, patterns: Tuple[str, ...], max_files: int) -> List[Path]:
    out: List[Path] = []
    for pat in patterns:
        out.extend([p for p in base.glob(pat) if p.is_file()])
    if not out:
        return []
    uniq = {str(p.resolve()): p for p in out}
    rows = list(uniq.values())
    rows.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return rows[: max(1, int(max_files))]


def _copy_one(src: Path, dst: Path) -> bool:
    if dst.exists():
        s1 = src.stat()
        s2 = dst.stat()
        if int(s1.st_mtime) == int(s2.st_mtime) and int(s1.st_size) == int(s2.st_size):
            return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _quality_rank(v: Any) -> int:
    s = str(v or "").strip().lower()
    if s in {"ok", "good", "normal", "fresh"}:
        return 0
    if s in {"stale", "degraded"}:
        return 1
    if s in {"suspect", "warn"}:
        return 2
    if s in {"missing", "bad"}:
        return 3
    return 4


def _extract_risk_action(v: Any) -> str:
    if isinstance(v, dict):
        for k in ("risk_action_proposal", "risk_action", "action", "proposal"):
            x = v.get(k)
            if isinstance(x, str) and x.strip():
                return x.strip().lower()
        for k in ("items", "events", "rows", "data"):
            x = v.get(k)
            if isinstance(x, list) and x:
                return _extract_risk_action(x[0])
    if isinstance(v, list) and v:
        return _extract_risk_action(v[0])
    return ""


def _probe_upstream(research_root: Path) -> Dict[str, Any]:
    news_out = research_root / "ops" / "nanoclaw" / "core_task1" / "outputs"
    news_raw = research_root / "ops" / "nanoclaw" / "core_task1" / "raw"
    flow_out = research_root / "ops" / "nanoclaw" / "core_task1" / "flow" / "outputs"
    narr_out = _pick_narrative_dir(research_root)

    brief_p = _find_latest(news_out, ("brief_v3_*_optimized.md", "brief_v3_*.md", "brief_v2_*.md", "brief_*.md"))
    risk_p = _find_latest(news_raw, ("risk_action_events_*.json",))
    flow_p = _find_latest(flow_out, ("flow_regime_*.json",))
    narr_p = _find_latest(narr_out, ("narrative_registry_*.json",))

    flow_obj = _read_json_file(flow_p) if flow_p else None
    narr_obj = _read_json_file(narr_p) if narr_p else None
    risk_obj = _read_json_file(risk_p) if risk_p else None

    flow_turning = ""
    flow_quality = ""
    flow_cov = None
    if isinstance(flow_obj, dict):
        flow_turning = str(
            flow_obj.get("turning_point_state")
            or ((flow_obj.get("regime") or {}).get("turning_point_state") if isinstance(flow_obj.get("regime"), dict) else "")
            or ""
        ).strip().lower()
        qv = flow_obj.get("quality")
        if isinstance(qv, dict):
            flow_quality = str(qv.get("status") or qv.get("overall_quality") or "").strip().lower()
        else:
            flow_quality = str(qv or "").strip().lower()
        try:
            flow_cov = float(flow_obj.get("coverage"))
        except Exception:
            flow_cov = None

    narr_quality = ""
    if isinstance(narr_obj, dict):
        narr_quality = str(
            narr_obj.get("quality")
            or narr_obj.get("overall_quality")
            or ((narr_obj.get("summary") or {}).get("quality") if isinstance(narr_obj.get("summary"), dict) else "")
            or ""
        ).strip().lower()

    risk_action = _extract_risk_action(risk_obj)

    marker = {
        "brief": {
            "name": (brief_p.name if brief_p else ""),
            "mtime_ms": (int(brief_p.stat().st_mtime * 1000) if brief_p else 0),
            "size": (int(brief_p.stat().st_size) if brief_p else 0),
        },
        "risk_action_events": {
            "name": (risk_p.name if risk_p else ""),
            "mtime_ms": (int(risk_p.stat().st_mtime * 1000) if risk_p else 0),
            "size": (int(risk_p.stat().st_size) if risk_p else 0),
            "risk_action": str(risk_action or ""),
        },
        "flow_regime": {
            "name": (flow_p.name if flow_p else ""),
            "mtime_ms": (int(flow_p.stat().st_mtime * 1000) if flow_p else 0),
            "size": (int(flow_p.stat().st_size) if flow_p else 0),
            "turning_point_state": str(flow_turning or ""),
            "quality": str(flow_quality or ""),
            "coverage": flow_cov,
        },
        "narrative_registry": {
            "name": (narr_p.name if narr_p else ""),
            "mtime_ms": (int(narr_p.stat().st_mtime * 1000) if narr_p else 0),
            "size": (int(narr_p.stat().st_size) if narr_p else 0),
            "quality": str(narr_quality or ""),
        },
    }
    marker["signature"] = _json_hash(marker)
    return marker


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _detect_trigger(prev_probe: Dict[str, Any], curr_probe: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    prev_sig = str(prev_probe.get("signature") or "")
    curr_sig = str(curr_probe.get("signature") or "")
    if prev_sig and curr_sig and prev_sig != curr_sig:
        reasons.append("marker_changed")

    prev_risk = str(((prev_probe.get("risk_action_events") or {}).get("risk_action")) or "")
    curr_risk = str(((curr_probe.get("risk_action_events") or {}).get("risk_action")) or "")
    if prev_risk and curr_risk and prev_risk != curr_risk:
        reasons.append("risk_action_changed")

    prev_turn = str(((prev_probe.get("flow_regime") or {}).get("turning_point_state")) or "")
    curr_turn = str(((curr_probe.get("flow_regime") or {}).get("turning_point_state")) or "")
    if prev_turn and curr_turn and prev_turn != curr_turn:
        reasons.append("turning_point_state_changed")

    prev_q_flow = _quality_rank((prev_probe.get("flow_regime") or {}).get("quality"))
    curr_q_flow = _quality_rank((curr_probe.get("flow_regime") or {}).get("quality"))
    prev_q_narr = _quality_rank((prev_probe.get("narrative_registry") or {}).get("quality"))
    curr_q_narr = _quality_rank((curr_probe.get("narrative_registry") or {}).get("quality"))
    if curr_q_flow > prev_q_flow or curr_q_narr > prev_q_narr:
        reasons.append("quality_worsened")

    force_sync = any(x in reasons for x in ("risk_action_changed", "turning_point_state_changed", "quality_worsened"))
    return {"hit": bool(reasons), "force_sync": bool(force_sync), "reasons": reasons}


def _rules() -> List[SyncRule]:
    return [
        SyncRule(
            source_rel="ops/nanoclaw/core_task1/outputs",
            target_rel="ops/nanoclaw/core_task1/outputs",
            patterns=("brief_v3_*_optimized.md", "brief_v3_*.md", "brief_v2_*.md", "brief_*.md"),
            max_files=80,
        ),
        SyncRule(
            source_rel="ops/nanoclaw/core_task1/raw",
            target_rel="ops/nanoclaw/core_task1/raw",
            patterns=("coverage_report_*.json", "risk_action_events_*.json", "anchor_delta_view_*.json", "event_ledger_*.jsonl"),
            max_files=160,
        ),
        SyncRule(
            source_rel="ops/nanoclaw/core_task1/flow/outputs",
            target_rel="ops/nanoclaw/core_task1/flow/outputs",
            patterns=("flow_brief_v*.md", "flow_brief_*.md", "flow_regime_*.json"),
            max_files=120,
        ),
        SyncRule(
            source_rel="ops/nanoclaw/core_task1/flow/raw/exogenous",
            target_rel="ops/nanoclaw/core_task1/flow/raw/exogenous",
            patterns=("exogenous_flow_*.json",),
            max_files=120,
        ),
        SyncRule(
            source_rel="ops/nanoclaw/core_task1/flow/raw/leverage",
            target_rel="ops/nanoclaw/core_task1/flow/raw/leverage",
            patterns=("leverage_flow_*.json",),
            max_files=120,
        ),
        SyncRule(
            source_rel="ops/nanoclaw/core_task1/flow/raw/onchain",
            target_rel="ops/nanoclaw/core_task1/flow/raw/onchain",
            patterns=("onchain_flow_*.json",),
            max_files=120,
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-root", default="/Users/zhangjiangtao/ft_userdata/基本面分析_fundamental")
    parser.add_argument("--trading-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--manifest", default="")
    parser.add_argument("--policy-state", default="")
    parser.add_argument("--baseline-sec", type=int, default=28800)
    parser.add_argument("--burst-sec", type=int, default=900)
    parser.add_argument("--burst-hold-sec", type=int, default=7200)
    parser.add_argument("--sla-sec", type=int, default=900)
    args = parser.parse_args()

    research_root = Path(str(args.research_root)).resolve()
    trading_root = Path(str(args.trading_root)).resolve()
    ts = _now_ms()

    if not (research_root / "ml_trade_service.py").exists():
        raise SystemExit("invalid research root")
    if not (trading_root / "ml_trade_service.py").exists():
        raise SystemExit("invalid trading root")

    manifest = str(args.manifest or "").strip()
    if not manifest:
        manifest = str(trading_root / "user_data" / "fundamental_sync" / "last_sync.json")
    mp = Path(manifest)
    mp.parent.mkdir(parents=True, exist_ok=True)

    policy_state = str(args.policy_state or "").strip()
    if not policy_state:
        policy_state = str(trading_root / "user_data" / "fundamental_sync" / "policy_state.json")
    pp = Path(policy_state)
    pp.parent.mkdir(parents=True, exist_ok=True)

    baseline_sec = max(300, int(args.baseline_sec or 28800))
    burst_sec = max(300, min(baseline_sec, int(args.burst_sec or 900)))
    burst_hold_sec = max(burst_sec, int(args.burst_hold_sec or 7200))
    sla_sec = max(60, int(args.sla_sec or 900))

    st = _load_json(pp)
    last_full_sync_ms = int(st.get("last_full_sync_ms") or 0)
    burst_until_ms = int(st.get("burst_until_ms") or 0)
    prev_probe = st.get("last_probe") if isinstance(st.get("last_probe"), dict) else {}
    curr_probe = _probe_upstream(research_root)
    trigger = _detect_trigger(prev_probe, curr_probe)
    now_ms = int(ts)
    if bool(trigger.get("hit")):
        burst_until_ms = max(int(burst_until_ms), int(now_ms + burst_hold_sec * 1000))
    in_burst = int(now_ms) < int(burst_until_ms)
    effective_interval_sec = int(burst_sec if in_burst else baseline_sec)
    due_by_interval = (int(now_ms) - int(last_full_sync_ms)) >= int(effective_interval_sec * 1000)
    should_sync = bool(due_by_interval or bool(trigger.get("force_sync")))

    if not bool(should_sync):
        out_skip = {
            "ok": True,
            "ts": ts,
            "research_root": str(research_root),
            "trading_root": str(trading_root),
            "mode": ("burst" if in_burst else "baseline"),
            "baseline_sec": int(baseline_sec),
            "burst_sec": int(burst_sec),
            "burst_hold_sec": int(burst_hold_sec),
            "sla_sec": int(sla_sec),
            "effective_interval_sec": int(effective_interval_sec),
            "last_full_sync_ms": int(last_full_sync_ms),
            "next_due_ms": int(last_full_sync_ms + effective_interval_sec * 1000),
            "trigger": trigger,
            "upstream_probe": curr_probe,
            "scanned": 0,
            "copied": 0,
            "missing_sources": [],
            "touched": [],
            "skipped": True,
        }
        st["last_probe"] = curr_probe
        st["last_check_ms"] = int(now_ms)
        st["burst_until_ms"] = int(burst_until_ms)
        st["last_decision"] = {"mode": ("burst" if in_burst else "baseline"), "should_sync": False, "trigger": trigger}
        pp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        mp.write_text(json.dumps(out_skip, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(out_skip, ensure_ascii=False))
        return

    copied = 0
    scanned = 0
    touched: List[Dict[str, str]] = []
    missing_sources: List[str] = []

    for rule in _rules():
        src_dir = research_root / rule.source_rel
        dst_dir = trading_root / rule.target_rel
        if not src_dir.exists():
            missing_sources.append(str(src_dir))
            continue
        src_files = _glob_latest(src_dir, rule.patterns, max_files=rule.max_files)
        scanned += len(src_files)
        for src in src_files:
            dst = dst_dir / src.name
            changed = _copy_one(src, dst)
            if changed:
                copied += 1
                touched.append({"src": str(src), "dst": str(dst)})

    src_narr = _pick_narrative_dir(research_root)
    dst_narr = _pick_narrative_dir(trading_root)
    if src_narr.exists():
        rows = _glob_latest(src_narr, ("narrative_brief_*.md", "narrative_registry_*.json"), max_files=160)
        scanned += len(rows)
        for src in rows:
            dst = dst_narr / src.name
            changed = _copy_one(src, dst)
            if changed:
                copied += 1
                touched.append({"src": str(src), "dst": str(dst)})
    else:
        missing_sources.append(str(src_narr))

    out = {
        "ok": len(missing_sources) == 0,
        "ts": ts,
        "research_root": str(research_root),
        "trading_root": str(trading_root),
        "mode": ("burst" if in_burst else "baseline"),
        "baseline_sec": int(baseline_sec),
        "burst_sec": int(burst_sec),
        "burst_hold_sec": int(burst_hold_sec),
        "sla_sec": int(sla_sec),
        "effective_interval_sec": int(effective_interval_sec),
        "trigger": trigger,
        "upstream_probe": curr_probe,
        "scanned": int(scanned),
        "copied": int(copied),
        "missing_sources": missing_sources,
        "touched": touched[:120],
        "skipped": False,
    }

    st["last_probe"] = curr_probe
    st["last_check_ms"] = int(now_ms)
    st["last_full_sync_ms"] = int(now_ms)
    st["burst_until_ms"] = int(burst_until_ms)
    st["last_decision"] = {"mode": ("burst" if in_burst else "baseline"), "should_sync": True, "trigger": trigger}
    pp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    mp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
