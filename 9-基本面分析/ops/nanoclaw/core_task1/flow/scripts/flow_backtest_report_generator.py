#!/usr/bin/env python3
"""
资金流回测报告生成器

功能：
1. 生成 Markdown 格式回测报告
2. 包含收益分析、风险评估、预测准确率等
3. 与新闻分析 skill 回测结果对比
4. 生成可视化图表数据（JSON 格式）
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 导入回测引擎
from flow_backtester import FlowBacktestResult, FlowBacktestConfig


def generate_backtest_report(
    result: FlowBacktestResult,
    config: FlowBacktestConfig,
    benchmark_data: dict = None,
    extra_notes: str = None
) -> str:
    """
    生成回测报告

    Args:
        result: 回测结果
        config: 回测配置
        benchmark_data: 基准数据（用于对比）
        extra_notes: 额外说明

    Returns:
        Markdown 格式报告
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 解读文本
    sharpe_text = interpret_sharpe(result.sharpe_ratio)
    drawdown_text = interpret_drawdown(result.max_drawdown)
    winrate_text = interpret_winrate(result.win_rate)

    # 基准对比
    benchmark_return = benchmark_data.get("return", -0.2526) if benchmark_data else -0.2526
    benchmark_drawdown = benchmark_data.get("max_drawdown", 0.2856) if benchmark_data else 0.2856
    benchmark_sharpe = benchmark_data.get("sharpe", 0) if benchmark_data else 0

    # 评估结论
    evaluation = generate_evaluation(result, benchmark_data)

    report = f"""# 资金流回测评估报告

**生成时间**: {ts}
**回测期间**: {config.start_date} 至 {config.end_date}
**初始资金**: ${config.initial_capital:,.0f}

---

## 📊 核心指标

| 指标 | 策略值 | 基准值 | 超额 |
|------|--------|--------|------|
| **总收益** | {result.total_return*100:+.2f}% | {benchmark_return*100:+.2f}% | {(result.total_return-benchmark_return)*100:+.2f}% |
| **年化收益** | {result.annualized_return*100:+.2f}% | - | - |
| **夏普比率** | {result.sharpe_ratio:.2f} | {benchmark_sharpe:.2f} | {result.sharpe_ratio-benchmark_sharpe:+.2f} |
| **最大回撤** | {result.max_drawdown*100:.2f}% | {benchmark_drawdown*100:.2f}% | {(result.max_drawdown-benchmark_drawdown)*100:+.2f}% |
| **胜率** | {result.win_rate*100:.1f}% | - | - |

---

## 📈 收益分析

### 收益构成
| 项目 | 数值 |
|------|------|
| 总交易次数 | {result.total_trades} |
| 盈利交易 | {result.winning_trades} |
| 亏损交易 | {result.losing_trades} |
| 平均盈亏 | ${result.avg_trade_pnl:,.2f} |
| 平均盈利 | ${result.avg_win:,.2f} |
| 平均亏损 | ${result.avg_loss:,.2f} |
| 盈亏比 | {result.profit_factor:.2f} |

### 月度收益
| 月份 | 收益 |
|------|------|
"""

    # 添加月度收益
    monthly = result.monthly_returns
    for month in sorted(monthly.keys())[:12]:  # 最多显示 12 个月
        report += f"| {month} | {monthly[month]*100:+.2f}% |\n"

    if len(monthly) > 12:
        report += f"| ... | ... |\n"

    report += f"""
---

## 🎯 预测准确率

| Bias 类型 | 准确率 | 样本数 |
|-----------|--------|--------|
| **总体** | {result.prediction_accuracy.get('overall', 0)*100:.1f}% | {result.total_trades} |
| Bullish | {result.prediction_accuracy.get('bullish', 0)*100:.1f}% | - |
| Bearish | {result.prediction_accuracy.get('bearish', 0)*100:.1f}% | - |
| Neutral | {result.prediction_accuracy.get('neutral', 0)*100:.1f}% | - |

### 目标准确率对比
| 指标 | 目标 | 实际 | 状态 |
|------|------|------|------|
| 总体准确率 | ≥55% | {result.prediction_accuracy.get('overall', 0)*100:.1f}% | {"✅" if result.prediction_accuracy.get('overall', 0) >= 0.55 else "❌"} |
| Bullish 准确率 | ≥60% | {result.prediction_accuracy.get('bullish', 0)*100:.1f}% | {"✅" if result.prediction_accuracy.get('bullish', 0) >= 0.60 else "❌"} |
| Bearish 准确率 | ≥60% | {result.prediction_accuracy.get('bearish', 0)*100:.1f}% | {"✅" if result.prediction_accuracy.get('bearish', 0) >= 0.60 else "❌"} |

---

## ⚠️ 风险评估

### 回撤分析
| 指标 | 数值 | 解读 |
|------|------|------|
| 最大回撤 | {result.max_drawdown*100:.2f}% | {drawdown_text} |
| 回撤持续天数 | {result.max_drawdown_duration} | {"较长" if result.max_drawdown_duration > 30 else "中等" if result.max_drawdown_duration > 14 else "较短"} |
| 索提诺比率 | {result.sortino_ratio:.2f} | {"优" if result.sortino_ratio > 1.5 else "良" if result.sortino_ratio > 1.0 else "中" if result.sortino_ratio > 0.5 else "差"} |

### 风险指标解读
- **夏普比率**: {result.sharpe_ratio:.2f} - {sharpe_text}
- **胜率**: {result.win_rate*100:.1f}% - {winrate_text}
- **盈亏比**: {result.profit_factor:.2f} - {"盈利覆盖亏损" if result.profit_factor > 1.5 else "需改善" if result.profit_factor > 1 else "亏损大于盈利"}

---

## 📊 权益曲线

### 累计收益走势
"""

    # 添加权益曲线数据（采样）
    if result.daily_equity:
        report += "```json\n"
        equity_data = []
        # 采样：每 7 天取一个点
        step = max(1, len(result.daily_equity) // 50)
        for i, record in enumerate(result.daily_equity):
            if i % step == 0:
                equity_data.append({
                    "date": record["date"],
                    "equity": round(record["equity"], 2),
                    "return": round((record["equity"] - config.initial_capital) / config.initial_capital * 100, 2)
                })
        report += json.dumps(equity_data, indent=2)
        report += "\n```\n"

    report += f"""
---

## 🎯 综合评估

**{evaluation["title"]}**

### 评估详情
{evaluation["details"]}

### 与新闻分析 Skill 对比
| 策略 | 周期 | 收益 | 最大回撤 | 夏普比率 |
|------|------|------|----------|----------|
| 基准 (Buy & Hold) | - | {benchmark_return*100:.2f}% | {benchmark_drawdown*100:.2f}% | {benchmark_sharpe:.2f} |
| V9.3/V9.8事件账本 | 90 天 | +5.22% | 15.96% | 0.85 |
| **资金流三层状态机** | 本次 | {result.total_return*100:.2f}% | {result.max_drawdown*100:.2f}% | {result.sharpe_ratio:.2f} |

---

## 📝 交易记录详情
"""

    # 添加交易记录（最近 20 条）
    if result.trades:
        report += """
| 入场日期 | 信号 | 置信度 | 出场日期 | 盈亏 | 原因 |
|----------|------|--------|----------|------|------|
"""
        for trade in result.trades[-20:]:
            pnl_icon = "✅" if trade.pnl > 0 else "❌"
            report += f"| {trade.entry_date[:10]} | {trade.entry_signal} | {trade.entry_confidence:.2f} | {trade.exit_date[:10] if trade.exit_date else '-'} | {pnl_icon} {trade.pnl_pct*100:+.1f}% | {trade.exit_reason} |\n"

    if extra_notes:
        report += f"""
---

## 📋 额外说明

{extra_notes}
"""

    report += """
---

## 🔧 回测参数

| 参数 | 值 |
|------|-----|
"""
    report += f"| 开始日期 | {config.start_date} |\n"
    report += f"| 结束日期 | {config.end_date} |\n"
    report += f"| 初始资金 | ${config.initial_capital:,.0f} |\n"
    report += f"| 交易成本 | {config.transaction_cost*100:.2f}% |\n"
    report += f"| 持有周期 | {config.hold_period} 天 |\n"
    report += f"| 信号阈值 | {config.signal_threshold:.2f} |\n"
    report += f"| 目标仓位 | {config.position_size*100:.0f}% |\n"
    report += f"| 止损阈值 | {config.stop_loss*100:.1f}% |\n"
    report += f"| 止盈阈值 | {config.take_profit*100:.1f}% |\n"

    report += """
---

*本报告由 flow_backtest_report_generator.py 生成 | 回测结果仅供参考，不构成投资建议*
*风险提示：历史业绩不代表未来表现，加密货币市场波动剧烈*
"""

    return report


def interpret_sharpe(sharpe: float) -> str:
    """解读夏普比率"""
    if sharpe > 2.0:
        return "优秀 - 风险调整后收益极佳"
    elif sharpe > 1.5:
        return "良好 - 风险调整后收益较好"
    elif sharpe > 1.0:
        return "中等 - 风险调整后收益一般"
    elif sharpe > 0.5:
        return "偏弱 - 风险调整后收益较差"
    else:
        return "差 - 风险调整后收益很差"


def interpret_drawdown(drawdown: float) -> str:
    """解读最大回撤"""
    dd_pct = drawdown * 100
    if dd_pct < 10:
        return "低风险 - 回撤控制优秀"
    elif dd_pct < 20:
        return "中等风险 - 回撤控制良好"
    elif dd_pct < 30:
        return "较高风险 - 回撤需关注"
    else:
        return "高风险 - 回撤过大"


def interpret_winrate(winrate: float) -> str:
    """解读胜率"""
    wr_pct = winrate * 100
    if wr_pct > 65:
        return "优秀 - 预测准确度高"
    elif wr_pct > 55:
        return "良好 - 预测准确度较好"
    elif wr_pct > 45:
        return "中等 - 预测准确度一般"
    else:
        return "偏弱 - 预测准确度需提升"


def generate_evaluation(result: FlowBacktestResult, benchmark_data: dict = None) -> dict:
    """生成综合评估"""
    benchmark_return = benchmark_data.get("return", -0.2526) if benchmark_data else -0.2526

    # 评分
    score = 0
    details = []

    # 收益评估
    if result.total_return > 0:
        score += 2
        details.append("✅ 策略实现正收益")
    elif result.total_return > benchmark_return:
        score += 1
        details.append("⚠️ 策略收益为负但跑赢基准")
    else:
        details.append("❌ 策略收益为负且未跑赢基准")

    # 夏普比率评估
    if result.sharpe_ratio > 1.5:
        score += 2
        details.append("✅ 夏普比率优秀")
    elif result.sharpe_ratio > 0.5:
        score += 1
        details.append("⚠️ 夏普比率中等")
    else:
        details.append("❌ 夏普比率偏低")

    # 回撤评估
    if result.max_drawdown < 0.15:
        score += 2
        details.append("✅ 回撤控制优秀")
    elif result.max_drawdown < 0.25:
        score += 1
        details.append("⚠️ 回撤控制中等")
    else:
        details.append("❌ 回撤过大")

    # 预测准确率评估
    accuracy = result.prediction_accuracy.get("overall", 0)
    if accuracy >= 0.60:
        score += 2
        details.append("✅ 预测准确度高")
    elif accuracy >= 0.55:
        score += 1
        details.append("⚠️ 预测准确度中等")
    else:
        details.append("❌ 预测准确度偏低")

    # 综合评级
    if score >= 7:
        title = "✅ 强烈推荐 - 策略表现优秀"
    elif score >= 5:
        title = "⚠️ 推荐 - 策略表现良好"
    elif score >= 3:
        title = "⚠️ 观望 - 策略需要优化"
    else:
        title = "❌ 不推荐 - 策略需要重大调整"

    return {
        "title": title,
        "details": "\n".join(details)
    }


def save_backtest_report(
    result: FlowBacktestResult,
    config: FlowBacktestConfig,
    output_dir: str = None,
    benchmark_data: dict = None,
    extra_notes: str = None
) -> str:
    """
    保存回测报告到文件

    Args:
        result: 回测结果
        config: 回测配置
        output_dir: 输出目录
        benchmark_data: 基准数据
        extra_notes: 额外说明

    Returns:
        报告文件路径
    """
    if output_dir is None:
        output_dir = "/workspace/ops/nanoclaw/core_task1/flow/outputs"

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 生成报告
    report = generate_backtest_report(result, config, benchmark_data, extra_notes)

    # 保存 Markdown
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    md_path = output_path / f"flow_backtest_report_{ts}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)

    # 保存 JSON 结果
    json_data = {
        "timestamp": ts,
        "config": {
            "start_date": config.start_date,
            "end_date": config.end_date,
            "initial_capital": config.initial_capital,
            "transaction_cost": config.transaction_cost,
            "hold_period": config.hold_period,
            "signal_threshold": config.signal_threshold,
            "position_size": config.position_size,
            "stop_loss": config.stop_loss,
            "take_profit": config.take_profit
        },
        "result": {
            "total_return": result.total_return,
            "annualized_return": result.annualized_return,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "max_drawdown": result.max_drawdown,
            "max_drawdown_duration": result.max_drawdown_duration,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "avg_trade_pnl": result.avg_trade_pnl,
            "avg_win": result.avg_win,
            "avg_loss": result.avg_loss,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "prediction_accuracy": result.prediction_accuracy,
            "monthly_returns": result.monthly_returns
        },
        "daily_equity": result.daily_equity,
        "trades": [
            {
                "entry_date": t.entry_date,
                "entry_price": t.entry_price,
                "entry_signal": t.entry_signal,
                "entry_confidence": t.entry_confidence,
                "exit_date": t.exit_date,
                "exit_price": t.exit_price,
                "exit_reason": t.exit_reason,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct
            }
            for t in result.trades
        ]
    }

    json_path = output_path / f"flow_backtest_result_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    print(f"[REPORT] 报告已保存：{md_path}")
    print(f"[REPORT] JSON 已保存：{json_path}")

    return str(md_path)


# =============================================================================
# 命令行入口
# =============================================================================

if __name__ == "__main__":
    import sys

    # 延迟导入避免循环引用
    from flow_backtester import run_flow_backtest, FlowBacktestConfig

    start = sys.argv[1] if len(sys.argv) > 1 else None
    end = sys.argv[2] if len(sys.argv) > 2 else None
    data_dir = sys.argv[3] if len(sys.argv) > 3 else None

    # 执行回测
    result = run_flow_backtest(start, end, data_dir)

    # 创建配置（用于报告）
    config = FlowBacktestConfig(
        start_date=start or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
        end_date=end or datetime.now().strftime("%Y-%m-%d")
    )

    benchmark = {
        "return": -0.2526,
        "max_drawdown": 0.2856,
        "sharpe": 0
    }

    report_path = save_backtest_report(result, config, benchmark_data=benchmark)
    print(f"\n[INFO] 报告生成完成：{report_path}")
