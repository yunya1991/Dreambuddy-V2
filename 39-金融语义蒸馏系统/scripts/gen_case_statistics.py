# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P-案例 阶段2：分组描述性统计（SPEC §9.10.3，零 token）

对 trade_cases.jsonl 做分组统计（描述性，不产生交易信号）：
  - 按 方向 × 子系统 × 维度状态（情维极值/时维盘整/空维斐波那契）分组
  - 统计胜率 / 均盈亏 / 盈亏比 / 样本量
  - 证据强度：n>=30 正式结论；n<30 标注『弱证据』进候选池（SPEC §7.4）
  - 质量过滤：仅 A/B 级进入正式统计，C 级排除

产出: case_statistics.json
用法: /home/luke/venv-trading/bin/python3 gen_case_statistics.py
边界: 描述性统计报表，方向性结论的消费归 23 门禁体系（SPEC §9.10.3 强制）
"""
import json
import os
from collections import defaultdict

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
CASES_PATH = os.path.join(_SYS_DIR, "trade_cases.jsonl")
OUT_PATH = os.path.join(_SYS_DIR, "case_statistics.json")

N_FORMAL = 30  # 正式结论最小样本量（预注册，SPEC §7.4）


def load_cases():
    cases = []
    if not os.path.exists(CASES_PATH):
        print(f"[WARN] 案例文件不存在，跳过本轮: {CASES_PATH}")
        return cases
    with open(CASES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                c = json.loads(line)
            except Exception:
                continue
            if c.get("quality") in ("A", "B"):  # C 级排除
                cases.append(c)
    return cases


def dim_states(c):
    """提取案例的维度状态标签（用于分组）。"""
    snap = c.get("five_dim_snapshot") or {}
    sent = (snap.get("sentiment") or {}).get("extreme_state") or "无极值"
    time_d = snap.get("time") or {}
    consol = time_d.get("consolidation") or "无盘整事件"
    fib = (snap.get("space") or {}).get("fib_touches") or {}
    fib_state = "触及斐波那契位" if sum(fib.values()) > 0 else "未触及"
    return {"sentiment": sent, "consolidation": consol, "fib": fib_state}


def stat_group(cases):
    """统计一组案例的胜率/均盈亏/盈亏比。"""
    n = len(cases)
    if n == 0:
        return None
    pnls = [c["result"]["pnl"] for c in cases if isinstance(c.get("result", {}).get("pnl"), (int, float))]
    if not pnls:
        return {"n": n, "note": "无有效盈亏数据"}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    return {
        "n": n,
        "win_rate": round(len(wins) / len(pnls), 4),
        "avg_pnl": round(sum(pnls) / len(pnls), 2),
        "total_pnl": round(sum(pnls), 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
        "evidence": "strong" if n >= N_FORMAL else "weak（弱证据，仅进候选池）",
    }


def main():
    cases = load_cases()
    print(f"[OK] 载入 A/B 级案例 {len(cases)} 条")

    groups = defaultdict(list)
    for c in cases:
        ds = dim_states(c)
        sub = c.get("sub_tag") or "未标注"
        key_base = f"{c.get('direction')}|{c.get('strategy_source')}|{sub}"
        groups[key_base].append(c)
        groups[f"{key_base}|情维={ds['sentiment']}"].append(c)
        groups[f"{key_base}|时维={ds['consolidation']}"].append(c)
        groups[f"{key_base}|空维={ds['fib']}"].append(c)

    stats = {}
    for key, cs in sorted(groups.items()):
        s = stat_group(cs)
        if s and s.get("n", 0) >= 3:  # 少于 3 笔不构成统计组
            stats[key] = s

    out = {
        "generated_at": "2026-10-20",
        "total_cases": len(cases),
        "grouping": "方向|子系统|子标签[|维度状态]",
        "evidence_rule": f"n>={N_FORMAL} 为强证据；n<{N_FORMAL} 为弱证据（仅进因果候选池）",
        "boundary": "描述性统计（P-案例），不构成看多/看空建议；方向性结论消费归 23 门禁体系",
        "groups": stats,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[OK] P-案例统计完成: {len(stats)} 个统计组 -> {OUT_PATH}")
    for key, s in sorted(stats.items(), key=lambda kv: -kv[1]["n"])[:12]:
        if isinstance(s, dict) and "win_rate" in s:
            print(f"     {key}: n={s['n']}, 胜率 {s['win_rate']:.0%}, 均盈亏 {s['avg_pnl']}U, 证据 {s['evidence']}")


if __name__ == "__main__":
    main()
