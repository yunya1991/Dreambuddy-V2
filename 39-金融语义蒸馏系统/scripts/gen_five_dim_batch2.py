# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · §9.8 五维量变观测 第二批（零 token）

时维：盘整区间检测（『横有多长竖有多高』：盘整时长→突破幅度预期）
空维：斐波那契回撤/扩展关键位触及检测
时维：四年周期（减半节律）静态配置与距离观测

数据源：18 中心 PostgreSQL records 表 BTC/USDT（每小时 OHLC：high/low/last）
产出：atomic_events.jsonl 追加新原子事件类型（变化驱动，描述性观察）：
n  - consolidation_enter / consolidation_exit / consolidation_breakout（盘整进入/退出/突破）
  - fib_touch:0.382/0.5/0.618（斐波那契关键位触及）
  - cycle_halving_distance（四年周期距离观测，每日一条）

边界：全部为描述性观察，不做方向判断，不产生交易信号。
用法: /home/luke/venv-trading/bin/python3 gen_five_dim_batch2.py [--backfill]
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
sys.path.insert(0, _THIS_DIR)
import dc_pg

OUT_PATH = os.path.join(_SYS_DIR, "atomic_events.jsonl")
STATE_PATH = os.path.join(_SYS_DIR, ".five_dim_batch2_state.json")

# ── 盘整检测参数（预注册阈值，禁止事后调整）──
CONSOL_WINDOW = 72        # 盘整观察窗口：72 根小时线
CONSOL_RANGE_MAX = 0.06   # 窗口内振幅（high-low)/mid <= 6% 判定盘整
CONSOL_MIN_HOURS = 24     # 持续 >= 24h 才记录盘整事件
# ── 斐波那契参数 ──
FIB_SWING_LOOKBACK = 240  # 摆动高低点回看窗口：240 根小时线（10 天）
FIB_LEVELS = [0.382, 0.5, 0.618]
FIB_TOLERANCE = 0.003    # 触及容差：价格距关键位 0.3% 以内判定触及
# ── 四年周期（减半节律，静态配置）──
HALVING_DATES = ["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20"]
CYCLE_YEARS = 4


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_ts": ""}


def _save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def load_candles(limit=600):
    """加载 BTC/USDT 小时线（升序），返回 [{ts, high, low, last}]。"""
    rows = dc_pg.fetch_records("BTC/USDT", limit=limit, order_desc=False)
    candles = []
    for r in rows:
        m = r.get("metrics") or {}
        high, low, last = m.get("high"), m.get("low"), m.get("last")
        if not all(isinstance(v, (int, float)) for v in (high, low, last)):
            continue
        candles.append({"ts": r["timestamp"], "high": float(high), "low": float(low), "last": float(last)})
    return candles


def detect_consolidation(candles):
    """盘整区间检测：滑窗振幅压缩 → 盘整进入/退出/突破（描述性）。"""
    events = []
    in_consolidation = False
    consol_start = None
    for i in range(CONSOL_WINDOW, len(candles)):
        window = candles[i - CONSOL_WINDOW:i]
        hi = max(c["high"] for c in window)
        lo = min(c["low"] for c in window)
        mid = (hi + lo) / 2
        amp = (hi - lo) / mid if mid > 0 else 0.0
        c = candles[i]
        if not in_consolidation:
            if amp <= CONSOL_RANGE_MAX:
                in_consolidation = True
                consol_start = window[0]["ts"]
        else:
            # 盘整中：价格突破窗口边界 → 突破事件（记录方向幅度，不做方向判断）
            if c["last"] > hi:
                events.append({
                    "layer": "atomic", "category": "five_dim_time",
                    "metric": "consolidation_breakout",
                    "timestamp": c["ts"], "value": c["last"],
                    "prev_value": hi,
                    "reasons": [f"consolidation_breakout:up:amp={amp:.1%}:span_h={CONSOL_WINDOW}"],
                    "source": "five_dim_batch2",
                })
                in_consolidation = False
            elif c["last"] < lo:
                events.append({
                    "layer": "atomic", "category": "five_dim_time",
                    "metric": "consolidation_breakout",
                    "timestamp": c["ts"], "value": c["last"],
                    "prev_value": lo,
                    "reasons": [f"consolidation_breakout:down:amp={amp:.1%}:span_h={CONSOL_WINDOW}"],
                    "source": "five_dim_batch2",
                })
                in_consolidation = False
            elif amp > CONSOL_RANGE_MAX * 1.5:
                # 振幅重新放大 → 盘整退出（未突破）
                events.append({
                    "layer": "atomic", "category": "five_dim_time",
                    "metric": "consolidation_exit",
                    "timestamp": c["ts"], "value": round(amp, 4),
                    "prev_value": CONSOL_RANGE_MAX,
                    "reasons": [f"consolidation_exit:amp={amp:.1%}:span_h={CONSOL_WINDOW}"],
                    "source": "five_dim_batch2",
                })
                in_consolidation = False
    # 尾部仍在盘整 → 记录进行中事件
    if in_consolidation and consol_start:
        events.append({
            "layer": "atomic", "category": "five_dim_time",
            "metric": "consolidation_ongoing",
            "timestamp": candles[-1]["ts"], "value": CONSOL_WINDOW,
            "prev_value": None,
            "reasons": [f"consolidation_ongoing:since={consol_start}:span_h>={CONSOL_WINDOW}"],
            "source": "five_dim_batch2",
        })
    return events


