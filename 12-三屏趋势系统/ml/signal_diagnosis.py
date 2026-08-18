"""诊断信号生成问题

检查不同train_window和阈值下，AI V2策略在真实数据上的信号分布。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from data.market_data import fetch_candles
from ml.lr_ml_strategy_v2 import LeastResistanceAIStrategyV2
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


def diagnose(inst_id="BTC-USDT", name="BTC"):
    print(f"\n{'='*70}")
    print(f"  诊断: {name}")
    print(f"{'='*70}")

    prices = fetch_real_data(inst_id)
    if prices.empty:
        print("  数据获取失败")
        return
    print(f"  数据: {len(prices)} 天")
    n = len(prices)

    # 测试不同参数组合
    configs = [
        # (描述, train_window, min_ml_confidence, base_rule_weight)
        ("原始(train=200,conf=0.1)", 200, 0.1, 0.3),
        ("小窗口(train=100)", 100, 0.1, 0.3),
        ("低置信(train=100,conf=0.02)", 100, 0.02, 0.3),
        ("极低置信(train=100,conf=0.01)", 100, 0.01, 0.3),
        ("最小窗口(train=80,conf=0.01)", 80, 0.01, 0.3),
    ]

    print(f"\n  {'配置':>35} {'多信号':>6} {'空信号':>6} {'空仓':>6} {'交易':>4} {'收益':>8} {'夏普':>7}")
    print("  " + "-" * 80)

    for desc, tw, min_conf, brw in configs:
        try:
            strategy = LeastResistanceAIStrategyV2(
                label_lookahead=7, train_window=tw, retrain_interval=20,
                min_ml_confidence=min_conf, enable_fundamental=True,
                enable_multitask=True, enable_dynamic_weight=True,
                enable_feature_selection=False, base_rule_weight=brw,
                fundamental_data=get_fundamental_data(),
            )
            if strategy.dynamic_fusion:
                strategy.dynamic_fusion.base_rule_weight = brw

            signals = strategy.generate_signals(prices)

            n_long = (signals > 0).sum()
            n_short = (signals < 0).sum()
            n_flat = (signals == 0).sum()

            engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
            result = engine.run(prices["close"], signals)
            m = result["metrics"]

            print(f"  {desc:>35} {n_long:>6} {n_short:>6} {n_flat:>6} {m['total_trades']:>4} "
                  f"{m['total_return_pct']:>7.2f}% {m['sharpe_ratio']:>7.3f}")
        except Exception as e:
            print(f"  {desc:>35} 失败: {e}")


def main():
    print("=" * 70)
    print("  信号生成诊断")
    print("=" * 70)

    for inst_id, name in [("BTC-USDT", "BTC"), ("ETH-USDT", "ETH"), ("SOL-USDT", "SOL"), ("UNI-USDT", "UNI")]:
        diagnose(inst_id, name)


if __name__ == "__main__":
    main()
