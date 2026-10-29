#!/usr/bin/env python3
"""P6 E1 基线固化 v5：12 系统 LightGBM 基线指标落表（baseline_metrics.json）。
依据：docs/SPEC_encoder_trend_classifier.md v0.2 实施阶段 E1——基线指标（准确率/IC）落表。
方法（复用 12 系统既有管道，只读不修改 12 系统任何文件）：
  1. 18 中心 data_center.compat.fetch_candles("BTC-USDT", "1D", 300) 获取日线
  2. 12 系统 prepare_ohlcv_dataframe 转换列名（date/open/high/low/close/volume）
  3. TrendFeatureEngineer(views=5 视图).create_features(df, label_lookahead=7) 生成特征
     （talib 兼容层：① 本环境 abstract 返回 ndarray，包装回 Series；
      ② 本环境缺失 ELDER_RAY，按 Elder-ray 标准定义补齐：
        bull_power = high - EMA13，bear_power = low - EMA13）
  4. 按 baseline/meta.json 的 25 特征顺序取列（与基线模型训练列序一致）
  5. 基线模型 predict_proba，最近 20% 时间段样本外评估（预注册，禁止随机打乱）
  6. accuracy：预测方向 vs label 一致率；direction_ic：预测概率与未来 7 日收益的 Spearman 秩相关
  7. 落盘 40系统/baseline_metrics.json（供 p6_gate E1 门槛消费）
红线：不修改 12/18 系统文件；指标为基线固化记录，不产生交易信号。
"""
import json
import os
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

TREND = "/home/luke/dreambuddy/12-三屏趋势系统"
DCENTER = "/home/luke/dreambuddy/18-数据获取中心"
sys.path.insert(0, TREND)
sys.path.insert(0, DCENTER)

MODEL_PATH = os.path.join(TREND, "ml", "models", "baseline", "model.pkl")
META_PATH = os.path.join(TREND, "ml", "models", "baseline", "meta.json")
OUT_PATH = "/home/luke/dreambuddy/40-周期神经网络系统/baseline_metrics.json"

TEST_RATIO = 0.2   # 最近 20% 样本外评估（预注册）
LOOKAHEAD = 7       # 标签前瞻 7 日（对齐基线训练配置）


def _patch_talib_abstract():
    """talib 兼容层（不改 12 系统文件）：
    ① 本环境 abstract 接口对 Series 输入返回 ndarray，特征工程假设返回 Series
      （调用 .pct_change()/.diff() 等），将返回值包装回 Series（保留输入索引）。
    ② 本环境 talib 无 ELDER_RAY，按 Elder-ray 标准定义补齐：
      bull_power = high - EMA(period)，bear_power = low - EMA(period)。
    """
    from talib import abstract as ta

    def _wrap(fn):
        def wrapped(*args, **kwargs):
            ref = next((a for a in args if isinstance(a, (pd.Series, pd.DataFrame))), None)
            out = fn(*args, **kwargs)

            def conv(v):
                if isinstance(v, np.ndarray) and ref is not None:
                    return pd.Series(v, index=ref.index)
                return v

            if isinstance(out, tuple):
                return tuple(conv(v) for v in out)
            if isinstance(out, list):
                return [conv(v) for v in out]
            if isinstance(out, dict):
                return {k: conv(v) for k, v in out.items()}
            return conv(out)

        return wrapped

    for name in ("EMA", "ATR", "RSI", "MACD"):
        if hasattr(ta, name):
            setattr(ta, name, _wrap(getattr(ta, name)))

    if not hasattr(ta, "ELDER_RAY"):
        def _elder_ray(df, period=13):
            close = df["close"] if isinstance(df, pd.DataFrame) else df
            high = df["high"] if isinstance(df, pd.DataFrame) else None
            low = df["low"] if isinstance(df, pd.DataFrame) else None
            ema = ta.EMA(close, timeperiod=period)
            return {
                "ema": ema,
                "bull_power": (high - ema) if high is not None else None,
                "bear_power": (low - ema) if low is not None else None,
            }

        ta.ELDER_RAY = _elder_ray


