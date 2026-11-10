"""training_events.py — 统一 TrainingEvent 落盘（48 NN 反馈网关 P0）。

职责（SPEC-NN-FEEDBACK-GATEWAY v0.1 §2.2）：
  1. `normalize_event` / `record_event`：append-only JSONL，event_id 幂等；
  2. `backfill_from_decisions`：把 50 `runtime/decisions.jsonl` 映射为 TrainingEvent；
  3. `load_events`：供网关聚合。

落盘：`48-涌现架构/events/training_events/*.jsonl`。
纪律：FAIL-OPEN（IO/解析异常降级返回，不中断主链）；不写 50/23/40。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = _REPO_ROOT / "48-涌现架构" / "events" / "training_events"
SCHEMA_VERSION = "training_event.v0.1"
_NESTED = (
    "constraints",
    "signals",
    "evidence",
    "decision",
    "execution",
    "pnl",
    "cognitive_recall",
    "reflection",
    "action",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(payload: Dict[str, Any]) -> str:
    seed = "|".join(str(payload.get(k, "")) for k in ("decision_id", "source", "ts", "symbol"))
    return "TE-" + hashlib.sha256(seed.encode()).hexdigest()[:12]


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    """补齐字段并生成幂等 event_id；不修改入参。"""
    ev: Dict[str, Any] = dict(raw)
    ev.setdefault("source", "unknown")
    ev.setdefault("symbol", "unknown")
    ev.setdefault("ts", _now_iso())
    ev.setdefault("decision_id", f"{ev['source']}|{ev['ts']}|{ev['symbol']}")
    for key in _NESTED:
        ev[key] = _as_dict(ev.get(key))
    ev.setdefault("provenance", {})
    ev["version"] = SCHEMA_VERSION
    ev["event_id"] = _event_id(ev)
    ev.setdefault("recorded_at", _now_iso())
    return ev


def _default_path(ts: str) -> Path:
    day = (ts or "")[:10].replace("-", "")
    return DEFAULT_DIR / f"train_{day}.jsonl"


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
                obj = json.loads(line)
                if isinstance(obj, dict):
                    out.append(obj)
            except json.JSONDecodeError:
                logger.warning("跳过损坏行: %.60s", line)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("读取 training_events 失败（降级）: %s", exc)
    return out


def load_events(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """读取单个文件或目录下全部 JSONL。"""
    path = Path(path) if path else DEFAULT_DIR
    if path.is_dir():
        events: List[Dict[str, Any]] = []
        for f in sorted(path.glob("*.jsonl")):
            events.extend(_load(f))
        return events
    return _load(path)


def record_event(event: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    """幂等追加单条事件。返回 {status, event_id, path}。"""
    ev = normalize_event(event)
    target = Path(path) if path else _default_path(ev["ts"])
    existing = {e.get("event_id") for e in _load(target)}
    if ev["event_id"] in existing:
        return {"status": "duplicate", "event_id": ev["event_id"], "path": str(target)}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return {"status": "recorded", "event_id": ev["event_id"], "path": str(target)}
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("写 training_event 失败（降级）: %s", exc)
        return {
            "status": "error",
            "event_id": ev["event_id"],
            "path": str(target),
            "error": str(exc),
        }


def record_events(events: Iterable[Dict[str, Any]], path: Optional[Path] = None) -> int:
    n = 0
    for ev in events:
        if record_event(ev, path=path)["status"] == "recorded":
            n += 1
    return n


def from_decision(decision: Dict[str, Any], source_path: Optional[str] = None) -> Dict[str, Any]:
    """50/23 决策 → TrainingEvent（只映射，不推断）。"""
    payload = _as_dict(decision.get("payload"))
    w4 = _as_dict(payload.get("w4"))
    dominance = _as_dict(payload.get("dominance"))
    execution = _as_dict(payload.get("execution"))
    conflict = w4.get("conflict_flag")
    return normalize_event(
        {
            "decision_id": decision.get("signal_id") or decision.get("decision_id"),
            "source": decision.get("source", "unknown"),
            "symbol": decision.get("symbol", "unknown"),
            "ts": decision.get("ts") or _now_iso(),
            "constraints": _as_dict(payload.get("constraints") or payload.get("constraint")),
            "signals": {
                "source": decision.get("source"),
                "direction": decision.get("direction"),
                "confidence": decision.get("confidence"),
                "horizon": decision.get("horizon"),
                "intent": payload.get("intent"),
                "dimension_hint": payload.get("dimension_hint"),
            },
            "evidence": {
                "provenance": payload.get("provenance"),
                "agreement": payload.get("agreement"),
                "conflict_flags": [conflict] if conflict else [],
            },
            "decision": {
                "action": decision.get("direction"),
                "tier": decision.get("mode"),
                "position_mult": decision.get("position_pct"),
                "primary_contradiction": dominance.get("overall_leader"),
            },
            "execution": execution,
            "pnl": _as_dict(payload.get("pnl")),
            "cognitive_recall": _as_dict(payload.get("cognitive_recall")),
            "reflection": _as_dict(payload.get("reflection")),
            "action": _as_dict(payload.get("action")),
            "provenance": {
                "producer": decision.get("source", "unknown"),
                "producer_version": decision.get("contract_version") or decision.get("version"),
                "source_path": source_path,
            },
        }
    )


def backfill_from_decisions(
    decisions_path: Path,
    out_path: Optional[Path] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """把 decisions.jsonl 回填为 TrainingEvent；二次执行幂等追加 0 条。"""
    decisions_path = Path(decisions_path)
    target = Path(out_path) if out_path else DEFAULT_DIR / "train_50_decisions.jsonl"
    stats = {"scanned": 0, "appended": 0, "duplicates": 0, "invalid": 0, "error": 0}
    if not decisions_path.exists():
        return stats
    try:
        lines = decisions_path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("读取 decisions 失败（降级）: %s", exc)
        return stats
    for line in lines:
        if limit is not None and stats["scanned"] >= limit:
            break
        line = line.strip()
        if not line:
            continue
        stats["scanned"] += 1
        try:
            decision = json.loads(line)
            if not isinstance(decision, dict) or not (
                decision.get("signal_id") or decision.get("decision_id")
            ):
                stats["invalid"] += 1
                continue
        except json.JSONDecodeError:
            stats["invalid"] += 1
            continue
        res = record_event(from_decision(decision, source_path=str(decisions_path)), path=target)
        if res["status"] == "recorded":
            stats["appended"] += 1
        elif res["status"] == "duplicate":
            stats["duplicates"] += 1
        else:
            stats["error"] += 1
    return stats
