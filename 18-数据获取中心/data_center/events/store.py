"""EventRecord 存储与契约校验 — SPEC-EMERGENCE-FINANCIAL-ENV v1.9 §3.1。

纪律（硬约束）：
  1. append-only，幂等键 = event_id（sha1(source|symbols|event_time|type)[:16]）
  2. `available_at` 必填且必须是带时区的 ISO8601 —— 它是回测唯一可用时间；
     缺失直接拒写（因此落盘文件 available_at 完整率恒为 100%）
  3. `event_time` 仅用于事件窗口对齐，同样必填
  4. 只允许 §3.1 的 13 种 type；`surprise_unit` 只允许 z/sue/pct/null
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

EVENTS_PATH = Path(__file__).resolve().parent / "events.jsonl"

# §3.1 事件类型枚举（禁止扩展，扩展须先改 SPEC）
EVENT_TYPES = (
    "earnings",
    "guidance",
    "fomc",
    "cpi",
    "nfp",
    "rate_decision",
    "mna",
    "buyback",
    "dividend",
    "regulatory",
    "product",
    "legal",
    "macro_other",
)

SURPRISE_UNITS = ("z", "sue", "pct")
QUALITIES = ("A", "B", "C")

_REQUIRED = ("type", "symbols", "event_time", "available_at", "source", "title", "quality")


class EventContractError(ValueError):
    """事件不满足 canonical EventRecord 契约。"""


def _parse_iso(ts: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        raise EventContractError(f"{field} 非合法 ISO8601：{ts!r}") from e
    if dt.tzinfo is None:
        raise EventContractError(f"{field} 必须带时区（UTC）：{ts!r}")
    return dt.astimezone(timezone.utc)


def make_event_id(source: str, symbols: list[str], event_time: str, type_: str) -> str:
    """幂等键：sha1(source|symbols|event_time|type)[:16]（SPEC §3.0）。"""
    key = f"{source}|{','.join(sorted(str(s) for s in symbols))}|{event_time}|{type_}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def normalize_event(rec: dict) -> dict:
    """补齐可选字段并校验；返回可直接落盘的 dict。不允许静默丢弃 available_at。"""
    if not isinstance(rec, dict):
        raise EventContractError(f"事件必须是 dict，收到 {type(rec).__name__}")

    missing = [k for k in _REQUIRED if rec.get(k) in (None, "", [])]
    if missing:
        raise EventContractError(f"缺少必填字段 {missing}：{rec.get('title')!r}")

    type_ = str(rec["type"])
    if type_ not in EVENT_TYPES:
        raise EventContractError(f"type={type_!r} 不在 §3.1 枚举内")

    if rec["quality"] not in QUALITIES:
        raise EventContractError(f"quality={rec['quality']!r} 非 A/B/C")

    symbols = [str(s).strip() for s in rec["symbols"] if str(s).strip()]
    if not symbols:
        raise EventContractError("symbols 不能全为空")

    event_time = _parse_iso(rec["event_time"], "event_time")
    available_at = _parse_iso(rec["available_at"], "available_at")
    if available_at < event_time:
        raise EventContractError(
            f"available_at({available_at.isoformat()}) 早于 event_time({event_time.isoformat()})"
        )

    unit = rec.get("surprise_unit")
    if unit is not None and unit not in SURPRISE_UNITS:
        raise EventContractError(f"surprise_unit={unit!r} 非 z/sue/pct/null")

    event_id = rec.get("event_id") or make_event_id(
        str(rec["source"]), symbols, event_time.isoformat().replace("+00:00", "Z"), type_
    )

    return {
        "event_id": event_id,
        "type": type_,
        "type_source": rec.get("type_source") or "fin_env_spec",
        "subtype": rec.get("subtype"),
        "symbols": symbols,
        "sector": rec.get("sector"),
        "event_time": event_time.isoformat().replace("+00:00", "Z"),
        "available_at": available_at.isoformat().replace("+00:00", "Z"),
        "source": str(rec["source"]),
        "source_url": rec.get("source_url"),
        "title": str(rec["title"]),
        "body_ref": rec.get("body_ref"),
        "surprise": rec.get("surprise"),
        "surprise_unit": unit,
        "expected": rec.get("expected"),
        "actual": rec.get("actual"),
        "confidence": rec.get("confidence", 0.0),
        "quality": rec["quality"],
        "trace_id": rec.get("trace_id") or event_id,
    }


def _existing_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    if not path.is_file():
        return ids
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event_id"):
                ids.add(row["event_id"])
    return ids


def append_events(records: list[dict], path: Path | str | None = None) -> tuple[int, int]:
    """按 event_id 幂等追加；返回 (新增数, 跳过数)。"""
    target = Path(path or EVENTS_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    seen = _existing_ids(target)

    to_write: list[dict] = []
    skipped = 0
    for rec in records:
        norm = normalize_event(rec)
        if norm["event_id"] in seen:
            skipped += 1
            continue
        seen.add(norm["event_id"])
        to_write.append(norm)

    if to_write:
        with open(target, "a", encoding="utf-8") as f:
            for row in to_write:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(to_write), skipped


def load_events(path: Path | str | None = None) -> list[dict]:
    target = Path(path or EVENTS_PATH)
    if not target.is_file():
        return []
    rows = []
    with open(target, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def audit_events(records: list[dict]) -> dict:
    """质量审计：available_at 完整率 / 类型分布 / 源分布 / 前视违规数。"""
    total = len(records)
    complete = sum(1 for r in records if r.get("available_at"))
    forward = 0
    for r in records:
        try:
            if _parse_iso(r["available_at"], "available_at") < _parse_iso(
                r["event_time"], "event_time"
            ):
                forward += 1
        except (EventContractError, KeyError):
            forward += 1

    by_source: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for r in records:
        by_source[r.get("source", "")] = by_source.get(r.get("source", ""), 0) + 1
        by_type[r.get("type", "")] = by_type.get(r.get("type", ""), 0) + 1

    return {
        "total": total,
        "available_at_complete": complete,
        "available_at_completeness": round(complete / total, 4) if total else 0.0,
        "available_at_before_event_time": forward,
        "by_source": dict(sorted(by_source.items())),
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
    }
