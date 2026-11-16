# -*- coding: utf-8 -*-
"""L1 意图阈值校准 + leave-one-intent-out uplift（SPEC v1.6 §3）。

约束优化：在 FPR ≤ 2% 的前提下最大化 OOD top1。
输入：training/l1_intent/datasets/{in_dist,ood_spoken,holdout}.jsonl
输出：training/l1_intent/snapshots/<YYYYMMDD>/{calibration.json,REPORT.md}

用法：
  python3 34-前端应用训练系统/training/l1_intent/calibrate.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
_TRAIN_DIR = os.path.abspath(os.path.join(_HERE, "..", ".."))
_ROOT = os.path.abspath(os.path.join(_TRAIN_DIR, ".."))
_SCRIPTS = os.path.join(_ROOT, "3.1-FRONTEND", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import l1_route_signal as lrs  # noqa: E402

DATASETS = os.path.join(_HERE, "datasets")
GRID = [round(0.55 + 0.01 * i, 2) for i in range(21)]  # 0.55–0.75
DELTAS = [0.0, 0.02, 0.05, 0.08, 0.10]
FPR_LIMIT = 0.02
MIN_UPLIFT = 0.02


def _read(name: str) -> list[dict]:
    path = os.path.join(DATASETS, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _topk(msg: str, cache: dict[str, list[tuple[str, float]]], k: int = 5):
    if msg not in cache:
        # 走生产同款入口（含别称归一），validated=False 保留原始分数供网格搜索
        try:
            cache[msg] = lrs.semantic_candidates(msg, k, validated=False)
        except Exception:  # noqa: BLE001
            cache[msg] = []
    return cache[msg]


def _predict(
    top: list[tuple[str, float]],
    t: float,
    msg: str = "",
    exclude: str = "",
    delta: float = 0.0,
    thresholds: dict | None = None,
) -> str:
    """生产口径：复合闸 + 分数≥阈值 + G2 特征闸 + margin≥δ。"""
    if lrs.is_compound_query(msg or ""):
        return ""
    if len(top) >= 2 and (top[0][1] - top[1][1]) < delta:
        return ""
    for intent, score in top:
        if intent == exclude:
            continue
        # G1 能力闸：无执行器的意图在生产会交 L2，不计为误路由
        if intent not in lrs.EXECUTORS:
            continue
        if not lrs.required_pattern_ok(intent, msg, strict_series=True):
            continue
        th = (thresholds or {}).get(intent, t)
        return intent if score >= th else ""
    return ""


def evaluate(
    rows: list[dict], cache: dict, t: float, delta: float = 0.0, thresholds: dict | None = None
) -> dict:
    pos = [r for r in rows if r.get("expected_intent")]
    neg = [r for r in rows if not r.get("expected_intent") and r.get("expected_route") == "L2"]
    hit1 = sum(
        1
        for r in pos
        if _predict(_topk(r["message"], cache), t, r["message"], delta=delta, thresholds=thresholds)
        == r["expected_intent"]
    )
    hit3 = sum(
        1
        for r in pos
        if r["expected_intent"]
        in [
            i
            for i, s in _topk(r["message"], cache)[:3]
            if s >= t and lrs.required_pattern_ok(i, r["message"], strict_series=True)
        ]
    )
    fp = 0
    for r in neg:
        pred = _predict(
            _topk(r["message"], cache), t, r["message"], delta=delta, thresholds=thresholds
        )
        if not pred:
            continue
        marker = r.get("notes") or ""
        if marker.startswith("negative_for:"):
            # 跨意图硬负例：只有被判成「它不该属于的那个意图」才算误报
            fp += int(pred == marker.split(":", 1)[1])
        else:
            fp += 1
    return {
        "n_pos": len(pos),
        "n_neg": len(neg),
        "top1": hit1 / len(pos) if pos else 0.0,
        "top3": hit3 / len(pos) if pos else 0.0,
        "fpr": fp / len(neg) if neg else 0.0,
    }


def choose(rows: list[dict], cache: dict) -> tuple[float, float, dict, list[dict]]:
    table = [
        {"threshold": t, "delta": d, **evaluate(rows, cache, t, d)} for t in GRID for d in DELTAS
    ]
    feasible = [r for r in table if r["fpr"] <= FPR_LIMIT]
    pool = feasible or table
    best = max(pool, key=lambda r: (r["top1"], r["top3"], -r["delta"]))
    return best["threshold"], best["delta"], best, table


def uplift(rows: list[dict], cache: dict, t: float, delta: float = 0.0) -> dict[str, float]:
    pos = [r for r in rows if r.get("expected_intent")]
    intents = sorted({r["expected_intent"] for r in pos})
    base = sum(
        1
        for r in pos
        if _predict(_topk(r["message"], cache), t, r["message"], delta=delta)
        == r["expected_intent"]
    ) / len(pos)
    out = {}
    for intent in intents:
        acc = sum(
            1
            for r in pos
            if _predict(_topk(r["message"], cache), t, r["message"], exclude=intent, delta=delta)
            == r["expected_intent"]
        ) / len(pos)
        out[intent] = round(base - acc, 4)
    return out


def calibrate_per_intent(rows: list[dict], cache: dict, delta: float = 0.0) -> dict:
    """分意图阈值：在 dev 集（in_dist）上按全局 FPR 预算贪心抬升各意图阈值。

    每个意图独立阈值 t_i；抬升选择「每消除 1 个 FP 损失召回最小」的意图。
    """
    pos = [r for r in rows if r.get("expected_intent")]
    neg = [r for r in rows if not r.get("expected_intent") and r.get("expected_route") == "L2"]
    intents = sorted({r["expected_intent"] for r in pos})
    grid = [round(0.40 + 0.02 * i, 2) for i in range(0, 26)]
    budget = int(FPR_LIMIT * len(neg)) if neg else 0

    stats = {it: {} for it in intents}
    for it in intents:
        n_it = sum(1 for r in pos if r["expected_intent"] == it)
        for t in grid:
            tp = sum(
                1
                for r in pos
                if r["expected_intent"] == it
                and _predict(_topk(r["message"], cache), t, r["message"], delta=delta) == it
            )
            fp = sum(
                1
                for r in neg
                if _predict(_topk(r["message"], cache), t, r["message"], delta=delta) == it
            )
            stats[it][t] = (tp, fp, n_it)

    th = dict.fromkeys(intents, grid[0])
    total_fp = sum(stats[it][grid[0]][1] for it in intents)
    while total_fp > budget:
        best = None
        for it in intents:
            cur = th[it]
            tp0, fp0, n_it = stats[it][cur]
            for t in grid:
                if t <= cur:
                    continue
                tp1, fp1, _ = stats[it][t]
                if fp1 >= fp0:
                    continue
                cost = (tp0 - tp1) / max(1, n_it)  # 召回损失占比
                gain = fp0 - fp1
                score = cost / gain
                if best is None or score < best[0]:
                    best = (score, it, t)
        if best is None:
            break
        _, it, t = best
        total_fp -= stats[it][th[it]][1] - stats[it][t][1]
        th[it] = t
    return {"thresholds": th, "dev_fp": total_fp, "dev_budget": budget}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", default=os.path.join(_HERE, "snapshots", date.today().strftime("%Y%m%d"))
    )
    args = ap.parse_args()

    in_dist, ood, holdout = (
        _read("in_dist.jsonl"),
        _read("ood_spoken.jsonl"),
        _read("holdout.jsonl"),
    )
    cache: dict[str, list] = {}

    t_star, d_star, best_ood, table = choose(ood, cache)
    up = uplift(ood + holdout, cache, t_star, d_star)
    pi = calibrate_per_intent(in_dist, cache)
    pi_ood = evaluate(ood, cache, t_star, d_star, pi["thresholds"])
    pi_hold = evaluate(holdout, cache, t_star, d_star, pi["thresholds"])
    pi_in = evaluate(in_dist, cache, t_star, d_star, pi["thresholds"])
    result = {
        "threshold": t_star,
        "delta": d_star,
        "fpr_limit": FPR_LIMIT,
        "ood": best_ood,
        "in_dist": evaluate(in_dist, cache, t_star, d_star),
        "holdout": evaluate(holdout, cache, t_star, d_star),
        "per_intent": {
            "thresholds": pi["thresholds"],
            "dev_fp": pi["dev_fp"],
            "dev_budget": pi["dev_budget"],
            "ood": pi_ood,
            "in_dist": pi_in,
            "holdout": pi_hold,
        },
        "uplift": up,
        "gate": {
            "ood_top1_ge_60": best_ood["top1"] >= 0.60,
            "ood_top3_ge_75": best_ood["top3"] >= 0.75,
            "fpr_le_2": best_ood["fpr"] <= FPR_LIMIT,
            "intents_uplift_ok": sum(1 for v in up.values() if v >= MIN_UPLIFT),
        },
        "grid": table,
    }

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "calibration.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    g = result["gate"]
    passed = all([g["ood_top1_ge_60"], g["ood_top3_ge_75"], g["fpr_le_2"]])
    lines = [
        "# L1 意图校准报告",
        "",
        f"- 选中：threshold **{t_star}** / delta **{d_star}**（约束 FPR≤{FPR_LIMIT:.0%}）",
        f"- OOD：top1 {best_ood['top1']:.1%} / top3 {best_ood['top3']:.1%} / FPR {best_ood['fpr']:.1%}（n={best_ood['n_pos']}/{best_ood['n_neg']}）",
        f"- in_dist：top1 {result['in_dist']['top1']:.1%} / top3 {result['in_dist']['top3']:.1%}",
        f"- holdout：top1 {result['holdout']['top1']:.1%} / top3 {result['holdout']['top3']:.1%}",
        "",
        "## 分意图阈值（dev=in_dist，全局 FPR 预算贪心）",
        f"- OOD：top1 {pi_ood['top1']:.1%} / top3 {pi_ood['top3']:.1%} / FPR {pi_ood['fpr']:.1%}",
        f"- in_dist：top1 {pi_in['top1']:.1%} / holdout top1 {pi_hold['top1']:.1%}",
        f"- 门禁（G1/G2/G3）：{'通过' if passed else '**未通过**'}",
        "",
        "## uplift ≥0.02 的意图",
        "",
    ]
    good = [k for k, v in result["uplift"].items() if v >= MIN_UPLIFT]
    bad = [k for k, v in result["uplift"].items() if v < MIN_UPLIFT]
    lines.append(f"- 达标（{len(good)}）：{', '.join(good) or '无'}")
    lines.append(f"- 待剪枝候选（{len(bad)}）：{', '.join(bad) or '无'}")
    with open(os.path.join(args.out, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
