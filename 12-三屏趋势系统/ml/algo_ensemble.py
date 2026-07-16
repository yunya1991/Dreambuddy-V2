"""五大算法集成推理引擎

将五大算法的完整输出（趋势一致性、贝叶斯置信度、经典指标置信度、技术基本面融合、价值风险评估）
作为特征，用 LightGBM 学习各算法在不同市场状态下的最优权重组合。

解决"固定权重不够智能"的问题：
- 贝叶斯置信度用固定公式计算权重
- 技术/基本面用固定 60%/40% 加权
- 本模块让模型从历史数据中学习最优权重

特征来源（~40维）：
1. 趋势一致性：周线/日线方向、置信度、逆转分数、速度、加速度
2. 贝叶斯置信度：方向、置信度、多空概率
3. 经典指标置信度：Screen1/Screen2 各项指标统计
4. 技术基本面融合：一致性、冲突级别
5. 价值风险评估：波动率比、风险收益比、价值>风险
6. Freqtrade信号：1h/4h方向和置信度
7. 最终信号：方向、置信度、各维度一致性

标签：未来N日收益方向（1=涨, 0=跌）
"""

import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ── 路径配置 ──────────────────────────────────────────────────────────────

TREND_SYSTEM = Path(__file__).parent.parent
ENSEMBLE_DIR = TREND_SYSTEM / "ml" / "models" / "ensemble"
DATA_COLLECTOR = TREND_SYSTEM / "ml" / "models" / "ensemble" / "collected"
ENSEMBLE_DIR.mkdir(parents=True, exist_ok=True)
DATA_COLLECTOR.mkdir(parents=True, exist_ok=True)

MODEL_PATH = ENSEMBLE_DIR / "ensemble_model.pkl"
META_PATH = ENSEMBLE_DIR / "meta.json"

# 模块级缓存
_ensemble_cache = {"model": None, "features": None, "loaded_at": 0}
_MODEL_TTL = 3600  # 1小时缓存


# ── 特征提取 ──────────────────────────────────────────────────────────────

def _dir_to_num(direction: str) -> int:
    """方向编码: BULL=1, BEAR=-1, NEUTRAL=0"""
    if direction in ("BULL", "BUY", "LONG", "long"):
        return 1
    elif direction in ("BEAR", "SELL", "SHORT", "short"):
        return -1
    return 0


def _safe_float(val, default=0.0) -> float:
    """安全提取浮点数"""
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=0) -> int:
    try:
        if val is None:
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_bool(val, default=0) -> int:
    """布尔转 0/1"""
    if val is None:
        return default
    return 1 if bool(val) else 0


# 完整特征名列表（40维）
FEATURE_NAMES: List[str] = [
    # 趋势一致性 (14维)
    "tc_weekly_confidence", "tc_weekly_reversal", "tc_weekly_bull", "tc_weekly_bear",
    "tc_weekly_speed", "tc_weekly_accel", "tc_weekly_static_dir",
    "tc_daily_confidence", "tc_daily_reversal", "tc_daily_bull", "tc_daily_bear",
    "tc_daily_speed", "tc_daily_accel", "tc_daily_static_dir",
    "tc_consistent", "tc_consistency_confidence",
    # 贝叶斯置信度 (3维)
    "bayes_confidence", "bayes_bull_prob", "bayes_bear_prob",
    # 经典指标置信度 (9维)
    "classic_s1_confidence", "classic_s1_bull", "classic_s1_bear", "classic_s1_dynamics_bonus",
    "classic_s2_confidence", "classic_s2_bull", "classic_s2_bear", "classic_s2_dynamics_bonus",
    "classic_overall_confidence", "classic_trend_consistent",
    # 技术基本面融合 (4维)
    "fusion_tech_conf", "fusion_fund_conf", "fusion_consistent", "fusion_conflict_level",
    # 价值风险评估 (4维)
    "vr_vol_ratio", "vr_rr_ratio", "vr_value_gt_risk", "vr_tp_pct",
    # Freqtrade信号 (4维)
    "ft_1h_signal", "ft_1h_confidence", "ft_4h_signal", "ft_4h_confidence",
    # 最终信号 (5维)
    "fs_direction", "fs_confidence", "fs_trend_consistent",
    "fs_fusion_consistent", "fs_freqtrade_consistent",
]


