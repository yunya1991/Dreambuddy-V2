#!/usr/bin/env python3
"""风险缓解机制模块（SPEC v0.7 关键风险缓解，供 P4 汇聚时统一应用）。

四项机制：
1. 数据新鲜度检查：产出物 generated_at 距今每超 24h，置信度降一档 + stale=true
2. 美林时钟失效降级：象限判定的输入数据（INDPRO/CPI）末端 6 期不足或 stale 时
   clock_degraded=true，策略建议降级为观望
3. FOMC/CPI ±2 日事件窗口状态冻结：事件日前后 2 日内 state_frozen=true，
   不更新周期判定（数据不足时 fail-open 不冻结）
4. 末端 6 期低置信：数据序列末端 6 期（初值/修正期）标记 low_confidence_tail=true

fail-open：本模块任何异常不阻断主流程，仅记录 guard_errors。
"""
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta

DB = "/home/luke/dreambuddy/18-数据获取中心/data_center.db"

CONFIDENCE_LADDER = ["high", "medium", "low"]


def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(ts):
    """解析 ISO 时间戳（容忍 Z 后缀与无时区）。"""
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def degrade_confidence(level, n_steps):
    """置信度降档：high→medium→low，最多降到底。"""
    if level not in CONFIDENCE_LADDER:
        return level
    i = CONFIDENCE_LADDER.index(level) + max(0, int(n_steps))
    return CONFIDENCE_LADDER[min(i, len(CONFIDENCE_LADDER) - 1)]


def check_freshness(artifacts, max_age_hours=48):
    """机制1：产出物新鲜度检查。每超 24h 置信度降一档，超 48h 标记 stale。
    artifacts: {name: generated_at_iso}
    返回 {name: {age_hours, degrade_steps, stale}}
    """
    result = {}
    now = now_utc()
    for name, ts in (artifacts or {}).items():
        dt = parse_ts(ts)
        if dt is None:
            result[name] = {"age_hours": None, "degrade_steps": 0, "stale": True,
                            "note": "时间戳缺失，按 stale 处理"}
            continue
        age_h = (now - dt).total_seconds() / 3600.0
        degrade = int(age_h // 24)
        result[name] = {
            "age_hours": round(age_h, 1),
            "degrade_steps": degrade,
            "stale": age_h > max_age_hours,
        }
    return result


def check_event_window(db_path=DB, window_days=2):
    """机制3：FOMC/CPI 事件 ±2 日窗口检查。
    数据源：cme/fomc_decision 与 econ_calendar/cpi 的最近事件时间戳。
    返回 {in_window, event, event_ts, days_to_event}；数据不足 fail-open 不冻结。
    """
    try:
        conn = sqlite3.connect(db_path)
        now = now_utc()
        for source, sub, label in (("cme", "fomc_decision", "FOMC"),
                                   ("econ_calendar", "cpi", "CPI")):
            rows = conn.execute(
                "SELECT timestamp FROM records WHERE source=? AND sub_category=? "
                "ORDER BY timestamp DESC LIMIT 5", (source, sub)).fetchall()
            for (ts,) in rows:
                dt = parse_ts(ts)
                if dt is None:
                    continue
                delta_days = (dt - now).total_seconds() / 86400.0
                if abs(delta_days) <= window_days:
                    conn.close()
                    return {"in_window": True, "event": label,
                            "event_ts": ts, "days_to_event": round(delta_days, 2),
                            "note": "事件窗口内状态冻结，不更新周期判定"}
        conn.close()
    except Exception:
        pass
    return {"in_window": False, "note": "无临近事件或数据不足（fail-open 不冻结）"}


def check_clock_degradation(rotation, freshness):
    """机制2：美林时钟失效降级。
    触发：asset_rotation 数据 stale 或覆盖不足（indpro/cpi 序列末端 6 期缺口）。
    返回 {clock_degraded, reason}
    """
    reasons = []
    ar_fresh = freshness.get("asset_rotation", {})
    if ar_fresh.get("stale"):
        reasons.append("asset_rotation 数据 stale")
    coverage = (rotation or {}).get("data_coverage", {})
    for key in ("indpro", "cpi"):
        n = coverage.get(key, 0)
        if n and n < 6:
            reasons.append(f"{key} 序列仅 {n} 期（<6）")
    return {"clock_degraded": bool(reasons), "reasons": reasons}


def check_tail_confidence(db_path=DB, series=("INDPRO", "CPIAUCSL"), tail_n=6):
    """机制4：末端 6 期低置信标记（初值/修正期）。
    返回 {series: {tail_points, low_confidence_tail}}
    """
    result = {}
    try:
        conn = sqlite3.connect(db_path)
        for s in series:
            n = conn.execute(
                "SELECT COUNT(*) FROM records WHERE source='fred' AND sub_category=?",
                (s,)).fetchone()[0]
            result[s] = {"tail_points": min(n, tail_n),
                         "low_confidence_tail": n >= tail_n,
                         "note": "末端 6 期为初值/修正期，置信度降权" if n >= tail_n else "序列不足 6 期"}
        conn.close()
    except Exception as e:
        result["error"] = str(e)
    return result


def apply_guards(cycle, rotation, transmission, stovall, fund_flow, washout):
    """P4 汇聚点统一应用四项机制。返回 guards 汇总与降级后的置信度。"""
    guards = {"generated_at": now_utc().isoformat(), "guard_errors": []}
    try:
        artifacts = {
            "cycle_state": (cycle or {}).get("generated_at"),
            "asset_rotation": (rotation or {}).get("generated_at"),
            "sector_transmission": (transmission or {}).get("generated_at"),
            "stovall_breadth": (stovall or {}).get("generated_at"),
            "fund_flow": (fund_flow or {}).get("generated_at"),
            "washout_verdicts": (washout or {}).get("generated_at"),
        }
        guards["freshness"] = check_freshness(artifacts)
    except Exception as e:
        guards["guard_errors"].append(f"freshness: {e}")

    try:
        guards["event_window"] = check_event_window()
    except Exception as e:
        guards["guard_errors"].append(f"event_window: {e}")

    try:
        guards["clock_degradation"] = check_clock_degradation(
            rotation, guards.get("freshness", {}))
    except Exception as e:
        guards["guard_errors"].append(f"clock_degradation: {e}")

    try:
        guards["tail_confidence"] = check_tail_confidence()
    except Exception as e:
        guards["guard_errors"].append(f"tail_confidence: {e}")

    # 置信度综合降级：象限置信度 + 最陈旧产出物的降档数
    base_conf = (rotation or {}).get("merrill_clock", {}).get("confidence", "medium")
    max_degrade = 0
    for v in guards.get("freshness", {}).values():
        max_degrade = max(max_degrade, v.get("degrade_steps", 0))
    guards["effective_confidence"] = degrade_confidence(base_conf, max_degrade)
    guards["confidence_degrade_steps"] = max_degrade
    return guards


if __name__ == "__main__":
    # 自测：直接读产出物跑一遍
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _load(n):
        p = os.path.join(ROOT, n)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        return {}

    g = apply_guards(_load("cycle_state.json"), _load("asset_rotation.json"),
                     _load("sector_transmission.json"), _load("stovall_breadth.json"),
                     _load("fund_flow.json"), _load("washout_verdicts.json"))
    print(json.dumps(g, ensure_ascii=False, indent=2))
