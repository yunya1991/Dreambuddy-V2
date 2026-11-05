"""e4b_readout.py — E4b 埋点①：recall 读回率（SPEC v0.5 §4 E4b）。

断链诊断（v0.4 重勘）：主链已消费 recall（polling_trader `_inject_cognitive_recall`），
真正断链是 **recall 无结构化持久化日志** → 召回到决策改变无法 join。
本模块补三件事：
  1. `record_recall` / `record_action`：recall 事件与后续动作落盘
     `events/memory_readout/recall_events.jsonl`（append-only，event_id 幂等）
  2. `backfill_from_sessions`：从既有 shadow 数据（.cognitive/sessions 的
     session.json recalled_memory_ids + action_chain.jsonl）回填，零侵入起步
  3. `compute_readout_rate`：写→召回→改变行动 全链比例
     口径：action 必须发生在 recall 之后（ts 严格），且 changed_decision=True；
     仅有 recall 无动作不计（与 M1 动作下限同原则）。

域分层（如实）：会话域（开发）有数据可算；**交易域 no_data**——生产
`_inject_cognitive_recall` 只写文本日志，无结构化 memory_ids，需 11 域埋点协商。

FAIL-OPEN：IO/解析异常返回降级值，不抛出。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = _REPO_ROOT / "48-涌现架构" / "events" / "memory_readout" / "recall_events.jsonl"
DEFAULT_SESSIONS = _REPO_ROOT / ".cognitive" / "sessions"
# 动作下限：只认实际改动，会话类型演化不算「改变行动」
ACTION_TYPES = ("git_commit", "file_change")
MIN_RECALLS = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(kind: str, trace_id: str, ts: str, extra: str = "") -> str:
    seed = f"{kind}|{trace_id}|{ts}|{extra}"
    return f"{kind[0].upper()}-{hashlib.sha256(seed.encode()).hexdigest()[:10]}"


def _load(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("跳过损坏行: %.60s", line)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("load 失败（降级）: %s", exc)
    return out


def _append(events: Iterable[Dict[str, Any]], path: Path) -> int:
    """幂等追加：按 event_id 去重。返回实际追加条数。FAIL-OPEN。"""
    path = Path(path)
    existing = {e.get("event_id") for e in _load(path)}
    n = 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for ev in events:
                if ev.get("event_id") in existing:
                    continue
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
                existing.add(ev.get("event_id"))
                n += 1
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("append 失败（降级）: %s", exc)
    return n


def record_recall(
    trace_id: str,
    session_id: str,
    memory_ids: List[str],
    ts: Optional[str] = None,
    query: str = "",
    path: Optional[Path] = None,
    domain: str = "session",
) -> Optional[Dict[str, Any]]:
    """落盘一条 recall 事件。memory_ids 为空则跳过（无召回不算读回）。"""
    if not memory_ids:
        return None
    ts = ts or _now_iso()
    ev = {
        "event_id": _event_id("recall", trace_id, ts),
        "kind": "recall",
        "trace_id": trace_id,
        "session_id": session_id,
        "domain": domain,
        "ts": ts,
        "memory_ids": list(memory_ids),
        "n_memory": len(memory_ids),
        "query": query,
        "recorded_at": _now_iso(),
    }
    _append([ev], Path(path) if path else DEFAULT_LOG)
    return ev


def record_action(
    trace_id: str,
    session_id: str,
    ts: str,
    action_type: str,
    changed_decision: bool = True,
    path: Optional[Path] = None,
    detail: str = "",
) -> Dict[str, Any]:
    """落盘一条 recall 之后（或无关的）动作事件。"""
    ev = {
        "event_id": _event_id("action", trace_id, ts, action_type),
        "kind": "action",
        "trace_id": trace_id,
        "session_id": session_id,
        "ts": ts,
        "action_type": action_type,
        "changed_decision": bool(changed_decision),
        "detail": detail[:300],
        "recorded_at": _now_iso(),
    }
    _append([ev], Path(path) if path else DEFAULT_LOG)
    return ev


def _parse_ts(ts: Any) -> Optional[float]:
    if isinstance(ts, (int, float)):
        return float(ts)
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def compute_readout_rate(
    path: Optional[Path] = None,
    min_recalls: int = MIN_RECALLS,
    action_types: Iterable[str] = ACTION_TYPES,
) -> Dict[str, Any]:
    """readout_rate = 有后续改变动作的 recall 数 / 总 recall 数。"""
    events = _load(Path(path) if path else DEFAULT_LOG)
    recalls = [e for e in events if e.get("kind") == "recall" and e.get("n_memory")]
    allowed = set(action_types)
    actions = [
        e
        for e in events
        if e.get("kind") == "action"
        and e.get("changed_decision")
        and e.get("action_type") in allowed
    ]
    if not recalls:
        return {
            "value": None,
            "status": "no_data",
            "n_recalls": 0,
            "n_readout": 0,
            "note": "无结构化 recall 事件（交易域埋点需 11 域协商）",
        }
    by_trace: Dict[str, List[Dict[str, Any]]] = {}
    for a in actions:
        by_trace.setdefault(a.get("trace_id"), []).append(a)
    n_readout = 0
    for r in recalls:
        r_ts = _parse_ts(r.get("ts"))
        cands = by_trace.get(r.get("trace_id")) or []
        if r_ts is None:
            continue
        if any(((_parse_ts(a.get("ts")) or -1) > r_ts) for a in cands):
            n_readout += 1
    rate = n_readout / len(recalls)
    status = "ok" if len(recalls) >= min_recalls else "insufficient_data"
    # 会话域退化：recall 批次落在 session start，任何后续动作都满足时序条件 →
    # 率趋近 1，仅证明管道可 join，不构成「召回改变决策」证据
    degenerate = rate >= 0.95
    return {
        "value": rate,
        "status": status,
        "evidence_grade": "pipeline_only" if degenerate else "proxy",
        "n_recalls": len(recalls),
        "n_readout": n_readout,
        "n_memories_recalled": sum(int(r.get("n_memory") or 0) for r in recalls),
        "n_actions_matched": len(actions),
        "note": "时序 join 代理：动作发生在 recall 之后即计读回，非因果证明",
        "caveat": (
            "会话域 recall 在会话起始、动作必然随后 → 率退化接近 1，仅验证管道；"
            "交易域 recall 无结构化 memory_ids 日志 → 待 11 域埋点"
            if degenerate
            else None
        ),
    }


def _emit_trading_gap(path: Optional[Path] = None) -> bool:
    """交易域 recall 无结构化日志 → E6 需求单（同类型 open 单不重复发）。"""
    try:
        _reg = str(_REPO_ROOT / "48-涌现架构" / "registry")
        if _reg not in sys.path:
            sys.path.insert(0, _reg)
        import capability_gaps as cg

        gaps_path = Path(path) if path else cg.DEFAULT_GAPS_PATH
        for g in cg.load_gaps(gaps_path):
            if (
                g.get("gap_type") == "trading_recall_log_missing"
                and g.get("created_by") == "e4b_readout"
                and g.get("status") in ("open", "claimed")
            ):
                return False
        gap = cg.new_gap(
            gap_type="trading_recall_log_missing",
            evidence={
                "source": "e4b_readout",
                "reason": "polling_trader._inject_cognitive_recall 仅 self._log 文本日志，"
                "无结构化 memory_ids/trace_id，无法 join 决策改变",
            },
            expected_value="readout_rate 可从会话代理升级为交易主链真实度量",
            target_domain_hint="11-易经推理系统",
            created_by="e4b_readout",
        )
        return cg.append_gap(gap, path=gaps_path)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("发 E6 需求单失败（降级）: %s", exc)
        return False


def backfill_from_sessions(
    sessions_root: Optional[Path] = None,
    path: Optional[Path] = None,
    action_types: Iterable[str] = ACTION_TYPES,
    max_sessions: Optional[int] = None,
) -> Dict[str, Any]:
    """从既有 .cognitive/sessions 回填 recall/action 事件（零侵入起步）。幂等。"""
    root = Path(sessions_root) if sessions_root else DEFAULT_SESSIONS
    allowed = set(action_types)
    events: List[Dict[str, Any]] = []
    n_sess = 0
    try:
        dirs = sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []
        if max_sessions:
            dirs = dirs[:max_sessions]
        for d in dirs:
            sj = d / "session.json"
            if not sj.exists():
                continue
            try:
                s = json.loads(sj.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            sid = s.get("id") or d.name
            trace_id = f"readout-{sid}"
            ts = _parse_ts(s.get("start_time"))
            if ts is None:
                continue
            ts_iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
            mem_ids = s.get("recalled_memory_ids") or []
            if mem_ids:
                events.append(
                    {
                        "event_id": _event_id("recall", trace_id, ts_iso),
                        "kind": "recall",
                        "trace_id": trace_id,
                        "session_id": sid,
                        "domain": "session",
                        "ts": ts_iso,
                        "memory_ids": list(mem_ids),
                        "n_memory": len(mem_ids),
                        "query": s.get("task_type", ""),
                        "recorded_at": _now_iso(),
                        "source": "backfill_sessions",
                    }
                )
            chain = d / "action_chain.jsonl"
            if chain.exists():
                try:
                    # 只记每个 session 的首个合格动作：readout 只需「存在后续动作」，
                    # 全量动作（实测 6.3 万条）会让日志膨胀且指标无增益
                    recorded = False
                    for line in chain.read_text(encoding="utf-8").splitlines():
                        if recorded:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        a = json.loads(line)
                        a_ts = _parse_ts(a.get("timestamp"))
                        atype = a.get("action_type")
                        if a_ts is None or atype not in allowed:
                            continue
                        if a_ts <= ts:  # 只记 recall 之后的动作
                            continue
                        a_iso = datetime.fromtimestamp(a_ts, timezone.utc).isoformat()
                        events.append(
                            {
                                "event_id": _event_id("action", trace_id, a_iso, str(atype)),
                                "kind": "action",
                                "trace_id": trace_id,
                                "session_id": sid,
                                "ts": a_iso,
                                "action_type": atype,
                                "changed_decision": True,
                                "detail": str(a.get("detail", ""))[:300],
                                "recorded_at": _now_iso(),
                                "source": "backfill_sessions",
                            }
                        )
                        recorded = True
                except Exception:  # noqa: BLE001
                    continue
            n_sess += 1
        recall_n = sum(1 for e in events if e["kind"] == "recall")
        action_n = sum(1 for e in events if e["kind"] == "action")
        appended = _append(events, Path(path) if path else DEFAULT_LOG)
        return {
            "n_sessions": n_sess,
            "n_recalls": recall_n,
            "n_actions": action_n,
            "n_appended": appended,
            "n_skipped": len(events) - appended,
        }
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("backfill FAIL-OPEN: %s", exc)
        return {"n_sessions": 0, "n_recalls": 0, "n_actions": 0, "n_appended": 0, "n_skipped": 0}


def main() -> int:
    bf = backfill_from_sessions()
    res = compute_readout_rate()
    if res.get("caveat"):
        _emit_trading_gap()
    print(
        f"E4b readout: backfill={json.dumps(bf, ensure_ascii=False)} "
        f"rate={res.get('value')} status={res.get('status')} "
        f"grade={res.get('evidence_grade')} "
        f"n_recalls={res.get('n_recalls')} n_readout={res.get('n_readout')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
