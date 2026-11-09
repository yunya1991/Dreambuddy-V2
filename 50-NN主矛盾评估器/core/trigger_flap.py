"""M4-7: trigger 防振荡（trigger_flap 防护）。

同一标的 4h 内 trigger 切换 ≤ 2 次；超出则锁定为上一 profile 并审计。

状态持久化到 50/runtime/trigger_flap.jsonl（每条记录一次 trigger 决策）。
fail-open：任何 IO/解析异常 → 不锁定，放行当前 trigger。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_FLAP_PATH = Path(__file__).resolve().parents[1] / "runtime" / "trigger_flap.jsonl"

# SPEC-M3 §三.4：4h 窗口内最多 2 次切换
FLAP_WINDOW_HOURS = 4.0
FLAP_MAX_SWITCHES = 2


@dataclass
class FlapDecision:
    """trigger 防振荡裁决结果。"""

    trigger: str  # 最终采用的 trigger（可能被锁定为上一值）
    locked: bool  # 是否因振荡被锁定
    switches_in_window: int  # 窗口内切换次数
    reason: str  # 裁决原因


def _load_records() -> list[dict]:
    if not _FLAP_PATH.exists():
        return []
    records: list[dict] = []
    try:
        with open(_FLAP_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:  # noqa: BLE001
        return []
    return records


def _append_record(record: dict) -> None:
    try:
        _FLAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_FLAP_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def check_trigger_flap(
    symbol: str,
    proposed_trigger: str,
    now: datetime | None = None,
) -> FlapDecision:
    """检查 proposed_trigger 是否触发振荡防护。

    返回 FlapDecision：若窗口内切换次数超限，locked=True 且 trigger=上一值。
    """
    moment = now or datetime.now(timezone.utc)
    window_start = moment - timedelta(hours=FLAP_WINDOW_HOURS)

    records = _load_records()
    # 取该标的窗口内的记录
    sym_records = [r for r in records if r.get("symbol") == symbol]

    # 按 ts 排序
    def _ts(r):
        try:
            return datetime.fromisoformat(str(r.get("ts", "")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    sym_records = [r for r in sym_records if _ts(r) is not None]
    sym_records.sort(key=_ts)

    # 统计窗口内的 trigger 切换次数
    window_records = [r for r in sym_records if _ts(r) >= window_start]  # type: ignore[arg-type]
    switches = 0
    prev_trigger = None
    for r in window_records:
        t = r.get("adopted_trigger") or r.get("trigger")
        if prev_trigger is not None and t != prev_trigger:
            switches += 1
        prev_trigger = t

    # 上一次采用的 trigger（窗口内最后一条，或全量最后一条）
    last_trigger = None
    if sym_records:
        last_trigger = sym_records[-1].get("adopted_trigger") or sym_records[-1].get("trigger")

    locked = False
    final_trigger = proposed_trigger
    reason = "within_limit"

    if switches > FLAP_MAX_SWITCHES and last_trigger is not None:
        # 超出阈值：锁定为上一 profile
        locked = True
        final_trigger = last_trigger
        reason = f"flap_locked: {switches} switches in {FLAP_WINDOW_HOURS}h window"

    # 记录本次裁决（fail-open）
    _append_record(
        {
            "ts": moment.isoformat(),
            "symbol": symbol,
            "proposed_trigger": proposed_trigger,
            "adopted_trigger": final_trigger,
            "locked": locked,
            "switches_in_window": switches,
            "reason": reason,
        }
    )

    return FlapDecision(
        trigger=final_trigger,
        locked=locked,
        switches_in_window=switches,
        reason=reason,
    )
