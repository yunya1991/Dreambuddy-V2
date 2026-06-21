#!/usr/bin/env python3
"""
加密新闻技能回测分析报告生成器
基于历史回测数据生成详细分析报告
"""

import json
from datetime import datetime
from pathlib import Path

HISTORICAL_DATA_DIR = "/workspace/ops/nanoclaw/core_task1/historical_data"
OUTPUT_DIR = "/workspace/ops/nanoclaw/core_task1/outputs"

def load_backtest_results():
    """加载历史回测结果"""
    files = [
        "backtest_result.json",
        "backtest_result_real_news.json",
        "backtest_result_ledger_v9_3.json",
        "backtest_result_ledger_v9_4.json",
        "backtest_result_ledger_v9_5.json",
        "backtest_result_ledger_v9_7.json",
        "backtest_result_ledger_v9_8_onchain.json"
    ]

    results = {}
    for filename in files:
        filepath = Path(HISTORICAL_DATA_DIR) / filename
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                results[filename.replace("backtest_result_", "").replace(".json", "")] = data

    return results

def analyze_equity_curve(equity_data):
    """分析权益曲线"""
    if not equity_data:
        return {}

    equities = [d.get("equity", 0) for d in equity_data]
    prices = [d.get("price", 0) for d in equity_data]
    signals = [d.get("signal", 0) for d in equity_data]
    positions = [d.get("position", 0) for d in equity_data]

    # 计算统计
    initial = equities[0] if equities else 0
    final = equities[-1] if equities else 0
    total_return = (final - initial) / initial if initial > 0 else 0

    # 最大回撤
    peak = initial
    max_dd = 0
    for equity in equities:
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # 信号统计
    positive_signals = sum(1 for s in signals if s > 0)
    negative_signals = sum(1 for s in signals if s < 0)
    avg_signal = sum(signals) / len(signals) if signals else 0

    # 仓位统计
    avg_position = sum(positions) / len(positions) if positions else 0

    return {
        "initial_capital": initial,
        "final_capital": final,
        "total_return": total_return,
        "max_drawdown": max_dd,
        "positive_signal_days": positive_signals,
        "negative_signal_days": negative_signals,
        "avg_signal": avg_signal,
        "avg_position": avg_position,
        "trading_days": len(equity_data)
    }

