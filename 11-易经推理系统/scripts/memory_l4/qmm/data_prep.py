"""数据准备：从 L4 cases/distills 提取并清洗时间序列特征。"""

import statistics
from typing import Any, Dict, List, Optional

from .types import CleanedEvent


def prepare_events(
    cases: List[Dict[str, Any]],
    distills: List[Dict[str, Any]],  # noqa: ARG001 — 预留
) -> List[CleanedEvent]:
    """主入口：提取 + 排序 + 异常值检测 + 质量评分。"""
    events: List[CleanedEvent] = []
    for c in cases:
        ev = _extract_event(c)
        if ev:
            events.append(ev)

    # 时间排序
    events.sort(key=lambda e: e.ts)

    # 异常值检测（IQR）
    events = _detect_outliers(events)

    # 质量评分
    for ev in events:
        ev.quality = _compute_quality(ev)

    return events


def _extract_event(case: Dict[str, Any]) -> Optional[CleanedEvent]:
    """从单个 TradeCase 提取事件。"""
    do = case.get("decision_outcome") or {}
    if not isinstance(do, dict):
        do = {}
    ao = case.get("actual_outcome") or {}
    if not isinstance(ao, dict):
        ao = {}
    q = case.get("quadrant") or {}
    if not isinstance(q, dict):
        q = {}
    env = case.get("environment_snapshot") or {}
    if not isinstance(env, dict):
        env = {}

    # pnl_pct: 优先 decision_outcome, 其次 actual_outcome
    pnl = do.get("pnl_pct")
    if pnl is None:
        pnl = ao.get("pnl_pct")
    if pnl is None:
        pnl = do.get("pnl")
    if pnl is None:
        pnl = ao.get("pnl")

    # 象限: 优先 quadrant 字段, 否则从 pnl + direction 推算
    x_val = float(q.get("x", 0)) if isinstance(q, dict) and q.get("x") is not None else None
    y_val = float(q.get("y", 0)) if isinstance(q, dict) and q.get("y") is not None else None

    if x_val is None:
        # 从 pnl_pct 和 direction 推算象限
        direction = case.get("direction", "")
        if pnl is not None:
            x_val = 1.0 if pnl > 0 else (-1.0 if pnl < 0 else 0.0)
        elif direction:
            x_val = 1.0 if direction in ("long", "up", "LONG", "UP") else (
                -1.0 if direction in ("short", "down", "SHORT", "DOWN") else 0.0)
        else:
            x_val = 0.0

    if y_val is None:
        # 从 is_correct + confidence 推算
        is_correct = do.get("is_correct", ao.get("is_correct"))
        if is_correct is not None:
            y_val = 0.7 if is_correct else 0.3
        else:
            y_val = 0.5

    # regime: 优先 environment_snapshot, 其次从 liangyi_state 推断
    regime = env.get("regime") if isinstance(env, dict) else None
    if not regime or regime == "unknown":
        ly = case.get("liangyi_state", {})
        if not isinstance(ly, dict):
            ly = {}
        macro = ly.get("macro_phase", "")
        micro = ly.get("micro_phase", "")
        regime = f"{macro}|{micro}" if macro and micro else "unknown"

    return CleanedEvent(
        event_id=case.get("case_id", ""),
        ts=case.get("ts_start", case.get("ts", "")),
        regime=regime,
        quadrant_x=x_val,
        quadrant_y=y_val,
        pnl_pct=float(pnl) if pnl is not None else None,
        is_profit=(pnl > 0) if pnl is not None else None,
        severity=_compute_severity(pnl, (do.get("drawdown") if isinstance(do, dict) else None) or (ao.get("drawdown") if isinstance(ao, dict) else None)),
        quality=0.0,
        clean_flags=[],
    )


def _compute_severity(pnl: Optional[float], drawdown: Optional[float]) -> Optional[float]:
    """从 pnl 和 drawdown 计算影响程度。"""
    if pnl is None:
        return None
    if drawdown and drawdown > 0:
        return round(abs(pnl) / (drawdown + 0.001), 4)
    return round(abs(pnl), 4)


def _detect_outliers(events: List[CleanedEvent]) -> List[CleanedEvent]:
    """IQR 异常值检测，标记但不剔除。"""
    pnls = [e.pnl_pct for e in events if e.pnl_pct is not None]
    if len(pnls) < 4:
        return events

    q1 = _percentile(pnls, 25)
    q3 = _percentile(pnls, 75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    for ev in events:
        if ev.pnl_pct is not None and (ev.pnl_pct < lower or ev.pnl_pct > upper):
            ev.clean_flags.append("OUTLIER_PNL")

    return events


def _percentile(data: List[float], pct: int) -> float:
    """计算百分位数。"""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100.0
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


def _compute_quality(ev: CleanedEvent) -> float:
    """质量评分：completeness + recency。

    completeness = 非空字段数 / 总字段数
    recency = exp(-days_since_event / 90)  -- 与 L4 90 天半衰期一致
    """
    from datetime import datetime, timezone

    # 完整性
    fields = [ev.event_id, ev.ts, ev.regime, ev.pnl_pct, ev.severity]
    non_null = sum(1 for f in fields if f is not None and f != "")
    completeness = non_null / max(len(fields), 1)

    # 近期性
    try:
        ts = datetime.fromisoformat(ev.ts)
        now = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        days_old = max(0, (now - ts).total_seconds() / 86400)
        recency = __import__("math").exp(-days_old / 90)
    except (ValueError, TypeError):
        recency = 0.0

    return round(0.4 * completeness + 0.3 * 1.0 + 0.3 * recency, 4)


def _compute_data_version(cases: List[Dict[str, Any]]) -> str:
    """生成 data_version: dv-{YYYYMMDD}-{N}。"""
    from datetime import datetime, timezone
    import json

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")

    from .paths import qmm_dir

    out_dir = qmm_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "data_version_state.json"

    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}

    prev_date = state.get("date")
    prev_seq = state.get("seq")
    if prev_date == date_str and isinstance(prev_seq, int) and prev_seq > 0:
        seq = prev_seq + 1
    else:
        seq = 1

    data_version = f"dv-{date_str}-{seq:03d}"
    state_path.write_text(
        json.dumps({"date": date_str, "seq": seq, "data_version": data_version}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data_version
