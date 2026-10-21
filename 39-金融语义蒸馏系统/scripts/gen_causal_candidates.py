# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P-案例 阶段4：因果候选池（SPEC §9.10.4 / §8.3，零 token）

从案例统计中筛选『维度状态 × 结果一致趋势』的组，登记为因果候选：
  - 筛选规则（预注册）：维度状态组的胜率相对同方向基线偏离 >= 10 个百分点
  - 候选登记：带样本量 / 胜率 / 均盈亏 / 证据强度 / 时间窗口标注
  - n>=30 强证据候选；n<30 弱证据候选（均进池，标注区分）

产出: causal_candidates.json（供 23 自进化系统按其治理流程消费）
用法: /home/luke/venv-trading/bin/python3 gen_causal_candidates.py
边界: 仅提供因果候选证据（描述性统计），不直接改 23 决策参数（SPEC §8.3 反哺边界）
"""
import json
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
STATS_PATH = os.path.join(_SYS_DIR, "case_statistics.json")
OUT_PATH = os.path.join(_SYS_DIR, "causal_candidates.json")

DEVIATION_THRESHOLD = 0.10  # 胜率相对基线偏离阈值（预注册，10 个百分点）
N_FORMAL = 30


def parse_key(key):
    """解析统计组键：方向|子系统|子标签[|维度=状态]。"""
    parts = key.split("|")
    direction = parts[0] if parts else None
    dim_state = None
    for p in parts[3:]:
        if "=" in p:
            dim_state = p
    return direction, dim_state


def main():
    with open(STATS_PATH, "r", encoding="utf-8") as f:
        stats = json.load(f)
    groups = stats.get("groups", {})

    # 基线：各方向不含维度状态的组（方向|子系统|子标签）
    baselines = {}
    for key, s in groups.items():
        if "=" not in key and isinstance(s, dict) and "win_rate" in s:
            baselines[key] = s["win_rate"]

    candidates = []
    for key, s in groups.items():
        if "=" not in key or not isinstance(s, dict) or "win_rate" not in s:
            continue
        direction, dim_state = parse_key(key)
        if dim_state is None:
            continue
        # 找同方向基线（取该方向全部基线的加权均值）
        base_keys = [k for k in baselines if k.startswith(f"{direction}|")]
        if not base_keys:
            continue
        total_n = sum(groups[k]["n"] for k in base_keys)
        base_wr = sum(baselines[k] * groups[k]["n"] for k in base_keys) / total_n
        deviation = s["win_rate"] - base_wr
        if abs(deviation) >= DEVIATION_THRESHOLD:
            trend = "胜率显著高于基线" if deviation > 0 else "胜率显著低于基线"
            candidates.append({
                "group": key,
                "direction": direction,
                "dim_state": dim_state,
                "n": s["n"],
                "win_rate": s["win_rate"],
                "baseline_win_rate": round(base_wr, 4),
                "deviation": round(deviation, 4),
                "trend": trend,
                "avg_pnl": s.get("avg_pnl"),
                "evidence": "strong" if s["n"] >= N_FORMAL else "weak（弱证据）",
                "window": "历史全量案例（2026-08 ~ 2026-10）",
                "consumer": "23 自进化系统（提案→WalkForward→三步门禁，SPEC §8.3）",
            })

    candidates.sort(key=lambda c: -abs(c["deviation"]))
    out = {
        "generated_at": "2026-10-20",
        "rule": f"维度状态组胜率相对同方向基线偏离 >= {DEVIATION_THRESHOLD:.0%}（预注册）",
        "total_candidates": len(candidates),
        "boundary": "因果候选证据（描述性统计），不直接改 23 决策参数；消费归 23 治理流程",
        "candidates": candidates,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[OK] P-案例因果候选池完成: {len(candidates)} 项 -> {OUT_PATH}")
    strong = [c for c in candidates if c["evidence"] == "strong"]
    print(f"     强证据候选: {len(strong)} | 弱证据候选: {len(candidates) - len(strong)}")
    for c in candidates[:8]:
        print(f"     {c['group']}: n={c['n']}, 胜率 {c['win_rate']:.0%} vs 基线 {c['baseline_win_rate']:.0%}, "
              f"偏离 {c['deviation']:+.0%}, {c['trend']}, 证据 {c['evidence']}")


if __name__ == "__main__":
    main()
