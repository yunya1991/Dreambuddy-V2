#!/usr/bin/env python3
"""
五角校验完整回测脚本 — 用WalkForwardBacktester集成五角校验做完整回测。

对比模式：
  - baseline: 不启用五角校验（enable_pentagon=False）
  - pentagon: 启用五角校验（enable_pentagon=True）
"""
import sys
import os
import time
import logging
import pandas as pd

# 设置路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)

# 修复inspect模块
import importlib
_std_inspect = importlib.import_module('inspect')
sys.modules['inspect'] = _std_inspect

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)


def load_klines(symbol, timeframe="1H"):
    data_dir = os.path.join(PROJECT_ROOT, "scripts", "data", "klines")
    filepath = os.path.join(data_dir, f"{symbol}_{timeframe}.csv")
    if os.path.exists(filepath):
        df = pd.read_csv(filepath)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df.set_index("timestamp", inplace=True)
        return df
    return None


def run_backtest(symbol, df, enable_pentagon=True, n_folds=3):
    """运行单币种回测"""
    from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester, generate_report

    bt = WalkForwardBacktester(
        symbol=symbol,
        n_folds=n_folds,
        train_ratio=0.7,
        min_train_bars=500,
        min_test_bars=100,
        conf_threshold=0.40,
        tp_atr=3.0,
        sl_atr=2.0,
        max_hold_bars=60,
    )
    bt.enable_pentagon = enable_pentagon
    if not enable_pentagon:
        bt._triangle_verifier = None

    t0 = time.time()
    result = bt.run(df, verbose=False)
    elapsed = time.time() - t0

    report = generate_report(result)
    return result, report, elapsed


def main():
    symbols = ["BTC", "ETH"]

    print("=" * 80)
    print("  WalkForwardBacktester 五角校验完整回测")
    print("=" * 80)

    for symbol in symbols:
        df = load_klines(symbol, "1H")
        if df is None or len(df) < 800:
            print(f"\n  {symbol} 数据不足，跳过")
            continue

        print(f"\n{'='*80}")
        print(f"  {symbol} — 数据量: {len(df)} 根K线")
        print(f"{'='*80}")

        # Baseline（不启用五角校验）
        print(f"\n  [1/2] {symbol} Baseline（无五角校验）...")
        _, report_base, t_base = run_backtest(symbol, df, enable_pentagon=False)
        print(report_base)
        print(f"  耗时: {t_base:.1f}秒")

        # Pentagon（启用五角校验）
        print(f"\n  [2/2] {symbol} Pentagon（启用五角校验）...")
        _, report_pent, t_pent = run_backtest(symbol, df, enable_pentagon=True)
        print(report_pent)
        print(f"  耗时: {t_pent:.1f}秒")


if __name__ == "__main__":
    main()
