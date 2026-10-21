# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · L2 事件线聚合（SPEC v1.2 §9.7，零 token）

同主题快讯事件一致聚合，叠加时间标签，描述事件语义变化：
  1. 规则聚类：事件类型 + 关键词重叠 + 关联代币 → 事件线
  2. 时间标签：每条事件线含起止时间与时间跨度
  3. 变化描述（观察性，不做方向判断）：频次变化 + 情绪均值变化

产出: event_lines.json（覆盖式更新）
用法: python3 gen_event_lines.py
前端消费: exec_event_line_query 意图（『XX事件最近怎么演变』）
"""
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)

sys.path.insert(0, _THIS_DIR)
import dc_pg  # PostgreSQL 辅助模块（18 中心迁移后替代 SQLite）

OUT_PATH = os.path.join(_SYS_DIR, "event_lines.json")
ATOMIC_PATH = os.path.join(_SYS_DIR, "atomic_events.jsonl")

# 主题关键词组（聚类锚点，复用 P-术语词典口径）
TOPIC_ANCHORS = {
    "美联储利率": ["美联储", "加息", "降息", "利率决议", "FOMC", "鲍威尔"],
    "加密监管": ["监管", "SEC", "牌照", "ETF审批", "反洗钱", "稳定币监管"],
    "代币解锁": ["解锁", "锁仓到期", "代币释放"],
    "巨鲸动向": ["巨鲸", "大户", "转移", "增持", "减持"],
    "地缘冲突": ["地缘", "中东", "俄乌", "制裁", "冲突"],
    "ETF 动态": ["ETF", "现货ETF", "资金流入", "资金流出"],
}

_POS_WORDS = ("上涨", "突破", "新高", "利好", "批准", "融资", "增持")
_NEG_WORDS = ("下跌", "暴跌", "利空", "制裁", "禁止", "黑客", "清算", "减持")


def _sentiment(text):
    pos = sum(1 for w in _POS_WORDS if w in text)
    neg = sum(1 for w in _NEG_WORDS if w in text)
    return 1 if pos > neg else (-1 if neg > pos else 0)


def _parse_ts(ts):
    t = (ts or "").replace("Z", "").replace("T", " ")
    try:
        return datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def load_events(limit=1500):
    events = []
    # PostgreSQL 查询（dc_pg 统一接口，FAIL-OPEN：异常返回空）
    rows = dc_pg.fetch_records("newsflash_%", limit=limit, order_desc=True)
    for row in rows:
        ts = row.get("timestamp", "") or ""
        m = row.get("metrics") or {}
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except Exception:
                continue
        if not isinstance(m, dict):
            continue
        desc = re.sub(r"<[^>]+>", "", m.get("description", "")).strip()
        if not desc:
            continue
        tickers = m.get("tickers_hit") or []
        if isinstance(tickers, str):
            try:
                tickers = json.loads(tickers)
            except Exception:
                tickers = []
        t = _parse_ts(ts)
        if t is None:
            continue
        events.append({
            "ts": t, "ts_str": (ts or "")[:16], "desc": desc,
            "event_type": m.get("od_event_type", ""),
            "tickers": tickers, "sentiment": _sentiment(desc),
        })
    events.sort(key=lambda e: e["ts"])
    return events


def load_atomic_dims():
    """加载原子层五维事件（SPEC §9.8 第一批+第二批）。

    返回 (volume_events, extreme_events, time_events, space_events, cycle_events)：
