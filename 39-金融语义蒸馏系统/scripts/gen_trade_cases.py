# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P-案例 阶段1：历史回填（SPEC §9.10，零 token）

将子交易系统真实开单记录（all_trades.jsonl）回填五维量变快照：
  - 每笔开单按 entry_time 前后时间窗（前 24h ~ 开单时刻）对齐原子事件流
  - 挂接五维快照：量维(放量/缩量) / 情维(极值状态) / 时维(盘整+周期) / 空维(斐波那契) / 频维(事件线量变信号)
  - 保留决策上下文与全生命周期结果（pnl/exit_reason 等）
  - 质量分级：A(快照+关键字段完整) / B(部分缺失) / C(关键字段缺失)

数据源：
  - 11-易经推理系统/.workbuddy/memory_l4/stats/all_trades.jsonl（真实交易记录）
  - atomic_events.jsonl（原子事件流，五维快照源）
  - event_lines.json（事件线，频维信号源）

产出: trade_cases.jsonl（覆盖式全量重建）
用法: /home/luke/venv-trading/bin/python3 gen_trade_cases.py
边界: 描述性记录与统计，不产生交易信号（SPEC §9.10.3）
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)

TRADES_PATH = os.path.join(_REPO, "11-易经推理系统", ".workbuddy", "memory_l4", "stats", "all_trades.jsonl")
ATOMIC_PATH = os.path.join(_SYS_DIR, "atomic_events.jsonl")
EVENT_LINES_PATH = os.path.join(_SYS_DIR, "event_lines.json")
OUT_PATH = os.path.join(_SYS_DIR, "trade_cases.jsonl")
STATE_PATH = os.path.join(_SYS_DIR, ".trade_cases_state.json")

SNAPSHOT_WINDOW_H = 24  # 快照窗口：开单前 24h 至开单时刻


