#!/usr/bin/env python3
"""
V9.4 回测对比分析

对比 V9.3 vs V9.4 的回测结果
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from event_ledger_backtester import EventLedgerBacktester, BacktestConfig


def run_v94_backtest(ledger_path: Path, data_dir: Path):
    """运行 V9.4 回测"""
    global config
    config = BacktestConfig(
        start_date="2025-12-09",
        end_date="2026-03-08",
        initial_capital=100000,
        transaction_cost=0.001,
        lookback_days=7
    )

    backtester = EventLedgerBacktester(config)
    result = backtester.run_backtest(ledger_path, data_dir)

    return backtester.generate_report(result), result


def main():
    """主函数"""
    print("=" * 70)
    print("  V9.4 回测对比分析 - 金十数据 + Twitter 大 V")
    print("=" * 70)

    data_dir = Path(__file__).parent.parent / "historical_data"
    raw_dir = Path(__file__).parent.parent / "raw"

    # V9.3 结果（已有的）
    v93_result_file = data_dir / "backtest_result_ledger_v9_3.json"

    # V9.4 回测
    v94_ledger = sorted(raw_dir.glob("event_ledger_v94_*.jsonl"))[-1]
    print(f"\n使用 V9.4 账本：{v94_ledger.name}")

    report, result = run_v94_backtest(v94_ledger, data_dir)

    # 加载 V9.3 结果对比
    if v93_result_file.exists():
        with open(v93_result_file, 'r') as f:
            v93_data = json.load(f)
        v93_results = v93_data['results']
    else:
        v93_results = None

    print(report)

    # 对比分析
    print("\n" + "=" * 70)
    print("  V9.3 vs V9.4 对比")
    print("=" * 70)

    v94_results = {
        "total_return": result.total_return,
        "annualized_return": result.annualized_return,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "total_trades": result.total_trades
    }

    print(f"\n{'指标':<15} {'V9.3':>15} {'V9.4':>15} {'变化':>15}")
    print("-" * 60)

    metrics = [
        ("总收益", "total_return"),
        ("年化收益", "annualized_return"),
        ("夏普比率", "sharpe_ratio"),
        ("最大回撤", "max_drawdown"),
        ("交易次数", "total_trades"),
    ]

    for name, key in metrics:
        v93_val = v93_results.get(key, 0) if v93_results else 0
        v94_val = v94_results.get(key, 0)

        if key in ["total_return", "annualized_return", "sharpe_ratio"]:
            v93_str = f"{v93_val:.2%}" if key != "sharpe_ratio" else f"{v93_val:.2f}"
            v94_str = f"{v94_val:.2%}" if key != "sharpe_ratio" else f"{v94_val:.2f}"
        else:
            v93_str = str(v93_val)
            v94_str = str(v94_val)

        change = v94_val - v93_val if v93_results else 0
        if key in ["total_return", "annualized_return"]:
            change_str = f"{change:+.2%}"
        elif key == "sharpe_ratio":
            change_str = f"{change:+.2f}"
        else:
            change_str = f"{int(change):+d}" if change != 0 else "+0"

        print(f"{name:<15} {v93_str:>15} {v94_str:>15} {change_str:>15}")

    # V9.4 事件统计
    if hasattr(result, 'event_stats') and result.event_stats:
        print("\n【V9.4 事件统计】")
        es = result.event_stats
        print(f"  总事件数：{es.get('total_events', 0)}")
        print(f"  触发交易：{es.get('triggered_trades', 0)}")

    # 保存结果
    result_summary = {
        "version": "V9.4",
        "features": ["金十数据", "Twitter 大 V", "影响力加权"],
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
            "total_trades": result.total_trades
        }
    }

    output_file = data_dir / "backtest_result_ledger_v9_4.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result_summary, f, indent=2, ensure_ascii=False)

    print(f"\n[✓] 回测结果已保存：{output_file}")

    return result


if __name__ == "__main__":
    main()
