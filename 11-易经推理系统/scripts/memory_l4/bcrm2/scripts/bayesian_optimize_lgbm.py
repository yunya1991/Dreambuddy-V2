"""贝叶斯超参搜索 — Optuna TPE 优化 LGBM 概率校正器超参

目标: 最大化 WalkForward 5 折 Macro F1 融合后均值
搜索空间:
  - n_estimators: [50, 300]
  - learning_rate: [0.01, 0.2] (log)
  - num_leaves: [7, 63]
  - max_depth: [3, 8]
  - reg_alpha: [0.01, 10.0] (log)
  - reg_lambda: [0.01, 20.0] (log)
  - min_child_samples: [5, 50]
  - colsample_bytree: [0.5, 1.0]
  - subsample: [0.5, 1.0]
  - w_gauss: [0.3, 0.8]
  - temperature: [0.3, 1.0]

用法:
  python bayesian_optimize_lgbm.py --csv ../../data/klines/BTC_1D_full.csv --n-trials 50 --out ../../artifacts/evolution_btc/best_params.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

_THIS = Path(__file__).resolve()
_MEMORY_L4 = _THIS.parent.parent.parent
if str(_MEMORY_L4) not in sys.path:
    sys.path.insert(0, str(_MEMORY_L4))

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

from bcrm2.indicators import IndicatorBank
from bcrm2.score_composer import ScoreComposer
from bcrm2.temporal_smoother import TemporalSmoother
from bcrm2.regime_mapper import RegimeMapper, REGIME_ORDER
from bcrm2.labels.regime_labeler import generate_8state_label, REGIME_CODE
from bcrm2.walk_forward_splitter import walk_forward_time_series_split
from bcrm2.lgbm_calibrator import LGBMCalibrator


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


def _compute_level_trend(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    bank = IndicatorBank()
    indicators = bank.compute_all(df)
    composer = ScoreComposer()
    level_raw, trend_raw = composer.compose(indicators, df)
    smoother = TemporalSmoother(n_hmm_states=3, random_state=42)
    so = smoother.transform(level_raw, trend_raw)
    return so.level_smooth, so.trend_smooth


def _compute_features(df: pd.DataFrame, feature_set: str = "btc_morphology_v6") -> pd.DataFrame:
    import importlib as _il
    for _m in ("classic_experience_features", "ma200_cycle_features",
               "multi_timeframe_features", "rolling_regime_stats",
               "sector_beta_pool"):
        try:
            _il.import_module(f"bcrm2.{_m}")
        except Exception:
            pass
    from bcrm2.feature_registry import FeatureRegistry
    feats_df, _ = FeatureRegistry.compute_all(df, enabled_set=feature_set, verbose=False)
    return feats_df


def _evaluate_fold_with_params(
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    df: pd.DataFrame,
    level_smooth: pd.Series,
    trend_smooth: pd.Series,
    labels: pd.Series,
    feats_df: pd.DataFrame,
    params: Dict,
) -> Tuple[float, float]:
    """单折评估：返回 (macro_f1_fused, top3_hit_rate_fused)。"""
    # 校准 centers
    train_labels = labels.iloc[train_idx]
    train_valid = train_labels.notna()
    train_L = level_smooth.iloc[train_idx][train_valid]
    train_T = trend_smooth.iloc[train_idx][train_valid]

    centers = {}
    for regime in REGIME_ORDER:
        mask = (train_labels == regime) & train_valid
        n = int(mask.sum())
        if n >= 30:
            centers[regime] = (float(train_L[mask].mean()), float(train_T[mask].mean()))
        else:
            from bcrm2.regime_mapper import REGIME_CENTERS
            centers[regime] = REGIME_CENTERS[regime]

    mapper = RegimeMapper(centers=centers, softmax_temperature=0.6)

    # LGBM 训练
    X_train_full = feats_df.iloc[train_idx].copy()
    y_train_full = train_labels.reset_index(drop=True)
    valid_mask = y_train_full.notna()
    X_tr = X_train_full.loc[valid_mask.values].copy()
    y_tr = y_train_full.loc[valid_mask.values].copy()
    X_tr.index = pd.RangeIndex(len(X_tr))
    y_tr.index = pd.RangeIndex(len(y_tr))

    calibrator = None
    if len(X_tr) >= 100:
        cal = LGBMCalibrator(random_state=42)
        try:
            cal.fit(
                X_tr, y_tr, schema_path="/tmp/_optuna_lgbm_schema.json",
                n_estimators=params["n_estimators"],
                learning_rate=params["learning_rate"],
                num_leaves=params["num_leaves"],
                max_depth=params["max_depth"],
                reg_alpha=params["reg_alpha"],
                reg_lambda=params["reg_lambda"],
                min_child_samples=params["min_child_samples"],
                colsample_bytree=params["colsample_bytree"],
                subsample=params["subsample"],
                subsample_freq=1,
                regime_order=list(REGIME_ORDER),
                class_weight="balanced",
            )
            calibrator = cal
        except Exception:
            calibrator = None

    # Test 段
    test_labels = labels.iloc[test_idx]
    test_valid_mask = test_labels.notna()
    test_L = level_smooth.iloc[test_idx]
    test_T = trend_smooth.iloc[test_idx]

    y_true = []
    y_pred_fused = []
    top3_hits_fused = 0
    n_valid = 0

    gauss_probs_list: List[np.ndarray] = []
    valid_test_indices: List[int] = []

    for i in range(len(test_labels)):
        if not test_valid_mask.iloc[i]:
            continue
        true_label = test_labels.iloc[i]
        L_val = float(test_L.iloc[i])
        T_val = float(test_T.iloc[i])

        mr = mapper.map_frame(L_val, T_val)
        p_gauss = np.array([mr["regime_probs"][r] for r in REGIME_ORDER])
        gauss_probs_list.append(p_gauss)
        valid_test_indices.append(i)
        y_true.append(REGIME_CODE[true_label])
        n_valid += 1

    # calibrate 融合
    p_fused_arr = None
    if calibrator is not None and len(valid_test_indices) > 0:
        valid_positions = [test_idx[i] for i in valid_test_indices]
        X_valid = feats_df.iloc[valid_positions].copy()
        X_valid.index = pd.RangeIndex(len(X_valid))
        p_gauss_arr = np.array(gauss_probs_list)
        try:
            # 临时覆盖全局融合权重
            import bcrm2.lgbm_calibrator as _lc_mod
            _orig_wg = _lc_mod.W_GAUSS
            _orig_wl = _lc_mod.W_LGBM
            _orig_t = _lc_mod.TEMPERATURE
            _lc_mod.W_GAUSS = params["w_gauss"]
            _lc_mod.W_LGBM = 1.0 - params["w_gauss"]
            _lc_mod.TEMPERATURE = params["temperature"]
            p_fused_arr = calibrator.calibrate(p_gauss_arr, X_valid)
            _lc_mod.W_GAUSS = _orig_wg
            _lc_mod.W_LGBM = _orig_wl
            _lc_mod.TEMPERATURE = _orig_t
        except Exception:
            p_fused_arr = None
            _lc_mod.W_GAUSS = _orig_wg
            _lc_mod.W_LGBM = _orig_wl
            _lc_mod.TEMPERATURE = _orig_t

    if p_fused_arr is not None:
        for j in range(len(valid_test_indices)):
            p_fused = p_fused_arr[j]
            top3_idx = np.argsort(-p_fused)[:3]
            true_label = test_labels.iloc[valid_test_indices[j]]
            top3_names = [REGIME_ORDER[idx] for idx in top3_idx]
            if true_label in top3_names:
                top3_hits_fused += 1
            y_pred_fused.append(int(np.argmax(p_fused)))
    else:
        # 退化为纯高斯
        for j in range(len(valid_test_indices)):
            p_g = gauss_probs_list[j]
            top3_idx = np.argsort(-p_g)[:3]
            true_label = test_labels.iloc[valid_test_indices[j]]
            top3_names = [REGIME_ORDER[idx] for idx in top3_idx]
            if true_label in top3_names:
                top3_hits_fused += 1
            y_pred_fused.append(int(np.argmax(p_g)))

    macro_f1 = f1_score(y_true, y_pred_fused, average="macro", labels=list(range(8)), zero_division=0)
    top3_rate = top3_hits_fused / max(1, n_valid)
    return float(macro_f1), top3_rate


def run_optimization(
    csv_path: Path,
    n_trials: int = 50,
    n_splits: int = 5,
    feature_set: str = "btc_morphology_v6",
    out_path: Optional[Path] = None,
) -> Dict:
    """运行 Optuna TPE 搜索。"""
    df = _read_csv(csv_path)
    n = len(df)
    print(f"[Optuna] 数据 {csv_path} ({n} 条)")

    level_smooth, trend_smooth = _compute_level_trend(df)
    labels = generate_8state_label(df, forward_days=20, lookback=252)
    feats_df = _compute_features(df, feature_set)
    print(f"[Optuna] 特征形状 {feats_df.shape} ({feature_set})")

    folds = list(walk_forward_time_series_split(n, n_splits=n_splits, gap=20, expanding=True))

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 50, 300),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 7, 63),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "reg_alpha": trial.suggest_float("reg_alpha", 0.01, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 0.01, 20.0, log=True),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "w_gauss": trial.suggest_float("w_gauss", 0.3, 0.8),
            "temperature": trial.suggest_float("temperature", 0.3, 1.0),
        }

        f1s = []
        for k, (train_idx, test_idx) in enumerate(folds):
            try:
                f1, _ = _evaluate_fold_with_params(
                    train_idx, test_idx, df,
                    level_smooth, trend_smooth, labels,
                    feats_df, params,
                )
                f1s.append(f1)
            except Exception as e:
                print(f"  [Trial {trial.number}] Fold {k+1} 失败: {e}", flush=True)
                f1s.append(0.0)

        mean_f1 = float(np.mean(f1s))
        trial.set_user_attr("folds_f1", [round(f, 4) for f in f1s])
        return mean_f1

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_trial
    result = {
        "best_macro_f1": round(best.value, 4),
        "best_params": dict(best.params),
        "best_trial_folds_f1": best.user_attrs.get("folds_f1", []),
        "n_trials": n_trials,
        "feature_set": feature_set,
        "n_samples": n,
        "n_features": int(feats_df.shape[1]),
        "all_trials_summary": [
            {
                "trial": t.number,
                "macro_f1": round(t.value, 4) if t.value is not None else None,
                "params": {k: round(v, 4) if isinstance(v, float) else v for k, v in t.params.items()},
            }
            for t in study.trials
            if t.value is not None
        ],
    }

    print(f"\n=== Optuna 搜索结果 ===")
    print(f"  最佳 Macro F1: {best.value:.4f}")
    print(f"  最佳参数:")
    for k, v in best.params.items():
        print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[Optuna] 结果已写入 {out_path}")

    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="贝叶斯超参搜索 — Optuna TPE 优化 LGBM 概率校正器")
    p.add_argument("--csv", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--n-trials", type=int, default=50, help="Optuna 搜索次数（默认 50）")
    p.add_argument("--n-splits", type=int, default=5)
    p.add_argument("--feature-set", default="btc_morphology_v6")
    args = p.parse_args(argv)

    out_p = Path(args.out).resolve() if args.out else None
    run_optimization(
        csv_path=Path(args.csv).resolve(),
        n_trials=args.n_trials,
        n_splits=args.n_splits,
        feature_set=args.feature_set,
        out_path=out_p,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
