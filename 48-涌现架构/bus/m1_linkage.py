"""m1_linkage.py — M1 广播联动率度量（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E1 + §5）。

M1 = 广播事件被非目标域消费并产生动作的比例（actions / consumed）。
动作下限：watchlist 变更（新入列/优先级升级）才算动作，仅记日志/ACK 不算。

数据源：events/emergence_shadow/bus_*.jsonl（广播）+ resp_*.jsonl（响应）。
FAIL-OPEN：目录缺失/文件损坏返回 no_events，不抛出。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVENTS_DIR = _REPO_ROOT / "48-涌现架构" / "events" / "emergence_shadow"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("跳过损坏行: %.80s", line)
    except Exception:  # noqa: BLE001
        pass
    return rows


def compute_m1(events_dir: Optional[Path] = None, day: Optional[str] = None) -> Dict[str, Any]:
    """计算 M1 联动率。day 指定 YYYYMMDD 只算当日；默认累计全部。"""
    events_dir = Path(events_dir) if events_dir else DEFAULT_EVENTS_DIR
    if not events_dir.is_dir():
        return {
            "status": "no_events",
            "m1_rate": None,
            "broadcasts": 0,
            "consumed": 0,
            "actions": 0,
        }

    bus_files = sorted(events_dir.glob(f"bus_{day or '*'}.jsonl"))
    resp_files = sorted(events_dir.glob(f"resp_{day or '*'}.jsonl"))
    broadcasts = sum(len(_read_jsonl(f)) for f in bus_files)
    consumed = 0
    actions = 0
    by_subscriber: Dict[str, Dict[str, int]] = {}
    for f in resp_files:
        for resp in _read_jsonl(f):
            sub = resp.get("subscriber", "?")
            bucket = by_subscriber.setdefault(sub, {"consumed": 0, "actions": 0})
            if resp.get("consumed"):
                consumed += 1
                bucket["consumed"] += 1
            if resp.get("action"):
                actions += 1
                bucket["actions"] += 1
    if broadcasts == 0 and consumed == 0:
        return {
            "status": "no_events",
            "m1_rate": None,
            "broadcasts": 0,
            "consumed": 0,
            "actions": 0,
        }
    return {
        "status": "ok",
        "broadcasts": broadcasts,
        "consumed": consumed,
        "actions": actions,
        "m1_rate": (actions / consumed) if consumed else None,
        "by_subscriber": by_subscriber,
    }
