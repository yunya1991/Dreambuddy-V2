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
# 添加 SELF_DIR（直接模块导入）和 SELF_DIR.parent（bcrm2 包导入）到 sys.path
for _p in [str(SELF_DIR), str(SELF_DIR.parent)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
ROOT = SELF_DIR.parent.parent.parent
ARTIFACT_DIR = ROOT / "artifacts" / "regime_predictor_btc"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("train_btc_regime_predictor")

# 注册 FeatureRegistry 中的形态+广度+MA200周期+多时间框架模块
import bcrm2.classic_experience_features as _c  # noqa: F401 触发注册
import bcrm2.cross_asset_features as _x          # noqa: F401 触发注册
import bcrm2.ma200_cycle_features as _mc          # noqa: F401 触发注册
import bcrm2.multi_timeframe_features as _mt      # noqa: F401 触发注册

from bcrm2.feature_registry import FeatureRegistry
from bcrm2.labels.regime_labeler import REGIME_ORDER, generate_8state_label
from bcrm2.regime_predictor import RegimePredictor
from bcrm2.walk_forward_splitter import walk_forward_time_series_split

# Breadth 8 币
BREADTH_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX"]


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def fetch_external_data(df: pd.DataFrame, enable_external: bool = True) -> pd.DataFrame:
    """OPT-2: 拉取外部数据并合并到特征 DataFrame。

    获取 VIX、Fear & Greed Index 作为附加特征列。
    失败时用前向填充，保留 OHLCV 原始数据不变。

    Args:
        df: OHLCV DataFrame, index 为 DatetimeIndex
        enable_external: 是否启用外部数据

    Returns:
        df 附带 vix, fear_greed_index 列
    """
    if not enable_external:
        df["vix"] = np.nan
        df["fear_greed_index"] = np.nan
        return df

    logger.info("   拉取外部数据（VIX, F&G）...")

    # VIX via yfinance
    vix_series = None
    try:
        import yfinance as yf
        ticker = yf.Ticker("^VIX")
        vix_hist = ticker.history(start=df.index[0], end=df.index[-1] + pd.Timedelta(days=1))
        if not vix_hist.empty:
            vix_series = vix_hist["Close"].copy()
            vix_series.index = vix_series.index.tz_localize(None).normalize()
            logger.info(f"   VIX 数据: {len(vix_series)} 条")
    except Exception as e:
        logger.warning(f"   VIX 获取失败: {e}")

    # Fear & Greed Index via alternative.me
    fgi_series = None
    try:
        import requests
        # 拉取历史 F&G 数据（最大 limit）
        r = requests.get("https://api.alternative.me/fng/?limit=0", timeout=15)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                fgi_df = pd.DataFrame(data)
                fgi_df["timestamp"] = pd.to_datetime(fgi_df["timestamp"].astype(int), unit="s")
                fgi_df["value"] = fgi_df["value"].astype(float)
                fgi_series = fgi_df.set_index("timestamp")["value"]
                fgi_series.index = fgi_series.index.tz_localize(None).normalize()
                logger.info(f"   F&G 数据: {len(fgi_series)} 条")
    except Exception as e:
        logger.warning(f"   F&G 获取失败: {e}")

    # 合并到 df
    df_idx = df.index.tz_localize(None).normalize() if df.index.tz else df.index.normalize()
    df["vix"] = np.nan
    df["fear_greed_index"] = np.nan
    if vix_series is not None:
        df["vix"] = df_idx.map(vix_series).values
    if fgi_series is not None:
        df["fear_greed_index"] = df_idx.map(fgi_series).values

    # 前向填充
    df["vix"] = df["vix"].ffill().bfill()
    df["fear_greed_index"] = df["fear_greed_index"].ffill().bfill()

    logger.info(f"   外部数据合并完成: vix非空={df['vix'].notna().sum()}, fgi非空={df['fear_greed_index'].notna().sum()}")
    return df


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
    cfg: dict | None = None,
) -> pd.DataFrame:
    FeatureRegistry.clear()
    importlib.reload(_c)
    importlib.reload(_x)
    importlib.reload(_mc)
    importlib.reload(_mt)
    feats, _names = FeatureRegistry.compute_all(
        df=df, symbol=symbol, enabled_set=feature_set, coins_closes=coins_closes,
        config=cfg or {},
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
    # 默认使用真实 BTC 日线数据（2020-01-01 ~ 至今，~2400 行）
    _default_csv = str(ROOT / "scripts" / "data" / "klines" / "BTC_1D_full.csv")
    parser.add_argument("--csv", default=_default_csv, help="BTCUSDT.csv 真实数据路径")
    parser.add_argument("--n-samples", type=int, default=1825)
    parser.add_argument("--enable-external", action="store_true", default=True,
                        help="启用 P5 外部数据（VIX, F&G）")
    parser.add_argument("--enable-ensemble", action="store_true", default=True,
                        help="启用 P4 BOCPD+HMM 集成")
    parser.add_argument("--no-external", dest="enable_external", action="store_false")
    parser.add_argument("--no-ensemble", dest="enable_ensemble", action="store_false")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    labeler_cfg = cfg["labeler"]
    wf_cfg = cfg["walk_forward"]

    logger.info("1. 加载 OHLCV 数据")
    df, coins_closes = load_ohlcv(cfg["symbol"], args.csv, args.n_samples)
    logger.info(f"   {len(df)} bars, {df.index[0].date()} ~ {df.index[-1].date()}")

    # OPT-2: 外部数据接入
    if args.enable_external:
        logger.info("1b. 拉取外部数据（VIX, Fear & Greed）")
        df = fetch_external_data(df, enable_external=True)

    logger.info("2. 计算 Phase 0 形态 + 广度特征")
    features_df = compute_features(df, cfg["symbol"], cfg["feature_set"], coins_closes, cfg=cfg)
    feature_cols = [c for c in features_df.columns
                    if c not in ("open", "high", "low", "close", "volume")]

    # OPT-2: 将外部数据列加入特征
    if args.enable_external and "vix" in df.columns:
        for ext_col in ["vix", "fear_greed_index"]:
            if ext_col in df.columns:
                features_df[ext_col] = df[ext_col].values
                feature_cols.append(ext_col)
        logger.info(f"   外部特征已加入: vix, fear_greed_index")

    logger.info(f"   {len(feature_cols)} 个特征列")

    logger.info("3. 生成 8 态标签（滚动分位数动态阈值）")
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
    report["config"] = {
        "enable_external": args.enable_external,
        "enable_ensemble": args.enable_ensemble,
        "feature_count": len(feature_cols),
        "sample_count": int(len(df2)),
        "label_distribution": df2["label"].value_counts().to_dict(),
    }
    best_f1 = -1.0
    best_fold_path = None

    for i, (tr_idx, te_idx) in enumerate(splits):
        X_tr, y_tr = X_all[tr_idx], y_all[tr_idx]
        X_te, y_te = X_all[te_idx], y_all[te_idx]
        logger.info(f"   fold {i}: train={len(tr_idx)}, test={len(te_idx)}")

        # OPT-4: LightGBM 首选引擎（强正则 + 早停）
        predictor = RegimePredictor(config_dict=cfg)
        predictor.fit(X_tr, y_tr, feature_names=feature_cols,
                      lgbm_params=cfg.get("lgbm_hparams"))

        # OPT-3: P4 BOCPD+HMM 集成
        if args.enable_ensemble:
            try:
                from models.hmm_regime import HMMRegime
                predictor.enable_bocpd_hmm = True
                hmm = HMMRegime(n_states=8, n_iter=50)
                hmm.fit_with_labels(X_tr, y_tr, predictor.REGIME_ORDER)
                predictor.hmm_model = hmm
                y_pred, _, _ = predictor.predict_with_ensemble(X_te, X_te, feature_names=feature_cols)
                logger.info(f"        集成预测已启用（LGBM×0.7 + HMM×0.3）")
            except Exception as e:
                logger.warning(f"        HMM 集成失败，回退纯 LGBM: {e}")
                y_pred, _, _ = predictor.predict(X_te, feature_names=feature_cols)
        else:
            y_pred, _, _ = predictor.predict(X_te, feature_names=feature_cols)

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
