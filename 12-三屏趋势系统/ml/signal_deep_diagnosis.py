"""深入诊断信号生成链路

追踪每个环节的信号过滤情况：
1. 特征提取后有多少有效行
2. 模型训练条件是否满足
3. 规则引擎产生多少信号
4. AI预测产生多少信号
5. 融合后最终信号
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from data.market_data import fetch_candles
from ml.lr_ml_strategy_v2 import LeastResistanceAIStrategyV2, _resample_to_weekly
from ml.lr_feature_engineer import LeastResistanceFeatureEngineer
from backtest.engine import BacktestEngine


def fetch_real_data(inst_id, bar="1D", limit=600):
    candles = fetch_candles(inst_id, bar=bar, limit=limit)
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def get_fundamental_data():
    return {
        "screen1": {
            "composite_score": 65.0, "momentum_score": 70.0,
            "value_score": 60.0, "growth_score": 65.0,
            "quality_score": 68.0, "sentiment_score": 55.0,
        },
        "fundamental_9": {
            "pe_ttm": 15.0, "pb": 2.0, "roe": 12.0,
            "revenue_growth": 20.0, "profit_growth": 18.0,
            "debt_ratio": 45.0, "cash_ratio": 30.0,
            "gross_margin": 35.0, "net_margin": 15.0,
        }
    }


def deep_diagnose(inst_id="BTC-USDT", name="BTC"):
    print(f"\n{'='*70}")
    print(f"  深入诊断: {name}")
    print(f"{'='*70}")

    prices = fetch_real_data(inst_id)
    if prices.empty:
        return
    n = len(prices)
    print(f"  数据: {n} 天")

    # 步骤1: 检查特征提取
    print(f"\n  [步骤1] 特征提取")
    weekly_df = _resample_to_weekly(prices)
    print(f"    周线数据: {len(weekly_df)} 根")

    fe = LeastResistanceFeatureEngineer(enable_fundamental=True)
    features_df = fe.create_features(
        weekly_df, prices,
        fundamental_data=get_fundamental_data(),
        label_lookahead=7,
    )

    all_feature_cols = [c for c in features_df.columns if not c.startswith("label_")]
    first_valid = features_df[all_feature_cols].dropna().index
    if len(first_valid) == 0:
        print("    ✗ 无有效特征行")
        return
    start_idx = features_df.index.get_loc(first_valid[0])
    print(f"    特征列数: {len(all_feature_cols)}")
    print(f"    第一个有效行位置: start_idx={start_idx} (即第{start_idx+1}天)")
    print(f"    可交易天数: {n - start_idx} 天")

    # 步骤2: 检查规则引擎信号分布
    print(f"\n  [步骤2] 规则引擎信号分布")
    weekly_res = features_df.iloc[start_idx:]["weekly_res_diff"].fillna(0)
    daily_res = features_df.iloc[start_idx:]["daily_res_diff"].fillna(0)

    rule_long = ((weekly_res > 0.05) | ((weekly_res.abs() <= 0.05) & (daily_res > 0.05))).sum()
    rule_short = ((weekly_res < -0.05) | ((weekly_res.abs() <= 0.05) & (daily_res < -0.05))).sum()
    rule_neutral = len(weekly_res) - rule_long - rule_short

    print(f"    weekly_res范围: [{weekly_res.min():.4f}, {weekly_res.max():.4f}]")
    print(f"    daily_res范围:  [{daily_res.min():.4f}, {daily_res.max():.4f}]")
    print(f"    规则多: {rule_long}, 规则空: {rule_short}, 中性: {rule_neutral}")

    # 步骤3: 检查不同阈值下的信号
    print(f"\n  [步骤3] 不同阈值下的规则信号")
    for threshold in [0.05, 0.03, 0.02, 0.01, 0.005]:
        r_long = ((weekly_res > threshold) | ((weekly_res.abs() <= threshold) & (daily_res > threshold))).sum()
        r_short = ((weekly_res < -threshold) | ((weekly_res.abs() <= threshold) & (daily_res < -threshold))).sum()
        r_neutral = len(weekly_res) - r_long - r_short
        print(f"    阈值={threshold:.3f}: 多={r_long}, 空={r_short}, 中性={r_neutral}")

    # 步骤4: 检查模型训练条件
    print(f"\n  [步骤4] 模型训练条件")
    train_window = 200
    label_lookahead = 7
    min_train_i = train_window + label_lookahead + 10  # 217
    print(f"    train_window={train_window}, label_lookahead={label_lookahead}")
    print(f"    最小训练位置: i>={min_train_i} (第{min_train_i+1}天)")
    print(f"    start_idx={start_idx}")
    print(f"    可训练天数: {n - max(start_idx, min_train_i)} 天")

    train_end = min_train_i - label_lookahead - 1
    train_start = max(start_idx, train_end - train_window)
    print(f"    训练范围: [{train_start}, {train_end}]")
    train_data = features_df.iloc[train_start:train_end].dropna(
        subset=all_feature_cols + ["label_direction"]
    )
    print(f"    有效训练样本: {len(train_data)} (需>=40)")

    # 步骤5: 如果用train_window=100
    print(f"\n  [步骤4b] train_window=100时")
    min_train_i_100 = 100 + label_lookahead + 10  # 117
    train_end_100 = min_train_i_100 - label_lookahead - 1
    train_start_100 = max(start_idx, train_end_100 - 100)
    train_data_100 = features_df.iloc[train_start_100:train_end_100].dropna(
        subset=all_feature_cols + ["label_direction"]
    )
    print(f"    最小训练位置: i>={min_train_i_100} (第{min_train_i_100+1}天)")
    print(f"    训练范围: [{train_start_100}, {train_end_100}]")
    print(f"    有效训练样本: {len(train_data_100)}")
    print(f"    可交易天数: {n - max(start_idx, min_train_i_100)} 天")

    # 步骤6: 实际运行策略看信号分布
    print(f"\n  [步骤5] 实际策略信号分布")
    strategy = LeastResistanceAIStrategyV2(
        label_lookahead=7, train_window=100, retrain_interval=20,
        min_ml_confidence=0.01, enable_fundamental=True,
        enable_multitask=True, enable_dynamic_weight=True,
        enable_feature_selection=False, base_rule_weight=0.3,
        fundamental_data=get_fundamental_data(),
    )
    signals = strategy.generate_signals(prices)

    n_long = (signals > 0).sum()
    n_short = (signals < 0).sum()
    n_flat = (signals == 0).sum()
    print(f"    多: {n_long}, 空: {n_short}, 空仓: {n_flat}")

    # 信号时间分布
    if n_long + n_short > 0:
        sig_dates = signals[signals != 0]
        print(f"    信号时间范围: {sig_dates.index[0].date()} ~ {sig_dates.index[-1].date()}")
        print(f"    信号详情(前10):")
        for date, val in sig_dates.head(10).items():
            direction = "多" if val > 0 else "空"
            print(f"      {date.date()}: {direction} {abs(val):.3f}")


def main():
    print("=" * 70)
    print("  信号生成深入诊断")
    print("=" * 70)

    for inst_id, name in [("BTC-USDT", "BTC"), ("SOL-USDT", "SOL")]:
        deep_diagnose(inst_id, name)


if __name__ == "__main__":
    main()
