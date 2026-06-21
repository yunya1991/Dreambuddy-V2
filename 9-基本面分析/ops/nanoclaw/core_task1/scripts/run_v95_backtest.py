#!/usr/bin/env python3
"""
V9.5 回测对比分析

对比 V9.3 vs V9.4 vs V9.5 的回测结果

V9.5 优化点:
1. 降低金十数据权重 (1.2 → 1.0)
2. 提高大 V 影响力权重 (T0: 1.5→1.8, T1: 1.3→1.5)
3. 限制每日金十数据数量 (最多 3 条)
4. 优化信号计算 (加法而非连乘)
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from event_ledger_backtester import EventLedgerBacktester, BacktestConfig


def run_backtest(ledger_path: Path, data_dir: Path):
    """运行回测"""
    config = BacktestConfig(
        start_date="2025-12-09",
        end_date="2026-03-08",
        initial_capital=100000,
        transaction_cost=0.001,
        lookback_days=7
    )

    backtester = EventLedgerBacktester(config)
    result = backtester.run_backtest(ledger_path, data_dir)

    return backtester.generate_report(result), result, config


def main():
    """主函数"""
    print("=" * 70)
    print("  V9.5 回测对比分析 - 优化版")
    print("=" * 70)

    data_dir = Path(__file__).parent.parent / "historical_data"
    raw_dir = Path(__file__).parent.parent / "raw"

    # 加载 V9.3 结果
    v93_result_file = data_dir / "backtest_result_ledger_v9_3.json"
    if v93_result_file.exists():
        with open(v93_result_file, 'r') as f:
            v93_data = json.load(f)
        v93_results = v93_data.get('results', {})
    else:
        v93_results = None

    # 加载 V9.4 结果
    v94_result_file = data_dir / "backtest_result_ledger_v9_4.json"
    if v94_result_file.exists():
        with open(v94_result_file, 'r') as f:
            v94_data = json.load(f)
        v94_results = v94_data.get('results', {})
    else:
        v94_results = None

    # V9.5 回测
    v95_ledger = sorted(raw_dir.glob("event_ledger_v95_*.jsonl"))
    if not v95_ledger:
        print("\n[ERROR] 未找到 V9.5 事件账本，请先运行 event_ledger_generator_v95.py")
        return None

    v95_ledger = v95_ledger[-1]
    print(f"\n使用 V9.5 账本：{v95_ledger.name}")

    report, result, config = run_backtest(v95_ledger, data_dir)

    print(report)

    # 对比分析
    print("\n" + "=" * 70)
    print("  V9.3 vs V9.4 vs V9.5 对比")
    print("=" * 70)

    v95_results = {
        "total_return": result.total_return,
        "annualized_return": result.annualized_return,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "total_trades": result.total_trades
    }

    print(f"\n{'指标':<15} {'V9.3':>15} {'V9.4':>15} {'V9.5':>15} {'V9.5 vs V9.4':>15}")
    print("-" * 75)

    metrics = [
        ("总收益", "total_return"),
        ("年化收益", "annualized_return"),
        ("夏普比率", "sharpe_ratio"),
        ("最大回撤", "max_drawdown"),
        ("交易次数", "total_trades"),
    ]

    for name, key in metrics:
        v93_val = v93_results.get(key, 0) if v93_results else 0
        v94_val = v94_results.get(key, 0) if v94_results else 0
        v95_val = v95_results.get(key, 0)

        if key in ["total_return", "annualized_return", "sharpe_ratio"]:
            v93_str = f"{v93_val:.2%}" if key != "sharpe_ratio" else f"{v93_val:.2f}"
            v94_str = f"{v94_val:.2%}" if key != "sharpe_ratio" else f"{v94_val:.2f}"
            v95_str = f"{v95_val:.2%}" if key != "sharpe_ratio" else f"{v95_val:.2f}"
        else:
            v93_str = str(v93_val)
            v94_str = str(v94_val)
            v95_str = str(v95_val)

        change_v94 = v94_val - v93_val if v93_results else 0
        change_v95 = v95_val - v94_val

        if key in ["total_return", "annualized_return"]:
            change_str = f"{change_v95:+.2%}"
        elif key == "sharpe_ratio":
            change_str = f"{change_v95:+.2f}"
        else:
            change_str = f"{int(change_v95):+d}" if change_v95 != 0 else "+0"

        print(f"{name:<15} {v93_str:>15} {v94_str:>15} {v95_str:>15} {change_str:>15}")

    # V9.5 事件统计
    if hasattr(result, 'event_stats') and result.event_stats:
        print("\n【V9.5 事件统计】")
        es = result.event_stats
        print(f"  总事件数：{es.get('total_events', 0)}")
        print(f"  触发交易：{es.get('triggered_trades', 0)}")

        print("\n  按行动分布:")
        for action, count in sorted(es.get("by_action", {}).items()):
            bar = "█" * (count // 2)
            pct = count / es.get('total_events', 1) * 100
            print(f"    {action}: {count} ({pct:.1f}%) {bar}")

    # 保存结果
    result_summary = {
        "version": "V9.5",
        "features": [
            "金十数据权重降低 (1.0)",
            "大 V 影响力提升 (T0:1.8, T1:1.5)",
            "限制每日金十数量 (≤3 条)",
            "信号计算优化 (加法非连乘)"
        ],
        "backtest_config": {
            "start_date": config.start_date,
            "end_date": config.end_date,
            "initial_capital": config.initial_capital,
            "transaction_cost": config.transaction_cost,
            "lookback_days": config.lookback_days
        },
        "results": {
            "total_return": result.total_return,
            "annualized_return": result.annualized_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "total_trades": result.total_trades,
            "event_stats": result.event_stats
        },
        "comparison": {
            "v93": v93_results,
            "v94": v94_results,
            "v95": v95_results
        }
    }

    output_file = data_dir / "backtest_result_ledger_v9_5.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result_summary, f, indent=2, ensure_ascii=False)

    print(f"\n[✓] 回测结果已保存：{output_file}")

    # 评估结论
    print("\n" + "=" * 70)
    print("  评估结论")
    print("=" * 70)

    if result.annualized_return > v93_results.get("annualized_return", 0) if v93_results else False:
        print("✅ V9.5 年化收益超越 V9.3")
    else:
        print("⚠️ V9.5 年化收益未超越 V9.3")

    if result.annualized_return > v94_results.get("annualized_return", 0) if v94_results else False:
        print("✅ V9.5 年化收益超越 V9.4")
    else:
        print("⚠️ V9.5 年化收益未超越 V9.4")

    if result.sharpe_ratio > 0.5:
        print("✅ 夏普比率良好 (>0.5)")
    elif result.sharpe_ratio > 0:
        print("⚠️ 夏普比率偏低但为正")
    else:
        print("❌ 夏普比率为负")

    if result.max_drawdown < 0.15:
        print("✅ 回撤可控 (<15%)")
    else:
        print("⚠️ 回撤较大 (≥15%)")

    return result


if __name__ == "__main__":
    main()
