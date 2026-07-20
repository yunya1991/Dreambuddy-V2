"""四类目的特征映射器

将现有100+维特征按"交易目的"重新组织，分为四类：
1. DIP_BUY   (牛市抄底) — 识别底部区域，指导买入时机
2. TOP_EXIT  (牛市离场) — 识别顶部区域，指导卖出逃顶
3. BEAR_SHORT(熊市做空) — 识别下跌趋势，指导做空入场
4. BEAR_EXIT (熊市空平) — 识别下跌衰竭，指导空头止盈

设计原则：
- 双维度分类：保留原有"按来源（三个管道）"分类，增加"按目的（四类）"分类
- 渐进式：不破坏现有代码，只增加映射层
- 可迭代：映射关系可通过回测验证不断修正
- 带权重：每个特征对每个目的有"相关性权重"[0, 1]，而非简单的0/1归属

特征相关性权重定义：
  1.0 = 核心特征，专为该目的设计
  0.7 = 强相关，对该目的有重要贡献
  0.4 = 弱相关，有辅助作用
  0.1 = 微相关，聊胜于无
  0.0 = 不相关

文件：four_objective_framework_design.md
"""

from typing import Dict, List, Tuple, Optional, Any
from enum import Enum
import numpy as np
import pandas as pd


class ObjectiveType(str, Enum):
    """四类交易目的"""
    DIP_BUY = "dip_buy"          # 牛市抄底
    TOP_EXIT = "top_exit"        # 牛市离场
    BEAR_SHORT = "bear_short"    # 熊市做空
    BEAR_EXIT = "bear_exit"      # 熊市空平


# ── 特征→四类目的 相关性权重映射 ──────────────────────────────────────
# 每个特征对四个目的的相关性权重 [0, 1]
# 来源：理论分析 + v2策略回测经验 + 哲学贡献验证
# 注：初始权重基于理论和经验，后续通过回测消融实验不断修正

