"""AI 模型对比回测

对比三种策略：
1. 纯规则引擎（最小阻力方向）
2. AI 增强（纯技术面特征）
3. AI 增强（技术面 + 基本面特征）

用法:
    python3 ml/ai_backtest_comparison.py
    python3 ml/ai_backtest_comparison.py --symbol BTC --days 500
"""

import sys
import os
import json
import argparse
from datetime import timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest.engine import BacktestEngine
from backtest.strategy import BaseStrategy
from core.least_resistance import compute_least_resistance
from ml.lr_feature_engineer import LeastResistanceFeatureEngineer
from ml.lr_ml_strategy import LeastResistanceAIStrategy
from ml.lr_ml_strategy_v2 import LeastResistanceAIStrategyV2


class PureRuleStrategy(BaseStrategy):
    """纯规则引擎策略（最小阻力方向）"""

    def __init__(self, lookback: int = 60):
        super().__init__(name="pure_rule")
        self.lookback = lookback

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        n = len(prices)
        positions = np.zeros(n)

        weekly = prices.resample('W').agg({
            'open': 'first', 'high': 'max', 'low': 'min',
            'close': 'last', 'volume': 'sum',
        }).dropna()

        for i in range(self.lookback, n):
            daily_slice = prices.iloc[:i + 1]
            last_date = prices.index[i]
            weekly_slice = weekly[weekly.index <= last_date]

            if len(weekly_slice) < 20:
                continue

            try:
                daily_lr = compute_least_resistance(daily_slice)
                weekly_lr = compute_least_resistance(weekly_slice)

                weekly_dir = weekly_lr.get("direction", 0)
                daily_dir = daily_lr.get("direction", 0)
                weekly_conf = weekly_lr.get("confidence", 0)
                daily_conf = daily_lr.get("confidence", 0)

                # 周线为主，日线辅助
                if weekly_dir > 0.1 and daily_dir > 0:
                    positions[i] = weekly_conf * 0.6 + daily_conf * 0.4
                elif weekly_dir < -0.1 and daily_dir < 0:
                    positions[i] = -(weekly_conf * 0.6 + daily_conf * 0.4)
            except Exception:
                pass

        return pd.Series(positions, index=prices.index, name="position")


def _generate_price_data(n_days: int = 500, seed: int = 42) -> pd.DataFrame:
    """生成模拟价格数据（带趋势+噪声+周期）"""
    np.random.seed(seed)
    dates = pd.date_range('2023-01-01', periods=n_days, freq='D')

    t = np.arange(n_days)

    # 长期趋势（年化约 30% 涨幅 → 日均 ~0.07%）
    daily_trend = 0.0007

    # 周期性（模拟牛熊周期，约 180 天，振幅 ±1.5%）
    cycle = 0.015 * np.sin(2 * np.pi * t / 180)

    # 中周期波动（约 30 天，振幅 ±0.8%）
    mid_cycle = 0.008 * np.sin(2 * np.pi * t / 30)

    # 噪声（日均波动 ~2%）
    noise = np.random.randn(n_days) * 0.02

    # 合成对数收益率
    log_ret = daily_trend + cycle + mid_cycle + noise
    # 限制每日涨跌幅，避免极端值
    log_ret = np.clip(log_ret, -0.08, 0.08)

    # 价格
    close = 100 * np.exp(np.cumsum(log_ret))

    prices = pd.DataFrame({
        'open': close * (1 + np.random.randn(n_days) * 0.003),
        'high': close * (1 + np.abs(np.random.randn(n_days) * 0.01)),
        'low': close * (1 - np.abs(np.random.randn(n_days) * 0.01)),
        'close': close,
        'volume': np.random.rand(n_days) * 1000 + 100,
    }, index=dates)

    # 确保 high >= max(open, close), low <= min(open, close)
    prices['high'] = prices[['high', 'open', 'close']].max(axis=1)
    prices['low'] = prices[['low', 'open', 'close']].min(axis=1)

    return prices


