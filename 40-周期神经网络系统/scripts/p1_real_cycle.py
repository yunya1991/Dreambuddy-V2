#!/usr/bin/env python3
"""P1 周期判定模块 — 真实周期状态机 v1.1
v1.1 修复：flat 分支补上去抖动切换 plateau；新增渐进趋势检测
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone

DB = "/home/luke/dreambuddy/18-数据获取中心/data_center.db"
OUT = "/home/luke/dreambuddy/40-周期神经网络系统/cycle_state.json"

PLATEAU_BAND = 0.25
CONFIRM_N = 2
GRAD_ACCUM = 0.5

def load_fedfunds():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT timestamp, json_extract(metrics, ?) FROM records WHERE source = ? AND sub_category = ? ORDER BY timestamp",
        ("$.value", "fred", "FEDFUNDS"),
    ).fetchall()
    conn.close()
    return [(r[0][:7], float(r[1])) for r in rows if r[1] is not None]

def classify_change(cur, prev):
    d = cur - prev
    if d > PLATEAU_BAND:
        return "hike"
    if d < -PLATEAU_BAND:
        return "cut"
    return "flat"

def run_state_machine(series):
    states = []
    state = "init"
    pending = 0
    pending_dir = None
    grad_sign = 0
    grad_accum = 0.0
    for i in range(1, len(series)):
        prev = series[i - 1][1]
        ts, cur = series[i]
        d = cur - prev
        chg = classify_change(cur, prev)
        if chg == "flat":
            target = "plateau"
        else:
            target = "hiking" if chg == "hike" else "cutting"
        if chg == "flat":
            s = 1 if d > 0 else (-1 if d < 0 else 0)
            if s != 0 and s == grad_sign:
                grad_accum += abs(d)
            else:
                grad_sign = s
                grad_accum = abs(d) if s != 0 else 0.0
            if grad_sign != 0 and grad_accum > GRAD_ACCUM:
                target = "hiking" if grad_sign > 0 else "cutting"
                chg = "hike" if grad_sign > 0 else "cut"
                grad_sign, grad_accum = 0, 0.0
        else:
            grad_sign, grad_accum = 0, 0.0
        if target == state:
            pending = 0
            pending_dir = None
        elif chg == pending_dir:
            pending += 1
        else:
            pending = 1
            pending_dir = chg
        if pending >= CONFIRM_N and state != target:
            state = target
            pending = 0
            pending_dir = None
        states.append({"month": ts, "rate": cur, "change": chg, "state": state})
    return states

def main():
    series = load_fedfunds()
    if len(series) < 3:
        raise SystemExit("FEDFUNDS 数据不足")
    states = run_state_machine(series)
    cur = states[-1]
    recent = [s["state"] for s in states[-12:]]
    dist = {k: recent.count(k) for k in ("hiking", "cutting", "plateau")}
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "real_cycle": {
            "anchor": "FEDFUNDS",
            "current_month": cur["month"],
            "current_rate": cur["rate"],
            "state": cur["state"],
            "last_change": cur["change"],
            "recent_12m_distribution": dist,
            "confidence": "high" if dist[cur["state"]] >= 8 else ("medium" if dist[cur["state"]] >= 5 else "low"),
        },
        "params": {"plateau_band": PLATEAU_BAND, "confirm_n": CONFIRM_N, "grad_accum": GRAD_ACCUM},
        "data_coverage": {"records": len(series), "first": series[0][0], "last": series[-1][0]},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out["real_cycle"], ensure_ascii=False))
    print("saved:", OUT)

if __name__ == "__main__":
    main()
