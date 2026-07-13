#!/usr/bin/env python3
"""
BCRM 2.0 Phase 0 — 基线验证主入口

功能:
  1. 获取BTC/ETH历史K线
  2. 计算八卦特征 + 三重障碍标签
  3. Walk-Forward回测
  4. 输出回测报告 + 卦象统计

用法:
  python -m scripts.memory_l4.bcrm2.run_phase0_validation
  python -m scripts.memory_l4.bcrm2.run_phase0_validation --symbols BTC,ETH,SOL
  python -m scripts.memory_l4.bcrm2.run_phase0_validation --timeframe 1H --n-folds 5
"""

import argparse
import sys
import os
from pathlib import Path

# 确保包路径正确
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pandas as pd
import numpy as np

from .data_fetcher import get_klines
from .walk_forward_backtester import WalkForwardBacktester, generate_report


def main():
    parser = argparse.ArgumentParser(description="BCRM 2.0 Phase 0 基线验证")
    parser.add_argument("--symbols", type=str, default="BTC,ETH",
                        help="交易对，逗号分隔，默认 BTC,ETH")
    parser.add_argument("--timeframe", type=str, default="1H",
                        help="K线周期，默认1H")
    parser.add_argument("--n-folds", type=int, default=5,
                        help="Walk-Forward折数，默认5")
    parser.add_argument("--conf-threshold", type=float, default=0.40,
                        help="开仓置信度阈值，默认0.40")
    parser.add_argument("--tp-atr", type=float, default=3.0,
                        help="止盈ATR倍数，默认3.0")
    parser.add_argument("--sl-atr", type=float, default=2.0,
                        help="止损ATR倍数，默认2.0")
    parser.add_argument("--max-hold-bars", type=int, default=60,
                        help="最大持仓bar数，默认60")
    parser.add_argument("--max-bars", type=int, default=3000,
                        help="使用的最大K线数，默认3000")
    parser.add_argument("--refresh", action="store_true",
                        help="强制刷新K线数据")
    parser.add_argument("--output", type=str, default=None,
                        help="报告输出目录")
    parser.add_argument("--no-pivot", action="store_true",
                        help="禁用枢纽点特征")
    parser.add_argument("--no-rsi", action="store_true",
                        help="禁用RSI情绪特征")
    parser.add_argument("--no-wdh", action="store_true",
                        help="禁用周/日/时三屏+量变积累特征")
    parser.add_argument("--wdh-weekly-only", action="store_true",
                        help="WDH仅保留周线量变积累层 (消融实验)")
    parser.add_argument("--feature-selection", action="store_true", default=True,
                        help="启用特征选择 (LightGBM重要性+相关性去冗余), 默认启用")
    parser.add_argument("--no-feature-selection", action="store_true",
                        help="禁用特征选择")
    parser.add_argument("--fs-imp-threshold", type=float, default=0.05,
                        help="特征重要性阈值 (占最高重要性的比例), 默认0.05")
    parser.add_argument("--fs-corr-threshold", type=float, default=0.85,
                        help="特征相关性阈值, 高于此值的冗余特征将被剔除, 默认0.85")
    parser.add_argument("--portfolio", action="store_true",
                        help="启用多币种组合回测 (资金分配+组合层指标)")

    args = parser.parse_args()
    args.enable_pivot = not args.no_pivot
    args.enable_rsi = not args.no_rsi
    args.enable_wdh = not args.no_wdh
    args.wdh_weekly_only = args.wdh_weekly_only
    if args.no_feature_selection:
        args.feature_selection = False
    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    print("=" * 70)
    print("  BCRM 2.0 Phase 0 — 基线验证")
    print("=" * 70)
    print()
    print(f"  交易对: {', '.join(symbols)}")
    print(f"  周期: {args.timeframe}")
    print(f"  Folds: {args.n_folds}")
    print(f"  置信度阈值: {args.conf_threshold}")
    print(f"  止盈/止损: {args.tp_atr}x / {args.sl_atr}x ATR")
    print(f"  最大持仓: {args.max_hold_bars} bars")
    print(f"  枢纽点特征: {'ON' if args.enable_pivot else 'OFF'}")
    print(f"  RSI情绪特征: {'ON' if args.enable_rsi else 'OFF'}")
    print(f"  周/日/时+量变积累: {'ON' if args.enable_wdh else 'OFF'}")
    print(f"  特征选择: {'ON' if args.feature_selection else 'OFF'}")
    if args.feature_selection:
        print(f"    重要性阈值: {args.fs_imp_threshold}, 相关性阈值: {args.fs_corr_threshold}")
    print()

    # 输出目录
    if args.output is None:
        output_dir = Path(__file__).parent.parent.parent.parent / "data" / "bcrm2_phase0"
    else:
        output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_results = {}

    for symbol in symbols:
        print("-" * 70)
        print(f"  正在处理: {symbol}")
        print("-" * 70)

        # 1. 获取数据
        print(f"\n[1/4] 获取K线数据...")
        df = get_klines(
            symbol=symbol,
            timeframe=args.timeframe,
            refresh=args.refresh,
            max_bars=args.max_bars,
        )

        if len(df) < 500:
            print(f"  ⚠️  数据不足 ({len(df)}根)，跳过 {symbol}")
            continue

        print(f"  K线数量: {len(df)}")
        print(f"  时间范围: {df.index[0]} ~ {df.index[-1]}")

        # 跨资产参考: 非BTC币种使用BTC作为参考资产
        ref_df = None
        if symbol != "BTC":
            print(f"  加载BTC参考数据 (跨资产特征)...")
            ref_df = get_klines("BTC", timeframe=args.timeframe, use_cache=True, max_bars=args.max_bars)
            if len(ref_df) < 200:
                print(f"  ⚠️  BTC参考数据不足，跳过跨资产特征")
                ref_df = None

        # 2. Walk-Forward回测
        print(f"\n[2/4] Walk-Forward回测...")
        backtester = WalkForwardBacktester(
            symbol=symbol,
            n_folds=args.n_folds,
            conf_threshold=args.conf_threshold,
            tp_atr=args.tp_atr,
            sl_atr=args.sl_atr,
            max_hold_bars=args.max_hold_bars,
            use_regime_switching=True,  # 启用市态切换（最优配置关键）
            feature_selection=args.feature_selection,
            fs_imp_threshold=args.fs_imp_threshold,
            fs_corr_threshold=args.fs_corr_threshold,
        )

        try:
            result = backtester.run(
                df, ref_df=ref_df, verbose=True,
                enable_pivot=args.enable_pivot,
                enable_rsi=args.enable_rsi,
                enable_wdh=args.enable_wdh,
                wdh_weekly_only=args.wdh_weekly_only,
                auto_mcap_config=True,
            )
        except Exception as e:
            print(f"  ❌ 回测失败: {e}")
            import traceback
            traceback.print_exc()
            continue

        all_results[symbol] = result

        # 3. 生成报告
        print(f"\n[3/4] 生成报告...")
        report_path = output_dir / f"report_{symbol}_{args.timeframe}.txt"
        report = generate_report(result, str(report_path))
        print(report)

        # 4. 保存交易明细
        print(f"\n[4/4] 保存交易明细...")
        trades_df = pd.DataFrame([
            {
                "entry_time": df.index[t.entry_bar] if t.entry_bar < len(df) else "N/A",
                "exit_time": df.index[t.exit_bar] if t.exit_bar < len(df) else "N/A",
                "direction": "LONG" if t.direction == 1 else "SHORT",
                "entry_price": round(t.entry_price, 4),
                "exit_price": round(t.exit_price, 4),
                "pnl_pct": round(t.pnl_pct, 3),
                "hold_bars": t.hold_bars,
                "exit_reason": t.exit_reason,
                "confidence": t.confidence,
                "hexagram": t.hexagram_name,
            }
            for t in result.all_trades
        ])
        trades_path = output_dir / f"trades_{symbol}_{args.timeframe}.csv"
        trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")
        print(f"  交易明细已保存: {trades_path}")

    # 汇总报告
    if all_results:
        print("\n" + "=" * 70)
        print("  汇总结果")
        print("=" * 70)
        print()
        print(f"  {'交易对':<10} {'交易数':<8} {'胜率':<8} {'总收益':<10} "
              f"{'最大回撤':<10} {'盈亏比':<8} {'夏普':<8}")
        print(f"  {'-'*10} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")

        for symbol, result in all_results.items():
            print(f"  {symbol:<10} {result.total_trades:<8} "
                  f"{result.overall_win_rate*100:<7.1f}% "
                  f"{result.total_return:<9.2f}% "
                  f"{result.max_drawdown:<9.2f}% "
                  f"{result.profit_factor:<7.2f} "
                  f"{result.sharpe_ratio:<7.2f}")

        print()
        print(f"  报告目录: {output_dir}")
        print()

        # 相位验证结果
        print("=" * 70)
        print("  Phase 0 验证结论")
        print("=" * 70)

        # 简单判定: 胜率>50% 且 夏普>1.0 则通过
        passed = 0
        for symbol, result in all_results.items():
            if result.overall_win_rate > 0.5 and result.sharpe_ratio > 1.0:
                print(f"  ✅ {symbol}: 通过 (胜率{result.overall_win_rate*100:.1f}%, "
                      f"夏普{result.sharpe_ratio:.2f})")
                passed += 1
            else:
                print(f"  ⚠️  {symbol}: 待优化 (胜率{result.overall_win_rate*100:.1f}%, "
                      f"夏普{result.sharpe_ratio:.2f})")

        print()
        if passed >= 1:
            print("  🎯 Phase 0 验证: 部分通过 → 可推进Phase 1核心落地")
        else:
            print("  🔧 Phase 0 验证: 需优化 → 调整特征/参数后重试")
        print()

    # 多币种组合回测
    if args.portfolio and all_results:
        print("=" * 70)
        print("  多币种组合回测")
        print("=" * 70)

        from .portfolio_backtester import PortfolioBacktester

        # 收集所有币种的数据
        data_dict = {}
        btc_ref = None
        for symbol in symbols:
            df = get_klines(symbol, args.timeframe, max_bars=args.max_bars)
            df = df.iloc[-args.max_bars:] if len(df) > args.max_bars else df
            data_dict[symbol] = df
            if symbol == "BTC":
                btc_ref = df

        # 运行组合回测
        portfolio = PortfolioBacktester(
            symbols=symbols,
            n_folds=args.n_folds,
            conf_threshold=args.conf_threshold,
            tp_atr=args.tp_atr,
            sl_atr=args.sl_atr,
            max_hold_bars=args.max_hold_bars,
            feature_selection=not args.no_feature_selection,
            fs_imp_threshold=args.fs_imp_threshold,
            fs_corr_threshold=args.fs_corr_threshold,
            use_regime_switching=True,
        )

        portfolio_result = portfolio.run(
            data_dict,
            ref_df=btc_ref,
            enable_pivot=args.enable_pivot,
            enable_rsi=args.enable_rsi,
            enable_wdh=args.enable_wdh,
            wdh_weekly_only=args.wdh_weekly_only,
            verbose=True,
        )

        # 生成组合报告
        report = portfolio.generate_portfolio_report(portfolio_result)
        print(report)

        # 保存组合交易明细
        timeline_df = pd.DataFrame(portfolio_result.timeline_trades)
        timeline_path = output_dir / f"portfolio_timeline_{args.timeframe}.csv"
        timeline_df.to_csv(timeline_path, index=False, encoding="utf-8-sig")
        print(f"  组合交易明细已保存: {timeline_path}")
        print()


if __name__ == "__main__":
    main()