def _generate_mock_fundamental_data(dates: pd.DatetimeIndex) -> dict:
    """生成模拟基本面历史数据"""
    n = len(dates)

    # 模拟 screen1 周更新（每周一更新）
    screen1_history = []
    for i, dt in enumerate(dates):
        if dt.weekday() == 0:  # 周一
            week_idx = i // 7
            cycle_phase = np.sin(2 * np.pi * i / 180)

            screen1_data = {
                'direction': 'BULL' if cycle_phase > 0 else 'BEAR',
                'confidence': 'MODERATE',
                'total_score': 50 + 40 * cycle_phase,
                'max_score': 100,
                'ach': {
                    'h1': {'probability': 0.5 + 0.2 * cycle_phase},
                    'h2': {'probability': 0.3},
                    'h3': {'probability': 0.2 - 0.2 * cycle_phase},
                },
                'dimensions': {
                    dim: {
                        'weight': w,
                        'anchor': 'BULL' if cycle_phase > 0.2 else ('BEAR' if cycle_phase < -0.2 else 'NEUTRAL'),
                        'score': 50 + 40 * cycle_phase + np.random.randn() * 5,
                        'max_score': 100,
                    }
                    for dim, w in [
                        ('technical', 40), ('cycle', 15), ('miner', 15),
                        ('onchain', 15), ('macro', 10), ('cross_market', 5)
                    ]
                }
            }
            screen1_history.append({'date': str(dt.date()), 'data': screen1_data})

    # 模拟 9-基本面 日更新
    fund9_history = []
    for i, dt in enumerate(dates):
        cycle_phase = np.sin(2 * np.pi * i / 180)
        noise = np.random.randn() * 0.1

        fund9_data = {
            'resistance_3d': {
                'direction_score': cycle_phase + noise,
                'velocity': 0.05 * np.cos(2 * np.pi * i / 180),
                'acceleration': -0.01 * np.sin(2 * np.pi * i / 180),
                'confidence': 0.5 + 0.3 * abs(cycle_phase),
            },
            'metrics': {
                'core': {
                    mod: 50 + 30 * (cycle_phase + np.random.randn() * 0.2)
                    for mod in [
                        'flow', 'valuation', 'onchain', 'macro',
                        'news', 'sentiment', 'breadth', 'intermarket',
                        'narrative', 'calendar'
                    ]
                }
            },
            'signals': []
        }
        fund9_history.append({'date': str(dt.date()), 'data': fund9_data})

    return {
        'screen1_history': screen1_history,
        'fundamental_9_history': fund9_history,
    }


