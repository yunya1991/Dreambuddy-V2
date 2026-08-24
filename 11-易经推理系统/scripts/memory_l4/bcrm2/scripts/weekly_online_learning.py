"""P3.4 周度在线学习 batch 脚本

用法:
  python weekly_online_learning.py --csv ../../data/klines/BTC_1D_full.csv --storage ../../artifacts/evolution_btc/evolution.db

搜索空间:
  - Level 6 权重 × [0.90, 1.00, 1.10] 乘数 (整体)
  - Trend 5 权重 × [0.90, 1.00, 1.10] 乘数 (整体)
  - MAX_DAILY_DELTA ∈ {0.3, 0.4, 0.5, 0.6, 0.8}
  - 8 态中心 ± {0, 0.3} → 随机采样 128 次

目标函数: Top-3 × 0.40 - ContinuityLoss × 0.25 + MacroF1 × 0.20 + Consensus-R² × 0.15

决策规则: 若相比上周目标函数下降 ≥ 2% → REJECTED，保留上周
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

_THIS = Path(__file__).resolve()
_MEMORY_L4 = _THIS.parent.parent.parent
if str(_MEMORY_L4) not in sys.path:
    sys.path.insert(0, str(_MEMORY_L4))

from bcrm2.indicators import IndicatorBank
from bcrm2.score_composer import ScoreComposer, DEFAULT_LEVEL_WEIGHTS, DEFAULT_TREND_WEIGHTS
from bcrm2.temporal_smoother import TemporalSmoother
from bcrm2.regime_mapper import RegimeMapper, REGIME_ORDER, REGIME_CENTERS
from bcrm2.labels.regime_labeler import generate_8state_label, REGIME_CODE
from bcrm2.storage import EvolutionStorageSQLite
from bcrm2.walk_forward_splitter import walk_forward_time_series_split


def _read_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    ts_cols = [c for c in df.columns if c.lower() in {"timestamp", "datetime", "date"}]
    if ts_cols:
        df[ts_cols[0]] = pd.to_datetime(df[ts_cols[0]])
        df = df.set_index(ts_cols[0])
    else:
        df.index = pd.to_datetime(df.index)
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = df[c].astype(float)
    return df.sort_index()


def _evaluate_params(
    df: pd.DataFrame,
    indicators: dict,
    labels: pd.Series,
    level_mult: float,
    trend_mult: float,
    max_daily_delta: float,
    centers: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, float]:
    """用给定参数重算 Level/Trend 并评估目标函数。"""
    # 构造带乘数的权重
    lw = {k: v * level_mult for k, v in DEFAULT_LEVEL_WEIGHTS.items()}
    tw = {k: v * trend_mult for k, v in DEFAULT_TREND_WEIGHTS.items()}

    composer = ScoreComposer(
        level_weights=lw, trend_weights=tw,
        max_daily_delta=max_daily_delta,
    )
    level_raw, trend_raw = composer.compose(indicators, df)
    smoother = TemporalSmoother(n_hmm_states=3, random_state=42)
    so = smoother.transform(level_raw, trend_raw)

    # Mapper
    if centers is None:
        mapper = RegimeMapper()
    else:
        mapper = RegimeMapper(centers=centers, softmax_temperature=0.6)

    # 用最后 252 天评估
    n = len(df)
    eval_start = max(0, n - 252)
    L_eval = so.level_smooth.iloc[eval_start:]
    T_eval = so.trend_smooth.iloc[eval_start:]
    labels_eval = labels.iloc[eval_start:]

    valid = labels_eval.notna()
    L_v = L_eval[valid]
    T_v = T_eval[valid]
    labels_v = labels_eval[valid]

    if len(labels_v) < 20:
        return {"objective": -1.0, "top3": 0.0, "macro_f1": 0.0, "continuity": 0.0, "consensus_r2": 0.0}

    y_true = []
    y_pred = []
    top3_hits = 0
    consensus_vals = []

    for i in range(len(labels_v)):
        L_val = float(L_v.iloc[i])
        T_val = float(T_v.iloc[i])
        true_label = labels_v.iloc[i]

        mr = mapper.map_frame(L_val, T_val)
        top3_names = [r for r, _ in mr["top3"]]

        if true_label in top3_names:
            top3_hits += 1

        probs_arr = np.array([mr["regime_probs"][r] for r in REGIME_ORDER])
        y_true.append(REGIME_CODE[true_label])
        y_pred.append(int(np.argmax(probs_arr)))

        consensus_vals.append(float(mr["consensus"]))

    top3 = top3_hits / len(labels_v)
    macro_f1 = f1_score(y_true, y_pred, average="macro", labels=list(range(8)), zero_division=0)

    # 连续性 loss = mean(|ΔL| + |ΔT|)
    dL = np.abs(np.diff(so.level_smooth.values))
    dT = np.abs(np.diff(so.trend_smooth.values))
    continuity_loss = float(np.mean(dL + dT))

    # consensus R² (vs forward return)
    consensus_arr = np.array(consensus_vals)
    close_eval = df["close"].iloc[eval_start:].values
    valid_indices = np.arange(len(consensus_arr))
    fwd_ret = []
    consensus_aligned = []
    for i in valid_indices:
        pos = eval_start + np.where(valid.values)[0][i]
        if pos + 20 < n:
            fr = np.log(close_eval[pos + 20 - eval_start] / close_eval[pos - eval_start]) if (pos - eval_start + 20) < len(close_eval) else 0.0
            fwd_ret.append(float(fr))
            consensus_aligned.append(consensus_arr[i])

    consensus_r2 = 0.0
    if len(consensus_aligned) >= 20:
        c = np.array(consensus_aligned)
        r = np.array(fwd_ret)
        if np.std(c) > 1e-8 and np.std(r) > 1e-8:
            consensus_r2 = float(np.corrcoef(c, r)[0, 1] ** 2)

    # 目标函数
    objective = (
        top3 * 0.40
        - min(continuity_loss, 1.0) * 0.25
        + macro_f1 * 0.20
        + consensus_r2 * 0.15
    )

    return {
        "objective": round(float(objective), 6),
        "top3": round(float(top3), 4),
        "macro_f1": round(float(macro_f1), 4),
        "continuity": round(float(continuity_loss), 4),
        "consensus_r2": round(float(consensus_r2), 4),
    }


def run_weekly_learning(csv_path: Path, storage: Optional[EvolutionStorageSQLite] = None) -> Dict:
    df = _read_csv(csv_path)
    n = len(df)
    print(f"[P3.4] 读取 {csv_path} ({n} 条)")

    bank = IndicatorBank()
    indicators = bank.compute_all(df)
    labels = generate_8state_label(df, forward_days=20, lookback=252)

    # 上周权重
    prev_weights = None
    prev_obj = None
    if storage is not None:
        prev_weights = storage.get_latest_weights()
        if prev_weights:
            prev_obj = prev_weights.get("objective")

    print(f"[P3.4] 上周 objective = {prev_obj}")

    # ===== Phase 1: 基础网格搜索 (45 组) =====
    best_base = None
    best_base_obj = -1.0
    level_mults = [0.9, 1.0, 1.1]
    trend_mults = [0.9, 1.0, 1.1]
    deltas = [0.3, 0.4, 0.5, 0.6, 0.8]

    print(f"[P3.4] Phase 1: 基础网格搜索 ({len(level_mults)*len(trend_mults)*len(deltas)} 组) ...")
    for lm in level_mults:
        for tm in trend_mults:
            for md in deltas:
                result = _evaluate_params(df, indicators, labels, lm, tm, md)
                if result["objective"] > best_base_obj:
                    best_base_obj = result["objective"]
                    best_base = {
                        "level_mult": lm, "trend_mult": tm,
                        "max_daily_delta": md, **result,
                    }

    print(f"[P3.4] Phase 1 最优: obj={best_base_obj:.6f}  "
          f"(L×{best_base['level_mult']}, T×{best_base['trend_mult']}, delta={best_base['max_daily_delta']})")

    # ===== Phase 2: 随机中心采样 (128 次) =====
    print(f"[P3.4] Phase 2: 随机中心采样 (128 次) ...")
    rng = np.random.RandomState(42)
    best_overall = best_base
    best_overall_obj = best_base_obj

    # 用 best_base 的参数作为基础
    base_centers = dict(REGIME_CENTERS)

    for trial in range(128):
        # 随机扰动每个中心 ±0.3
        perturbed = {}
        for regime in REGIME_ORDER:
            dl = rng.choice([-0.3, 0.0, 0.3])
            dt = rng.choice([-0.3, 0.0, 0.3])
            orig_l, orig_t = base_centers[regime]
            perturbed[regime] = (orig_l + dl, orig_t + dt)

        result = _evaluate_params(
            df, indicators, labels,
            best_base["level_mult"], best_base["trend_mult"],
            best_base["max_daily_delta"],
            centers=perturbed,
        )
        if result["objective"] > best_overall_obj:
            best_overall_obj = result["objective"]
            best_overall = {
                **best_base,
                "centers": {r: [round(c[0], 2), round(c[1], 2)] for r, c in perturbed.items()},
                **result,
            }
            print(f"  trial {trial}: obj={best_overall_obj:.6f} (improved)")

    print(f"\n[P3.4] Phase 2 最优: obj={best_overall_obj:.6f}")

    # ===== 决策 =====
    decision = "accepted"
    if prev_obj is not None:
        change_pct = (best_overall_obj - prev_obj) / max(abs(prev_obj), 1e-8) * 100
        if change_pct <= -2.0:
            decision = "rejected"
            print(f"[P3.4] REJECTED: obj {prev_obj:.6f} → {best_overall_obj:.6f} ({change_pct:+.2f}%)")
            # 保留上周
            best_overall = {
                **best_overall,
                "objective": prev_obj,
                "comment": "rejected",
            }
        else:
            print(f"[P3.4] ACCEPTED: obj {prev_obj:.6f} → {best_overall_obj:.6f} ({change_pct:+.2f}%)")
            best_overall["comment"] = "accepted"
    else:
        print(f"[P3.4] 首次运行，直接接受: obj={best_overall_obj:.6f}")
        best_overall["comment"] = "initial"

    # ===== 保存到 SQLite =====
    weights_obj = {
        "level_weights": {k: round(v * best_overall["level_mult"], 4)
                          for k, v in DEFAULT_LEVEL_WEIGHTS.items()},
        "trend_weights": {k: round(v * best_overall["trend_mult"], 4)
                          for k, v in DEFAULT_TREND_WEIGHTS.items()},
        "regime_centers": best_overall.get("centers") or
                          {r: list(c) for r, c in REGIME_CENTERS.items()},
        "max_daily_delta": best_overall["max_daily_delta"],
    }

    if storage is not None and decision != "rejected":
        week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        storage.save_weekly_weights(
            week_start, weights_obj,
            objective=best_overall_obj,
            comment=decision,
        )
        print(f"[P3.4] 已保存到 SQLite (week_start={week_start})")

    # Summary
    summary = {
        "prev_obj": prev_obj,
        "new_obj": best_overall_obj,
        "decision": decision,
        "best_params": {
            "level_mult": best_overall["level_mult"],
            "trend_mult": best_overall["trend_mult"],
            "max_daily_delta": best_overall["max_daily_delta"],
        },
        "metrics": {
            "top3": best_overall.get("top3", 0),
            "macro_f1": best_overall.get("macro_f1", 0),
            "continuity": best_overall.get("continuity", 0),
            "consensus_r2": best_overall.get("consensus_r2", 0),
        },
        "weights": weights_obj,
    }
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="P3.4 周度在线学习 batch")
    p.add_argument("--csv", required=True)
    p.add_argument("--storage", default=None, help="SQLite DB 路径")
    args = p.parse_args(argv)

    storage = None
    if args.storage:
        db_path = Path(args.storage).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        storage = EvolutionStorageSQLite(db_path)

    summary = run_weekly_learning(Path(args.csv).resolve(), storage)

    print("\n=== Summary ===")
    print(f"  prev_obj: {summary['prev_obj']}")
    print(f"  new_obj:  {summary['new_obj']:.6f}")
    print(f"  decision: {summary['decision']}")
    print(f"  best: L×{summary['best_params']['level_mult']}, "
          f"T×{summary['best_params']['trend_mult']}, "
          f"delta={summary['best_params']['max_daily_delta']}")
    print(f"  top3={summary['metrics']['top3']}, "
          f"f1={summary['metrics']['macro_f1']}, "
          f"continuity={summary['metrics']['continuity']}, "
          f"r2={summary['metrics']['consensus_r2']}")

    if storage is not None:
        storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
