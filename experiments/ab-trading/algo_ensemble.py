#!/usr/bin/env python3
"""
五大算法集成推理模块 (Priority 1)

职责：
  将五大算法的输出（趋势一致性、贝叶斯置信度、经典指标置信度、技术基本面融合等）
  作为特征，用 LightGBM 学习各算法在不同市场状态下的最优权重组合，
  输出最终决策方向和置信度。

与现有系统的隔离边界：
  - 特征来源：仅限 12-三屏趋势系统/engine.py 的 compute_full_trading_signal() 输出
  - 模型存储：experiments/ab-trading/models/algo_ensemble/（独立目录）
  - 不导入 11-易经推理系统 的任何模块（两者 LightGBM 训练逻辑完全不同）
  - 不导入 12-三屏趋势系统/ml/ 的 TrendFeatureEngineer（那是价格特征模型）

接入点：screen_executor.py 的 check_and_execute()
作用：在五大算法计算完成、ML第三屏修正之前，对五大算法输出做集成推理
"""
import os, sys, json, time, pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

# ============================================================
# 路径与常量
# ============================================================

BASE_DIR = Path(__file__).parent
MODEL_DIR = BASE_DIR / "models" / "algo_ensemble"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH = MODEL_DIR / "algo_ensemble_lgb.pkl"
META_PATH = MODEL_DIR / "meta.json"

# 模型缓存
_model_cache = {}
_last_load_time = 0
_MODEL_TTL = 3600  # 1小时缓存

# ============================================================
# 特征提取：从五大算法输出中提取特征
# ============================================================

# 固定特征名列表（顺序固定，训练和推理必须一致）
ALGO_FEATURE_NAMES: List[str] = [
    # --- 趋势一致性 (Screen1) ---
    "tc_weekly_confidence",
    "tc_weekly_bull_count",
    "tc_weekly_bear_count",
    "tc_weekly_avg_speed",
    "tc_weekly_avg_acceleration",
    "tc_weekly_reversal_score",
    "tc_daily_confidence",
    "tc_daily_bull_count",
    "tc_daily_bear_count",
    "tc_daily_avg_speed",
    "tc_daily_avg_acceleration",
    "tc_daily_reversal_score",
    "tc_consistent",              # 0 or 1
    "tc_consistency_confidence",

    # --- 贝叶斯置信度 ---
    "bc_confidence",
    "bc_bull_probability",
    "bc_bear_probability",

    # --- 经典指标综合置信度 ---
    "cc_weekly_confidence",
    "cc_weekly_bull_count",
    "cc_weekly_bear_count",
    "cc_weekly_neutral_count",
    "cc_weekly_dynamics_bonus",
    "cc_daily_confidence",
    "cc_daily_bull_count",
    "cc_daily_bear_count",
    "cc_daily_neutral_count",
    "cc_daily_dynamics_bonus",
    "cc_overall_confidence",
    "cc_trend_consistent",

    # --- 技术面+基本面融合 ---
    "tff_tech_confidence",
    "tff_fund_confidence",
    "tff_consistent",
    "tff_conflict_level",

    # --- 价值风险评估 ---
    "vr_vol_ratio",
    "vr_rr_ratio",
    "vr_value_gt_risk",

    # --- Freqtrade信号 ---
    "ft_1h_signal_bull",          # 0 or 1
    "ft_1h_signal_bear",          # 0 or 1
    "ft_1h_confidence",
    "ft_4h_signal_bull",
    "ft_4h_signal_bear",
    "ft_4h_confidence",
    "ft_consistent",

    # --- 最终信号 ---
    "fs_confidence",
    "fs_trend_consistent",
    "fs_fusion_consistent",
    "fs_freqtrade_consistent",
]

NUM_FEATURES = len(ALGO_FEATURE_NAMES)


