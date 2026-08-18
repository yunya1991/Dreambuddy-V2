"""
§4.3 WalkForward 5 折训练 BTC Regime Predictor 脚本

使用：
  cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2
  python train_btc_regime_predictor.py

输出目录：
  <project_root>/11-易经推理系统/artifacts/regime_predictor_btc/
    ├── fold_{0..4}.lgb / .skl.joblib / .pkl
    ├── fold_{0..4}.meta.json
    ├── train_report.json           (Macro F1 / Balanced Acc / 混淆矩阵)
    └── best.lgb / best.meta.json   (Macro F1 最高的一折权重)
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

SELF_DIR = Path(__file__).resolve().parent
if str(SELF_DIR) not in sys.path:
    sys.path.insert(0, str(SELF_DIR))
ROOT = SELF_DIR.parent.parent.parent
ARTIFACT_DIR = ROOT / "artifacts" / "regime_predictor_btc"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("train_btc_regime_predictor")

# 注册 FeatureRegistry 中的形态+广度模块
import bcrm2.classic_experience_features as _c  # noqa: F401 触发注册
import bcrm2.cross_asset_features as _x          # noqa: F401 触发注册

from bcrm2.feature_registry import FeatureRegistry
from bcrm2.labels.regime_labeler import REGIME_ORDER, generate_8state_label
from bcrm2.regime_predictor import RegimePredictor
from bcrm2.walk_forward_splitter import walk_forward_time_series_split

# Breadth 8 币
BREADTH_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX"]


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_ohlcv(
    symbol: str,
    csv_path: str | None = None,
    n_samples: int = 1825,
) -> Tuple[pd.DataFrame, Dict[str, List[float]]]:
    """加载 BTC OHLCV + 8 币收盘价。

    优先使用 csv_path（真实数据）；否则返回合成 5 年日线（用于 CI/沙盒）。
    """
    if csv_path and Path(csv_path).exists():
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                raise ValueError(f"{csv_path} 缺少列 {col}")
        # 8 币广度：若同目录下有 <COIN>USDT.csv 就读；否则用 BTC*扰动
        coins_closes: Dict[str, List[float]] = {}
        parent = Path(csv_path).parent
        close_arr = df["close"].to_numpy()[::-1].tolist()
        coins_closes["BTC"] = close_arr
        rng = np.random.RandomState(7)
        pert = {
            "ETH": 0.004, "SOL": 0.01, "BNB": 0.003, "XRP": 0.006,
            "ADA": 0.008, "DOGE": 0.012, "AVAX": 0.009,
        }
        n = len(df)
        for coin, sigma in pert.items():
            fp = parent / f"{coin}USDT.csv"
            if fp.exists():
                cdf = pd.read_csv(fp, index_col=0, parse_dates=True)
                coins_closes[coin] = cdf["close"].to_numpy()[::-1].tolist()
            else:
                btc = np.asarray(df["close"])
                series = btc * np.exp(np.cumsum(rng.randn(n) * sigma))
                coins_closes[coin] = series[::-1].tolist()
        return df.sort_index(), coins_closes

    # 合成数据：严格跟测试一致
    rng = np.random.RandomState(123)
    N = n_samples
    t = np.arange(N, dtype=float)
    drift = np.zeros(N)
    drift[0:500] = 0.0
    drift[500:1100] = 0.0038
    drift[1100:1220] = -0.0085
    drift[1220:1500] = -0.0007
    drift[1500:1825] = 0.0012
    rets_noise = rng.randn(N) * 0.022
    vol_mult = np.ones(N)
    vol_mult[500:1100] = 0.55
    vol_mult[1100:1220] = 2.0
    vol_mult[1220:1500] = 1.1
    vol_mult[1500:1825] = 0.65
    rets = drift + rets_noise * vol_mult
    close = 15000.0 * np.exp(np.cumsum(rets))
    high = close * (1.0 + np.abs(rng.randn(N)) * 0.015)
    low = close * (1.0 - np.abs(rng.randn(N)) * 0.015)
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = np.abs(rng.lognormal(mean=14.0, sigma=0.5, size=N))
    volume[1100:1220] *= 3.0
    volume[980:1080] *= 2.2
    idx = pd.date_range("2020-01-01", periods=N, freq="D")
    df = pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    }, index=idx)
    coins_closes = {"BTC": list(close[::-1])}
    pert = {
        "ETH": 0.004, "SOL": 0.01, "BNB": 0.003, "XRP": 0.006,
        "ADA": 0.008, "DOGE": 0.012, "AVAX": 0.009,
    }
    for coin, sigma in pert.items():
        c = close * np.exp(np.cumsum(rng.randn(N) * sigma))
        coins_closes[coin] = list(c[::-1])
    return df, coins_closes


def compute_features(
    df: pd.DataFrame,
    symbol: str,
    feature_set: str,
    coins_closes: Dict[str, List[float]],
) -> pd.DataFrame:
    FeatureRegistry.clear()
    importlib.reload(_c)
    importlib.reload(_x)
    feats, _names = FeatureRegistry.compute_all(
        df=df, symbol=symbol, enabled_set=feature_set, coins_closes=coins_closes,
    )
    for col in ["open", "high", "low", "close", "volume"]:
        feats[col] = df[col].values
    return feats


def evaluate(y_true, y_pred) -> Dict[str, float]:
    from sklearn.metrics import (
        balanced_accuracy_score,
        f1_score,
        confusion_matrix,
    )
    macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    bal_acc = float(balanced_accuracy_score(y_true, y_pred))
    cm = confusion_matrix(y_true, y_pred, labels=REGIME_ORDER).tolist()
    return {"macro_f1": macro_f1, "balanced_accuracy": bal_acc, "confusion_matrix": cm}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(SELF_DIR / "regime_predictor_config.json"))
    parser.add_argument("--csv", default=None, help="BTCUSDT.csv 真实数据路径")
    parser.add_argument("--n-samples", type=int, default=1825)
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    labeler_cfg = cfg["labeler"]
    wf_cfg = cfg["walk_forward"]

    logger.info("1. 加载 OHLCV 数据")
    df, coins_closes = load_ohlcv(cfg["symbol"], args.csv, args.n_samples)
    logger.info(f"   {len(df)} bars, {df.index[0].date()} ~ {df.index[-1].date()}")

    logger.info("2. 计算 Phase 0 形态 + 广度特征")
    features_df = compute_features(df, cfg["symbol"], cfg["feature_set"], coins_closes)
    feature_cols = [c for c in features_df.columns
                    if c not in ("open", "high", "low", "close", "volume")]
    logger.info(f"   {len(feature_cols)} 个特征列")

    logger.info("3. 生成 8 态标签")
    labels = generate_8state_label(features_df, **labeler_cfg)
    features_df["label"] = labels
    df2 = features_df.dropna(subset=feature_cols + ["label"])
    logger.info(f"   可用样本 {len(df2)}，标签分布：{df2['label'].value_counts().to_dict()}")

    X_all = df2[feature_cols].to_numpy(dtype=float)
    y_all = df2["label"].astype(str).to_numpy()

    splits = list(walk_forward_time_series_split(
        len(df2),
        n_splits=wf_cfg["n_splits"],
        gap=wf_cfg["gap"],
        train_ratio=wf_cfg["train_ratio"],
        test_ratio=wf_cfg["test_ratio"],
        expanding=wf_cfg.get("expanding", True),
    ))
    logger.info(f"4. WalkForward {len(splits)} 折")

    report: Dict[str, object] = {"folds": [], "regime_order": REGIME_ORDER}
    best_f1 = -1.0
    best_fold_path = None

    for i, (tr_idx, te_idx) in enumerate(splits):
        X_tr, y_tr = X_all[tr_idx], y_all[tr_idx]
        X_te, y_te = X_all[te_idx], y_all[te_idx]
        logger.info(f"   fold {i}: train={len(tr_idx)}, test={len(te_idx)}")

        predictor = RegimePredictor(config_dict=cfg)
        predictor.fit(X_tr, y_tr, feature_names=feature_cols,
                      lgbm_params=cfg.get("lgbm_hparams"))
        y_pred, _, _ = predictor.predict(X_te)
        metrics = evaluate(y_te, y_pred)
        logger.info(f"        MacroF1={metrics['macro_f1']:.3f} BalAcc={metrics['balanced_accuracy']:.3f}")
        fold_path = ARTIFACT_DIR / f"fold_{i}"
        predictor.save(fold_path)
        metrics["fold"] = i
        metrics["train_size"] = int(len(tr_idx))
        metrics["test_size"] = int(len(te_idx))
        report["folds"].append(metrics)
        if metrics["macro_f1"] > best_f1:
            best_f1 = metrics["macro_f1"]
            best_fold_path = fold_path

    # 汇总
    f1s = [f["macro_f1"] for f in report["folds"] if "macro_f1" in f]
    bas = [f["balanced_accuracy"] for f in report["folds"] if "balanced_accuracy" in f]
    report["avg_macro_f1"] = float(np.mean(f1s)) if f1s else 0.0
    report["avg_balanced_accuracy"] = float(np.mean(bas)) if bas else 0.0
    report["best_fold_f1"] = best_f1
    with (ARTIFACT_DIR / "train_report.json").open("w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=2)

    # 拷贝 best → best.lgb
    if best_fold_path is not None:
        for suf in [".lgb", ".skl.joblib", ".pkl", ".meta.json"]:
            src = best_fold_path.with_suffix(suf)
            if src.exists():
                dst = ARTIFACT_DIR / f"best{suf}"
                dst.write_bytes(src.read_bytes())
    logger.info(f"5. 完成。avg MacroF1={report['avg_macro_f1']:.3f}，输出：{ARTIFACT_DIR}")


if __name__ == "__main__":
    main()