def run_comparison(n_days: int = 500):
    """运行对比回测"""
    print("=" * 60)
    print("  AI 模型对比回测")
    print("=" * 60)

    # 生成数据
    print(f"\n1. 生成数据: {n_days} 天")
    prices = _generate_price_data(n_days)
    fundamental_data = _generate_mock_fundamental_data(prices.index)
    print(f"   价格范围: {prices['close'].min():.2f} ~ {prices['close'].max():.2f}")

    engine = BacktestEngine(
        initial_capital=10000,
        commission=0.001,
        slippage=0.001,
    )

    results = {}

    # 策略 1: 纯规则引擎
    print("\n2. 运行策略对比...")
    print("   [1/5] 纯规则引擎...", end=" ", flush=True)
    try:
        rule_strategy = PureRuleStrategy()
        rule_signals = rule_strategy.generate_signals(prices)
        rule_result = engine.run(prices['close'], rule_signals)
        results['纯规则引擎'] = rule_result
        ret = rule_result['metrics'].get('total_return_pct', 0)
        print(f"✓ 收益: {ret:.1f}%")
    except Exception as e:
        print(f"✗ {e}")
        import traceback
        traceback.print_exc()

    # 策略 2: AI 增强（纯技术面）
    print("   [2/5] AI增强(纯技术面)...", end=" ", flush=True)
    try:
        ai_tech_strategy = LeastResistanceAIStrategy(
            label_lookahead=7,
            train_window=200,
            retrain_interval=30,
            ml_weight=0.4,
            enable_walk_forward=True,
            feature_engineer=LeastResistanceFeatureEngineer(enable_fundamental=False),
        )
        ai_tech_signals = ai_tech_strategy.generate_signals(prices)
        ai_tech_result = engine.run(prices['close'], ai_tech_signals)
        results['AI增强(技术面)'] = ai_tech_result
        ret = ai_tech_result['metrics'].get('total_return_pct', 0)
        print(f"✓ 收益: {ret:.1f}%")
    except Exception as e:
        print(f"✗ {e}")
        import traceback
        traceback.print_exc()

    # 策略 3: AI 增强（技术面 + 基本面）
    print("   [3/5] AI增强(技术+基本面)...", end=" ", flush=True)
    try:
        ai_fund_strategy = LeastResistanceAIStrategy(
            label_lookahead=7,
            train_window=200,
            retrain_interval=30,
            ml_weight=0.4,
            enable_walk_forward=True,
            feature_engineer=LeastResistanceFeatureEngineer(enable_fundamental=True),
            fundamental_data=fundamental_data,
        )
        ai_fund_signals = ai_fund_strategy.generate_signals(prices)
        ai_fund_result = engine.run(prices['close'], ai_fund_signals)
        results['AI增强(技术+基本面)'] = ai_fund_result
        ret = ai_fund_result['metrics'].get('total_return_pct', 0)
        print(f"✓ 收益: {ret:.1f}%")
    except Exception as e:
        print(f"✗ {e}")
        import traceback
        traceback.print_exc()

    # 策略 4: AI v2 多任务 + 动态权重
    print("   [4/5] AI v2(多任务+动态权重)...", end=" ", flush=True)
    try:
        ai_v2_strategy = LeastResistanceAIStrategyV2(
            label_lookahead=7,
            train_window=200,
            retrain_interval=30,
            min_ml_confidence=0.1,
            enable_fundamental=True,
            enable_multitask=True,
            enable_dynamic_weight=True,
            enable_feature_selection=False,
            base_rule_weight=0.3,
            fundamental_data=fundamental_data,
        )
        ai_v2_signals = ai_v2_strategy.generate_signals(prices)
        ai_v2_result = engine.run(prices['close'], ai_v2_signals)
        results['AI v2(多任务+动态权重)'] = ai_v2_result
        ret = ai_v2_result['metrics'].get('total_return_pct', 0)
        print(f"✓ 收益: {ret:.1f}%")
    except Exception as e:
        print(f"✗ {e}")
        import traceback
        traceback.print_exc()

    # 策略 5: AI v2 + 特征筛选
    print("   [5/5] AI v2(全功能+特征筛选)...", end=" ", flush=True)
    try:
        ai_v2_full_strategy = LeastResistanceAIStrategyV2(
            label_lookahead=7,
            train_window=200,
            retrain_interval=30,
            min_ml_confidence=0.1,
            enable_fundamental=True,
            enable_multitask=True,
            enable_dynamic_weight=True,
            enable_feature_selection=True,
            top_k_features=40,
            base_rule_weight=0.3,
            fundamental_data=fundamental_data,
        )
        ai_v2_full_signals = ai_v2_full_strategy.generate_signals(prices)
        ai_v2_full_result = engine.run(prices['close'], ai_v2_full_signals)
        results['AI v2(全功能+特征筛选)'] = ai_v2_full_result
        ret = ai_v2_full_result['metrics'].get('total_return_pct', 0)
        print(f"✓ 收益: {ret:.1f}%")
    except Exception as e:
        print(f"✗ {e}")
        import traceback
        traceback.print_exc()

    # 对比结果
    print("\n" + "=" * 60)
    print("  对比结果")
    print("=" * 60)

    metrics_order = [
        ('total_return_pct', '总收益率', '%'),
        ('annualized_return', '年化收益', '%'),
        ('sharpe_ratio', '夏普比率', ''),
        ('max_drawdown_pct', '最大回撤', '%'),
        ('win_rate_pct', '胜率', '%'),
        ('total_trades', '交易次数', ''),
    ]

    strategy_names = list(results.keys())
    header = f"{'指标':<12}"
    for name in strategy_names:
        header += f"{name:>20}"
    print(header)
    print("-" * (12 + 20 * len(strategy_names)))

    for m_key, m_name, m_suffix in metrics_order:
        row = f"{m_name:<12}"
        for name in strategy_names:
            val = results[name]['metrics'].get(m_key, 0)
            if m_suffix == '%':
                row += f"{val:>18.2f}%"
            elif m_key == 'total_trades':
                row += f"{val:>20d}"
            else:
                row += f"{val:>20.3f}"
        print(row)

    print("\n" + "=" * 60)
    return results


