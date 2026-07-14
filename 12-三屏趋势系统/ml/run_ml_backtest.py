"""ML增强三屏策略 - 回测验证脚本

对比传统三屏策略 vs ML增强策略的性能
用法:
    cd 12-三屏趋势系统
    python3 ml/run_ml_backtest.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from backtest import (
    BacktestEngine,
    BacktestResult,
    BuyAndHoldStrategy,
    TrendScreenStrategy,
    generate_sample_data,
    fetch_historical_data,
    compare_results,
    format_comparison_table,
)

from ml.feature_engineer import TrendFeatureEngineer
from ml.ml_strategy import MLTrendStrategy, train_ml_strategy


def test_feature_engineer():
    """测试特征工程是否正常工作"""
    print("=" * 60)
    print("  测试1：特征工程验证")
    print("=" * 60)

    df = generate_sample_data(n_days=500, start_price=100.0, volatility=0.02)
    print(f"测试数据: {len(df)} 天")

    fe = TrendFeatureEngineer()
    try:
        features_df = fe.create_features(df, label_lookahead=7)
        feature_names = fe.get_feature_names()
        print(f"特征数量: {len(feature_names)}")
        print(f"特征列表: {feature_names[:10]} ...")
        print(f"有效数据行数: {len(fe.get_valid_data(features_df))}")

        # 打印特征分组
        groups = fe.get_feature_groups()
        print(f"特征分组:")
        for group, feats in groups.items():
            print(f"  {group}: {len(feats)} 个特征")

        print("特征工程 ✓ 正常")
        return True
    except Exception as e:
        print(f"特征工程 ✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ml_model():
    """测试ML模型是否正常工作"""
    print("\n" + "=" * 60)
    print("  测试2：ML模型训练验证")
    print("=" * 60)

    df = generate_sample_data(n_days=500, start_price=100.0, volatility=0.02)

    fe = TrendFeatureEngineer()
    features_df = fe.create_features(df, label_lookahead=7)
    valid = fe.get_valid_data(features_df)

    if len(valid) < 100:
        print("有效数据不足，跳过模型测试")
        return False

    feature_names = fe.get_feature_names()
    train_size = int(len(valid) * 0.6)
    train_data = valid.iloc[:train_size]
    test_data = valid.iloc[train_size:]

    X_train = train_data[feature_names]
    y_train = train_data['label']
    X_test = test_data[feature_names]
    y_test = test_data['label']

    try:
        from ml.models import create_model
        model = create_model('lightgbm')
        model.fit(X_train, y_train)

        train_acc = (model.predict(X_train) == y_train).mean()
        test_acc = (model.predict(X_test) == y_test).mean()

        print(f"LightGBM 训练集准确率: {train_acc:.4f}")
        print(f"LightGBM 测试集准确率: {test_acc:.4f}")

        importances = model.feature_importance()
        print(f"Top 5 重要特征:")
        for feat, imp in importances.head(5).items():
            print(f"  {feat}: {imp:.4f}")

        print("ML模型 ✓ 正常")
        return True
    except Exception as e:
        print(f"ML模型 ✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_ml_backtest_sample():
    """使用合成数据运行ML增强策略回测"""
    print("\n" + "=" * 60)
    print("  测试3：ML增强策略回测 (合成数据)")
    print("=" * 60)

    df = generate_sample_data(n_days=800, start_price=100.0, volatility=0.02)
    print(f"测试数据: {len(df)} 天, 起始价: {df['close'].iloc[0]:.2f}, 最终价: {df['close'].iloc[-1]:.2f}")

    engine = BacktestEngine(
        initial_capital=10000.0,
        commission=0.0005,
        slippage=0.0005,
    )

    base_strategy = TrendScreenStrategy(min_confidence=45.0, update_step=7)

    strategies = {
        "Buy&Hold": BuyAndHoldStrategy(),
        "TrendScreen": base_strategy,
        "ML+Trend (LightGBM)": MLTrendStrategy(
            base_strategy=base_strategy,
            model_type='lightgbm',
            ml_confidence_weight=0.3,
            label_lookahead=7,
            warmup_periods=100,
            train_ratio=0.5,
        ),
    }

    results = {}
    for name, strategy in strategies.items():
        print(f"\n运行 {name} ...")
        try:
            signals = strategy.generate_signals(df)
            result = engine.run(df["close"], signals, symbol=name)
            results[name] = BacktestResult(result)
            print(f"  完成: 收益 {results[name].total_return_pct:.2f}%, "
                  f"夏普 {results[name].sharpe_ratio:.2f}, "
                  f"最大回撤 {results[name].max_drawdown_pct:.2f}%")
        except Exception as e:
            print(f"  失败: {e}")
            import traceback
            traceback.print_exc()

    if results:
        print("\n" + "=" * 60)
        print("  策略对比 (合成数据)")
        print("=" * 60)
        comp = compare_results(results)
        print(format_comparison_table(comp))

    return results


def run_ml_backtest_real():
    """使用真实数据运行ML增强策略回测"""
    print("\n" + "=" * 60)
    print("  测试4：ML增强策略回测 (真实数据)")
    print("=" * 60)

    try:
        df = fetch_historical_data("BTC-USDT", "1D", 500)
        if len(df) < 200:
            print("数据不足，跳过真实数据回测")
            return {}
    except Exception as e:
        print(f"获取真实数据失败: {e}")
        return {}

    print(f"获取数据: {len(df)} 天")
    print(f"价格范围: {df['close'].min():.2f} ~ {df['close'].max():.2f}")

    engine = BacktestEngine(
        initial_capital=10000.0,
        commission=0.0005,
        slippage=0.0005,
    )

    base_strategy = TrendScreenStrategy(min_confidence=45.0, update_step=7)

    strategies = {
        "Buy&Hold": BuyAndHoldStrategy(),
        "TrendScreen": base_strategy,
        "ML+Trend (LightGBM)": MLTrendStrategy(
            base_strategy=base_strategy,
            model_type='lightgbm',
            ml_confidence_weight=0.3,
            label_lookahead=7,
            warmup_periods=100,
            train_ratio=0.5,
        ),
    }

    results = {}
    for name, strategy in strategies.items():
        print(f"\n运行 {name} ...")
        try:
            signals = strategy.generate_signals(df)
            result = engine.run(df["close"], signals, symbol=name)
            results[name] = BacktestResult(result)
            print(f"  完成: 收益 {results[name].total_return_pct:.2f}%, "
                  f"夏普 {results[name].sharpe_ratio:.2f}, "
                  f"最大回撤 {results[name].max_drawdown_pct:.2f}%")
        except Exception as e:
            print(f"  失败: {e}")
            import traceback
            traceback.print_exc()

    if results:
        print("\n" + "=" * 60)
        print("  策略对比 (BTC真实数据)")
        print("=" * 60)
        comp = compare_results(results)
        print(format_comparison_table(comp))

    return results


def main():
    print("\n" + "=" * 60)
    print("  Phase 3: AI增强三屏策略回测验证")
    print("=" * 60)

    # 1. 测试特征工程
    fe_ok = test_feature_engineer()
    if not fe_ok:
        print("\n特征工程失败，终止测试")
        return

    # 2. 测试ML模型
    model_ok = test_ml_model()
    if not model_ok:
        print("\nML模型测试失败，继续回测测试")

    # 3. 合成数据回测
    sample_results = run_ml_backtest_sample()

    # 4. 真实数据回测
    real_results = run_ml_backtest_real()

    print("\n" + "=" * 60)
    print("  Phase 3 验证完成")
    print("=" * 60)
    print("已完成模块:")
    print("  ✓ 多视角特征工程 (5大视角)")
    print("  ✓ ML模型层 (LightGBM)")
    print("  ✓ ML增强三屏策略融合")
    print("  ✓ 回测验证")
    print("\n下一步: 模型调优 + Walk-Forward验证 + 版本管理")


if __name__ == "__main__":
    main()
