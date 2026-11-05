"""shadow_subscribers.py — E1 shadow 订阅者（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E1）。

rea/eval/data 三域的 shadow 代理：消费广播事件，按兴趣规则判定相关性，
相关事件触发 watchlist 变更（新入列或优先级升级）= 可审计的行为改变。

动作下限（SPEC v0.3 封口）：仅记日志/仅 ACK 不算动作，必须改变接收模块后续输出。
watchlist 影响该订阅者对后续事件的处理优先级排序——即"改变后续输出"的 shadow 形态。

响应落盘 events/emergence_shadow/resp_YYYYMMDD.jsonl；watchlist 持久化
events/emergence_shadow/watchlist_<domain>.json。

FAIL-OPEN：任何异常不抛出（订阅者回调被 WorkspaceBus 吞掉，本层自身也不抛）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVENTS_DIR = _REPO_ROOT / "48-涌现架构" / "events" / "emergence_shadow"

# 兴趣规则：各 shadow 域关心的 metric 类型（非目标域相关事件才可能产生动作）
INTEREST_RULES: Dict[str, List[str]] = {
    "rea": ["coupling"],  # 域耦合异常是做梦器/逆向解析的推理输入
    "eval": ["psi"],  # PSI 分布漂移影响评测有效性
    "data": ["data_quality", "missing_data"],  # 数据域关心质量/缺失异常
}


class ShadowSubscriber:
    """单域 shadow 订阅者：消费 → 相关性判定 → watchlist 动作 → 响应落盘。"""

    def __init__(self, domain: str, events_dir: Optional[Path] = None) -> None:
        self.domain = domain
        self._events_dir = Path(events_dir) if events_dir else DEFAULT_EVENTS_DIR
        self._watchlist_path = self._events_dir / f"watchlist_{domain}.json"
        self._interests = INTEREST_RULES.get(domain, [])

    def attach(self, bus: Any) -> str:
        """挂到 EmergenceBus（bus.subscribe(domain, callback)）。"""
        return bus.subscribe(self.domain, self._on_event)

    def _on_event(self, content: Any) -> None:
        """WorkspaceBus 回调。content.execution_result 即 bus envelope。"""
        try:
            envelope = getattr(content, "execution_result", None) or {}
            source_domain = envelope.get("source_domain", "")
            metric = envelope.get("metric", "")
            # 自身域事件不算"非目标域消费"（SPEC M1 口径）
            consumed = source_domain != self.domain
            relevant = consumed and metric in self._interests
            action = False
            action_detail: Dict[str, Any] = {}
            if relevant:
                action, action_detail = self._update_watchlist(source_domain, metric, envelope)
            self._persist_response(
                {
                    "event_id": envelope.get("event_id"),
                    "trace_id": envelope.get("trace_id"),
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "subscriber": self.domain,
                    "source_domain": source_domain,
                    "metric": metric,
                    "consumed": consumed,
                    "action": action,
                    "action_detail": action_detail,
                }
            )
        except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
            logger.warning("shadow subscriber %s 处理异常（吞掉）: %s", self.domain, exc)

    def _update_watchlist(
        self, source_domain: str, metric: str, envelope: Dict[str, Any]
    ) -> tuple[bool, Dict[str, Any]]:
        """watchlist 变更 = 动作。新入列 priority=1；重复事件 hits+1 且 priority 升级。"""
        wl = self._load_watchlist()
        entry = next(
            (
                e
                for e in wl["entries"]
                if e["source_domain"] == source_domain and e["metric"] == metric
            ),
            None,
        )
        if entry is None:
            entry = {
                "source_domain": source_domain,
                "metric": metric,
                "hits": 1,
                "priority": 1,
                "first_seen": envelope.get("ts"),
                "last_event_id": envelope.get("event_id"),
            }
            wl["entries"].append(entry)
            detail = {"kind": "watchlist_add", "priority": 1}
        else:
            before = entry["priority"]
            entry["hits"] += 1
            entry["priority"] = before + 1  # 优先级升级 = 行为改变
            entry["last_event_id"] = envelope.get("event_id")
            detail = {
                "kind": "watchlist_escalate",
                "priority_before": before,
                "priority_after": entry["priority"],
            }
        # watchlist 按 priority 降序——直接影响该订阅者后续事件处理顺序
        wl["entries"].sort(key=lambda e: -e["priority"])
        self._save_watchlist(wl)
        return True, detail

    def _load_watchlist(self) -> Dict[str, Any]:
        try:
            if self._watchlist_path.exists():
                return json.loads(self._watchlist_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
        return {"domain": self.domain, "entries": []}

    def _save_watchlist(self, wl: Dict[str, Any]) -> None:
        try:
            self._events_dir.mkdir(parents=True, exist_ok=True)
            self._watchlist_path.write_text(
                json.dumps(wl, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("watchlist 落盘失败: %s", exc)

    def _persist_response(self, resp: Dict[str, Any]) -> None:
        try:
            self._events_dir.mkdir(parents=True, exist_ok=True)
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            with (self._events_dir / f"resp_{day}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(resp, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("响应落盘失败: %s", exc)
