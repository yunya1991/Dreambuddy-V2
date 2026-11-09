"""历史事件库存储层 — SPEC-D1-NARRATIVE-PRIMITIVES §2.4 + D3 硬要求。

事件 schema：
  {event_id, event_type, asset_scope, trigger_ts, ts_onchain_visible,
   unlock_pct_supply, ts_precision, market_state, reaction, source, attribution}

D3 硬要求（调研报告实证锚点）：
  - ts_onchain_visible：最早公开可见时间（hack 类 36% 跌幅在公告前）
  - unlock_pct_supply：解锁类必填（>5% 流通盘才统计显著）

存储：JSONL（shadow/FAIL-OPEN，不动 PG/SQLite 既有表）。
event_id 幂等去重。全部写操作先过 validate_event。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("data_center.processing.event_store")

REQUIRED_FIELDS = [
    "event_id",
    "event_type",
    "asset_scope",
    "trigger_ts",
    "ts_precision",
    "market_state",
    "reaction",
    "source",
    "attribution",
]

_VALID_TS_PRECISION = {"day", "second"}
_VALID_ATTRIBUTION = {"strong", "weak"}


def validate_event(ev: Any) -> list[str]:
    """返回错误列表；空列表 = 合法。"""
    errs: list[str] = []
    if not isinstance(ev, dict):
        return ["event not a dict"]

    for f in REQUIRED_FIELDS:
        if f not in ev:
            errs.append(f"missing required field: {f}")

    ts = ev.get("trigger_ts")
    if "trigger_ts" in ev and not isinstance(ts, (int, float)):
        errs.append("trigger_ts must be numeric epoch")

    tsv = ev.get("ts_onchain_visible")
    if tsv is not None and not isinstance(tsv, (int, float)):
        errs.append("ts_onchain_visible must be numeric epoch or None")

    if ev.get("ts_precision") not in _VALID_TS_PRECISION and "ts_precision" in ev:
        errs.append(f"ts_precision must be one of {_VALID_TS_PRECISION}")

    if ev.get("attribution") not in _VALID_ATTRIBUTION and "attribution" in ev:
        errs.append(f"attribution must be one of {_VALID_ATTRIBUTION}")

    etype = str(ev.get("event_type", ""))
    if etype.startswith("unlock"):
        ups = ev.get("unlock_pct_supply")
        if not isinstance(ups, (int, float)) or ups <= 0:
            errs.append("unlock_pct_supply required (>0) for unlock events")

    if "asset_scope" in ev and not isinstance(ev["asset_scope"], list):
        errs.append("asset_scope must be list")

    if "reaction" in ev and not isinstance(ev["reaction"], dict):
        errs.append("reaction must be dict")

    return errs


class EventStore:
    """JSONL 事件库（幂等追加 + 全量读取）。FAIL-OPEN。"""

    def __init__(self, path: Any):
        self.path = Path(path)

    def add(self, ev: Any) -> bool:
        """校验 + 幂等落盘。失败返回 False，不抛。"""
        try:
            errs = validate_event(ev)
            if errs:
                logger.warning(
                    "[FAIL-OPEN] 事件校验失败 %s: %s",
                    ev.get("event_id") if isinstance(ev, dict) else "?",
                    errs,
                )
                return False
            existing = {e.get("event_id") for e in self.load()}
            if ev["event_id"] in existing:
                return True  # 幂等：已存在视为成功
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            return True
        except Exception as e:  # noqa: BLE003
            logger.warning(
                "[FAIL-OPEN] event_store.add 异常 %s: %s", type(e).__name__, str(e)[:200]
            )
            return False

    def load(self) -> list[dict]:
        """全量读取。文件不存在/坏行跳过。FAIL-OPEN。"""
        try:
            if not self.path.exists():
                return []
            out = []
            for line in self.path.open(encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
            return out
        except Exception as e:  # noqa: BLE003
            logger.warning(
                "[FAIL-OPEN] event_store.load 异常 %s: %s", type(e).__name__, str(e)[:200]
            )
            return []
