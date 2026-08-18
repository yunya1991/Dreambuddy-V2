"""技术指标基线回测（使用2年历史数据）

测试核心策略：
1. 双均线策略（基准）
2. 最小阻力策略（LeastResistanceStrategy）
3. AI V2策略

数据量：730天（约2年）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd

from data.market_data import fetch_historical_candles
from backtest.engine import BacktestEngine
from backtest.strategy import MovingAverageStrategy, LeastResistanceStrategy
from ml.lr_ml_strategy_v2 import LeastResistanceAIStrategyV2


def fetch_real_data(inst_id, days=730):
    candles = fetch_historical_candles(inst_id, bar="1D", days=days)
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def get_fundamental_data():
    return {
        "screen1": {"composite_score": 65.0, "momentum_score": 70.0,
                    "value_score": 60.0, "growth_score": 65.0,
                    "quality_score": 68.0, "sentiment_score": 55.0},
        "fundamental_9": {"pe_ttm": 15.0, "pb": 2.0, "roe": 12.0,
                          "revenue_growth": 20.0, "profit_growth": 18.0,
                          "debt_ratio": 45.0, "cash_ratio": 30.0,
                          "gross_margin": 35.0, "net_margin": 15.0}
    }


def run_backtest(prices, strategy, name):
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    try:
        signals = strategy.generate_signals(prices)
        result = engine.run(prices["close"], signals)
        m = result["metrics"]
        return {
            "name": name,
            "return": m["total_return_pct"],
            "sharpe": m["sharpe_ratio"],
            "drawdown": m["max_drawdown_pct"],
            "trades": m["total_trades"],
        }
    except Exception as e:
        print(f"  [ERROR] {name}: {e}")
        return None


def main():
    print("=" * 60)
    print("  技术指标基线回测（2年历史数据）")
    print("=" * 60)

    symbols = [("BTC-USDT", "BTC"), ("ETH-USDT", "ETH"), ("SOL-USDT", "SOL"), ("UNI-USDT", "UNI")]

    print(f"\n{'标的':>6} {'策略':>18} {'收益':>10} {'夏普':>8} {'回撤':>8} {'交易':>6}")
    print("-" * 65)

    for inst_id, name in symbols:
        prices = fetch_real_data(inst_id, days=730)
        if prices.empty:
            print(f"{name:>6} 数据获取失败")
            continue

        n = len(prices)
        bh = (prices["close"].iloc[-1] / prices["close"].iloc[0] - 1) * 100

        strategies = [
            ("双均线(20/200)", MovingAverageStrategy(20, 200)),
            ("最小阻力策略", LeastResistanceStrategy(warmup_periods=min(80, n-10), update_step=1)),
            ("AI V2策略", LeastResistanceAIStrategyV2(
                label_lookahead=7, train_window=min(200, n//3), retrain_interval=30,
                min_ml_confidence=0.05, enable_fundamental=True, enable_multitask=True,
                enable_dynamic_weight=True, enable_feature_selection=False,
                base_rule_weight=0.3, fundamental_data=get_fundamental_data()
            )),
        ]

        for sname, strategy in strategies:
            r = run_backtest(prices, strategy, sname)
            if r:
                print(f"{name:>6} {r['name']:>18} {r['return']:>9.2f}% {r['sharpe']:>8.3f} "
                      f"{r['drawdown']:>7.2f}% {r['trades']:>6d}")

        print(f"{name:>6} {'买入持有':>18} {bh:>9.2f}%")


if __name__ == "__main__":
    main()
