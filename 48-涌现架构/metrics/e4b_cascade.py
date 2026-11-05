"""e4b_cascade.py — E4b 埋点②：跨模块事件级联 σ（SPEC v0.5 §4 E4b）。

数据源：E1 shadow 总线日志 `48-涌现架构/events/emergence_shadow/bus_*.jsonl`（点火事件）
+ `resp_*.jsonl`（订阅者响应）。零新增埋点，复用 E1 既有事件流。

口径（与 §1 E5(b) 临界态三件套对齐，此处只出级联侧两件）：
  - cascade_size：单个点火事件的消费订阅者数（consumed=True）
  - sigma（分支系数）：总消费数 / 总点火事件数（σ≈1 = 临界）
  - 级联尺寸分布近幂律：对 size 分布做 log-log 最小二乘斜率（样本不足如实 null）
  - near_sigma_1：σ ∈ [0.8, 1.25] 判临界带（保守带，非精确判定）

样本门槛：点火事件 < min_events 时 status=insufficient_data（如实，不拿 1 个事件说事）。

FAIL-OPEN：IO/解析异常 → no_data。
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHADOW_DIR = _REPO_ROOT / "48-涌现架构" / "events" / "emergence_shadow"
MIN_EVENTS = 20
MIN_POWERLAW_POINTS = 5
SIGMA_CRITICAL_BAND = (0.8, 1.25)


def _load(paths: Sequence[Path]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
            logger.warning("cascade 日志读取失败（跳过 %s）: %s", p.name, exc)
    return out


def _default_paths(prefix: str) -> List[Path]:
    if not _SHADOW_DIR.exists():
        return []
    return sorted(_SHADOW_DIR.glob(f"{prefix}_*.jsonl"))


def _powerlaw_slope(sizes: List[int]) -> Optional[float]:
    """size 分布 log-log 斜率（负值=近幂律递减）。样本不足/退化 → None。"""
    if len(sizes) < MIN_POWERLAW_POINTS:
        return None
    counts: Dict[int, int] = {}
    for s in sizes:
        if s > 0:
            counts[s] = counts.get(s, 0) + 1
    if len(counts) < 2:
        return None
    xs = [math.log(k) for k in counts]
    ys = [math.log(v) for v in counts.values()]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom < 1e-12:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / denom


def compute_cascade(
    bus_paths: Optional[Sequence[Path]] = None,
    resp_paths: Optional[Sequence[Path]] = None,
    min_events: int = MIN_EVENTS,
) -> Dict[str, Any]:
    """计算级联尺寸分布 + 分支系数 σ。"""
    try:
        bus = _load(list(bus_paths) if bus_paths else _default_paths("bus"))
        resp = _load(list(resp_paths) if resp_paths else _default_paths("resp"))
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("compute_cascade FAIL-OPEN: %s", exc)
        return {"value": None, "status": "no_data", "note": str(exc)}

    ignited = [e for e in bus if e.get("ignited") is True]
    if not ignited:
        return {
            "value": None,
            "status": "no_data",
            "note": "无点火事件（E1 shadow 未跑或未点火）",
        }

    consumed_by_event: Dict[str, int] = {}
    actions_by_event: Dict[str, int] = {}
    for r in resp:
        if r.get("consumed"):
            eid = r.get("event_id")
            consumed_by_event[eid] = consumed_by_event.get(eid, 0) + 1
        if r.get("action"):
            eid = r.get("event_id")
            actions_by_event[eid] = actions_by_event.get(eid, 0) + 1

    sizes = [consumed_by_event.get(e.get("event_id"), 0) for e in ignited]
    total_consumed = sum(sizes)
    total_actions = sum(actions_by_event.values())
    sigma = total_consumed / len(ignited)
    slope = _powerlaw_slope(sizes)
    lo, hi = SIGMA_CRITICAL_BAND

    value = {
        "n_events": len(ignited),
        "n_consumed": total_consumed,
        "total_actions": total_actions,
        "sigma": sigma,
        "cascade_sizes": {
            "mean": total_consumed / len(ignited),
            "max": max(sizes),
            "min": min(sizes),
            "n_zero": sum(1 for s in sizes if s == 0),
        },
        "powerlaw_slope": slope,
        "near_sigma_1": lo <= sigma <= hi,
        "sigma_critical_band": [lo, hi],
    }
    status = "ok" if len(ignited) >= min_events else "insufficient_data"
    note = (
        "复用 E1 shadow 总线事件流；样本不足（<min_events）时不申报临界态"
        if status != "ok"
        else "级联侧两件（σ+尺寸分布）；序参量凝结信号待 E5(b) 独立埋点"
    )
    return {"value": value, "status": status, "note": note}


def main() -> int:
    res = compute_cascade()
    print(
        f"E4b cascade: status={res['status']} value={json.dumps(res['value'], ensure_ascii=False)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
