# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P1b 聚合层（SPEC §8.1 细胞层，零 token）

按时间窗口（1 小时）聚合原子层与分子层事件流，产出三类聚合语义事件：
  1. 单因子时间序列：各因子在窗口内的事件计数（head 独立编码）
  2. 跨因子聚合状态：窗口内活跃因子集合与总活跃度（多头融合）
  3. 多因子聚合离散度：因子间活跃度分布的变异系数（注意力熵/冲突度量）

输入: atomic_events.jsonl（原子层）+ semantic_events.jsonl（分子层）
产出: aggregate_events.jsonl（每窗口一条，持续追加）

运行模式:
  --backfill  回填模式：全量聚合历史事件
  --live      增量模式：只聚合上次处理窗口之后的事件
"""
import argparse
import json
import os
from collections import defaultdict

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)

ATOMIC_PATH = os.path.join(_SYS_DIR, "atomic_events.jsonl")
SEMANTIC_PATH = os.path.join(_SYS_DIR, "semantic_events.jsonl")
OUT_PATH = os.path.join(_SYS_DIR, "aggregate_events.jsonl")
STATE_PATH = os.path.join(_SYS_DIR, ".aggregate_events_state.json")

WINDOW_HOURS = 1


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_window": ""}


def _save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def _window_key(ts):
    """时间戳 → 小时窗口键（如 2026-10-17T05）。"""
    # 兼容两种格式: 2026-10-17 05:00:00 / 2026-10-17T05:00:00Z
    t = ts.replace("Z", "").replace("T", " ")
    return t[:13]


def _load_events(path, factor_key):
    """加载事件流，返回 {窗口: {因子: 计数}}。"""
    windows = defaultdict(lambda: defaultdict(int))
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                ts = e.get("timestamp", "")
                if not ts:
                    continue
                if factor_key == "atomic":
                    factor = f"{e.get('category', '?')}.{e.get('metric', '?')}"
                else:
                    factor = e.get("term", "?")
                windows[_window_key(ts)][factor] += 1
    except FileNotFoundError:
        pass
    return windows


def _dispersion(counts):
    """因子活跃度的变异系数（离散度）：CV = std/mean。"""
    vals = list(counts.values())
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    if mean == 0:
        return 0.0
    var = sum((v - mean) ** 2 for v in vals) / n
    return round((var ** 0.5) / mean, 4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    last_window = "" if args.backfill else _load_state().get("last_window", "")

    atomic = _load_events(ATOMIC_PATH, "atomic")
    semantic = _load_events(SEMANTIC_PATH, "semantic")
    all_windows = sorted(set(atomic) | set(semantic))

    events = []
    processed_last = last_window
    for w in all_windows:
        if args.live and w <= last_window:
            continue
        a_counts = dict(atomic.get(w, {}))
        s_counts = dict(semantic.get(w, {}))
        # 1) 单因子时间序列（原子因子 + 分子术语分别记录计数）
        # 2) 跨因子聚合状态（活跃因子数与总事件数）
        total_atomic = sum(a_counts.values())
        total_semantic = sum(s_counts.values())
        active_factors = len(a_counts) + len(s_counts)
        # 3) 多因子聚合离散度（全部因子活跃度的变异系数）
        merged = {**{f"atomic:{k}": v for k, v in a_counts.items()},
                  **{f"semantic:{k}": v for k, v in s_counts.items()}}
        disp = _dispersion(merged)
        events.append({
            "layer": "aggregate",
            "window": w,
            "window_hours": WINDOW_HOURS,
            "atomic_factor_counts": a_counts,
            "semantic_term_counts": s_counts,
            "total_atomic": total_atomic,
            "total_semantic": total_semantic,
            "active_factors": active_factors,
            "factor_dispersion_cv": disp,
            "source": "aggregate_of_atomic_and_semantic",
        })
        processed_last = w

    if events:
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    _save_state({"last_window": processed_last})

    print(f"[OK] 模式={'backfill' if args.backfill else 'live'} "
          f"聚合 {len(events)} 个窗口 → {OUT_PATH}")
    if events:
        # 抽样展示最近窗口
        last = events[-1]
        print(f"     最近窗口 {last['window']}: "
              f"原子事件 {last['total_atomic']}, 分子事件 {last['total_semantic']}, "
              f"活跃因子 {last['active_factors']}, 离散度CV {last['factor_dispersion_cv']}")


if __name__ == "__main__":
    main()