def extract_ensemble_features(full_signal: dict) -> Dict[str, float]:
    """从五大算法的完整输出中提取特征向量

    参数:
        full_signal: compute_full_trading_signal() / compute_trend_signal_from_dataframes() 的返回值

    返回:
        特征字典 {feature_name: value}
    """
    features = {}

    # ── 趋势一致性 ──
    tc = full_signal.get("trend_consistency", {})
    weekly = tc.get("weekly", {})
    daily = tc.get("daily", {})

    features["tc_weekly_confidence"] = _safe_float(weekly.get("confidence"))
    features["tc_weekly_reversal"] = _safe_float(weekly.get("reversal_score"))
    features["tc_weekly_bull"] = _safe_int(weekly.get("bull_count"))
    features["tc_weekly_bear"] = _safe_int(weekly.get("bear_count"))
    features["tc_weekly_speed"] = _safe_float(weekly.get("avg_speed"))
    features["tc_weekly_accel"] = _safe_float(weekly.get("avg_acceleration"))
    features["tc_weekly_static_dir"] = _dir_to_num(weekly.get("static_direction"))
    features["tc_daily_confidence"] = _safe_float(daily.get("confidence"))
    features["tc_daily_reversal"] = _safe_float(daily.get("reversal_score"))
    features["tc_daily_bull"] = _safe_int(daily.get("bull_count"))
    features["tc_daily_bear"] = _safe_int(daily.get("bear_count"))
    features["tc_daily_speed"] = _safe_float(daily.get("avg_speed"))
    features["tc_daily_accel"] = _safe_float(daily.get("avg_acceleration"))
    features["tc_daily_static_dir"] = _dir_to_num(daily.get("static_direction"))
    features["tc_consistent"] = _safe_bool(tc.get("consistent"))
    features["tc_consistency_confidence"] = _safe_float(tc.get("consistency_confidence"))

    # ── 贝叶斯置信度 ──
    bc = full_signal.get("bayesian_confidence", {})
    features["bayes_confidence"] = _safe_float(bc.get("confidence"))
    features["bayes_bull_prob"] = _safe_float(bc.get("bull_probability"))
    features["bayes_bear_prob"] = _safe_float(bc.get("bear_probability"))

    # ── 经典指标置信度 ──
    cc = full_signal.get("classic_indicator_confidence", {})
    s1 = cc.get("screen1_weekly", {})
    s2 = cc.get("screen2_daily", {})
    features["classic_s1_confidence"] = _safe_float(s1.get("confidence"))
    features["classic_s1_bull"] = _safe_int(s1.get("bull_count"))
    features["classic_s1_bear"] = _safe_int(s1.get("bear_count"))
    features["classic_s1_dynamics_bonus"] = _safe_float(s1.get("dynamics_bonus"))
    features["classic_s2_confidence"] = _safe_float(s2.get("confidence"))
    features["classic_s2_bull"] = _safe_int(s2.get("bull_count"))
    features["classic_s2_bear"] = _safe_int(s2.get("bear_count"))
    features["classic_s2_dynamics_bonus"] = _safe_float(s2.get("dynamics_bonus"))
    features["classic_overall_confidence"] = _safe_float(cc.get("overall_confidence"))
    features["classic_trend_consistent"] = _safe_bool(cc.get("trend_consistent"))

    # ── 技术基本面融合 ──
    tff = full_signal.get("technical_fundamental_fusion", {})
    features["fusion_tech_conf"] = _safe_float(tff.get("technical", {}).get("confidence"))
    features["fusion_fund_conf"] = _safe_float(tff.get("fundamental", {}).get("confidence"))
    features["fusion_consistent"] = _safe_bool(tff.get("consistent"))
    features["fusion_conflict_level"] = _safe_float(tff.get("conflict_level"))

    # ── 价值风险评估 ──
    vr = full_signal.get("value_risk_assessment", {})
    vol = vr.get("volatility", {})
    tp_sl = vr.get("take_profit_stop_loss", {})
    rr = tp_sl.get("risk_reward", {})
    features["vr_vol_ratio"] = _safe_float(vol.get("vol_ratio"))
    features["vr_rr_ratio"] = _safe_float(rr.get("rr_ratio"))
    features["vr_value_gt_risk"] = _safe_bool(vr.get("value_gt_risk"))
    features["vr_tp_pct"] = _safe_float(tp_sl.get("take_profit_pct"))

    # ── Freqtrade信号 ──
    ft = full_signal.get("freqtrade_signals", {})
    ft_1h = ft.get("1h", {})
    ft_4h = ft.get("4h", {})
    features["ft_1h_signal"] = _dir_to_num(ft_1h.get("signal", "HOLD"))
    features["ft_1h_confidence"] = _safe_float(ft_1h.get("confidence"))
    features["ft_4h_signal"] = _dir_to_num(ft_4h.get("signal", "HOLD"))
    features["ft_4h_confidence"] = _safe_float(ft_4h.get("confidence"))

    # ── 最终信号 ──
    fs = full_signal.get("final_signal", {})
    features["fs_direction"] = _dir_to_num(fs.get("direction"))
    features["fs_confidence"] = _safe_float(fs.get("confidence"))
    features["fs_trend_consistent"] = _safe_bool(fs.get("trend_consistent"))
    features["fs_fusion_consistent"] = _safe_bool(fs.get("fusion_consistent"))
    features["fs_freqtrade_consistent"] = _safe_bool(fs.get("freqtrade_consistent"))

    return features