def generate_report(all_results):
    """生成回测分析报告"""

    report = []
    report.append("# 加密新闻技能回测分析报告")
    report.append("")
    report.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")

    # 1. 各版本回测结果对比
    report.append("## 1. 各版本策略回测对比")
    report.append("")
    report.append("| 策略版本 | 总收益 | 年化收益 | 夏普比率 | 最大回撤 | 总交易次数 |")
    report.append("|----------|--------|----------|----------|----------|------------|")

    for version, data in all_results.items():
        if isinstance(data, dict) and "results" in data:
            results = data["results"]
            total_return = results.get("total_return", 0) * 100
            ann_return = results.get("annualized_return", 0) * 100
            sharpe = results.get("sharpe_ratio", 0)
            max_dd = results.get("max_drawdown", 0) * 100
            trades = results.get("total_trades", 0)

            report.append(f"| {version} | {total_return:.2f}% | {ann_return:.2f}% | {sharpe:.2f} | {max_dd:.2f}% | {trades} |")

    report.append("")

    # 2. 详细分析最新版本
    if "backtest_result" in all_results:
        data = all_results["backtest_result"]
        config = data.get("backtest_config", {})
        results = data.get("results", {})
        equity_data = data.get("daily_equity", [])

        stats = analyze_equity_curve(equity_data)

        report.append("## 2. 回测配置")
        report.append("")
        report.append(f"- **回测期间**: {config.get('start_date')} 至 {config.get('end_date')}")
        report.append(f"- **初始资金**: ${config.get('initial_capital'):,.0f}")
        report.append(f"- **交易成本**: {config.get('transaction_cost', 0)*100:.2f}%")
        report.append(f"- **回看天数**: {config.get('lookback_days')} 天")
        report.append("")

        report.append("## 3. 核心绩效指标")
        report.append("")
        report.append(f"| 指标 | 数值 | 评估 |")
        report.append(f"|------|------|------|")

        total_return = results.get("total_return", 0) * 100
        ann_return = results.get("annualized_return", 0) * 100
        sharpe = results.get("sharpe_ratio", 0)
        max_dd = results.get("max_drawdown", 0) * 100
        win_rate = results.get("win_rate", 0) * 100

        report.append(f"| 总收益 | {total_return:.2f}% | {'✅' if total_return > 0 else '❌'} |")
        report.append(f"| 年化收益 | {ann_return:.2f}% | {'✅' if ann_return > 0 else '❌'} |")
        report.append(f"| 夏普比率 | {sharpe:.2f} | {'✅' if sharpe > 1 else '⚠️' if sharpe > 0 else '❌'} |")
        report.append(f"| 最大回撤 | {max_dd:.2f}% | {'✅' if max_dd < 0.15 else '⚠️' if max_dd < 0.25 else '❌'} |")
        report.append(f"| 胜率 | {win_rate:.1f}% | {'✅' if win_rate > 55 else '⚠️' if win_rate > 45 else '❌'} |")
        report.append("")

        report.append("## 4. 信号统计分析")
        report.append("")
        report.append(f"- **交易天数**: {stats.get('trading_days', 0)}")
        report.append(f"- **正信号天数**: {stats.get('positive_signal_days', 0)} ({stats.get('positive_signal_days', 0)/stats.get('trading_days', 1)*100:.1f}%)")
        report.append(f"- **负信号天数**: {stats.get('negative_signal_days', 0)} ({stats.get('negative_signal_days', 0)/stats.get('trading_days', 1)*100:.1f}%)")
        report.append(f"- **平均信号强度**: {stats.get('avg_signal', 0):.4f}")
        report.append(f"- **平均仓位**: {stats.get('avg_position', 0)*100:.1f}%")
        report.append("")

        report.append("## 5. 权益曲线分析")
        report.append("")
        report.append(f"- **初始资金**: ${stats.get('initial_capital'):,.0f}")
        report.append(f"- **期末资金**: ${stats.get('final_capital'):,.0f}")
        report.append(f"- **绝对收益**: ${stats.get('final_capital', 0) - stats.get('initial_capital'):,.0f}")
        report.append(f"- **收益率**: {stats.get('total_return', 0)*100:.2f}%")
        report.append(f"- **最大回撤**: {stats.get('max_drawdown', 0)*100:.2f}%")
        report.append("")

    # 6. 问题诊断与改进建议
    report.append("## 6. 问题诊断")
    report.append("")

    # 根据数据判断问题
    if total_return < 0:
        report.append("### ❌ 问题 1：策略整体亏损")
        report.append("")
        report.append("**可能原因**:")
        report.append("1. 信号阈值设置不合理，导致过度交易")
        report.append("2. 新闻情感分析准确度不足")
        report.append("3. 未考虑市场状态（牛市/熊市）差异")
        report.append("4. 交易成本侵蚀利润")
        report.append("")

    if sharpe < 0:
        report.append("### ❌ 问题 2：风险调整后收益为负")
        report.append("")
        report.append("**可能原因**:")
        report.append("1. 收益波动过大")
        report.append("2. 回撤控制不当")
        report.append("3. 信号稳定性差")
        report.append("")

    if max_dd > 0.2:
        report.append("### ❌ 问题 3：最大回撤过大 (>20%)")
        report.append("")
        report.append("**可能原因**:")
        report.append("1. 仓位管理过于激进")
        report.append("2. 缺乏止损机制")
        report.append("3. 单边行情应对不足")
        report.append("")

    if win_rate < 50:
        report.append("### ❌ 问题 4：胜率偏低 (<50%)")
        report.append("")
        report.append("**可能原因**:")
        report.append("1. 信号方向判断错误率高")
        report.append("2. 新闻时效性不足")
        report.append("3. 市场反应与预期不符")
        report.append("")

    # 7. 改进建议
    report.append("## 7. 改进建议")
    report.append("")
    report.append("### 策略层面")
    report.append("")
    report.append("1. **优化信号阈值**")
    report.append("   - 当前使用固定阈值可能导致过度交易")
    report.append("   - 建议根据市场波动率动态调整阈值")
    report.append("")
    report.append("2. **引入市场状态识别**")
    report.append("   - 区分牛市/熊市/震荡市")
    report.append("   - 不同市场状态使用不同策略参数")
    report.append("")
    report.append("3. **改进仓位管理**")
    report.append("   - 根据信号强度动态调整仓位")
    report.append("   - 设置最大仓位限制和止损线")
    report.append("")

    report.append("### 技术层面")
    report.append("")
    report.append("1. **提升新闻质量筛选**")
    report.append("   - 增加来源可信度权重")
    report.append("   - 过滤低质量/重复新闻")
    report.append("")
    report.append("2. **引入链上数据验证**")
    report.append("   - 结合交易所流向")
    report.append("   - 监控大额转账和持仓变化")
    report.append("")
    report.append("3. **增加风险控制模块**")
    report.append("   - 实时监测极端行情")
    report.append("   - 自动触发风险关闭 (risk-off)")
    report.append("")

    report.append("### 下一步行动")
    report.append("")
    report.append("1. 运行 V2.1 版本回测（研究口径落地）")
    report.append("2. 引入资金流分析技能进行信号增强")
    report.append("3. 建立实时信号监控与评估机制")
    report.append("")

    # 保存报告
    report_content = "\n".join(report)
    report_file = Path(OUTPUT_DIR) / "backtest_analysis_report.md"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f"回测分析报告已保存至：{report_file}")
    print("\n" + "=" * 70)
    print(report_content)
    print("=" * 70)

    return report_content

if __name__ == "__main__":
    results = load_backtest_results()
    print(f"已加载 {len(results)} 个回测结果文件")
    generate_report(results)
