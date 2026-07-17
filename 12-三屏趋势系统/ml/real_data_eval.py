"""真实数据基线评估

使用OKX真实市场数据评估各策略版本的真实能力：
1. 纯规则引擎（最小阻力方向）
2. AI V1（单任务+静态权重）
3. AI V2 基线（多任务+动态权重，base_rule_weight=0.55）
4. AI V2 优化（多任务+动态权重，base_rule_weight=0.3）

对比合成数据回测结果，揭示策略在真实市场中的表现。

用法:
    python3 ml/real_data_eval.py
    python3 ml/real_data_eval.py --symbol BTC-USDT
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import argparse
import numpy as np
import pandas as pd
from datetime import datetime

from data.market_data import fetch_candles
from backtest.engine import BacktestEngine
from core.least_resistance import compute_least_resistance
from ml.lr_feature_engineer import LeastResistanceFeatureEngineer
from ml.lr_ml_strategy import LeastResistanceAIStrategy
from ml.lr_ml_strategy_v2 import LeastResistanceAIStrategyV2


def fetch_real_data(inst_id: str, bar: str = "1D", limit: int = 600) -> pd.DataFrame:
    """获取真实K线数据"""
    try:
        candles = fetch_candles(inst_id, bar=bar, limit=limit)
        if not candles:
            return pd.DataFrame()
        df = pd.DataFrame(candles)
        df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("timestamp")
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        print(f"  [ERROR] 获取 {inst_id} 数据失败: {e}")
        return pd.DataFrame()


class PureRuleStrategy:
    """纯规则引擎策略（最小阻力方向）"""

    def __init__(self, lookback: int = 60):
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

                if weekly_dir > 0.1 and daily_dir > 0:
                    positions[i] = weekly_conf * 0.6 + daily_conf * 0.4
                elif weekly_dir < -0.1 and daily_dir < 0:
                    positions[i] = -(weekly_conf * 0.6 + daily_conf * 0.4)
            except Exception:
                pass

        return pd.Series(positions, index=prices.index, name="position")


def get_fundamental_data():
    """模拟基本面数据（真实基本面数据需从6-TRADING和9-基本面分析模块获取）"""
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


def run_strategy_test(name, strategy, prices, engine):
    """运行单个策略测试"""
    print(f"  [{name}]...", end=" ", flush=True)
    try:
        signals = strategy.generate_signals(prices)
        result = engine.run(prices["close"], signals)
        m = result["metrics"]
        print(f"收益: {m['total_return_pct']:.2f}% 夏普: {m['sharpe_ratio']:.3f} "
              f"回撤: {m['max_drawdown_pct']:.2f}% 交易: {m['total_trades']}")
        return m
    except Exception as e:
        print(f"失败: {e}")
        return None


def evaluate_symbol(inst_id: str, symbol_name: str = None):
    """评估单个标的的所有策略"""
    if symbol_name is None:
        symbol_name = inst_id

    print("\n" + "=" * 70)
    print(f"  真实数据基线评估: {symbol_name}")
    print("=" * 70)

    # 获取数据
    print(f"\n1. 获取真实数据...", end=" ", flush=True)
    prices = fetch_real_data(inst_id, bar="1D", limit=600)
    if prices.empty:
        print("✗ 数据获取失败")
        return None
    print(f"✓ {len(prices)} 天")
    print(f"   时间范围: {prices.index[0].date()} ~ {prices.index[1].date()}")
    print(f"   价格范围: {prices['close'].min():.2f} ~ {prices['close'].max():.2f}")

    # 计算真实买入持有收益作为基准
    buy_hold_return = (prices['close'].iloc[-1] / prices['close'].iloc[0] - 1) * 100
    print(f"   买入持有收益: {buy_hold_return:.2f}%")

    fundamental_data = get_fundamental_data()

    print("\n2. 运行策略对比...")
    results = {}

    # 策略1: 纯规则引擎
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    results["纯规则引擎"] = run_strategy_test(
        "纯规则引擎", PureRuleStrategy(), prices, engine
    )

    # 策略2: AI V1（单任务+静态权重，技术面）
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    ai_v1 = LeastResistanceAIStrategy(
        label_lookahead=7, train_window=200, retrain_interval=30,
        ml_weight=0.4, enable_walk_forward=True,
        feature_engineer=LeastResistanceFeatureEngineer(enable_fundamental=False),
    )
    results["AI V1(技术面)"] = run_strategy_test("AI V1(技术面)", ai_v1, prices, engine)

    # 策略3: AI V2 基线（base_rule_weight=0.55，对应baseline_config.json）
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    ai_v2_baseline = LeastResistanceAIStrategyV2(
        label_lookahead=7, train_window=100, retrain_interval=20,
        min_ml_confidence=0.05, enable_fundamental=True, enable_multitask=True,
        enable_dynamic_weight=True, enable_feature_selection=False,
        base_rule_weight=0.55,  # 基线配置
        fundamental_data=fundamental_data,
    )
    if ai_v2_baseline.dynamic_fusion:
        ai_v2_baseline.dynamic_fusion.base_rule_weight = 0.55
        ai_v2_baseline.dynamic_fusion.trend_sensitivity = 0.25
        ai_v2_baseline.dynamic_fusion.vol_sensitivity = 0.25
        ai_v2_baseline.dynamic_fusion.volume_sensitivity = 0.2
        ai_v2_baseline.dynamic_fusion.duration_sensitivity = 0.25
    results["AI V2基线"] = run_strategy_test("AI V2基线", ai_v2_baseline, prices, engine)

    # 策略4: AI V2 优化（base_rule_weight=0.3，对应optimized_config.json）
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    ai_v2_opt = LeastResistanceAIStrategyV2(
        label_lookahead=7, train_window=100, retrain_interval=20,
        min_ml_confidence=0.05, enable_fundamental=True, enable_multitask=True,
        enable_dynamic_weight=True, enable_feature_selection=False,
        base_rule_weight=0.3,  # 优化配置
        fundamental_data=fundamental_data,
    )
    if ai_v2_opt.dynamic_fusion:
        ai_v2_opt.dynamic_fusion.base_rule_weight = 0.3
        ai_v2_opt.dynamic_fusion.trend_sensitivity = 0.25
        ai_v2_opt.dynamic_fusion.vol_sensitivity = 0.25
        ai_v2_opt.dynamic_fusion.volume_sensitivity = 0.2
        ai_v2_opt.dynamic_fusion.duration_sensitivity = 0.25
    results["AI V2优化"] = run_strategy_test("AI V2优化", ai_v2_opt, prices, engine)

    # 打印对比表
    print("\n" + "=" * 70)
    print(f"  {symbol_name} 策略对比报告")
    print("=" * 70)
    print(f"\n{'策略':>14} {'收益':>10} {'夏普':>8} {'回撤':>8} {'胜率':>8} {'交易':>6}")
    print("-" * 60)

    for name, m in results.items():
        if m:
            print(f"{name:>14} {m['total_return_pct']:>9.2f}% {m['sharpe_ratio']:>8.3f} "
                  f"{m['max_drawdown_pct']:>7.2f}% {m.get('win_rate', 0):>7.1f}% {m['total_trades']:>6d}")

    print(f"{'买入持有':>14} {buy_hold_return:>9.2f}% {'':>8} {'':>8} {'':>8} {'':>6}")

    return {"symbol": symbol_name, "inst_id": inst_id, "n_days": len(prices),
            "buy_hold_return": buy_hold_return, "results": results}


def main():
    parser = argparse.ArgumentParser(description="真实数据基线评估")
    parser.add_argument("--symbol", type=str, default=None, help="单个标的（如 BTC-USDT）")
    args = parser.parse_args()

    print("=" * 70)
    print("  真实数据基线评估")
    print("=" * 70)
    print("\n说明: 使用OKX真实市场数据评估各策略版本，对比合成数据回测结果")

    # 标的列表
    if args.symbol:
        symbols = [(args.symbol, args.symbol.replace("-USDT", ""))]
    else:
        symbols = [
            ("BTC-USDT", "BTC"),
            ("ETH-USDT", "ETH"),
            ("SOL-USDT", "SOL"),
            ("UNI-USDT", "UNI"),
        ]

    all_results = []
    for inst_id, name in symbols:
        r = evaluate_symbol(inst_id, name)
        if r:
            all_results.append(r)

    # 汇总报告
    if len(all_results) > 1:
        print("\n" + "=" * 70)
        print("  汇总报告（所有标的平均）")
        print("=" * 70)

        strategy_names = ["纯规则引擎", "AI V1(技术面)", "AI V2基线", "AI V2优化"]
        print(f"\n{'策略':>14} {'平均收益':>10} {'平均夏普':>10} {'平均回撤':>10}")
        print("-" * 50)

        for sname in strategy_names:
            rets = []
            sharpes = []
            drawdowns = []
            for r in all_results:
                m = r["results"].get(sname)
                if m:
                    rets.append(m["total_return_pct"])
                    sharpes.append(m["sharpe_ratio"])
                    drawdowns.append(m["max_drawdown_pct"])
            if rets:
                print(f"{sname:>14} {np.mean(rets):>9.2f}% {np.mean(sharpes):>10.3f} {np.mean(drawdowns):>9.2f}%")

        # 买入持有平均
        bh_rets = [r["buy_hold_return"] for r in all_results]
        print(f"{'买入持有':>14} {np.mean(bh_rets):>9.2f}%")

    # 保存结果
    os.makedirs("ml/optimization_results", exist_ok=True)
    result_file = f"ml/optimization_results/real_data_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    def clean_val(v):
        if isinstance(v, (np.floating, float)):
            return float(v)
        elif isinstance(v, (np.integer, int)):
            return int(v)
        elif isinstance(v, pd.Timestamp):
            return str(v)
        return v

    def clean_metrics(m):
        if m is None:
            return None
        return {k: clean_val(v) for k, v in m.items()}

    output = {
        "timestamp": datetime.now().isoformat(),
        "data_source": "OKX真实市场数据",
        "symbols": [],
    }
    for r in all_results:
        output["symbols"].append({
            "symbol": r["symbol"],
            "inst_id": r["inst_id"],
            "n_days": r["n_days"],
            "buy_hold_return": clean_val(r["buy_hold_return"]),
            "results": {k: clean_metrics(v) for k, v in r["results"].items()},
        })

    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {result_file}")


if __name__ == "__main__":
    main()