n      量维：放量/缩量 | 情维：恐惧贪婪极值 | 时维：盘整 | 空维：斐波那契 | 周期维：四年周期
    """
    volume_events, extreme_events, time_events, space_events, cycle_events = [], [], [], [], []
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
                item = {"ts": t, "reasons": reasons,
                        "category": e.get("category", ""), "metric": e.get("metric", "")}
                if any(r.startswith("volume_") for r in reasons):
                    volume_events.append(item)
                elif any(r.startswith("extreme_") for r in reasons):
                    extreme_events.append(item)
                elif e.get("category") == "five_dim_time":
                    time_events.append(item)
                elif e.get("category") == "five_dim_space":
                    space_events.append(item)
                elif e.get("category") == "five_dim_cycle":
                    cycle_events.append(item)
    except FileNotFoundError:
        pass
    return volume_events, extreme_events, time_events, space_events, cycle_events


def cluster_into_lines(events):
    """规则聚类：主题锚点关键词命中 → 事件线。"""
    lines = {topic: [] for topic in TOPIC_ANCHORS}
    for e in events:
        for topic, anchors in TOPIC_ANCHORS.items():
            if any(a in e["desc"] for a in anchors):
                lines[topic].append(e)
                break  # 每事件归入首个命中主题，避免重复
    return lines


def describe_line(topic, evs, atomic_dims=([], [], [], [], [])):
    """产出事件线的观察性变化描述（频次+情绪+量变统计分布+五维完整画像，不做方向判断）。"""
    if not evs:
        return None
    n = len(evs)
    start, end = evs[0], evs[-1]
    span_h = round((end["ts"] - start["ts"]).total_seconds() / 3600, 1)
    # 前后半段对比（频次与情绪均值变化）
    mid = n // 2
    early, late = evs[:mid] or evs[:1], evs[mid:] or evs[-1:]
    freq_early = len(early) / max(1, span_h / 2)
    freq_late = len(late) / max(1, span_h / 2)
    sent_early = sum(x["sentiment"] for x in early) / len(early)
    sent_late = sum(x["sentiment"] for x in late) / len(late)
    # 变化描述
    freq_trend = "升温" if freq_late > freq_early * 1.3 else ("降温" if freq_late < freq_early * 0.7 else "平稳")
    if sent_late > sent_early + 0.2:
        sent_trend = "情绪转暖"
    elif sent_late < sent_early - 0.2:
        sent_trend = "情绪转冷"
    else:
        sent_trend = "情绪平稳"
    # ── 量变统计分布（量变引发质变的观测基础，v1.2 §9.7 增强）──
    # 时间窗口频次分布：跨度均分 6 窗口，统计各窗口事件数
    n_windows = 6
    win_h = max(span_h / n_windows, 0.1)
    freq_dist = [0] * n_windows
    for e in evs:
        idx = min(n_windows - 1, int((e["ts"] - start["ts"]).total_seconds() / 3600 / win_h))
        freq_dist[idx] += 1
    mean_w = n / n_windows
    var_w = sum((c - mean_w) ** 2 for c in freq_dist) / n_windows
    std_w = var_w ** 0.5
    last_w = freq_dist[-1]
    # 量变强度：末窗口相对历史均值的偏离倍数（z-score 口径）
    quantity_intensity = round(last_w / mean_w, 2) if mean_w > 0 else 0.0
    quantity_z = round((last_w - mean_w) / std_w, 2) if std_w > 0 else 0.0
    # ── 改进1『度』区间（黑格尔：质得以保持的量的区间）──
    # 常态度区间：剔除末窗口后，历史窗口频次的 [P25, P75] 作为常态区间
    hist = freq_dist[:-1] or freq_dist
    hist_sorted = sorted(hist)
    p25 = hist_sorted[max(0, len(hist_sorted) // 4)]
    p75 = hist_sorted[min(len(hist_sorted) - 1, len(hist_sorted) * 3 // 4)]
    if last_w > p75:
        degree_position = "超度区上界"
        degree_distance = round((last_w - p75) / max(1, p75), 2)
    elif last_w < p25:
        degree_position = "低于度区下界"
        degree_distance = round((p25 - last_w) / max(1, p25), 2)
    else:
        degree_position = "度区内"
        degree_distance = 0.0
    # ── 改进2 临界慢化（复杂系统相变前兆：方差与自相关上升）──
    # 前三窗口 vs 后三窗口的频次方差对比（方差上升 = 波动加剧前兆）
    early_w = freq_dist[:3] or [0]
    late_w = freq_dist[-3:] or [0]
    var_early = sum((c - sum(early_w) / len(early_w)) ** 2 for c in early_w) / len(early_w)
    var_late = sum((c - sum(late_w) / len(late_w)) ** 2 for c in late_w) / len(late_w)
    variance_ratio = round(var_late / var_early, 2) if var_early > 0 else (1.0 if var_late == 0 else 99.0)
    # 自相关趋势：相邻窗口频次的皮尔逊相关（高自相关 = 状态持续性强，临界前兆）
    if n_windows >= 4 and std_w > 0:
        mean_adj = mean_w
        cov = sum((freq_dist[i] - mean_adj) * (freq_dist[i + 1] - mean_adj)
                  for i in range(n_windows - 1)) / max(1, n_windows - 1)
        autocorr = round(cov / (std_w * std_w), 2)
    else:
        autocorr = 0.0
    slowing_down = variance_ratio >= 1.5 or autocorr >= 0.6
    # 量变→质变预警信号（描述性，不做方向判断）：
    #   末窗口 ≥ 均值 2 倍 且 z ≥ 1.5 → 量变加速积累，关注质变可能
    #   叠加临界慢化（方差上升/自相关高）→ 信号增强标注
    if mean_w > 0 and last_w >= mean_w * 2 and quantity_z >= 1.5:
        quantity_signal = "量变加速积累（末窗口显著高于均值，关注质变可能）"
    elif mean_w > 0 and last_w >= mean_w * 1.5:
        quantity_signal = "量变温和积累"
    elif last_w <= mean_w * 0.5:
        quantity_signal = "量变消退"
    else:
        quantity_signal = "量变平稳"
    if slowing_down and "加速" in quantity_signal:
        quantity_signal += "；检出临界慢化前兆（方差/自相关上升），相变临近度较高"
    # ── 五维画像关联（SPEC §9.8 第一批：量维+情维接入 L2，窗口对齐）──
    def _in_span(ev):
        return start["ts"] <= ev["ts"] <= end["ts"]
    vol_in = [ev for ev in atomic_dims[0] if _in_span(ev)]
    ext_in = [ev for ev in atomic_dims[1] if _in_span(ev)]
    vol_surge = sum(1 for ev in vol_in if any(r.startswith("volume_surge") for r in ev["reasons"]))
    vol_shrink = sum(1 for ev in vol_in if any(r.startswith("volume_shrink") for r in ev["reasons"]))
    ext_enter = sum(1 for ev in ext_in if any(r.startswith("extreme_enter") for r in ev["reasons"]))
    ext_persist = sum(1 for ev in ext_in if any(r.startswith("extreme_persist") for r in ev["reasons"]))
    ext_exit = sum(1 for ev in ext_in if any(r.startswith("extreme_exit") for r in ev["reasons"]))
    # 情维当前状态：时间窗内最近一条极值事件方向（描述性）
    ext_state = "无极值区间记录"
    for ev in reversed(ext_in):
        matched = False
        for r in ev["reasons"]:
            if r.startswith(("extreme_persist", "extreme_enter")):
                ext_state = "极度恐慌持续" if "extreme_fear" in r else "极度贪婪持续"
                matched = True
                break
            if r.startswith("extreme_exit"):
                ext_state = "极值区间已退出"
                matched = True
                break
        if matched:
            break
    # ── 五维画像关联（SPEC §9.8 第二批：时维+空维+周期维接入 L2）──
    def _in_span2(ev):
        return start["ts"] <= ev["ts"] <= end["ts"]
    time_in = [ev for ev in atomic_dims[2] if _in_span2(ev)]
    space_in = [ev for ev in atomic_dims[3] if _in_span2(ev)]
    cycle_in = [ev for ev in atomic_dims[4] if _in_span2(ev)]
    consol_breakout = sum(1 for ev in time_in if "breakout" in ev["metric"])
    consol_ongoing = sum(1 for ev in time_in if "ongoing" in ev["metric"])
    fib_touches = defaultdict(int)
    for ev in space_in:
        if ev["metric"].startswith("fib_touch_"):
            fib_touches[ev["metric"].replace("fib_touch_", "")] += 1
    # 周期维：时间窗内最近一条周期距离事件
    cycle_info = "无周期记录"
    for ev in reversed(cycle_in):
        for r in ev["reasons"]:
            if r.startswith("cycle_halving_distance"):
                cycle_info = r.split(":", 1)[1]
                break
        else:
            continue
        break
    # 关联代币聚合
    tickers = defaultdict(int)
    for e in evs:
        for t in e["tickers"]:
            tickers[t] += 1
    top_tickers = sorted(tickers.items(), key=lambda kv: -kv[1])[:5]
    return {
        "topic": topic,
        "event_count": n,
        "time_start": start["ts_str"],
        "time_end": end["ts_str"],
        "span_hours": span_h,
        "freq_trend": freq_trend,
        "sentiment_trend": sent_trend,
        "sentiment_early": round(sent_early, 2),
        "sentiment_late": round(sent_late, 2),
        "quantity_distribution": freq_dist,
        "quantity_intensity": quantity_intensity,
        "quantity_z": quantity_z,
        "quantity_signal": quantity_signal,
        "degree_position": degree_position,
        "degree_distance": degree_distance,
        "critical_slowing": {
            "variance_ratio": variance_ratio,
            "autocorr": autocorr,
            "detected": slowing_down,
        },
        "volume_dimension": {
            "surge_events": vol_surge,
            "shrink_events": vol_shrink,
            "note": "量维：事件线时间窗内放量/缩量原子事件计数（描述性观察）",
        },
        "sentiment_dimension": {
            "extreme_enter": ext_enter,
            "extreme_persist": ext_persist,
            "extreme_exit": ext_exit,
            "current_state": ext_state,
            "note": "情维：恐惧贪婪极值区间事件（描述性观察）",
        },
        "time_dimension": {
            "consolidation_breakout": consol_breakout,
            "consolidation_ongoing": consol_ongoing,
            "halving_cycle": cycle_info,
            "note": "时维：盘整区间突破/进行中 + 四年减半周期距离（SPEC §9.8.1 时维口径，描述性观察）",
        },
        "space_dimension": {
            "fib_touches": dict(fib_touches),
            "note": "空维：斐波那契回撤关键位触及（描述性观察）",
        },
        "top_tickers": [t for t, _ in top_tickers],
        "recent_items": [
            {"time": e["ts_str"], "summary": e["desc"][:80], "sentiment": e["sentiment"]}
            for e in evs[-3:]
        ],
        "boundary": "观察性描述（L2），不做方向判断",
    }


def main():
    events = load_events()
    print(f"[INFO] 加载快讯事件 {len(events)} 条")
    atomic_dims = load_atomic_dims()
    print(f"[INFO] 加载原子层五维事件: 量维 {len(atomic_dims[0])} / 情维 {len(atomic_dims[1])} / 时维 {len(atomic_dims[2])} / 空维 {len(atomic_dims[3])} / 周期维 {len(atomic_dims[4])}")
    lines = cluster_into_lines(events)
    out_lines = []
    for topic, evs in lines.items():
        desc = describe_line(topic, evs, atomic_dims)
        if desc and desc["event_count"] >= 3:  # 少于 3 条不构成事件线
            out_lines.append(desc)
    out_lines.sort(key=lambda x: -x["event_count"])
    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_events": len(events),
        "lines": out_lines,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[OK] 事件线聚合完成: {len(out_lines)} 条事件线 → {OUT_PATH}")
    for l in out_lines[:6]:
        print(f"     {l['topic']}: {l['event_count']} 事件, 跨度 {l['span_hours']}h, "
              f"频次{l['freq_trend']}, {l['sentiment_trend']}, {l['quantity_signal']}")


if __name__ == "__main__":
    main()
