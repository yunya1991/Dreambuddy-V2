"""特征工程深度分析

分析现有特征的以下方面：
1. 特征数量和类型分布
2. 特征与目标变量的相关性
3. 特征之间的相关性（多重共线性）
4. 特征缺失值情况
5. 特征重要性排序（基于LightGBM）

帮助识别低质量特征和改进方向。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import json
from datetime import datetime

from data.market_data import fetch_candles
from ml.lr_feature_engineer import LeastResistanceFeatureEngineer


def fetch_real_data(inst_id, limit=600):
    candles = fetch_candles(inst_id, bar="1D", limit=limit)
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def _resample_to_weekly(daily_df):
    df = daily_df.copy()
    df.index = pd.to_datetime(df.index)
    weekly = df.resample("W").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    return weekly


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


def analyze_features(inst_id, name):
    print(f"\n{'='*70}")
    print(f"  {name} 特征工程深度分析")
    print(f"{'='*70}")

    prices = fetch_real_data(inst_id, limit=600)
    if prices.empty:
        print("  ✗ 数据获取失败")
        return None

    n = len(prices)
    weekly_df = _resample_to_weekly(prices)

    print(f"\n数据: {n} 天, 周线: {len(weekly_df)} 根")

    fe = LeastResistanceFeatureEngineer(enable_fundamental=True)
    features_df = fe.create_features(
        weekly_df, prices,
        fundamental_data=get_fundamental_data(),
        label_lookahead=7,
    )

    feature_cols = [c for c in features_df.columns if not c.startswith("label_")]
    label_cols = [c for c in features_df.columns if c.startswith("label_")]

    print(f"\n特征总数: {len(feature_cols)}")
    print(f"标签列: {label_cols}")

    # 1. 特征类型分布
    print(f"\n{'='*50}")
    print("  1. 特征类型分布")
    print(f"{'='*50}")

    feature_types = {
        "daily_res": [],
        "weekly_res": [],
        "cross": [],
        "daily_vel": [],
        "weekly_vel": [],
        "daily_window": [],
        "weekly_window": [],
        "trend_strength": [],
        "dominant": [],
        "screen1": [],
        "fundamental_9": [],
        "other": [],
    }

    for col in feature_cols:
        if col.startswith("daily_res_"):
            feature_types["daily_res"].append(col)
        elif col.startswith("weekly_res_"):
            feature_types["weekly_res"].append(col)
        elif col.startswith("cross_"):
            feature_types["cross"].append(col)
        elif col.startswith("daily_velocity") or col.startswith("daily_conf") or col.startswith("daily_accel"):
            feature_types["daily_vel"].append(col)
        elif col.startswith("weekly_velocity") or col.startswith("weekly_accel"):
            feature_types["weekly_vel"].append(col)
        elif col.startswith("daily_dir_") or col.startswith("daily_conf_mean"):
            feature_types["daily_window"].append(col)
        elif col.startswith("weekly_dir_"):
            feature_types["weekly_window"].append(col)
        elif col.startswith("trend_strength"):
            feature_types["trend_strength"].append(col)
        elif col.startswith("dominant"):
            feature_types["dominant"].append(col)
        elif col.startswith("s1_"):
            feature_types["screen1"].append(col)
        elif col.startswith("f9_"):
            feature_types["fundamental_9"].append(col)
        else:
            feature_types["other"].append(col)

    total = 0
    for k, v in feature_types.items():
        count = len(v)
        total += count
        print(f"  {k:20} {count:3d} 个")
    print(f"  {'总计':20} {total:3d} 个")

    # 2. 缺失值分析
    print(f"\n{'='*50}")
    print("  2. 缺失值分析")
    print(f"{'='*50}")

    missing_stats = features_df[feature_cols].isna().sum()
    total_rows = len(features_df)
    high_missing = missing_stats[missing_stats > total_rows * 0.3].sort_values(ascending=False)

    print(f"  总行数: {total_rows}")
    print(f"  完全无缺失的特征: {(missing_stats == 0).sum()} 个")
    print(f"  缺失率>30%的特征: {len(high_missing)} 个")

    if len(high_missing) > 0:
        print(f"\n  高缺失特征（缺失率>30%）:")
        for col, cnt in high_missing.items():
            print(f"    {col:30} {cnt:4d} ({cnt/total_rows*100:.1f}%)")

    # 3. 与目标变量的相关性
    print(f"\n{'='*50}")
    print("  3. 特征与目标变量的相关性")
    print(f"{'='*50}")

    valid_data = features_df.dropna(subset=feature_cols + ["label_direction"])
    if len(valid_data) < 20:
        print("  数据不足，跳过相关性分析")
        return None

    correlations = valid_data[feature_cols].corrwith(valid_data["label_direction"]).abs().sort_values(ascending=False)

    print(f"\n  相关性最高的前20个特征:")
    print(f"  {'特征':30} {'|相关性|':>12}")
    print(f"  {'-'*45}")
    for col, corr in correlations.head(20).items():
        print(f"  {col:30} {corr:>12.4f}")

    print(f"\n  相关性最低的前10个特征（可能冗余）:")
    for col, corr in correlations.tail(10).items():
        print(f"  {col:30} {corr:>12.4f}")

    low_corr_features = correlations[correlations < 0.05].index.tolist()
    print(f"\n  相关性<0.05的特征（共{len(low_corr_features)}个）:")
    for col in low_corr_features:
        print(f"    {col}")

    # 4. 特征间相关性（多重共线性）
    print(f"\n{'='*50}")
    print("  4. 特征间相关性（多重共线性检测）")
    print(f"{'='*50}")

    corr_matrix = valid_data[feature_cols].corr().abs()
    np.fill_diagonal(corr_matrix.values, 0)

    high_corr_pairs = []
    for i in range(len(corr_matrix.columns)):
        for j in range(i + 1, len(corr_matrix.columns)):
            col_i = corr_matrix.columns[i]
            col_j = corr_matrix.columns[j]
            corr = corr_matrix.iloc[i, j]
            if corr > 0.8:
                high_corr_pairs.append((col_i, col_j, corr))

    high_corr_pairs.sort(key=lambda x: -x[2])

    print(f"  相关性>0.8的特征对（共{len(high_corr_pairs)}对）:")
    if len(high_corr_pairs) > 0:
        for col1, col2, corr in high_corr_pairs[:20]:
            print(f"    {col1:30} <-> {col2:30} : {corr:.4f}")
    else:
        print("  无高度相关的特征对")

    # 5. 特征重要性（基于LightGBM）
    print(f"\n{'='*50}")
    print("  5. 特征重要性（基于LightGBM）")
    print(f"{'='*50}")

    try:
        import lightgbm as lgb

        X = valid_data[feature_cols].values
        y = valid_data["label_direction"].values

        model = lgb.LGBMClassifier(
            n_estimators=100, max_depth=5, learning_rate=0.1,
            random_state=42, verbose=-1
        )
        model.fit(X, y)

        importances = pd.Series(model.feature_importances_, index=feature_cols)
        importances = importances.sort_values(ascending=False)

        print(f"\n  重要性最高的前20个特征:")
        print(f"  {'特征':30} {'重要性':>10}")
        print(f"  {'-'*45}")
        for col, imp in importances.head(20).items():
            print(f"  {col:30} {imp:>10d}")

        print(f"\n  重要性为0的特征（共{len(importances[importances == 0])}个）:")
        zero_imp = importances[importances == 0].index.tolist()
        for col in zero_imp:
            print(f"    {col}")

        return {
            "symbol": name,
            "n_days": n,
            "total_features": len(feature_cols),
            "feature_types": {k: len(v) for k, v in feature_types.items()},
            "feature_correlations": correlations.to_dict(),
            "high_corr_pairs": [(c1, c2, float(c)) for c1, c2, c in high_corr_pairs],
            "low_corr_features": low_corr_features,
            "feature_importances": importances.to_dict(),
            "zero_importance_features": zero_imp,
        }

    except ImportError:
        print("  LightGBM未安装，跳过特征重要性分析")
        return {
            "symbol": name,
            "n_days": n,
            "total_features": len(feature_cols),
            "feature_types": {k: len(v) for k, v in feature_types.items()},
            "feature_correlations": correlations.to_dict(),
            "high_corr_pairs": [(c1, c2, float(c)) for c1, c2, c in high_corr_pairs],
            "low_corr_features": low_corr_features,
        }


def main():
    print("=" * 70)
    print("  特征工程深度分析")
    print("=" * 70)

    symbols = [("BTC-USDT", "BTC"), ("ETH-USDT", "ETH"), ("SOL-USDT", "SOL"), ("UNI-USDT", "UNI")]

    all_results = {}
    for inst_id, name in symbols:
        result = analyze_features(inst_id, name)
        if result:
            all_results[name] = result

    # 汇总分析
    print("\n\n" + "=" * 70)
    print("  汇总分析")
    print("=" * 70)

    # 统计各类型特征数量
    type_totals = {}
    for symbol, data in all_results.items():
        for ftype, count in data["feature_types"].items():
            type_totals[ftype] = type_totals.get(ftype, 0) + count

    print("\n各类型特征总数（4个标的）:")
    for ftype, count in type_totals.items():
        print(f"  {ftype:20} {count:4d}")

    # 统计低相关性特征（在多个标的中重复出现的）
    low_corr_all = set()
    for symbol, data in all_results.items():
        if "low_corr_features" in data:
            low_corr_all.update(data["low_corr_features"])

    print(f"\n多个标的中相关性<0.05的特征（共{len(low_corr_all)}个）:")
    for col in sorted(low_corr_all):
        print(f"  {col}")

    # 保存结果
    os.makedirs("ml/optimization_results", exist_ok=True)
    result_file = f"ml/optimization_results/feature_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {result_file}")


if __name__ == "__main__":
    main()