FEATURE_OBJECTIVE_MAP: Dict[str, Dict[str, float]] = {
    # ==================================================================
    # A. 价格特征管道（TrendFeatureEngineer，~30维）
    # 来源：三重滤网理论 + Elder-ray指标
    # ==================================================================

    # A1. 趋势方向 direction（8维）
    "ema_slope_13": {
        "dip_buy": 0.4, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.5,
    },
    "ema_slope_26": {
        "dip_buy": 0.4, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.5,
    },
    "ema_slope_50": {
        "dip_buy": 0.5, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },
    "ema_slope_100": {
        "dip_buy": 0.6, "top_exit": 0.8, "bear_short": 0.9, "bear_exit": 0.7,
    },
    "price_vs_ema_13": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "price_vs_ema_26": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "price_vs_ema_50": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "price_vs_ema_100": {
        "dip_buy": 0.7, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.7,
    },
    "trend_alignment": {
        "dip_buy": 0.6, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },
    "ema13_slope_dir": {
        "dip_buy": 0.3, "top_exit": 0.4, "bear_short": 0.5, "bear_exit": 0.4,
    },
    "hl_position_20": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.5, "bear_exit": 0.5,
    },
    "hl_position_60": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.6, "bear_exit": 0.6,
    },

    # A2. 趋势变化 change（9维）
    "bullish_divergence": {
        "dip_buy": 0.9, "top_exit": 0.2, "bear_short": 0.1, "bear_exit": 0.8,
    },
    "bearish_divergence": {
        "dip_buy": 0.2, "top_exit": 0.9, "bear_short": 0.8, "bear_exit": 0.2,
    },
    "bull_power_negative": {
        "dip_buy": 0.3, "top_exit": 0.8, "bear_short": 0.7, "bear_exit": 0.4,
    },
    "bear_power_positive": {
        "dip_buy": 0.8, "top_exit": 0.3, "bear_short": 0.4, "bear_exit": 0.7,
    },
    "macd_hist_change": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.6, "bear_exit": 0.6,
    },
    "macd_reversal_signal": {
        "dip_buy": 0.7, "top_exit": 0.7, "bear_short": 0.6, "bear_exit": 0.7,
    },
    "momentum_turn_10": {
        "dip_buy": 0.7, "top_exit": 0.7, "bear_short": 0.6, "bear_exit": 0.7,
    },
    "momentum_turn_20": {
        "dip_buy": 0.7, "top_exit": 0.7, "bear_short": 0.6, "bear_exit": 0.7,
    },
    "rsi_bear_divergence": {
        "dip_buy": 0.2, "top_exit": 0.9, "bear_short": 0.8, "bear_exit": 0.2,
    },
    "rsi_bull_divergence": {
        "dip_buy": 0.9, "top_exit": 0.2, "bear_short": 0.1, "bear_exit": 0.8,
    },

    # A3. 趋势速率 velocity（9维）
    "price_velocity_5": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "price_velocity_10": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "price_velocity_20": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "price_acceleration_10": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.5, "bear_exit": 0.5,
    },
    "price_acceleration_20": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.5, "bear_exit": 0.5,
    },
    "vol_adj_velocity_5": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "vol_adj_velocity_10": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "vol_adj_velocity_20": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "ema13_slope_accel": {
        "dip_buy": 0.4, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "momentum_accel_10": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.5, "bear_exit": 0.5,
    },

    # A4. Elder-ray力量 power（10维）
    "bull_power_norm": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.5, "bear_exit": 0.6,
    },
    "bear_power_norm": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "bull_power_slope": {
        "dip_buy": 0.5, "top_exit": 0.6, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "bear_power_slope": {
        "dip_buy": 0.5, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "bull_exhaustion": {
        "dip_buy": 0.2, "top_exit": 0.9, "bear_short": 0.7, "bear_exit": 0.3,
    },
    "bear_exhaustion": {
        "dip_buy": 0.9, "top_exit": 0.2, "bear_short": 0.3, "bear_exit": 0.9,
    },
    "power_balance": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "power_balance_change": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.6, "bear_exit": 0.6,
    },
    "both_weakening": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.4, "bear_exit": 0.5,
    },
    "bull_cross_negative": {
        "dip_buy": 0.3, "top_exit": 0.8, "bear_short": 0.7, "bear_exit": 0.4,
    },
    "bear_cross_positive": {
        "dip_buy": 0.8, "top_exit": 0.3, "bear_short": 0.4, "bear_exit": 0.7,
    },

    # A5. 多尺度层级 hierarchy（8维）
    "macro_trend_slope": {
        "dip_buy": 0.7, "top_exit": 0.8, "bear_short": 0.9, "bear_exit": 0.7,
    },
    "macro_trend_dir": {
        "dip_buy": 0.6, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },
    "micro_trend_slope": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "trend_scale_alignment": {
        "dip_buy": 0.6, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },
    "counter_trend_accum_10": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.5, "bear_exit": 0.6,
    },
    "counter_trend_accum_20": {
        "dip_buy": 0.7, "top_exit": 0.7, "bear_short": 0.6, "bear_exit": 0.7,
    },
    "reversal_warning": {
        "dip_buy": 0.8, "top_exit": 0.8, "bear_short": 0.6, "bear_exit": 0.8,
    },
    "vol_compression": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.4, "bear_exit": 0.5,
    },
    "volume_trend_20": {
        "dip_buy": 0.6, "top_exit": 0.5, "bear_short": 0.5, "bear_exit": 0.6,
    },

    # ==================================================================
    # B. 阻力特征管道（LeastResistanceFeatureEngineer，60+维）
    # 来源：最小阻力方向理论 + 哲学贡献特征
    # ==================================================================

    # B1. 五维阻力 daily_res（7维）
    "price_res_daily": {
        "dip_buy": 0.7, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.7,
    },
    "volume_res_daily": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.5, "bear_exit": 0.5,
    },
    "momentum_res_daily": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "trend_res_daily": {
        "dip_buy": 0.6, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },
    "composite_res_daily": {
        "dip_buy": 0.7, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.7,
    },
    "weekly_price_res": {
        "dip_buy": 0.8, "top_exit": 0.8, "bear_short": 0.9, "bear_exit": 0.8,
    },
    "weekly_composite_res": {
        "dip_buy": 0.8, "top_exit": 0.8, "bear_short": 0.9, "bear_exit": 0.8,
    },

    # B2. 三维动态特征（速度/加速度/动能）
    "price_speed": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.7, "bear_exit": 0.5,
    },
    "price_accel": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "momentum_strength": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "trend_strength": {
        "dip_buy": 0.6, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },

    # B3. 跨周期一致性
    "weekly_daily_align": {
        "dip_buy": 0.7, "top_exit": 0.8, "bear_short": 0.9, "bear_exit": 0.7,
    },
    "multi_timeframe_score": {
        "dip_buy": 0.7, "top_exit": 0.8, "bear_short": 0.9, "bear_exit": 0.7,
    },

    # B4. 多窗口统计
    "volatility_ratio": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "range_ratio": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.5, "bear_exit": 0.5,
    },

    # ==================================================================
    # C. 哲学贡献特征（15维，practice_validated）
    # 来源：v2增强版MA200策略消融验证
    # ==================================================================

    # 哲学1: BTC/小币分化（4维）
    "btc_regime_label": {
        "dip_buy": 0.8, "top_exit": 0.8, "bear_short": 0.9, "bear_exit": 0.8,
    },
    "btc_alt_divergence": {
        "dip_buy": 0.6, "top_exit": 0.5, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "is_btc_asset": {
        "dip_buy": 0.3, "top_exit": 0.3, "bear_short": 0.8, "bear_exit": 0.3,
    },
    "alt_short_risk_score": {
        "dip_buy": 0.2, "top_exit": 0.3, "bear_short": 0.9, "bear_exit": 0.4,
    },

    # 哲学2: 左侧抄底（4维）— DIP_BUY核心特征
    # Stage 2.0/2.1 WF验证：weekly_ma200_distance是唯一有效特征(#7, 82.2)
    # 其余三个派生特征重要性=0.0，LightGBM偏好连续值而非离散档位
    "weekly_ma200_distance": {
        "dip_buy": 1.0, "top_exit": 0.5, "bear_short": 0.8, "bear_exit": 0.7,
    },
    "dip_buy_level": {
        # ⚠️ Stage 2.4 降权：WF验证排名#56，重要性0.0，从weekly_ma200_distance派生
        # ML冗余特征：LightGBM已从连续值学到信息，离散档位无增益
        "dip_buy": 0.1, "top_exit": 0.1, "bear_short": 0.1, "bear_exit": 0.2,
    },
    "dip_buy_position_ratio": {
        # ⚠️ Stage 2.4 降权：WF验证排名#74，重要性0.0，从weekly_ma200_distance派生
        # ML冗余特征：与dip_buy_level信息重复
        "dip_buy": 0.1, "top_exit": 0.1, "bear_short": 0.1, "bear_exit": 0.2,
    },
    "left_side_buy_signal": {
        # ⚠️ Stage 2.4 降权：WF验证排名#75，重要性0.0，从dip_buy_position_ratio派生
        # ML冗余特征：三级派生链末端，信息量极低
        "dip_buy": 0.1, "top_exit": 0.1, "bear_short": 0.1, "bear_exit": 0.2,
    },

    # 哲学3: 分层仓位（4维）
    "bear_short_layer": {
        "dip_buy": 0.4, "top_exit": 0.6, "bear_short": 1.0, "bear_exit": 0.7,
    },
    "fib_tp_remaining_ratio": {
        "dip_buy": 0.3, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 1.0,
    },
    "layered_position_target": {
        "dip_buy": 0.7, "top_exit": 0.7, "bear_short": 0.9, "bear_exit": 0.8,
    },
    "position_adjustment": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.7,
    },

    # 哲学4: 双牛过滤（3维）— DIP_BUY强相关
    "btc_bull_confirmed": {
        "dip_buy": 0.9, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },
    "self_bull_confirmed": {
        "dip_buy": 0.8, "top_exit": 0.7, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "double_bull_score": {
        "dip_buy": 0.9, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },

    # 哲学5: 减半周期锚定（3维）— TOP_EXIT核心特征（V4新增）
    # Walk-Forward验证：halving_months_after排名#1，halving_phase/position_cap因冗余排名靠后
    "halving_months_after": {
        "dip_buy": 0.5, "top_exit": 1.0, "bear_short": 0.4, "bear_exit": 0.5,
    },
    "halving_phase": {
        # 冗余特征：与halving_months_after编码相同信息，LightGBM选择连续值版本
        # WF验证排名#61，重要性0.0 → 降权
        "dip_buy": 0.2, "top_exit": 0.3, "bear_short": 0.1, "bear_exit": 0.2,
    },
    "halving_position_cap": {
        # 冗余特征：与halving_months_after编码相同信息，LightGBM选择连续值版本
        # WF验证排名#64，重要性0.0 → 降权
        "dip_buy": 0.3, "top_exit": 0.3, "bear_short": 0.1, "bear_exit": 0.3,
    },

    # 哲学6: MA128破位逃顶（2维）— TOP_EXIT核心特征（V4新增）
    # Walk-Forward验证：ma128_distance_pct排名#8，ma128_below_days排名#10，均为核心
    "ma128_distance_pct": {
        "dip_buy": 0.7, "top_exit": 1.0, "bear_short": 0.8, "bear_exit": 0.8,
    },
    "ma128_below_days": {
        "dip_buy": 0.6, "top_exit": 1.0, "bear_short": 0.7, "bear_exit": 0.7,
    },

    # 哲学7: 越高越卖（2维）— V4新增
    # Walk-Forward验证：ath_drawdown_pct排名#5（TOP_EXIT核心），bounce_from_low_pct排名#43（低相关）
    "ath_drawdown_pct": {
        "dip_buy": 0.5, "top_exit": 0.9, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "bounce_from_low_pct": {
        # WF验证在TOP_EXIT排名#43，重要性2.2 → 降权
        # 迁移到BEAR_EXIT场景：反弹幅度是空头止盈的核心信号
        "dip_buy": 0.6, "top_exit": 0.3, "bear_short": 0.5, "bear_exit": 1.0,
    },

    # 哲学8: 量价抄底确认（2维）— Stage 2.1新增，假设DIP-001
    "rsi_14": {
        # DIP_BUY核心：RSI<30超卖是抄底确认信号
        "dip_buy": 1.0, "top_exit": 0.4, "bear_short": 0.3, "bear_exit": 0.7,
    },
    "volume_ratio_20d": {
        # DIP_BUY核心：底部放量确认抄底有效性
        "dip_buy": 0.9, "top_exit": 0.5, "bear_short": 0.4, "bear_exit": 0.4,
    },

    # ==================================================================
    # D. 集成推理管道特征（algo_ensemble，55维）
    # 来源：五大算法输出
    # ==================================================================

    # D1. 趋势一致性（14维）
    "tc_weekly_confidence": {
        "dip_buy": 0.7, "top_exit": 0.8, "bear_short": 0.9, "bear_exit": 0.7,
    },
    "tc_weekly_reversal": {
        "dip_buy": 0.8, "top_exit": 0.8, "bear_short": 0.6, "bear_exit": 0.8,
    },
    "tc_weekly_bull": {
        "dip_buy": 0.7, "top_exit": 0.6, "bear_short": 0.5, "bear_exit": 0.7,
    },
    "tc_weekly_bear": {
        "dip_buy": 0.5, "top_exit": 0.8, "bear_short": 0.9, "bear_exit": 0.6,
    },
    "tc_weekly_speed": {
        "dip_buy": 0.5, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "tc_weekly_accel": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "tc_weekly_static_dir": {
        "dip_buy": 0.6, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },
    "tc_daily_confidence": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "tc_daily_reversal": {
        "dip_buy": 0.7, "top_exit": 0.7, "bear_short": 0.5, "bear_exit": 0.7,
    },
    "tc_daily_bull": {
        "dip_buy": 0.6, "top_exit": 0.5, "bear_short": 0.4, "bear_exit": 0.6,
    },
    "tc_daily_bear": {
        "dip_buy": 0.4, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.5,
    },
    "tc_daily_speed": {
        "dip_buy": 0.4, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "tc_daily_accel": {
        "dip_buy": 0.4, "top_exit": 0.4, "bear_short": 0.5, "bear_exit": 0.4,
    },
    "tc_daily_static_dir": {
        "dip_buy": 0.5, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.5,
    },
    "tc_consistent": {
        "dip_buy": 0.6, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },
    "tc_consistency_confidence": {
        "dip_buy": 0.6, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },

    # D2. 贝叶斯置信度（3维）
    "bayes_confidence": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "bayes_bull_prob": {
        "dip_buy": 0.7, "top_exit": 0.5, "bear_short": 0.4, "bear_exit": 0.7,
    },
    "bayes_bear_prob": {
        "dip_buy": 0.4, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.5,
    },

    # D3. 经典指标置信度（9维）
    "classic_s1_confidence": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "classic_s1_bull": {
        "dip_buy": 0.7, "top_exit": 0.5, "bear_short": 0.4, "bear_exit": 0.6,
    },
    "classic_s1_bear": {
        "dip_buy": 0.4, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.5,
    },
    "classic_s1_dynamics_bonus": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.5, "bear_exit": 0.5,
    },
    "classic_s2_confidence": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "classic_s2_bull": {
        "dip_buy": 0.6, "top_exit": 0.4, "bear_short": 0.3, "bear_exit": 0.5,
    },
    "classic_s2_bear": {
        "dip_buy": 0.3, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.4,
    },
    "classic_s2_dynamics_bonus": {
        "dip_buy": 0.4, "top_exit": 0.4, "bear_short": 0.4, "bear_exit": 0.4,
    },
    "classic_overall_confidence": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.7, "bear_exit": 0.6,
    },
    "classic_trend_consistent": {
        "dip_buy": 0.6, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.6,
    },

    # D4. 技术基本面融合（4维）
    "fusion_consistency": {
        "dip_buy": 0.6, "top_exit": 0.6, "bear_short": 0.6, "bear_exit": 0.6,
    },
    "fusion_conflict_level": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.5, "bear_exit": 0.5,
    },
    "fusion_bull_weight": {
        "dip_buy": 0.7, "top_exit": 0.5, "bear_short": 0.4, "bear_exit": 0.6,
    },
    "fusion_bear_weight": {
        "dip_buy": 0.4, "top_exit": 0.7, "bear_short": 0.8, "bear_exit": 0.5,
    },

    # D5. 价值风险评估（4维）
    "rr_volatility_ratio": {
        "dip_buy": 0.5, "top_exit": 0.5, "bear_short": 0.6, "bear_exit": 0.5,
    },
    "rr_risk_reward_ratio": {
        "dip_buy": 0.7, "top_exit": 0.6, "bear_short": 0.6, "bear_exit": 0.7,
    },
    "rr_value_gt_risk": {
        "dip_buy": 0.8, "top_exit": 0.5, "bear_short": 0.4, "bear_exit": 0.7,
    },
    "rr_position_size": {
        "dip_buy": 0.7, "top_exit": 0.5, "bear_short": 0.5, "bear_exit": 0.7,
    },
}