def extract_features_from_signal(full_signal: Dict) -> Optional[np.ndarray]:
    """从 compute_full_trading_signal() 的输出中提取特征向量

    参数:
        full_signal: compute_full_trading_signal() / compute_trend_signal_from_dataframes() 的返回值

    返回:
        np.ndarray, shape=(NUM_FEATURES,) 或 None（数据不完整时）
    """
    if not full_signal or full_signal.get("error"):
        return None

    try:
        tc = full_signal.get("trend_consistency", {})
        bc = full_signal.get("bayesian_confidence", {})
        cc = full_signal.get("classic_indicator_confidence", {})
        tff = full_signal.get("technical_fundamental_fusion", {})
        vr = full_signal.get("value_risk_assessment", {})
        ft = full_signal.get("freqtrade_signals", {})
        fs = full_signal.get("final_signal", {})

        # --- 趋势一致性 ---
        tc_w = tc.get("weekly", {})
        tc_d = tc.get("daily", {})

        # --- 经典指标置信度 ---
        cc_w = cc.get("screen1_weekly", {})
        cc_d = cc.get("screen2_daily", {})

        # --- 价值风险评估 ---
        vr_tp_sl = vr.get("take_profit_stop_loss", {}) if vr else {}
        vr_rr = vr_tp_sl.get("risk_reward", {}) if vr_tp_sl else {}

        # --- Freqtrade信号 ---
        ft_1h = ft.get("1h", {}) if ft else {}
        ft_4h = ft.get("4h", {}) if ft else {}
        ft_1h_sig = ft_1h.get("signal", "HOLD") if ft_1h else "HOLD"
        ft_4h_sig = ft_4h.get("signal", "HOLD") if ft_4h else "HOLD"

        features = [
            # 趋势一致性 - 周线
            float(tc_w.get("confidence", 0)),
            float(tc_w.get("bull_count", 0)),
            float(tc_w.get("bear_count", 0)),
            float(tc_w.get("avg_speed", 0)),
            float(tc_w.get("avg_acceleration", 0)),
            float(tc_w.get("reversal_score", 0)),
            # 趋势一致性 - 日线
            float(tc_d.get("confidence", 0)),
            float(tc_d.get("bull_count", 0)),
            float(tc_d.get("bear_count", 0)),
            float(tc_d.get("avg_speed", 0)),
            float(tc_d.get("avg_acceleration", 0)),
            float(tc_d.get("reversal_score", 0)),
            # 趋势一致性 - 汇总
            1.0 if tc.get("consistent") else 0.0,
            float(tc.get("consistency_confidence", 0)),

            # 贝叶斯置信度
            float(bc.get("confidence", 0)),
            float(bc.get("bull_probability", 0)),
            float(bc.get("bear_probability", 0)),

            # 经典指标 - 周线
            float(cc_w.get("confidence", 0)),
            float(cc_w.get("bull_count", 0)),
            float(cc_w.get("bear_count", 0)),
            float(cc_w.get("neutral_count", 0)),
            float(cc_w.get("dynamics_bonus", 0)),
            # 经典指标 - 日线
            float(cc_d.get("confidence", 0)),
            float(cc_d.get("bull_count", 0)),
            float(cc_d.get("bear_count", 0)),
            float(cc_d.get("neutral_count", 0)),
            float(cc_d.get("dynamics_bonus", 0)),
            # 经典指标 - 汇总
            float(cc.get("overall_confidence", 0)),
            1.0 if cc.get("trend_consistent") else 0.0,

            # 技术面+基本面融合
            float(tff.get("technical", {}).get("confidence", 0)),
            float(tff.get("fundamental", {}).get("confidence", 0)),
            1.0 if tff.get("consistent") else 0.0,
            float(tff.get("conflict_level", 0)),

            # 价值风险评估
            float(vr.get("volatility", {}).get("vol_ratio", 1.0)) if vr else 1.0,
            float(vr_rr.get("rr_ratio", 0)) if vr_rr else 0,
            1.0 if (vr and vr.get("value_gt_risk")) else 0.