# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P3 组织层复杂语义衍生（SPEC §7.3/§8.1，零 token）

时间阈值门禁：三层事件流（原子/分子/聚合）时间跨度 ≥7 天才启动衍生，
未达阈值自动跳过（配合每日定时检查实现超阈值自动启动）。

衍生内容（描述性，§8.2 边界：不产生交易信号）：
  1. 时序共现语义：分子术语对的窗口共现率（n≥30 才入库）
  2. 状态语义：原子因子取值分布按市场状态（恐惧贪婪分区）分组统计
  3. 因子-结果时间关联：分子术语触发后 N 小时标的结果分布（n≥30，
     一致趋势 ≥70% 进入因果候选池，供 23 自进化按其门禁消化，§8.3）

产出: complex_semantics.json（覆盖式更新，带样本量与证据强度标注）
用法: python3 gen_complex_semantics.py [--force 强制运行忽略阈值]
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)

ATOMIC_PATH = os.path.join(_SYS_DIR, "atomic_events.jsonl")
SEMANTIC_PATH = os.path.join(_SYS_DIR, "semantic_events.jsonl")
AGGREGATE_PATH = os.path.join(_SYS_DIR, "aggregate_events.jsonl")
OUT_PATH = os.path.join(_SYS_DIR, "complex_semantics.json")

THRESHOLD_DAYS = 7          # 时间阈值：事件流跨度 ≥7 天
MIN_SAMPLES = 30            # §7.4 红线：n<30 仅弱证据
CAUSAL_TREND = 0.70         # §8.3：一致趋势 ≥70% 进因果候选池


def _parse_ts(ts):
    t = (ts or "").replace("Z", "").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H"):
        try:
            return datetime.strptime(t[:19], fmt)
        except Exception:
            continue
    return None


def _load_jsonl(path):
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return events


def check_threshold():
    """检查三层事件流时间跨度是否达到阈值。"""
    spans = []
    for p in (ATOMIC_PATH, SEMANTIC_PATH, AGGREGATE_PATH):
        events = _load_jsonl(p)
        if not events:
            return False, 0.0, 0
        tss = [e.get("timestamp") or e.get("window") for e in events]
        tss = [t for t in (_parse_ts(x) for x in tss) if t]
        if not tss:
            return False, 0.0, 0
        spans.append((min(tss), max(tss)))
    overall_min = min(s[0] for s in spans)
    overall_max = max(s[1] for s in spans)
    days = (overall_max - overall_min).total_seconds() / 86400
    total = sum(len(_load_jsonl(p)) for p in (ATOMIC_PATH, SEMANTIC_PATH, AGGREGATE_PATH))
    return days >= THRESHOLD_DAYS, round(days, 2), total


def _window_key(ts):
    t = (ts or "").replace("Z", "").replace("T", " ")
    return t[:13]


def derive_cooccurrence(semantic_events):
    """1) 时序共现：分子术语对的窗口共现统计（n≥30 入库）。"""
    win_terms = defaultdict(lambda: defaultdict(int))
    for e in semantic_events:
        win_terms[_window_key(e.get("timestamp", ""))][e.get("term", "?")] += 1
    pair_stats = defaultdict(lambda: {"both": 0, "a": 0, "b": 0})
    windows = list(win_terms.values())
    for w in windows:
        terms = list(w.keys())
        for i in range(len(terms)):
            for j in range(i + 1, len(terms)):
                a, b = terms[i], terms[j]
                key = tuple(sorted((a, b)))
                pair_stats[key]["both"] += 1
    for w in windows:
        for t in set(w.keys()):
            for key in pair_stats:
                if t in key:
                    pair_stats[key]["a" if t == key[0] else "b"] += 1
    out = []
    n_win = max(1, len(windows))
    for (a, b), s in pair_stats.items():
        if s["both"] >= MIN_SAMPLES:
            out.append({
                "pair": [a, b], "cooccur_windows": s["both"],
                "cooccur_rate": round(s["both"] / n_win, 4),
                "evidence": "strong", "n": s["both"],
            })
        elif s["both"] >= 10:
            out.append({
                "pair": [a, b], "cooccur_windows": s["both"],
                "cooccur_rate": round(s["both"] / n_win, 4),
                "evidence": "weak", "n": s["both"],
            })
    out.sort(key=lambda x: -x["n"])
    return out[:50]