# 各目的的核心特征（权重 >= 0.8）
CORE_FEATURES_BY_OBJECTIVE: Dict[str, List[str]] = {
    "dip_buy": [
        f for f, m in FEATURE_OBJECTIVE_MAP.items()
        if m.get("dip_buy", 0) >= 0.8
    ],
    "top_exit": [
        f for f, m in FEATURE_OBJECTIVE_MAP.items()
        if m.get("top_exit", 0) >= 0.8
    ],
    "bear_short": [
        f for f, m in FEATURE_OBJECTIVE_MAP.items()
        if m.get("bear_short", 0) >= 0.8
    ],
    "bear_exit": [
        f for f, m in FEATURE_OBJECTIVE_MAP.items()
        if m.get("bear_exit", 0) >= 0.8
    ],
}


# ── 四类目的的标签定义 ─────────────────────────────────────────────────

OBJECTIVE_LABEL_DEFS: Dict[str, Dict[str, Any]] = {
    "dip_buy": {
        "name": "牛市抄底",
        "description": "识别熊市底部区域，指导左侧/右侧抄底买入",
        "label_type": "binary",
        "lookahead_days": 20,
        "label_rule": "未来20日涨幅 > 15% 且 期间最大回撤 < 10% → 1（优质抄底点）",
        "positive_label": 1,
        "negative_label": 0,
        "baseline_signal": "v2策略周线MA200抄底4层触发点（跌破0%/5%/10%/15%）",
        "optimization_goal": "更早识别底部、更高收益风险比、更低假阳性",
    },
    "top_exit": {
        "name": "牛市离场",
        "description": "识别牛市顶部区域，指导逃顶卖出",
        "label_type": "binary",
        "lookahead_days": 20,
        "label_rule": "未来20日收盘价跌幅 > 20% → 1（优质逃顶点）",
        "label_note": "使用期末收盘价跌幅而非期间最低点，避免正样本率过高(34%→7%)",
        "positive_label": 1,
        "negative_label": 0,
        "baseline_signal": "v4策略减半周期Danger/Peak阶段 + MA128破位",
        "optimization_goal": "更早在顶部离场、减少利润回吐、避免假摔误判",
    },
    "bear_short": {
        "name": "熊市做空",
        "description": "识别下跌趋势确认，指导顺势做空入场",
        "label_type": "binary",
        "lookahead_days": 10,
        "label_rule": "未来10日跌幅 > 10% 且 期间反弹 < 5% → 1（优质做空点）",
        "positive_label": 1,
        "negative_label": 0,
        "baseline_signal": "v2策略跌破MA200 + 5日斜率负 → 5成仓做空",
        "optimization_goal": "更早识别下跌趋势、更准的做空入场点、更低假突破风险",
    },
    "bear_exit": {
        "name": "熊市空平",
        "description": "识别下跌衰竭/底部区域，指导空头止盈离场",
        "label_type": "binary",
        "lookahead_days": 10,
        "label_rule": "未来10日反弹 > 10% 或 跌幅连续收窄 → 1（优质空平点）",
        "positive_label": 1,
        "negative_label": 0,
        "baseline_signal": "v2策略斐波那契止盈最后一档（61.8%全部平仓）",
        "optimization_goal": "更早平空、避免反弹回吐、保留下跌趋势中的利润",
    },
}