def run_param_sweep(n_days: int = 600, seed: int = 42):
    """参数扫描：在相同数据上测试不同 AI V2 参数"""
    print("\n" + "=" * 60)
    print("  AI V2 参数扫描")
    print("=" * 60)

    prices = _generate_price_data(n_days, seed)
    fundamental_data = _generate_mock_fundamental_data(prices.index)

    test_cases = [
        ("基线", {}),
        ("高规则权重", {"fusion_base_rule_weight": 0.7}),
        ("低规则权重", {"fusion_base_rule_weight": 0.3}),
        ("高趋势敏感", {"fusion_trend_sensitivity": 0.4}),
        ("低趋势敏感", {"fusion_trend_sensitivity": 0.05}),
        ("高波动敏感", {"fusion_vol_sensitivity": 0.4}),
        ("低波动敏感", {"fusion_vol_sensitivity": 0.05}),
        ("高量敏感", {"fusion_volume_sensitivity": 0.4}),
        ("低量敏感", {"fusion_volume_sensitivity": 0.05}),
        ("高时长敏感", {"fusion_duration_sensitivity": 0.4}),
        ("低时长敏感", {"fusion_duration_sensitivity": 0.05}),
        ("高置信阈值", {"min_ml_confidence": 0.2}),
        ("低置信阈值", {"min_ml_confidence": 0.05}),
        ("大窗口", {"train_window": 300}),
        ("小窗口", {"train_window": 100}),
    ]

    results = []
    for desc, overrides in test_cases:
        strategy = LeastResistanceAIStrategyV2(
            label_lookahead=overrides.get("label_lookahead", 7),
            train_window=overrides.get("train_window", 200),
            retrain_interval=30,
            min_ml_confidence=overrides.get("min_ml_confidence", 0.1),
            enable_fundamental=True,
            enable_multitask=True,
            enable_dynamic_weight=True,
            enable_feature_selection=False,
            base_rule_weight=overrides.get("base_rule_weight", 0.3),
            fundamental_data=fundamental_data,
        )
        if strategy.dynamic_fusion:
            strategy.dynamic_fusion.base_rule_weight = overrides.get("fusion_base_rule_weight", 0.55)
            strategy.dynamic_fusion.trend_sensitivity = overrides.get("fusion_trend_sensitivity", 0.25)
            strategy.dynamic_fusion.vol_sensitivity = overrides.get("fusion_vol_sensitivity", 0.25)
            strategy.dynamic_fusion.volume_sensitivity = overrides.get("fusion_volume_sensitivity", 0.2)
            strategy.dynamic_fusion.duration_sensitivity = overrides.get("fusion_duration_sensitivity", 0.25)

        signals = strategy.generate_signals(prices)
        result = BacktestEngine(initial_capital=10000).run(prices["close"], signals)
        m = result["metrics"]
        results.append((desc, m))
        print(f"  {desc:12s} 收益: {m['total_return_pct']:7.2f}%  夏普: {m['sharpe_ratio']:6.3f}  交易: {m['total_trades']:3d}")

    print(f"\n{'=' * 60}")
    print("  排名 (按收益)")
    print(f"{'=' * 60}")
    results.sort(key=lambda x: -x[1]["total_return_pct"])
    for i, (desc, m) in enumerate(results[:10], 1):
        print(f"{i}. {desc:12s} 收益: {m['total_return_pct']:7.2f}%  夏普: {m['sharpe_ratio']:6.3f}  交易: {m['total_trades']:3d}")


def main():
    parser = argparse.ArgumentParser(description="AI模型对比回测")
    parser.add_argument("--days", type=int, default=500, help="回测天数")
    parser.add_argument("--sweep", action="store_true", help="参数扫描模式")
    args = parser.parse_args()

    if args.sweep:
        run_param_sweep(n_days=args.days)
    else:
        run_comparison(n_days=args.days)


if __name__ == "__main__":
    main()
