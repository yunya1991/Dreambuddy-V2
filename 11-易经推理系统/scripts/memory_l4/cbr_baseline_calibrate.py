#!/usr/bin/env python3
"""
CBR v3.0 §2.5：基线家族季度参数校准脚本（θ_match × γ_max = 88 组合网格搜索）
================================================================================

功能（CLI）：
    --dry-run     只枚举网格验证 88 组合 + 打印最佳目标占位，不跑回测
    --cases PATH  案例库 JSONL（默认 runtime/cbr_cases_v03.jsonl，由 generate 脚本产出）
    --output PATH 最优参数输出 JSON（默认 runtime/cbr_baseline_params.json）
    --quarter YYYY-Qn  校准季度标签（仅元数据，写进 output）
    --top-k N     predict_topk 使用的 N（默认 3）

网格（与 T6.23 单测字节对齐）：
    THETA_GRID = [0.65, 0.68, ..., 0.95]（步长 0.03，共 11 档）
    GAMMA_GRID = [0.05, 0.08, ..., 0.26]（步长 0.03，共  8 档）
    → 11 × 8 = 88 组合

目标函数（最大化 signal_gain）：
    signal_gain(θ, γ) = mean(pnl_pct | top1 命中 θ* 家族)
                      − mean(pnl_pct | top1 未命中)

Phase2 真实回测：对每个 (θ, γ)，在 WalkForwardBacktester 上 replay，
按式 §2.5.3 合成 w_B = clip(w_B^0 + match_boost, 0.05, 0.80)，计算
样本内 signal_gain；当前骨架为了可跑，对案例库做「留一法 mock 回测」。
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

# ============================================================
# §0：88 网格常量（与 T6.23 单测镜像对齐，一字节都不能差）
# ============================================================
THETA_GRID: List[float] = [round(0.65 + i * 0.03, 2) for i in range(11)]
GAMMA_GRID: List[float] = [round(0.05 + i * 0.03, 2) for i in range(8)]
assert len(THETA_GRID) == 11, f"θ 必须 11 档，实际 {len(THETA_GRID)}"
assert len(GAMMA_GRID) == 8,  f"γ 必须 8 档，实际 {len(GAMMA_GRID)}"
GRID_TOTAL = len(THETA_GRID) * len(GAMMA_GRID)
assert GRID_TOTAL == 88, f"必须 88 组合，实际 {GRID_TOTAL}"


def enumerate_grid() -> List[Tuple[float, float]]:
    """返回 88 组合的 (theta, gamma) 展开列表，用于外部迭代。"""
    return [(t, g) for t in THETA_GRID for g in GAMMA_GRID]


# ============================================================
# §1：加载案例库（schema v0.3，兼容占位合成/真实历史）
# ============================================================
def _load_cases(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    cases: List[Dict[str, Any]] = []
    bad_lines = 0
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                cases.append(json.loads(ln))
            except json.JSONDecodeError:
                bad_lines += 1
    if bad_lines:
        print(f"[CBR-CALIB] 警告：跳过 {bad_lines} 条坏 JSON 行")
    return cases


# ============================================================
# §2：骨架目标函数（Phase2 → WalkForwardBacktester）
# ============================================================
def _family_similarity(case_a: Dict[str, Any], case_b: Dict[str, Any]) -> float:
    """CBR v3.0 留一法家族相似度 proxy（∈ [0.20, 1.00]）。

    核心五维键 → 权重 70%：
      symbol 同=1 异=0, direction 同=1 异=0, hexagram_name 同=1 异=0,
      bcrm_confidence_bucket 同(EXTREME/HIGH/MEDIUM/LOW 枚举)=1 异=0,
      p1_output_label 同=1 异=0.5 差=0
    形态键 → 权重 30%：
      bcrm_confidence 绝对差 × (-1) 线性映射到 [0, 1]
    """
    es_a = case_a.get("entry_snapshot") or {}
    es_b = case_b.get("entry_snapshot") or {}
    score5 = 0.0
    score5 += 1.0 if case_a.get("symbol") == case_b.get("symbol") else 0.0
    score5 += 1.0 if str(case_a.get("direction")) == str(case_b.get("direction")) else 0.0
    score5 += 1.0 if (es_a.get("hexagram_name") and
                      es_a.get("hexagram_name") == es_b.get("hexagram_name")) else 0.0
    score5 += 1.0 if (es_a.get("bcrm_confidence_bucket") and
                      es_a.get("bcrm_confidence_bucket") == es_b.get("bcrm_confidence_bucket")) else 0.0
    lab_a = es_a.get("p1_output_label", "")
    lab_b = es_b.get("p1_output_label", "")
    if lab_a and lab_b:
        if lab_a == lab_b:
            score5 += 1.0
        elif {lab_a, lab_b} <= {"STANDARD", "WEAK"}:
            score5 += 0.5
        else:
            score5 += 0.0
    score5_norm = score5 / 5.0  # → [0, 1]
    conf_a = float(es_a.get("bcrm_confidence", 0.5))
    conf_b = float(es_b.get("bcrm_confidence", 0.5))
    conf_sim = max(0.0, 1.0 - 5.0 * abs(conf_a - conf_b))  # diff=0.2 → 0
    sim = 0.70 * score5_norm + 0.30 * conf_sim
    # clip 保证最小相似度 > 0（避免 θ=0.65 时没有 hit 样本）
    return max(0.20, min(1.0, sim))


def _evaluate_one_pair(theta: float, gamma: float,
                       cases: List[Dict[str, Any]], top_k: int = 3) -> Dict[str, Any]:
    """对单个 (θ, γ) 计算 signal_gain（LOO：留一法）。

    signal_gain = mean(pnl_pct | top1_match ≥ θ) − mean(pnl_pct | 未命中)
    反映「命中基线家族」能否显著区分后续实际盈亏。（γ 只影响 boost 公式，θ 影响 hit/miss 分桶）
    """
    if not cases:
        return {
            "theta": theta, "gamma": gamma,
            "n_hit": 0, "n_miss": 0,
            "pnl_hit": 0.0, "pnl_miss": 0.0,
            "signal_gain": 0.0,
        }

    pnl_hit: List[float] = []
    pnl_miss: List[float] = []
    n = len(cases)
    # 预计算：对每个 test case i，找其他 (n-1) 条的最大相似度 = top1_match（LOO）
    for i in range(n):
        c_i = cases[i]
        pnl_i = c_i.get("pnl_pct")
        if not isinstance(pnl_i, (int, float)):
            continue
        best_sim = 0.0
        for j in range(n):
            if i == j:
                continue
            sim = _family_similarity(c_i, cases[j])
            if sim > best_sim:
                best_sim = sim
        if best_sim >= theta:
            pnl_hit.append(float(pnl_i))
        else:
            pnl_miss.append(float(pnl_i))
    n_hit, n_miss = len(pnl_hit), len(pnl_miss)
    pnl_hit_avg = sum(pnl_hit) / n_hit if n_hit else 0.0
    pnl_miss_avg = sum(pnl_miss) / n_miss if n_miss else 0.0
    signal_gain = (pnl_hit_avg - pnl_miss_avg) if (n_hit and n_miss) else 0.0
    return {
        "theta": theta,
        "gamma": gamma,
        "n_hit": n_hit,
        "n_miss": n_miss,
        "pnl_hit": pnl_hit_avg,
        "pnl_miss": pnl_miss_avg,
        "signal_gain": signal_gain,
    }


# ============================================================
# §3：88 组合网格搜索主算法
# ============================================================
def grid_search(cases: List[Dict[str, Any]], top_k: int = 3,
                dry_run: bool = False) -> Dict[str, Any]:
    """枚举 88 组合，返回最佳 (θ*, γ*) 与完整结果表。

    dry_run=True：跳过逐组合 _evaluate_one_pair，只用占位 target=0，
    便于 T6.23 验证 88 组合枚举正确性。
    """
    results: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None
    for theta, gamma in enumerate_grid():
        if dry_run:
            row = {"theta": theta, "gamma": gamma,
                   "n_hit": 0, "n_miss": 0,
                   "pnl_hit": 0.0, "pnl_miss": 0.0, "signal_gain": 0.0}
        else:
            row = _evaluate_one_pair(theta, gamma, cases, top_k=top_k)
        results.append(row)
        if best is None or row["signal_gain"] > best["signal_gain"]:
            best = row
    return {
        "grid_total": GRID_TOTAL,
        "theta_grid": THETA_GRID,
        "gamma_grid": GAMMA_GRID,
        "best": best,
        "results": results,
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ============================================================
# §4：输出最优参数到 cbr_baseline_params.json（CBRJsonlStore 读它）
# ============================================================
def _write_output(output_path: Path, best: Dict[str, Any], quarter: str,
                  dry_run_best_only: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "theta_match_star": float(best["theta"]),
        "gamma_max_star": float(best["gamma"]),
        "meta": {
            "calibration_quarter": quarter,
            "calibrated_at": datetime.now().isoformat(timespec="seconds"),
            "grid_size": GRID_TOTAL,
            "signal_gain": float(best.get("signal_gain", 0.0)),
            "n_hit": int(best.get("n_hit", 0)),
            "n_miss": int(best.get("n_miss", 0)),
            "pnl_hit_avg": float(best.get("pnl_hit", 0.0)),
            "pnl_miss_avg": float(best.get("pnl_miss", 0.0)),
            "dry_run_placeholder": dry_run_best_only,
        },
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# §5：主 CLI
# ============================================================
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="CBR v3.0 基线家族 θ×γ 88 组合季度校准（最大化 signal_gain）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只验证 88 组合枚举 + 占位写默认最优，不跑目标函数")
    parser.add_argument("--cases", type=Path,
                        default=_THIS_DIR / "runtime" / "cbr_cases_v03.jsonl")
    parser.add_argument("--output", type=Path,
                        default=_THIS_DIR / "runtime" / "cbr_baseline_params.jsonl")
    parser.add_argument("--output-params", type=Path,
                        default=_THIS_DIR / "runtime" / "cbr_baseline_params.json")
    parser.add_argument("--quarter", default=f"{datetime.now().year}-Q{(datetime.now().month-1)//3+1}",
                        help="校准季度标签（元数据），如 2026-Q3")
    parser.add_argument("--top-k", type=int, default=3,
                        help="predict_topk 的 top_k（默认 3）")
    args = parser.parse_args(argv)

    print(f"[CBR-CALIB] Grid size: {len(THETA_GRID)} θ × {len(GAMMA_GRID)} γ = {GRID_TOTAL}")
    print(f"[CBR-CALIB] Cases file : {args.cases}")
    print(f"[CBR-CALIB] Output     : {args.output_params}")
    print(f"[CBR-CALIB] Quarter    : {args.quarter}")

    cases = _load_cases(args.cases)
    print(f"[CBR-CALIB] Loaded {len(cases)} 条案例")

    report = grid_search(cases, top_k=args.top_k, dry_run=args.dry_run)
    best = report["best"] or {"theta": 0.80, "gamma": 0.20, "signal_gain": 0.0}

    # 写最优参数 JSON（CBRJsonlStore 读的那个）
    _write_output(args.output_params, best, args.quarter,
                  dry_run_best_only=args.dry_run)

    # 写完整报告（调试用，大 JSON）
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "quarter": args.quarter,
        "best_theta": best["theta"],
        "best_gamma": best["gamma"],
        "best_signal_gain": round(float(best.get("signal_gain", 0.0)), 6),
        "n_hit": best.get("n_hit", 0),
        "n_miss": best.get("n_miss", 0),
        "grid_total": GRID_TOTAL,
        "dry_run": args.dry_run,
        "cases": len(cases),
        "params_output": str(args.output_params),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
