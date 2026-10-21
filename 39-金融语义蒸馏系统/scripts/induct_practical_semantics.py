# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · 阶段二第二圈：实操语义归纳（零 token）

从真实交易日志与交易记录中逆向归纳核心术语的实操语义，
为第一圈术语表补充『实操语义』字段（区别于文档定义）：
  - 触发频次：术语在真实交易中的出现次数
  - 典型场景：真实日志中的代表性上下文（截取）
  - 结果表现：关联交易的盈亏统计（胜率/均盈亏）

数据源（第二圈·内部数据）：
  - /home/luke/logs/yijing/trader.log: 交易主日志（BCRM/BDSM/弹性门控实操记录）
  - 11-易经推理系统/.workbuddy/memory_l4/stats/all_trades.jsonl: BCRM 真实交易记录

产出: practical_semantics.json
用法: python3 induct_practical_semantics.py
"""
import json
import os
import re
from collections import defaultdict

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)

TRADER_LOG = "/home/luke/logs/yijing/trader.log"
TRADES_JSONL = os.path.join(_REPO, "11-易经推理系统", ".workbuddy", "memory_l4", "stats", "all_trades.jsonl")
OUT_PATH = os.path.join(_SYS_DIR, "practical_semantics.json")

# 核心术语 → 日志匹配模式（第二圈聚焦交易系统核心术语）
TERM_PATTERNS = {
    "BCRM连续性": re.compile(r"BCRM连续=(\w+)\(([\d.]+)\)"),
    "弹性门控ElasticGate3L": re.compile(r"ElasticGate3L 将给? ?([\d.]+) ?试错仓|ElasticGate3L 将缩减仓位"),
    "BDSM最低仓位兜底": re.compile(r"BDSM 最低仓位兜底 \| ([\d.]+)U→([\d.]+)U"),
    "三层弹性放行": re.compile(r"方案C 三层弹性放行 \| P1=(\w+) Elder=(\w+) BCRM连续=(\w+)"),
    "P1长多趋势过滤": re.compile(r"P1长多趋势过滤 \| 共振(成功|失败)"),
    "反向信号软权重": re.compile(r"反向信号软权重.*?仓位 ×([\d.]+)"),
    "超时换仓信号": re.compile(r"超时换仓信号: (\w+) (\w+) conf=([\d.]+)"),
    "事件驱动独立路径": re.compile(r"事件驱动策略独立路径 \| event_boost=([\d.]+)"),
}


def scan_trader_log(max_lines=400000):
    """扫描交易日志，统计各术语的触发频次与典型场景。"""
    stats = {name: {"count": 0, "samples": [], "values": defaultdict(int)} for name in TERM_PATTERNS}
    try:
        with open(TRADER_LOG, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                for name, pat in TERM_PATTERNS.items():
                    m = pat.search(line)
                    if m:
                        s = stats[name]
                        s["count"] += 1
                        # 记录取值分布（如 DIVERGE_BASIC/0.45）
                        key = m.group(1) if m.groups() else "hit"
                        s["values"][key] += 1
                        # 保留最近 3 条典型场景（截断）
                        if len(s["samples"]) < 3:
                            s["samples"].append(line.strip()[:200])
    except FileNotFoundError:
        pass
    return stats


def scan_trades():
    """统计真实交易记录：总体与按置信度/卦象分组的盈亏表现。"""
    trades = []
    try:
        with open(TRADES_JSONL, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    trades.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    if not trades:
        return {}
    total = len(trades)
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    avg_pnl = sum(t.get("pnl", 0) for t in trades) / total
    # 按置信度区间分组
    by_conf = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
    for t in trades:
        c = t.get("confidence", 0)
        bucket = ">=0.8" if c >= 0.8 else ("0.7-0.8" if c >= 0.7 else "<0.7")
        g = by_conf[bucket]
        g["n"] += 1
        g["wins"] += 1 if t.get("pnl", 0) > 0 else 0
        g["pnl"] += t.get("pnl", 0)
    # 高频卦象 top5
    hexa = defaultdict(lambda: {"n": 0, "wins": 0})
    for t in trades:
        h = t.get("hexagram", "")
        if h:
            hexa[h]["n"] += 1
            hexa[h]["wins"] += 1 if t.get("pnl", 0) > 0 else 0
    top_hex = sorted(hexa.items(), key=lambda kv: -kv[1]["n"])[:5]
    return {
        "total_trades": total,
        "win_rate": round(wins / total, 4),
        "avg_pnl_usdt": round(avg_pnl, 2),
        "by_confidence": {k: {"n": v["n"], "win_rate": round(v["wins"] / v["n"], 4),
                              "total_pnl": round(v["pnl"], 2)} for k, v in by_conf.items()},
        "top_hexagrams": {h: {"n": v["n"], "win_rate": round(v["wins"] / v["n"], 4)} for h, v in top_hex},
    }


def main():
    log_stats = scan_trader_log()
    trades_stats = scan_trades()
    # 组装实操语义（值分布取 top3）
    terms = {}
    for name, s in log_stats.items():
        if s["count"] == 0:
            continue
        top_values = sorted(s["values"].items(), key=lambda kv: -kv[1])[:3]
        terms[name] = {
            "occurrences": s["count"],
            "top_values": {k: v for k, v in top_values},
            "typical_context": s["samples"],
            "source": "trader.log（真实交易日志归纳）",
            "quality": "A",
        }
    out = {
        "circle": "second",
        "generated_at": "2026-10-17",
        "terms": terms,
        "trade_performance": trades_stats,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[OK] 实操语义归纳完成: {len(terms)} 个术语 ← {OUT_PATH}")
    if trades_stats:
        print(f"     交易样本: {trades_stats.get('total_trades')} 笔, "
              f"胜率: {trades_stats.get('win_rate')}, 均盈亏: {trades_stats.get('avg_pnl_usdt')}U")
    for name, s in log_stats.items():
        print(f"     {name}: {s['count']} 次")


if __name__ == "__main__":
    main()