def derive_state_semantics(atomic_events):
    """2) 状态语义：原子因子事件按恐惧贪婪分区统计分布。"""
    fg_values = []
    for e in atomic_events:
        if e.get("category") in ("crypto_fear_greed", "fear_greed_enhanced"):
            v = e.get("value")
            if isinstance(v, (int, float)) and 0 <= v <= 100:
                fg_values.append((_parse_ts(e.get("timestamp", "")), v))
    if not fg_values:
        return {}
    fg_values.sort()
    def fg_zone_at(ts):
        if ts is None:
            return None
        val = None
        for t, v in fg_values:
            if t and t <= ts:
                val = v
        if val is None:
            return None
        if val < 25:
            return "extreme_fear"
        if val < 50:
            return "fear"
        if val < 75:
            return "greed"
        return "extreme_greed"
    by_state = defaultdict(lambda: defaultdict(int))
    for e in atomic_events:
        z = fg_zone_at(_parse_ts(e.get("timestamp", "")))
        if z:
            by_state[z][e.get("category", "?")] += 1
    return {z: dict(sorted(c.items(), key=lambda kv: -kv[1])[:10])
            for z, c in by_state.items()}


def derive_causal_candidates(semantic_events):
    """3) 因子-结果关联：分子术语触发后 4h 窗口内同标的开仓方向一致性。
    一致趋势 ≥70% 且 n≥30 → 因果候选池（§8.3，供 23 门禁消化）。"""
    # 标的的开仓事件时间线
    opens = defaultdict(list)  # symbol -> [(ts, ...)]
    for e in semantic_events:
        if e.get("term") == "开仓事件":
            ts = _parse_ts(e.get("timestamp", ""))
            if ts:
                opens[e.get("symbol", "?")].append(ts)
    for s in opens:
        opens[s].sort()
    import bisect
    stats = defaultdict(lambda: {"n": 0, "followed": 0})
    for e in semantic_events:
        term = e.get("term")
        if not term or term == "开仓事件":
            continue
        sym = e.get("symbol", "?")
        ts = _parse_ts(e.get("timestamp", ""))
        if ts is None or sym not in opens:
            continue
        lst = opens[sym]
        i = bisect.bisect_right(lst, ts)
        stats[term]["n"] += 1
        if i < len(lst):
            dt = (lst[i] - ts).total_seconds() / 3600
            if dt <= 4:
                stats[term]["followed"] += 1
    out = []
    for term, s in stats.items():
        if s["n"] < MIN_SAMPLES:
            continue
        rate = s["followed"] / s["n"]
        entry = {"term": term, "n": s["n"],
             "follow_rate_4h": round(rate, 4),
             "evidence": "strong" if s["n"] >= MIN_SAMPLES else "weak"}
        if rate >= CAUSAL_TREND:
            entry["causal_candidate"] = True
            entry["note"] = "一致趋势达标，进入因果候选池（供 23 自进化按其门禁流程消化）"
        out.append(entry)
    out.sort(key=lambda x: -x["follow_rate_4h"])
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="忽略阈值强制运行")
    args = parser.parse_args()

    ok, days, total = check_threshold()
    if not ok and not args.force:
        print(f"[SKIP] 事件流跨度 {days} 天 < 阈值 {THRESHOLD_DAYS} 天（共 {total} 条事件），"
              f"未达阈值自动跳过，待每日定时检查触发")
        return

    print(f"[OK] 阈值通过: 事件流跨度 {days} 天 ≥ {THRESHOLD_DAYS} 天，开始 P3 复杂语义衍生")
    semantic = _load_jsonl(SEMANTIC_PATH)
    atomic = _load_jsonl(ATOMIC_PATH)

    cooccur = derive_cooccurrence(semantic)
    state_sem = derive_state_semantics(atomic)
    causal = derive_causal_candidates(semantic)

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_span_days": days,
        "total_events": total,
        "cooccurrence": cooccur,
        "state_semantics": state_sem,
        "causal_candidates": causal,
        "boundary": "描述性观察知识（§8.2），不产生交易信号；因果候选仅供 23 按其门禁消化（§8.3）",
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[OK] 复杂语义衍生完成 → {OUT_PATH}")
    print(f"     时序共现: {len(cooccur)} 对（强证据 {sum(1 for c in cooccur if c['evidence']=='strong')}）")
    print(f"     状态语义: {len(state_sem)} 个市场状态分区")
    print(f"     因果候选: {len(causal)} 项（达标 {sum(1 for c in causal if c.get('causal_candidate'))} 项）")


if __name__ == "__main__":
    main()