def main() -> int:
    _patch_talib_abstract()

    from data_center.compat import fetch_candles
    from backtest.data_utils import prepare_ohlcv_dataframe
    from ml.feature_engineer import TrendFeatureEngineer

    with open(META_PATH, "r", encoding="utf-8") as f:
        meta = json.load(f)
    feature_names = meta["feature_names"]

    # 1) 数据（18 中心新入口，与基线训练同源：BTC-USDT 日线 300 天）
    candles = fetch_candles("BTC-USDT", "1D", 300)
    df = prepare_ohlcv_dataframe(candles)
    if df is None or len(df) < 100:
        print(f"[FAIL] K 线数据不足: {0 if df is None else len(df)}")
        return 1

    # 2) 特征工程（与基线训练同配置）
    fe = TrendFeatureEngineer(views=["direction", "change", "velocity", "power", "hierarchy"])
    features_df = fe.create_features(df, label_lookahead=LOOKAHEAD)
    valid = fe.get_valid_data(features_df)

    # 3) 按基线特征顺序取列（列序与训练一致）
    missing = [c for c in feature_names if c not in valid.columns]
    if missing:
        print(f"[FAIL] 特征缺失 {len(missing)}: {missing[:5]}")
        return 1
    X = valid[feature_names]
    y_label = valid["label"].astype(int)

    # 未来 7 日连续收益（direction_ic 用）：特征管道已含 future_return 列
    if "future_return" in valid.columns:
        fut_ret = valid["future_return"].astype(float)
    else:
        close = df["close"].astype(float)
        fr = close.shift(-LOOKAHEAD) / close - 1.0
        if "date" in valid.columns and "date" in df.columns:
            fr_map = dict(zip(df["date"], fr))
            fut_ret = valid["date"].map(fr_map).astype(float)
        else:
            fut_ret = pd.Series(np.nan, index=valid.index)

    # 4) 样本外评估段（最近 20%，时间正序，禁止随机打乱）
    n = len(X)
    n_test = max(1, int(n * TEST_RATIO))
    X_eval = X.iloc[-n_test:]
    y_eval = y_label.iloc[-n_test:]
    ret_eval = fut_ret.iloc[-n_test:]

    loaded = joblib.load(MODEL_PATH)
    # pkl 结构：{model: LightGBM Booster, params, feature_names, is_trained}
    # 二分类 Booster.predict() 直接返回正类概率
    model = loaded["model"] if isinstance(loaded, dict) else loaded
    prob = np.asarray(model.predict(X_eval))
    if prob.ndim > 1:
        prob = prob[:, 1]
    pred_dir = prob >= 0.5
    accuracy = float(np.mean(pred_dir == (y_eval.values == 1)))

    # direction_ic：预测概率与未来收益秩相关（NaN 收益样本剔除）
    mask = ret_eval.notna().values
    if mask.sum() >= 10:
        ic, _ = spearmanr(prob[mask], ret_eval.values[mask])
        direction_ic = float(ic) if ic == ic else 0.0
    else:
        direction_ic = 0.0

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "P6 E1 基线固化（12 系统 LightGBM 基线落表）",
        "baseline_source": {
            "system": "12-三屏趋势系统",
            "model_path": MODEL_PATH,
            "version": meta.get("version"),
            "model_type": meta.get("model_type"),
            "num_features": len(feature_names),
            "train_date_range": meta.get("train_date_range"),
        },
        "eval_protocol": {
            "data": "BTC-USDT 1D limit=300（18 中心 data_center.compat，与基线训练同源）",
            "feature_pipeline": "TrendFeatureEngineer(views=5) label_lookahead=7（talib 兼容层：返回类型包装 + ELDER_RAY 补齐）",
            "samples_total": n,
            "eval_samples": n_test,
            "test_ratio": TEST_RATIO,
            "ordering": "time_asc_no_shuffle",
            "ic_samples": int(mask.sum()),
        },
        "accuracy": accuracy,
        "direction_ic": direction_ic,
        "reference_metrics_from_meta": {
            "test_accuracy": meta.get("performance", {}).get("test_accuracy"),
            "walk_forward_roc_auc": meta.get("performance", {}).get("walk_forward_roc_auc"),
        },
        "note": "基线固化记录：E2 小模型训练须 Walk-Forward 准确率与方向 IC 均不低于本基线方可晋级（SPEC_encoder 红线 3）",
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[OK] E1 基线固化 -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
