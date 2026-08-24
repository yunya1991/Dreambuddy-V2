"""P3.2 WalkForward 5 折 Top-3 命中率 + Macro F1 回测基线

用法:
  python eval_walkforward.py --csv ../../data/klines/BTC_1D_full.csv --out ../../artifacts/evolution_btc/wf_baseline.json
  python eval_walkforward.py --csv ... --with-lgbm --out wf_lgbm.json

每折:
  - Train 段: 校准 REGIME_CENTERS (标签均值) + 训练 LGBM 校正器（--with-lgbm 时）
  - Test 段: 高斯软分配概率 → （可选）LGBM calibrate 融合 → argmax / Top-3 统计
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

from bcrm2.indicators import IndicatorBank
from bcrm2.score_composer import ScoreComposer
from bcrm2.temporal_smoother import TemporalSmoother
from bcrm2.regime_mapper import RegimeMapper, REGIME_ORDER
from bcrm2.labels.regime_labeler import generate_8state_label, REGIME_CODE
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


def _compute_level_trend(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    bank = IndicatorBank()
    indicators = bank.compute_all(df)
    composer = ScoreComposer()
    level_raw, trend_raw = composer.compose(indicators, df)
    smoother = TemporalSmoother(n_hmm_states=3, random_state=42)
    so = smoother.transform(level_raw, trend_raw)
    return so.level_smooth, so.trend_smooth, level_raw, trend_raw


def _compute_features(df: pd.DataFrame, feature_set: str = "btc_morphology_v6") -> pd.DataFrame:
    """预计算整段特征（滚动窗口特征，不泄露未来）。"""
    # 显式 import 所有涉及的特征模块，触发 FeatureRegistry.register
    import importlib as _il
    for _mod_name in ("classic_experience_features", "ma200_cycle_features",
                       "multi_timeframe_features", "rolling_regime_stats",
                       "sector_beta_pool"):
        try:
            _il.import_module(f"bcrm2.{_mod_name}")
        except Exception:
            pass
    from bcrm2.feature_registry import FeatureRegistry
    feats_df, _ = FeatureRegistry.compute_all(df, enabled_set=feature_set, verbose=False)
    return feats_df


def _evaluate_fold(
    train_idx: np.ndarray, test_idx: np.ndarray,
    df: pd.DataFrame, level_smooth: pd.Series, trend_smooth: pd.Series,
    labels: pd.Series,
    feats_df: Optional[pd.DataFrame] = None,
    with_lgbm: bool = False,
    tuned_params: Optional[Dict] = None,
) -> Dict:
    # Train 段: 校准 centers
    train_labels = labels.iloc[train_idx]
    train_valid = train_labels.notna()
    train_L = level_smooth.iloc[train_idx][train_valid]
    train_T = trend_smooth.iloc[train_idx][train_valid]

    centers = {}
    for regime in REGIME_ORDER:
        mask = (train_labels == regime) & train_valid
        n = int(mask.sum())
        if n >= 30:
            centers[regime] = (
                float(train_L[mask].mean()),
                float(train_T[mask].mean()),
            )
        else:
            from bcrm2.regime_mapper import REGIME_CENTERS
            centers[regime] = REGIME_CENTERS[regime]

    mapper = RegimeMapper(centers=centers, softmax_temperature=0.6)

    # LGBM 校正器训练（在 train 段，避免数据泄露）
    calibrator = None
    if with_lgbm and feats_df is not None:
        from bcrm2.lgbm_calibrator import LGBMCalibrator
        # train_idx 是整数位置；feats_df 的 index 是时间戳，用 iloc 取行
        X_train_full = feats_df.iloc[train_idx].copy()
        y_train_full = train_labels.reset_index(drop=True)
        valid_mask = y_train_full.notna()
        X_tr = X_train_full.loc[valid_mask.values].copy()
        y_tr = y_train_full.loc[valid_mask.values].copy()
        # 重置 index 为 RangeIndex，保证 schema 校验通过
        X_tr.index = pd.RangeIndex(len(X_tr))
        y_tr.index = pd.RangeIndex(len(y_tr))
        if len(X_tr) >= 100:
            cal = LGBMCalibrator(random_state=42)
            try:
                # 使用 tuned_params 覆盖默认超参；无 tuned_params 时用强正则默认值
                tp = tuned_params or {}
                cal.fit(
                    X_tr, y_tr, schema_path="/tmp/_wf_lgbm_schema.json",
                    n_estimators=tp.get("n_estimators", 80),
                    learning_rate=tp.get("learning_rate", 0.05),
                    num_leaves=tp.get("num_leaves", 15),
                    max_depth=tp.get("max_depth", 4),
                    reg_alpha=tp.get("reg_alpha", 1.0),
                    reg_lambda=tp.get("reg_lambda", 5.0),
                    min_child_samples=tp.get("min_child_samples", 15),
                    colsample_bytree=tp.get("colsample_bytree", 0.8),
                    subsample=tp.get("subsample", 0.8),
                    subsample_freq=1,
                    regime_order=list(REGIME_ORDER),
                    class_weight="balanced",
                )
                calibrator = cal
                tag = "tuned" if tuned_params else "default"
                print(f"    [LGBM] 训练完成（{len(X_tr)} 样本，{X_tr.shape[1]} 特征，balanced+{tag}）", flush=True)
            except Exception as e:
                print(f"    [LGBM] 训练失败，退化为纯高斯: {e}", flush=True)
                calibrator = None
        else:
            print(f"    [LGBM] 训练样本不足（{len(X_tr)} < 100），退化为纯高斯", flush=True)

    # Test 段: 评估
    test_labels = labels.iloc[test_idx]
    test_valid_mask = test_labels.notna()
    test_L = level_smooth.iloc[test_idx]
    test_T = trend_smooth.iloc[test_idx]

    y_true = []
    y_pred_gauss = []
    y_pred_fused = []
    top3_hits_gauss = 0
    top3_hits_fused = 0
    n_valid = 0
    consensus_vals = []
    fwd_ret_vals = []

    # 预提取 test 段特征（批量 calibrate，比逐帧快）
    X_test_full: Optional[pd.DataFrame] = None
    if calibrator is not None and feats_df is not None:
        X_test_full = feats_df.iloc[test_idx]

    # 收集所有有效 test 样本的高斯概率，用于批量 calibrate
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

        # 纯高斯 Top-3 + argmax
        top3_names = [r for r, _ in mr["top3"]]
        if true_label in top3_names:
            top3_hits_gauss += 1
        y_true.append(REGIME_CODE[true_label])
        y_pred_gauss.append(int(np.argmax(p_gauss)))

        consensus_vals.append(float(mr["consensus"]))

        orig_idx = test_idx[i]
        if orig_idx + 20 < len(df):
            fwd_ret = np.log(df["close"].iloc[orig_idx + 20] / df["close"].iloc[orig_idx])
            fwd_ret_vals.append(float(fwd_ret))

        n_valid += 1

    # LGBM calibrate 批量融合
    p_fused_arr: Optional[np.ndarray] = None
    if calibrator is not None and X_test_full is not None and len(valid_test_indices) > 0:
        # 构造有效样本的 X（保持 schema 列顺序）。valid_pos 是 test_idx 中的整数位置，用 iloc
        valid_positions = [test_idx[i] for i in valid_test_indices]
        X_valid = feats_df.iloc[valid_positions].copy()
        # 重置 index 为 RangeIndex，避免 DataFrame 索引差异引发 schema 校验问题
        X_valid.index = pd.RangeIndex(len(X_valid))
        p_gauss_arr = np.array(gauss_probs_list)  # shape (n_valid, 8), 列顺序 == REGIME_ORDER
        # 若有 tuned 融合权重，临时覆盖全局 W_GAUSS/W_LGBM/TEMPERATURE
        _lc_mod = None
        _orig_wg = _orig_wl = _orig_t = None
        if tuned_params and ("w_gauss" in tuned_params or "temperature" in tuned_params):
            import bcrm2.lgbm_calibrator as _lc_mod
            _orig_wg = _lc_mod.W_GAUSS
            _orig_wl = _lc_mod.W_LGBM
            _orig_t = _lc_mod.TEMPERATURE
            _lc_mod.W_GAUSS = tuned_params.get("w_gauss", _orig_wg)
            _lc_mod.W_LGBM = 1.0 - _lc_mod.W_GAUSS
            _lc_mod.TEMPERATURE = tuned_params.get("temperature", _orig_t)
        try:
            p_fused_arr = calibrator.calibrate(p_gauss_arr, X_valid)
        except Exception as e:
            print(f"    [LGBM] calibrate 失败，退化为纯高斯: {e}", flush=True)
            p_fused_arr = None
        finally:
            if _lc_mod is not None:
                _lc_mod.W_GAUSS = _orig_wg
                _lc_mod.W_LGBM = _orig_wl
                _lc_mod.TEMPERATURE = _orig_t

    # 统计融合后指标
    if p_fused_arr is not None:
        for j, true_label in enumerate([test_labels.iloc[i] for i in valid_test_indices]):
            p_fused = p_fused_arr[j]
            top3_idx_fused = np.argsort(-p_fused)[:3]
            top3_names_fused = [REGIME_ORDER[idx] for idx in top3_idx_fused]
            if true_label in top3_names_fused:
                top3_hits_fused += 1
            y_pred_fused.append(int(np.argmax(p_fused)))
    else:
        # 未融合时，fused 指标 = gauss 指标
        top3_hits_fused = top3_hits_gauss
        y_pred_fused = list(y_pred_gauss)

    top3_rate_gauss = top3_hits_gauss / max(1, n_valid)
    top3_rate_fused = top3_hits_fused / max(1, n_valid)
    macro_f1_gauss = f1_score(y_true, y_pred_gauss, average="macro", labels=list(range(8)), zero_division=0)
    macro_f1_fused = f1_score(y_true, y_pred_fused, average="macro", labels=list(range(8)), zero_division=0)

    # Consensus vs fwd_ret R²
    consensus_r2 = 0.0
    if len(consensus_vals) >= 20 and len(fwd_ret_vals) >= 20:
        min_len = min(len(consensus_vals), len(fwd_ret_vals))
        c_arr = np.array(consensus_vals[:min_len])
        r_arr = np.array(fwd_ret_vals[:min_len])
        if np.std(c_arr) > 1e-8 and np.std(r_arr) > 1e-8:
            consensus_r2 = float(np.corrcoef(c_arr, r_arr)[0, 1] ** 2)

    label_dist = {}
    for r in REGIME_ORDER:
        label_dist[r] = int((test_labels == r).sum())

    return {
        "train_size": int(len(train_idx)),
        "test_size": int(len(test_idx)),
        "test_valid": n_valid,
        "top3_hit_rate": round(top3_rate_gauss, 4),
        "top3_hit_rate_fused": round(top3_rate_fused, 4),
        "macro_f1": round(float(macro_f1_gauss), 4),
        "macro_f1_fused": round(float(macro_f1_fused), 4),
        "consensus_r2": round(consensus_r2, 4),
        "lgbm_enabled": calibrator is not None,
        "label_distribution": label_dist,
        "centers_calibrated": {r: [round(c[0], 2), round(c[1], 2)] for r, c in centers.items()},
    }


def run_walkforward(csv_path: Path, n_splits: int = 5, with_lgbm: bool = False,
                    feature_set: str = "btc_morphology_v6",
                    tuned_params: Optional[Dict] = None) -> Dict:
    df = _read_csv(csv_path)
    n = len(df)
    print(f"[P3.2] 读取 {csv_path} ({n} 条)")

    level_smooth, trend_smooth, _, _ = _compute_level_trend(df)
    labels = generate_8state_label(df, forward_days=20, lookback=252)

    # 预计算特征（滚动窗口，不泄露未来）
    feats_df: Optional[pd.DataFrame] = None
    if with_lgbm:
        print(f"[P3.2] 预计算 LGBM 特征池（{feature_set}）...", flush=True)
        feats_df = _compute_features(df, feature_set)
        print(f"[P3.2] 特征形状 {feats_df.shape}，列 {list(feats_df.columns)[:3]}... 共 {len(feats_df.columns)} 列", flush=True)

    folds: List[Dict] = []
    for k, (train_idx, test_idx) in enumerate(
        walk_forward_time_series_split(n, n_splits=n_splits, gap=20, expanding=True)
    ):
        print(f"\n--- Fold {k+1}/{n_splits} ---")
        print(f"  train: [0, {train_idx[-1]}]  ({len(train_idx)} 条)")
        print(f"  test:  [{test_idx[0]}, {test_idx[-1]}]  ({len(test_idx)} 条)")

        fold_result = _evaluate_fold(
            train_idx, test_idx, df, level_smooth, trend_smooth, labels,
            feats_df=feats_df, with_lgbm=with_lgbm, tuned_params=tuned_params,
        )
        folds.append(fold_result)
        print(f"  [Gauss]  Top-3: {fold_result['top3_hit_rate']:.4f}  Macro F1: {fold_result['macro_f1']:.4f}")
        if with_lgbm:
            print(f"  [Fused]  Top-3: {fold_result['top3_hit_rate_fused']:.4f}  Macro F1: {fold_result['macro_f1_fused']:.4f}  (LGBM={'ON' if fold_result['lgbm_enabled'] else 'OFF'})")
        print(f"  Consensus R²: {fold_result['consensus_r2']:.4f}")

    # 汇总
    top3_rates = [f["top3_hit_rate"] for f in folds]
    macro_f1s = [f["macro_f1"] for f in folds]
    r2s = [f["consensus_r2"] for f in folds]

    agg = {
        "top3_mean": round(float(np.mean(top3_rates)), 4),
        "top3_std": round(float(np.std(top3_rates)), 4),
        "macro_f1_mean": round(float(np.mean(macro_f1s)), 4),
        "macro_f1_std": round(float(np.std(macro_f1s)), 4),
        "consensus_r2_mean": round(float(np.mean(r2s)), 4),
    }

    if with_lgbm:
        top3_fused = [f["top3_hit_rate_fused"] for f in folds]
        macro_f1_fused = [f["macro_f1_fused"] for f in folds]
        agg["top3_fused_mean"] = round(float(np.mean(top3_fused)), 4)
        agg["top3_fused_std"] = round(float(np.std(top3_fused)), 4)
        agg["macro_f1_fused_mean"] = round(float(np.mean(macro_f1_fused)), 4)
        agg["macro_f1_fused_std"] = round(float(np.std(macro_f1_fused)), 4)

    summary = {
        "n_splits": n_splits,
        "n_samples": n,
        "with_lgbm": with_lgbm,
        "folds": folds,
        "aggregate": agg,
        "targets": {
            "top3_hit_rate": ">= 0.70",
            "macro_f1": ">= 0.45",
            "consensus_r2": ">= 0.30",
        },
    }
    return summary


# ================================================================
# Phase C: α blend WalkForward 对比回测
# 对比不同 α 值的回测表现，找出最优 α
# ================================================================

def _simulate_simple_pnl(
    test_close: pd.Series,
    level_smooth: pd.Series,
    trend_smooth: pd.Series,
    forecast_L: float | None = None,
    forecast_T: float | None = None,
    alpha_blend: float = 0.0,
) -> Dict:
    """简化的 PnL 模拟（基于 L/T 信号方向做多/做空）。

    策略：每天根据 ParameterMapper 的 L_effective 方向决定多/空仓位。
    alpha=0 时纯反应式；alpha>0 时混合前瞻值。
    """
    from bcrm2.parameter_mapper import ParameterMapper

    mapper = ParameterMapper()
    daily_returns: List[float] = []
    equity = 1.0
    equity_curve = [1.0]
    peak = 1.0
    max_dd = 0.0

    for i in range(len(test_close) - 1):
        L = float(level_smooth.iloc[i])
        T = float(trend_smooth.iloc[i])
        # 共识度用固定值（简化）
        C = 0.5

        # 用 ParameterMapper 计算 global params（触发 α blend）
        params = mapper.map_global_parameters(
            L, T, C,
            forecast_L=forecast_L, forecast_T=forecast_T,
            alpha_blend=alpha_blend,
        )

        # 方向：L > 0 做多，L < 0 做空（简化）
        direction = 1.0 if L > 0 else -1.0

        # 实际收益
        if i + 1 < len(test_close):
            ret = float(test_close.iloc[i + 1] / test_close.iloc[i] - 1.0)
            daily_ret = direction * ret
            daily_returns.append(daily_ret)
            equity *= (1.0 + daily_ret)
            equity_curve.append(equity)
            peak = max(peak, equity)
            dd = (equity - peak) / peak
            max_dd = min(max_dd, dd)

    if not daily_returns:
        return {"sharpe": 0.0, "pnl": 0.0, "max_dd": 0.0, "n_days": 0}

    arr = np.array(daily_returns)
    pnl = float(equity - 1.0)
    std = float(np.std(arr))
    sharpe = float(np.mean(arr) / std * np.sqrt(252)) if std > 1e-9 else 0.0

    return {
        "sharpe": round(sharpe, 4),
        "pnl": round(pnl, 4),
        "max_dd": round(float(max_dd), 4),
        "n_days": len(daily_returns),
    }


def run_alpha_blend_comparison(
    csv_path: Path,
    alpha_values: Optional[List[float]] = None,
    n_folds: int = 5,
    hist_days: int = 60,
    forecast_days: int = 5,
) -> Dict:
    """对比不同 α 值的 WalkForward 回测结果。

    参数:
        csv_path: BTC 1D CSV 路径
        alpha_values: 要测试的 α 值列表（默认 [0.0, 0.1, 0.2, 0.3, 0.5]）
        n_folds: WalkForward 折数
        hist_days: MorphCyclePredictor 历史天数
        forecast_days: 预测天数

    返回:
        {
            "symbol": "BTCUSDT",
            "n_folds": 5,
            "alpha_results": {
                "0.0": {"sharpe": ..., "pnl": ..., "max_dd": ..., "n_days": ...},
                ...
            },
            "best_alpha": 0.2,
            "improvement_vs_baseline": {
                "sharpe_improvement_pct": ...,
                "pnl_improvement_pct": ...,
            },
        }
    """
    if alpha_values is None:
        alpha_values = [0.0, 0.1, 0.2, 0.3, 0.5]

    df = _read_csv(csv_path)
    n = len(df)
    level_smooth, trend_smooth, _, _ = _compute_level_trend(df)

    # 初始化 MorphCyclePredictor
    from bcrm2.morph_cycle_predictor import MorphCyclePredictor
    from bcrm2.run_evolution_pipeline import get_storage
    storage = get_storage()
    predictor = MorphCyclePredictor(storage)

    alpha_results: Dict[str, Dict] = {}

    for alpha in alpha_values:
        fold_metrics: List[Dict] = []
        folds = list(walk_forward_time_series_split(n, n_splits=n_folds, gap=20, expanding=True))

        for k, (train_idx, test_idx) in enumerate(folds):
            test_close = df["close"].iloc[test_idx]
            test_L = level_smooth.iloc[test_idx]
            test_T = trend_smooth.iloc[test_idx]

            # 计算 forecast_L/T（用 test 段前一日数据预测，避免 look-ahead bias）
            forecast_L = None
            forecast_T = None
            if alpha > 0.0 and len(test_idx) > 0:
                # 用 test 段第一天的前一日作为预测起点
                pred_start_idx = max(0, test_idx[0] - 1)
                try:
                    result = predictor.predict(
                        "BTCUSDT",
                        hist_days=hist_days,
                        forecast_days=forecast_days,
                    )
                    if result.get("ok"):
                        forecast_series = result.get("series", {}).get("forecast", [])
                        if forecast_series:
                            forecast_L = float(forecast_series[-1])
                            if len(forecast_series) >= 2:
                                forecast_T = float(forecast_series[-1] - forecast_series[0])
                except Exception:
                    pass  # 预测失败 → forecast=None → 不 blend

            # 模拟 PnL
            metrics = _simulate_simple_pnl(
                test_close, test_L, test_T,
                forecast_L=forecast_L, forecast_T=forecast_T,
                alpha_blend=alpha,
            )
            fold_metrics.append(metrics)

        # 汇总各折
        sharpes = [m["sharpe"] for m in fold_metrics]
        pnls = [m["pnl"] for m in fold_metrics]
        max_dds = [m["max_dd"] for m in fold_metrics]
        n_days_list = [m["n_days"] for m in fold_metrics]

        alpha_results[str(alpha)] = {
            "sharpe": round(float(np.mean(sharpes)), 4),
            "pnl": round(float(np.mean(pnls)), 4),
            "max_dd": round(float(np.mean(max_dds)), 4),
            "n_days": int(np.mean(n_days_list)),
            "n_folds": len(fold_metrics),
        }

    # 找出 best_alpha（sharpe 最高的 α）
    best_alpha = max(alpha_values, key=lambda a: alpha_results[str(a)]["sharpe"])

    # 计算相对 α=0 基线的改善
    baseline = alpha_results.get("0.0", alpha_results[str(alpha_values[0])])
    best = alpha_results[str(best_alpha)]
    sharpe_imp = 0.0
    pnl_imp = 0.0
    if baseline["sharpe"] != 0:
        sharpe_imp = round((best["sharpe"] - baseline["sharpe"]) / abs(baseline["sharpe"]) * 100, 2)
    if baseline["pnl"] != 0:
        pnl_imp = round((best["pnl"] - baseline["pnl"]) / abs(baseline["pnl"]) * 100, 2)

    return {
        "symbol": "BTCUSDT",
        "n_folds": n_folds,
        "alpha_results": alpha_results,
        "best_alpha": best_alpha,
        "improvement_vs_baseline": {
            "sharpe_improvement_pct": sharpe_imp,
            "pnl_improvement_pct": pnl_imp,
        },
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="P3.2 WalkForward Top-3 回测基线（含 LGBM 概率校正器融合）")
    p.add_argument("--csv", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--n-splits", type=int, default=5)
    p.add_argument("--with-lgbm", action="store_true", default=True,
                   help="启用 LGBM 概率校正器融合（默认开启）")
    p.add_argument("--no-lgbm", dest="with_lgbm", action="store_false",
                   help="禁用 LGBM，仅用纯高斯软分配基线")
    p.add_argument("--feature-set", default="btc_morphology_v6",
                   help="LGBM 特征集（默认 v6 = v5 + rolling_regime_stats 16列）")
    p.add_argument("--tuned-params", default=None,
                   help="Optuna 搜索得到的最佳参数 JSON 路径（含 best_params 字段）")
    args = p.parse_args(argv)

    tuned_params = None
    if args.tuned_params:
        tp_path = Path(args.tuned_params).resolve()
        if tp_path.exists():
            tp_data = json.loads(tp_path.read_text(encoding="utf-8"))
            tuned_params = tp_data.get("best_params") or tp_data
            print(f"[P3.2] 加载 tuned_params from {tp_path}")
        else:
            print(f"[P3.2] WARNING: tuned-params 文件不存在: {tp_path}，使用默认参数")

    result = run_walkforward(Path(args.csv).resolve(), n_splits=args.n_splits,
                             with_lgbm=args.with_lgbm, feature_set=args.feature_set,
                             tuned_params=tuned_params)

    print("\n=== WalkForward 汇总 ===")
    a = result["aggregate"]
    print(f"  [Gauss]  Top-3: {a['top3_mean']:.4f} ± {a['top3_std']:.4f}  Macro F1: {a['macro_f1_mean']:.4f} ± {a['macro_f1_std']:.4f}")
    if args.with_lgbm and "macro_f1_fused_mean" in a:
        print(f"  [Fused]  Top-3: {a['top3_fused_mean']:.4f} ± {a['top3_fused_std']:.4f}  Macro F1: {a['macro_f1_fused_mean']:.4f} ± {a['macro_f1_fused_std']:.4f}")
        delta = a['macro_f1_fused_mean'] - a['macro_f1_mean']
        print(f"  [Delta]  Macro F1 提升: {delta:+.4f}")
    print(f"  Consensus R²: {a['consensus_r2_mean']:.4f}  (目标 ≥ 0.30)")
    print(f"  目标: Top-3 ≥ 0.70 | Macro F1 ≥ 0.45 | Consensus R² ≥ 0.30")

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[P3.2] 结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
