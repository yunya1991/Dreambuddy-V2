#!/usr/bin/env python3
"""
资金流回测主执行脚本

使用方法：
# 回测最近 90 天
python3 run_flow_backtest.py

# 回测指定期间
python3 run_flow_backtest.py 2024-01-01 2024-12-31

# 指定数据目录
python3 run_flow_backtest.py 2024-01-01 2024-12-31 /path/to/data
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加脚本目录到路径
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from flow_backtester import run_flow_backtest, FlowBacktestConfig
from flow_backtest_report_generator import save_backtest_report


def main():
    """主函数"""
    print("=" * 60)
    print("资金流回测引擎")
    print("=" * 60)

    # 解析参数
    start_date = sys.argv[1] if len(sys.argv) > 1 else None
    end_date = sys.argv[2] if len(sys.argv) > 2 else None
    data_dir = sys.argv[3] if len(sys.argv) > 3 else "/workspace/ops/nanoclaw/core_task1/flow"

    if not start_date:
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    print(f"\n回测配置:")
    print(f"  开始日期：{start_date}")
    print(f"  结束日期：{end_date}")
    print(f"  数据目录：{data_dir}")

    # 执行回测
    print("\n[1/3] 执行回测...")
    result = run_flow_backtest(start_date, end_date, data_dir)

    # 创建配置
    config = FlowBacktestConfig(
        start_date=start_date,
        end_date=end_date
    )

    # 基准数据
    benchmark = {
        "return": -0.2526,  # 基准收益 -25.26%
        "max_drawdown": 0.2856,  # 基准回撤 28.56%
        "sharpe": 0  # 基准夏普
    }

    # 生成报告
    print("\n[2/3] 生成报告...")
    report_path = save_backtest_report(result, config, benchmark_data=benchmark)

    # 输出摘要
    print("\n[3/3] 回测摘要:")
    print("\n" + "=" * 60)
    print(f"总收益：{result.total_return*100:+.2f}%")
    print(f"年化收益：{result.annualized_return*100:+.2f}%")
    print(f"夏普比率：{result.sharpe_ratio:.2f}")
    print(f"最大回撤：{result.max_drawdown*100:.2f}%")
    print(f"胜率：{result.win_rate*100:.1f}%")
    print(f"交易次数：{result.total_trades}")
    print(f"预测准确率：{result.prediction_accuracy.get('overall', 0)*100:.1f}%")
    print("=" * 60)

    # 评估
    if result.total_return > 0:
        print("✅ 策略实现正收益")
    else:
        print("⚠️ 策略收益为负")

    if result.sharpe_ratio > 1.0:
        print("✅ 夏普比率良好")
    else:
        print("⚠️ 夏普比率有待提升")

    if result.max_drawdown < 0.20:
        print("✅ 回撤控制良好")
    else:
        print("⚠️ 回撤较大")

    print(f"\n详细报告：{report_path}")

    return result


if __name__ == "__main__":
    main()