# ── 映射器类 ──────────────────────────────────────────────────────────

class FourObjectiveFeatureMapper:
    """四类目的特征映射器

    将特征从"按来源组织"转换为"按目的组织"，支持：
    - 查询每个特征对各目的的相关性权重
    - 获取某目的的核心特征列表
    - 按目的过滤特征集（只保留相关度高于阈值的特征）
    - 生成各目的的标签（基于价格数据）
    """

    def __init__(self):
        self.feature_map = FEATURE_OBJECTIVE_MAP
        self.core_features = CORE_FEATURES_BY_OBJECTIVE
        self.label_defs = OBJECTIVE_LABEL_DEFS

    def get_feature_weight(self, feature_name: str, objective: str) -> float:
        """获取某个特征对某目的的相关性权重"""
        return self.feature_map.get(feature_name, {}).get(objective, 0.0)

    def get_objective_features(
        self, objective: str, threshold: float = 0.0
    ) -> List[str]:
        """获取某目的的相关特征列表（按权重降序）

        Args:
            objective: 目的类型 (dip_buy / top_exit / bear_short / bear_exit)
            threshold: 权重阈值，只返回权重 >= threshold 的特征

        Returns:
            按权重降序排列的特征名列表
        """
        features = [
            (f, m.get(objective, 0.0))
            for f, m in self.feature_map.items()
            if m.get(objective, 0.0) >= threshold
        ]
        features.sort(key=lambda x: x[1], reverse=True)
        return [f for f, _ in features]

    def get_core_features(self, objective: str) -> List[str]:
        """获取某目的的核心特征（权重 >= 0.8）"""
        return self.core_features.get(objective, [])

    def get_feature_objectives(
        self, feature_name: str
    ) -> List[Tuple[str, float]]:
        """获取某个特征对四个目的的权重分布"""
        weights = self.feature_map.get(feature_name, {})
        result = [(obj, w) for obj, w in weights.items()]
        result.sort(key=lambda x: x[1], reverse=True)
        return result

    def generate_labels(
        self, df: pd.DataFrame, objective: str
    ) -> pd.Series:
        """为指定目的生成标签列

        Args:
            df: 包含OHLCV的DataFrame，索引为datetime
            objective: 目的类型

        Returns:
            标签Series，与df同长度
        """
        if objective not in self.label_defs:
            raise ValueError(f"未知目的: {objective}")

        ldef = self.label_defs[objective]
        lookahead = ldef["lookahead_days"]
        closes = df["close"].values
        n = len(closes)
        labels = np.zeros(n, dtype=int)

        if objective == "dip_buy":
            # 未来20日涨幅 > 15% 且 最大回撤 < 10%
            for i in range(n - lookahead):
                future_prices = closes[i:i + lookahead + 1]
                if len(future_prices) < 2:
                    continue
                entry_price = future_prices[0]
                max_price = np.max(future_prices)
                min_price_after = np.min(future_prices[1:])
                gain_pct = (max_price - entry_price) / entry_price
                drawdown_pct = (entry_price - min_price_after) / entry_price
                if gain_pct > 0.15 and drawdown_pct < 0.10:
                    labels[i] = 1

        elif objective == "top_exit":
            # 未来20日收盘价跌幅 > 20% → 1（优质逃顶点）
            # 修复：使用期末收盘价跌幅替代期间最低点跌幅
            # 原因：期间最低点方式正样本率高达34.4%，接近随机；
            #       期末收盘价方式正样本率约7%，更符合极端逃顶事件定义
            for i in range(n - lookahead):
                future_close = closes[i + lookahead]
                drop_pct = (closes[i] - future_close) / closes[i]
                if drop_pct > 0.20:
                    labels[i] = 1

        elif objective == "bear_short":
            # 未来10日跌幅 > 10% 且 反弹 < 5%
            for i in range(n - lookahead):
                future_prices = closes[i:i + lookahead + 1]
                if len(future_prices) < 2:
                    continue
                entry_price = future_prices[0]
                min_price = np.min(future_prices)
                max_rally = np.max(future_prices[1:]) - entry_price
                drop_pct = (entry_price - min_price) / entry_price
                rally_pct = max_rally / entry_price if entry_price > 0 else 0
                if drop_pct > 0.10 and rally_pct < 0.05:
                    labels[i] = 1

        elif objective == "bear_exit":
            # 未来10日反弹 > 10% 或 跌幅连续收窄
            for i in range(n - lookahead):
                future_prices = closes[i:i + lookahead + 1]
                if len(future_prices) < 2:
                    continue
                entry_price = future_prices[0]
                max_price = np.max(future_prices)
                rally_pct = (max_price - entry_price) / entry_price
                if rally_pct > 0.10:
                    labels[i] = 1
                    continue
                # 跌幅收窄：后5日跌幅小于前5日跌幅
                if len(future_prices) >= 11:
                    first_half_drop = entry_price - np.min(future_prices[1:6])
                    second_half_drop = future_prices[5] - np.min(future_prices[6:])
                    if first_half_drop > 0 and second_half_drop < first_half_drop * 0.5:
                        labels[i] = 1

        return pd.Series(labels, index=df.index, name=f"label_{objective}")

    def get_label_def(self, objective: str) -> Dict[str, Any]:
        """获取某目的的标签定义"""
        return self.label_defs.get(objective, {})

    def list_objectives(self) -> List[str]:
        """列出所有目的类型"""
        return list(self.label_defs.keys())

    def summary(self) -> Dict[str, Any]:
        """获取映射器的摘要信息"""
        total_features = len(self.feature_map)
        objective_stats = {}
        for obj in self.list_objectives():
            feats = self.get_objective_features(obj)
            core = self.get_core_features(obj)
            objective_stats[obj] = {
                "name": self.label_defs[obj]["name"],
                "total_related": len(feats),
                "core_features": len(core),
                "avg_weight": sum(
                    self.feature_map[f].get(obj, 0) for f in self.feature_map
                ) / total_features if total_features > 0 else 0,
            }
        return {
            "total_features": total_features,
            "objective_count": len(self.label_defs),
            "objectives": objective_stats,
        }


# ── 便捷函数 ────────────────────────────────────────────────────────────

def get_mapper() -> FourObjectiveFeatureMapper:
    """获取映射器单例"""
    return FourObjectiveFeatureMapper()


def print_summary():
    """打印四类目的特征映射摘要"""
    mapper = get_mapper()
    s = mapper.summary()
    print("=" * 60)
    print("四类目的特征映射摘要")
    print("=" * 60)
    print(f"总特征数: {s['total_features']}")
    print(f"目的类别数: {s['objective_count']}")
    print()
    for obj, stats in s["objectives"].items():
        print(f"  [{obj}] {stats['name']}")
        print(f"    相关特征: {stats['total_related']} 个")
        print(f"    核心特征: {stats['core_features']} 个")
        print(f"    平均权重: {stats['avg_weight']:.3f}")
        print()
    print("=" * 60)
    print("\n各目的Top 5核心特征：")
    for obj in mapper.list_objectives():
        core = mapper.get_core_features(obj)[:5]
        print(f"\n  [{obj}] {mapper.get_label_def(obj)['name']}:")
        for f in core:
            w = mapper.get_feature_weight(f, obj)
            print(f"    {f}: {w:.1f}")


if __name__ == "__main__":
    print_summary()