def detect_fibonacci(candles):
    """斐波那契回撤位触及检测：摆动高低点 → 关键位触及事件（描述性）。"""
    events = []
    last_touch = None
    for i in range(FIB_SWING_LOOKBACK, len(candles)):
        window = candles[i - FIB_SWING_LOOKBACK:i]
        swing_hi = max(c["high"] for c in window)
        swing_lo = min(c["low"] for c in window)
        span = swing_hi - swing_lo
        if span <= 0:
            continue
        c = candles[i]
        for lvl in FIB_LEVELS:
            fib_price = swing_hi - span * lvl
            if abs(c["last"] - fib_price) / fib_price <= FIB_TOLERANCE:
                key = (c["ts"][:13], lvl)  # 同一小时同级别只记一次
                if key == last_touch:
                    continue
                events.append({
                    "layer": "atomic", "category": "five_dim_space",
                    "metric": f"fib_touch_{lvl}",
                    "timestamp": c["ts"], "value": c["last"],
                    "prev_value": round(fib_price, 2),
                    "reasons": [f"fib_touch:{lvl}:swing=[{swing_lo:.0f},{swing_hi:.0f}]"],
                    "source": "five_dim_batch2",
                })
                last_touch = key
    return events


def detect_cycle(candles):
    """四年周期（减半节律）距离观测：每日一条描述性距离事件。"""
    events = []
    halvings = [datetime.fromisoformat(d) for d in HALVING_DATES]
    last_day = None
    for c in candles:
        day = c["ts"][:10]
        if day == last_day:
            continue
        last_day = day
        try:
            now = datetime.fromisoformat(day)
        except ValueError:
            continue
        past = [h for h in halvings if h <= now]
        if not past:
            continue
        last_halving = past[-1]
        days_since = (now - last_halving).days
        # 距下次预期减半（上次减半 + 4 年，近似 1458 天）
        days_to_next = round(CYCLE_YEARS * 365.25) - days_since
        events.append({
            "layer": "atomic", "category": "five_dim_cycle",
            "metric": "halving_cycle_distance",
            "timestamp": c["ts"], "value": days_since,
            "prev_value": days_to_next,
            "reasons": [f"cycle_halving_distance:since={last_halving.date()}:days={days_since}:to_next~{days_to_next}"],
            "source": "five_dim_batch2",
        })
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="全量重算（默认增量：只处理新数据）")
    args = parser.parse_args()

    candles = load_candles()
    if len(candles) < CONSOL_WINDOW + 10:
        print(f"[WARN] K 线数据不足（{len(candles)} 条），跳过")
        return
    print(f"[OK] 加载 BTC/USDT 小时线 {len(candles)} 条（{candles[0]['ts'][:16]} ~ {candles[-1]['ts'][:16]}）")

    state = _load_state()
    last_ts = "" if args.backfill else state.get("last_ts", "")

    events = []
    events += detect_consolidation(candles)
    events += detect_fibonacci(candles)
    events += detect_cycle(candles)

    # 增量过滤：只保留 last_ts 之后的新事件
    if last_ts:
        events = [e for e in events if e["timestamp"] > last_ts]

    if events:
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    if candles:
        _save_state({"last_ts": candles[-1]["ts"]})

    print(f"[OK] 第二批五维事件产出 {len(events)} 条 → {OUT_PATH}")
    by_metric = {}
    for e in events:
        k = e["metric"]
        by_metric[k] = by_metric.get(k, 0) + 1
    for k, n in sorted(by_metric.items(), key=lambda kv: -kv[1]):
        print(f"     {k}: {n} 条")


if __name__ == "__main__":
    main()
