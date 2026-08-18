#!/usr/bin/env python3
"""
运行 BCRM 2.0 回测，对比 BCRM 1.0 的胜率。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import pandas as pd
import numpy as np

from bcrm2.data_fetcher import get_klines
from bcrm2.walk_forward_backtester import WalkForwardBacktester, generate_report


def main():
    symbols = ['BTC', 'ETH', 'SOL', 'UNI']
    timeframe = '1H'
    max_bars = 3000
    n_folds = 5
    conf_threshold = 0.70  # P0修正：与实盘 config.json 对齐（原 0.60）
    tp_atr = 3.0
    sl_atr = 1.5  # 与实盘一致
    max_hold_bars = 60
    
    print("=" * 80)
    print("  BCRM 2.0 (辩证ML) vs BCRM 1.0 (矛盾力学) 回测对比")
    print("=" * 80)
    print()
    print(f"  交易对: {', '.join(symbols)}")
    print(f"  周期: {timeframe}")
    print(f"  K线数: {max_bars}")
    print(f"  Folds: {n_folds}")
    print(f"  置信度阈值: {conf_threshold}")
    print(f"  止盈/止损: {tp_atr}x / {sl_atr}x ATR")
    print(f"  最大持仓: {max_hold_bars} bars")
    print()
    
    all_results = {}
    
    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"  {symbol}")
        print(f"{'='*60}")
        
        try:
            df = get_klines(symbol, timeframe, max_bars=max_bars)
            print(f"  加载 {len(df)} 根K线: {df.index[0]} ~ {df.index[-1]}")
            
            backtester = WalkForwardBacktester(
                symbol=symbol,
                n_folds=n_folds,
                conf_threshold=conf_threshold,
                tp_atr=tp_atr,
                sl_atr=sl_atr,
                max_hold_bars=max_hold_bars,
                feature_selection=True,
            )
            
            result = backtester.run(df, symbol=symbol)
            
            report = generate_report([result], [symbol])
            print(report)
            
            all_results[symbol] = result
            
        except Exception as e:
            print(f"  错误: {e}")
            import traceback
            traceback.print_exc()
    
    # 综合统计
    if all_results:
        print(f"\n{'='*80}")
        print(f"  综合统计")
        print(f"{'='*80}")
        
        total_trades = 0
        total_wins = 0
        total_return = 0
        total_max_dd = 0
        
        for symbol, result in all_results.items():
            n_trades = sum(f.n_trades for f in result.folds)
            win_rate = sum(f.win_rate for f in result.folds) / len(result.folds)
            total_ret = sum(f.total_return for f in result.folds) / len(result.folds)
            max_dd = sum(f.max_drawdown for f in result.folds) / len(result.folds)
            
            total_trades += n_trades
            total_wins += n_trades * win_rate
            total_return += total_ret
            total_max_dd += max_dd
        
        n_symbols = len(all_results)
        avg_trades = total_trades / n_symbols
        avg_win_rate = total_wins / total_trades if total_trades > 0 else 0
        avg_return = total_return / n_symbols
        avg_max_dd = total_max_dd / n_symbols
        
        print(f"\n  平均交易数: {avg_trades:.1f}")
        print(f"  平均胜率: {avg_win_rate:.2%}")
        print(f"  平均总收益: {avg_return:+.2%}")
        print(f"  平均最大回撤: {avg_max_dd:.2%}")


if __name__ == '__main__':
    main()
