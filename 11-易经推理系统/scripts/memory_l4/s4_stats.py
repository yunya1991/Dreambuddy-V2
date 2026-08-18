#!/usr/bin/env python3
"""
s4_stats.py — S4 排名止盈长期效果统计

用法:
    python s4_stats.py [归档文件] [开始时间] [结束时间]
    python s4_stats.py                          # 默认读取 data/polling_trader/s4_eval_log.jsonl
    python s4_stats.py --since 2026-08-18       # 只看某天起
    python s4_stats.py --range 2026-08-18 2026-08-25

统计内容:
    1. 总评估次数 + A/B/C/SKIP 档位分布
    2. gap_ratio 趋势（均值/最大/最小）
    3. B 档排队写入次数 + 到期执行率
    4. A 档止盈触发次数 + 明细
    5. 持仓数分布
"""
import json
import sys
import argparse
from pathlib import Path
from collections import Counter, defaultdict


DEFAULT_PATH = "data/polling_trader/s4_eval_log.jsonl"


def load_records(path: str) -> list:
    """加载 JSONL 归档记录"""
    p = Path(path)
    if not p.exists():
        print(f"归档文件不存在: {path}")
        sys.exit(1)
    records = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def filter_by_time(records: list, start: str = None, end: str = None) -> list:
    """按时间范围过滤"""
    if start:
        records = [r for r in records if r.get("ts", "") >= start]
    if end:
        records = [r for r in records if r.get("ts", "") <= end]
    return records


def print_stats(records: list):
    """输出统计报告"""
    if not records:
        print("无记录")
        return

    total = len(records)
    ts_first = records[0].get("ts", "?")
    ts_last = records[-1].get("ts", "?")

    # ── 1. 档位分布 ──
    tier_dist = Counter(r.get("tier", "?") for r in records)
    triggered = [r for r in records if r.get("triggered")]

    print("=" * 60)
    print("S4 排名止盈长期效果统计")
    print("=" * 60)
    print(f"时间范围: {ts_first} ~ {ts_last}")
    print(f"总评估次数: {total}")
    print(f"档位分布: A={tier_dist.get('A', 0)}  B={tier_dist.get('B', 0)}  "
          f"C={tier_dist.get('C', 0)}  SKIP={tier_dist.get('SKIP', 0)}")
    print(f"A档触发止盈: {len(triggered)} ({len(triggered)/total*100:.1f}%)")

    # ── 2. gap_ratio 趋势 ──
    gaps = [float(r.get("gap_ratio", 0)) for r in records]
    if gaps:
        print(f"\n--- gap_ratio 趋势 ---")
        print(f"  均值={sum(gaps)/len(gaps):.3f}  最大={max(gaps):.3f}  最小={min(gaps):.3f}")
        # 按 10 分位看分布
        sorted_gaps = sorted(gaps)
        p50 = sorted_gaps[len(sorted_gaps) // 2]
        p90 = sorted_gaps[int(len(sorted_gaps) * 0.9)]
        print(f"  P50={p50:.3f}  P90={p90:.3f}")

    # ── 3. B 档排队统计 ──
    b_writes = [r for r in records if "B档排队写入" in str(r.get("reason", ""))
                or "B档" in str(r.get("reason", ""))]
    b_executes = [r for r in records if "到期执行" in str(r.get("reason", ""))]
    print(f"\n--- B 档排队统计 ---")
    print(f"  B档排队写入: {len(b_writes)} 次")
    print(f"  B档到期执行: {len(b_executes)} 次")
    if b_writes:
        print(f"  到期执行率: {len(b_executes)/len(b_writes)*100:.1f}%")

    # ── 4. A 档止盈明细 ──
    if triggered:
        print(f"\n--- A 档止盈明细 ---")
        for r in triggered:
            coin = r.get("top1_coin", "?")
            gap = r.get("gap_ratio", 0)
            ts = r.get("ts", "?")
            reason = r.get("reason", "")
            print(f"  {ts} | {coin} gap={gap:.2f} | {reason}")

    # ── 5. 持仓数分布 ──
    pos_counts = [len(r.get("positions", [])) for r in records]
    pos_dist = Counter(pos_counts)
    print(f"\n--- 持仓数分布 ---")
    for n in sorted(pos_dist.keys()):
        print(f"  {n} 仓: {pos_dist[n]} 次 ({pos_dist[n]/total*100:.1f}%)")

    # ── 6. Top1 币种频率 ──
    top1_coins = Counter(r.get("top1_coin", "") for r in records if r.get("top1_coin"))
    if top1_coins:
        print(f"\n--- Top1 币种频率 (Top 5) ---")
        for coin, cnt in top1_coins.most_common(5):
            print(f"  {coin}: {cnt} 次 ({cnt/total*100:.1f}%)")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="S4 排名止盈长期效果统计")
    parser.add_argument("path", nargs="?", default=DEFAULT_PATH,
                        help=f"归档文件路径 (默认: {DEFAULT_PATH})")
    parser.add_argument("--since", default=None, help="开始时间 (如 2026-08-18)")
    parser.add_argument("--until", default=None, help="结束时间 (如 2026-08-25)")
    args = parser.parse_args()

    records = load_records(args.path)
    records = filter_by_time(records, args.since, args.until)
    print_stats(records)


if __name__ == "__main__":
    main()
