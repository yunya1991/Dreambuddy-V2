# ruff: noqa: E402
"""recall 统计接入 — 为 M-ASIL-2 distill_effectiveness 提供真实数据源。

数据源优先级：
1. 48-涌现架构/events/memory_readout/recall_events.jsonl
   schema: {event_id, kind: recall|action, memory_ids, n_memory, ts(ISO8601)}
2. 4-MEMORY/data/verification_observer/recall_events.jsonl
   schema: {session_id, returned_ids, returned_scores, returned_qualities, ts(float)}

口径：
- 只统计 kind == "recall" 的事件（action 不计入）
- 命中：有 returned_qualities 时按「最高质量 ≥ B」判定；否则退回「返回数 ≥ 1」
- 蒸馏有效性 = 蒸馏后窗口命中率 − 蒸馏前等长窗口命中率
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECALL_EVENTS = _PKG_ROOT / "events" / "memory_readout" / "recall_events.jsonl"
FALLBACK_RECALL_EVENTS = (
    _PKG_ROOT.parent / "4-MEMORY" / "data" / "verification_observer" / "recall_events.jsonl"
)
DEFAULT_WINDOW_SECONDS = 7 * 24 * 3600

# 质量等级排序；B 及以上算命中
_QUALITY_RANK = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}
MIN_HIT_QUALITY_RANK = 3


@dataclass(frozen=True)
class RecallWindowStats:
    n_recalls: int
    n_hits: int
    hit_rate: float
    avg_returned: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RecallStatsProvider:
    """读取 recall 事件流，计算命中率与蒸馏前后对比。"""

    def __init__(
        self,
        events_path: Optional[Path] = None,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ):
        self.events_path = events_path
        self.window_seconds = window_seconds
        self._events: Optional[List[Dict[str, Any]]] = None

    # ---------------- 数据加载 ----------------
    def resolve_path(self) -> Optional[Path]:
        if self.events_path is not None:
            return self.events_path if self.events_path.exists() else None
        for p in (DEFAULT_RECALL_EVENTS, FALLBACK_RECALL_EVENTS):
            if p.exists():
                return p
        return None

    @staticmethod
    def _parse_ts(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        try:
            return float(text)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    def _normalize(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        kind = raw.get("kind")
        if kind is not None and kind != "recall":
            return None

        ids = raw.get("memory_ids")
        if ids is None:
            ids = raw.get("returned_ids") or []
        n = raw.get("n_memory")
        if n is None:
            n = len(ids)

        ts = self._parse_ts(raw.get("ts", raw.get("recorded_at")))
        if ts is None:
            return None

        qualities = raw.get("returned_qualities") or []
        if qualities:
            ranks = [_QUALITY_RANK.get(str(q).upper(), 0) for q in qualities]
            hit = max(ranks, default=0) >= MIN_HIT_QUALITY_RANK
            basis = "quality"
        else:
            hit = int(n) > 0
            basis = "count"
        return {"ts": ts, "n_returned": int(n), "hit": hit, "hit_basis": basis}

    def load(self) -> List[Dict[str, Any]]:
        if self._events is not None:
            return self._events
        path = self.resolve_path()
        if path is None:
            self._events = []
            return self._events

        events: List[Dict[str, Any]] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            norm = self._normalize(raw)
            if norm is not None:
                events.append(norm)
        self._events = events
        return events

    # ---------------- 指标 ----------------
    def stats(
        self,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> RecallWindowStats:
        rows = [
            e
            for e in self.load()
            if (since is None or e["ts"] >= since) and (until is None or e["ts"] < until)
        ]
        n = len(rows)
        hits = sum(1 for e in rows if e["hit"])
        returned = sum(e["n_returned"] for e in rows)
        return RecallWindowStats(
            n_recalls=n,
            n_hits=hits,
            hit_rate=round(hits / n, 6) if n else 0.0,
            avg_returned=round(returned / n, 3) if n else 0.0,
        )

    def effectiveness(self, distill_ts: float, window: Optional[int] = None) -> Dict[str, Any]:
        """蒸馏前后等长窗口的命中率对比。"""
        w = window or self.window_seconds
        before = self.stats(since=distill_ts - w, until=distill_ts)
        after = self.stats(since=distill_ts, until=distill_ts + w)
        sufficient = before.n_recalls > 0 and after.n_recalls > 0
        return {
            "distill_ts": distill_ts,
            "window_seconds": w,
            "before": before.to_dict(),
            "after": after.to_dict(),
            "delta": round(after.hit_rate - before.hit_rate, 6) if sufficient else 0.0,
            "sufficient": sufficient,
        }

    def summary(self) -> Dict[str, Any]:
        path = self.resolve_path()
        overall = self.stats()
        basis = {"quality": 0, "count": 0}
        for e in self.load():
            basis[e["hit_basis"]] = basis.get(e["hit_basis"], 0) + 1
        return {
            "source": str(path) if path else None,
            **overall.to_dict(),
            "hit_basis": basis,
        }