def _parse_ts(ts):
    if not ts:
        return None
    t = str(ts).replace("Z", "").replace("T", " ")
    # 兼容毫秒时间戳
    if t.replace(".", "").isdigit() and len(t.split(".")[0]) >= 13:
        try:
            return datetime.fromtimestamp(int(float(t)) / 1000)
        except Exception:
            return None
    try:
        return datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def load_atomic_events():
    """加载原子事件流，按类别分组返回。"""
    dims = {"volume": [], "extreme": [], "time": [], "space": [], "cycle": []}
    try:
        with open(ATOMIC_PATH, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                t = _parse_ts(e.get("timestamp", ""))
                if t is None:
                    continue
                reasons = e.get("reasons", [])
                cat = e.get("category", "")
                item = {"ts": t, "reasons": reasons, "metric": e.get("metric", "")}
                if any(r.startswith("volume_") for r in reasons):
                    dims["volume"].append(item)
                elif any(r.startswith("extreme_") for r in reasons):
                    dims["extreme"].append(item)
                elif cat == "five_dim_time":
                    dims["time"].append(item)
                elif cat == "five_dim_space":
                    dims["space"].append(item)
                elif cat == "five_dim_cycle":
                    dims["cycle"].append(item)
    except FileNotFoundError:
        pass
    return dims


def load_freq_signals():
    """加载事件线频维信号（quantity_signal），返回 [(time_end, topic, signal)]。"""
    signals = []
    try:
        with open(EVENT_LINES_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        for l in d.get("lines", []):
            signals.append({
                "topic": l.get("topic"),
                "time_end": l.get("time_end", ""),
                "quantity_signal": l.get("quantity_signal", ""),
                "sentiment_trend": l.get("sentiment_trend", ""),
            })
    except Exception:
        pass
    return signals


def build_snapshot(entry_dt, dims, freq_signals):
    """按开单时刻构建五维快照（前 24h 窗口对齐）。"""
    if entry_dt is None:
        return None
    win_start = entry_dt - timedelta(hours=SNAPSHOT_WINDOW_H)

    def _in(ev):
        return win_start <= ev["ts"] <= entry_dt

    vol_in = [ev for ev in dims["volume"] if _in(ev)]
    ext_in = [ev for ev in dims["extreme"] if _in(ev)]
    time_in = [ev for ev in dims["time"] if _in(ev)]
    space_in = [ev for ev in dims["space"] if _in(ev)]

    # 情维状态：窗口内最近一条极值事件
    ext_state = None
    for ev in reversed(ext_in):
        for r in ev["reasons"]:
            if r.startswith(("extreme_persist", "extreme_enter")):
                ext_state = "极度恐慌持续" if "extreme_fear" in r else "极度贪婪持续"
                break
            if r.startswith("extreme_exit"):
                ext_state = "极值区间已退出"
                break
        if ext_state:
            break

    # 时维：窗口内盘整事件 + 周期距离
    consol = None
    for ev in reversed(time_in):
        if "breakout" in ev["metric"]:
            consol = "盘整后突破"
            break
        if "ongoing" in ev["metric"]:
            consol = "盘整进行中"
            break
    cycle_info = None
    for ev in reversed(dims["cycle"]):
        if ev["ts"] <= entry_dt:
            for r in ev["reasons"]:
                if r.startswith("cycle_halving_distance"):
                    cycle_info = r.split(":", 1)[1]
                    break
            if cycle_info:
                break

    # 空维：窗口内斐波那契触及
    fib = defaultdict(int)
    for ev in space_in:
        if ev["metric"].startswith("fib_touch_"):
            fib[ev["metric"].replace("fib_touch_", "")] += 1

    # 频维：开单时刻最近的事件线信号（时间端点在开单前 48h 内）
    freq = None
    for s in freq_signals:
        t_end = _parse_ts(s.get("time_end", ""))
        if t_end and entry_dt - timedelta(hours=48) <= t_end <= entry_dt:
            freq = {"topic": s["topic"], "quantity_signal": s["quantity_signal"]}
            break

    return {
        "window_hours": SNAPSHOT_WINDOW_H,
        "volume": {"surge": sum(1 for ev in vol_in if any(r.startswith("volume_surge") for r in ev["reasons"])),
                   "shrink": sum(1 for ev in vol_in if any(r.startswith("volume_shrink") for r in ev["reasons"]))},
        "sentiment": {"extreme_state": ext_state,
                      "events_in_window": len(ext_in)},
        "time": {"consolidation": consol, "halving_cycle": cycle_info},
        "space": {"fib_touches": dict(fib)},
        "freq": freq,
    }


def quality_grade(trade, snapshot):
    """质量分级：A 快照+关键字段完整 / B 部分缺失 / C 关键字段缺失。"""
    critical_ok = all(trade.get(k) not in (None, "", []) for k in ("direction", "pnl"))
    ctx_ok = bool(trade.get("contradiction_list")) and trade.get("hexagram") not in (None, "", "已存在持仓")
    snap_ok = snapshot is not None and (snapshot["sentiment"]["extreme_state"] is not None
                                        or snapshot["volume"]["surge"] + snapshot["volume"]["shrink"] > 0)
    if critical_ok and ctx_ok and snap_ok:
        return "A"
    if critical_ok:
        return "B"
    return "C"


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"processed_trade_ids": []}


def _save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def build_case(trade, dims, freq_signals):
    """单笔交易 → 案例记录（含子标签）。"""
    entry_dt = _parse_ts(trade.get("entry_time"))
    snapshot = build_snapshot(entry_dt, dims, freq_signals)
    grade = quality_grade(trade, snapshot)
    sub_tag = trade.get("source_tag") or "未标注"
    return {
        "layer": "molecular",
        "event_type": "trade_case",
        "trade_id": trade.get("trade_id"),
        "coin": trade.get("coin"),
        "direction": trade.get("direction"),
        "strategy_source": trade.get("strategy_source"),
        "sub_tag": sub_tag,
        "entry_time": trade.get("entry_time"),
        "exit_time": trade.get("exit_time"),
        "entry_price": trade.get("entry_price"),
        "exit_price": trade.get("exit_price"),
        "decision_context": {
            "confidence": trade.get("confidence"),
            "hexagram": trade.get("hexagram"),
            "contradiction_list": trade.get("contradiction_list"),
            "regime_pred": trade.get("regime_pred"),
            "market_snapshot": trade.get("market_snapshot"),
        },
        "five_dim_snapshot": snapshot,
        "result": {
            "pnl": trade.get("pnl"),
            "pnl_pct": trade.get("pnl_pct"),
            "exit_reason": trade.get("exit_reason"),
            "reduce_count": trade.get("reduce_count"),
        },
        "quality": grade,
        "boundary": "描述性案例记录（P-案例），不产生交易信号",
    }, grade


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="增量模式：只处理新交易（阶段3实时接入）")
    parser.add_argument("--rebuild", action="store_true", help="全量重建（默认）")
    args = parser.parse_args()

    dims = load_atomic_events()
    freq_signals = load_freq_signals()
    print(f"[OK] 原子事件加载: 量维 {len(dims['volume'])} / 情维 {len(dims['extreme'])} / "
          f"时维 {len(dims['time'])} / 空维 {len(dims['space'])} / 周期 {len(dims['cycle'])}")

    state = _load_state()
    processed = set(state.get("processed_trade_ids", []))

    cases = []
    grades = defaultdict(int)
    if not os.path.exists(TRADES_PATH):
        print(f"[WARN] 交易文件不存在，跳过本轮: {TRADES_PATH}")
        return
    with open(TRADES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                trade = json.loads(line)
            except Exception:
                continue
            tid = trade.get("trade_id")
            if args.live and tid in processed:
                continue
            case, grade = build_case(trade, dims, freq_signals)
            grades[grade] += 1
            cases.append(case)
            processed.add(tid)

    if args.live:
        # 增量追加（阶段3：新开单自动挂接快照）
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            for c in cases:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        _save_state({"processed_trade_ids": sorted(processed)})
        print(f"[OK] P-案例增量接入: 新增 {len(cases)} 条 → {OUT_PATH}")
        return

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    _save_state({"processed_trade_ids": sorted(processed)})

    print(f"[OK] P-案例历史回填完成: {len(cases)} 条 -> {OUT_PATH}")
    print(f"     质量分级: A {grades['A']} / B {grades['B']} / C {grades['C']}")
    # 方向×子系统×子标签分布预览
    dist = defaultdict(int)
    for c in cases:
        dist[f"{c['direction']}|{c['strategy_source']}|{c['sub_tag']}"] += 1
    for k, n in sorted(dist.items(), key=lambda kv: -kv[1])[:12]:
        print(f"     {k}: {n} 笔")


if __name__ == "__main__":
    main()
