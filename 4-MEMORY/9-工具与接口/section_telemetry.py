"""Section Telemetry — T-G4 按 section 遥测

SPEC-33-G §1 G-G4 / §3 T-G4 / §0.5 非目标 4：遥测只落本地 JSONL，不外发。

指标：调用量 / 命中率 / 采纳率 / 预算命中（按 section 聚合）。
工程约束：纯标准库；append-only JSONL；FAIL-OPEN（调用方异常不应影响主流程）。
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1"
_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "telemetry" / "sections.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TelemetryEvent:
    event: str
    section: str
    hit: bool = False
    budget_hit: bool = True
    latency_ms: Optional[int] = None
    created_at: str = field(default_factory=_now)
    schema_version: str = SCHEMA_VERSION
    event_id: str = field(default_factory=lambda: f"te_{uuid.uuid4().hex}")

    def payload(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event": self.event,
            "section": self.section,
            "hit": self.hit,
            "budget_hit": self.budget_hit,
            "latency_ms": self.latency_ms,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


class SectionTelemetry:
    def __init__(self, path: Optional[str | Path] = None):
        if path is None:
            path = os.environ.get("COGNITIVE_SECTION_TELEMETRY_PATH") or _DEFAULT_PATH
        self.path = Path(path)

    def record_call(
        self,
        section: str,
        *,
        hit: bool = False,
        budget_hit: bool = True,
        latency_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._append(
            TelemetryEvent(
                event="call",
                section=_section(section),
                hit=bool(hit),
                budget_hit=bool(budget_hit),
                latency_ms=latency_ms,
            )
        )

    def record_adoption(self, section: str) -> Dict[str, Any]:
        return self._append(TelemetryEvent(event="adoption", section=_section(section)))

    def events(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def aggregate(self) -> Dict[str, Dict[str, Any]]:
        stats: Dict[str, Dict[str, Any]] = {}
        for event in self.events():
            item = stats.setdefault(
                event["section"],
                {"calls": 0, "hits": 0, "budget_hits": 0, "adoptions": 0},
            )
            if event["event"] == "call":
                item["calls"] += 1
                item["hits"] += int(bool(event.get("hit")))
                item["budget_hits"] += int(bool(event.get("budget_hit")))
            elif event["event"] == "adoption":
                item["adoptions"] += 1

        for item in stats.values():
            calls = item["calls"]
            item["hit_rate"] = round(item["hits"] / calls, 4) if calls else 0.0
            item["adoption_rate"] = round(item["adoptions"] / calls, 4) if calls else 0.0
            item["budget_hit_rate"] = round(item["budget_hits"] / calls, 4) if calls else 0.0
        return stats

    def _append(self, event: TelemetryEvent) -> Dict[str, Any]:
        payload = event.payload()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return payload


def _section(section: Any) -> str:
    value = str(section or "").strip()
    if not value:
        raise ValueError("section must be a non-empty string")
    return value