# ── 隔离声明 ──────────────────────────────────────────────────────────────
# 本模块的 LightGBM 与以下系统完全隔离：
# 1. 12-三屏趋势系统/ml/models.py 的 LightGBMModel
#    - 那个用价格特征（52维），本模块用算法输出特征（40维）
#    - 那个存 ml/models/current/，本模块存 ml/models/ensemble/
# 2. 11-易经推理系统/scripts/memory_l4/bcrm2/ 的 DialecticalMLEngine
#    - 那个用卦象特征，训练逻辑完全不同
# - 不共享模型文件、不共享特征、不共享训练代码
# ──────────────────────────────────────────────────────────────────────────


# ── 训练数据收集 ──────────────────────────────────────────────────────────

def collect_sample(full_signal: dict, future_return: Optional[float] = None,
                   symbol: str = "UNKNOWN", timestamp: Optional[str] = None) -> None:
    """收集训练样本到 collected/ 目录

    在实盘运行时调用，将五大算法的完整输出保存为训练样本。
    后续回测时根据时间戳计算 future_return 作为标签。

    参数:
        full_signal: compute_full_trading_signal() 的返回值
        future_return: 未来N日收益率（回测时填充，实盘时为 None）
        symbol: 交易对符号
        timestamp: 样本时间戳（默认当前时间）
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    features = extract_ensemble_features(full_signal)
    features["_symbol"] = symbol
    features["_timestamp"] = timestamp
    features["_future_return"] = future_return
    features["_price"] = _safe_float(full_signal.get("price"))

    # 按日期分文件存储，避免单文件过大
    date_str = timestamp[:10] if "T" in timestamp else timestamp[:10]
    file_path = DATA_COLLECTOR / f"samples_{date_str}.jsonl"

    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(features, ensure_ascii=False, default=str) + "\n")


def load_collected_samples() -> pd.DataFrame:
    """加载所有已收集的样本

    返回:
        DataFrame，每行一个样本，包含特征列和 _future_return 列
    """
    all_samples = []
    for f in DATA_COLLECTOR.glob("samples_*.jsonl"):
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        all_samples.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    if not all_samples:
        return pd.DataFrame()

    df = pd.DataFrame(all_samples)
    return df


# ── 模型训练 ──────────────────────────────────────────────────────────────

def train_ensemble(label_lookahead: int = 7, test_ratio: float = 0.3) -> dict:
    """训练集成推理模型

    从 collected/ 目录加载样本，用 LightGBM 训练二分类模型。
    标签：未来 label_lookahead 日收益 > 0 → 1，否则 → 0。

    隔离说明：
    - 直接使用 lightgbm 库，不经过 ml/models.py 的 LightGBMModel
    - 模型存储在 ml/models/ensemble/，与 ml/models/current/ 完全独立
    - 特征是五大算法输出（40维），不是价格指标（52维）

    参数:
        label_lookahead: 标签前瞻天数（用于过滤无标签样本）
        test_ratio: 测试集比例

    返回:
        训练结果 dict（含 AUC、准确率等）
    """
    import pickle
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score, accuracy_score

    df = load_collected_samples()
    if len(df) < 50:
        return {"error": f"样本不足（{len(df)} < 50），请先收集更多训练数据"}

    # 过滤有标签的样本
    df_labeled = df[df["_future_return"].notna()].copy()
    if len(df_labeled) < 30:
        return {"error": f"有标签样本不足（{len(df_labeled)} < 30），请先回测标注"}

    # 构造标签
    df_labeled["label"] = (df_labeled["_future_return"].astype(float) > 0).astype(int)

    # 特征矩阵
    feature_cols = [c for c in FEATURE_NAMES if c in df_labeled.columns]
    X = df_labeled[feature_cols].fillna(0).astype(float)
    y = df_labeled["label"].astype(int)

    # 时间序列分割（不 shuffle，避免未来信息泄漏）
    split_idx = int(len(X) * (1 - test_ratio))
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    if len(X_train) < 20 or len(X_test) < 5:
        return {"error": f"训练/测试集样本不足（train={len(X_train)}, test={len(X_test)}）"}

    # LightGBM 训练参数
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "min_data_in_leaf": 10,
        "max_depth": 4,
        "lambda_l1": 0.5,
        "lambda_l2": 5.0,
        "verbose": -1,
        "random_state": 42,
    }

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
    valid_data = lgb.Dataset(X_test, label=y_test, feature_name=feature_cols, reference=train_data)

    model = lgb.train(
        params, train_data,
        num_boost_round=200,
        valid_sets=[train_data, valid_data],
        valid_names=["train", "valid"],
        callbacks=[
            lgb.early_stopping(30, verbose=False),
            lgb.log_evaluation(0),
        ],
    )

    # 评估
    y_train_pred = model.predict(X_train)
    y_test_pred = model.predict(X_test)

    train_auc = roc_auc_score(y_train, y_train_pred) if len(set(y_train)) > 1 else 0.5
    test_auc = roc_auc_score(y_test, y_test_pred) if len(set(y_test)) > 1 else 0.5
    train_acc = accuracy_score(y_train, (y_train_pred > 0.5).astype(int))
    test_acc = accuracy_score(y_test, (y_test_pred > 0.5).astype(int))

    # 保存模型
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)

    # 保存元数据
    meta = {
        "model_type": "AlgoEnsembleModel",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_names": feature_cols,
        "num_features": len(feature_cols),
        "num_samples": len(df_labeled),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "label_lookahead": label_lookahead,
        "performance": {
            "train_roc_auc": round(train_auc, 4),
            "train_accuracy": round(train_acc, 4),
            "test_roc_auc": round(test_auc, 4),
            "test_accuracy": round(test_acc, 4),
            "overfit_gap": round(train_auc - test_auc, 4),
        },
        "isolation_note": (
            "本模型与 ml/models.py 的 LightGBMModel 完全独立。"
            "特征来源：五大算法输出（40维），非价格指标（52维）。"
            "不与 11-易经推理系统 的 DialecticalMLEngine 共享任何代码或数据。"
        ),
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 清除缓存
    _ensemble_cache["model"] = None
    _ensemble_cache["features"] = None

    return meta


# ── 推理 ──────────────────────────────────────────────────────────────────

def _load_model():
    """加载缓存的集成模型

    返回:
        (model, feature_names) 或 (None, None)
    """
    now = time.time()
    if _ensemble_cache["model"] is not None and now - _ensemble_cache["loaded_at"] < _MODEL_TTL:
        return _ensemble_cache["model"], _ensemble_cache["features"]

    if not MODEL_PATH.exists():
        return None, None

    try:
        import pickle
        with open(MODEL_PATH, "rb") as f:
            model = pickle.load(f)

        feature_names = FEATURE_NAMES
        if META_PATH.exists():
            with open(META_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
            feature_names = meta.get("feature_names", FEATURE_NAMES)

        _ensemble_cache["model"] = model
        _ensemble_cache["features"] = feature_names
        _ensemble_cache["loaded_at"] = now
        return model, feature_names
    except Exception:
        return None, None


def predict_ensemble(full_signal: dict) -> dict:
    """用集成模型预测

    将五大算法的输出作为特征，通过 LightGBM 模型预测最终方向和置信度。
    如果模型未训练，返回 fallback 结果。

    参数:
        full_signal: compute_full_trading_signal() 的返回值

    返回:
        {
            "direction": "BULL"/"BEAR"/"NEUTRAL",
            "confidence": 0-100,
            "prob_up": 0-1,
            "prob_down": 0-1,
            "source": "ensemble" | "fallback",
            "features": {...},  # 提取的特征向量
        }
    """
    features = extract_ensemble_features(full_signal)

    model, feature_names = _load_model()

    if model is None:
        # Fallback：用五大算法原始 final_signal
        fs = full_signal.get("final_signal", {})
        direction = fs.get("direction", "NEUTRAL")
        confidence = _safe_float(fs.get("confidence"), 50.0)
        return {
            "direction": direction,
            "confidence": confidence,
            "prob_up": confidence / 100.0,
            "prob_down": 1.0 - confidence / 100.0,
            "source": "fallback",
            "features": features,
        }

    # 构造特征向量（按模型训练时的特征顺序）
    import pandas as pd
    X = pd.DataFrame([[features.get(f, 0.0) for f in feature_names]],
                     columns=feature_names)

    prob_up = float(model.predict(X)[0])
    prob_down = 1.0 - prob_up

    # 方向判定
    if prob_up > 0.58:
        direction = "BULL"
    elif prob_up < 0.42:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"

    # 置信度：远离 0.5 的程度映射到 50-100
    confidence = round(abs(prob_up - 0.5) * 200, 1)  # 0.5→0, 1.0→100
    confidence = max(0.0, min(100.0, confidence))

    return {
        "direction": direction,
        "confidence": confidence,
        "prob_up": round(prob_up, 4),
        "prob_down": round(prob_down, 4),
        "source": "ensemble",
        "features": features,
    }