#!/usr/bin/env python3
"""
Dream OS 交易评估回测脚本

功能:
    1. 读取 execution_feedback.json 和 orchestration_memory.json
    2. 整合交易数据，转换为评估器格式
    3. 运行 TradingAnalysisEvaluator 进行分析
    4. 生成各场景最优编排策略
    5. 输出完整评估报告
"""

import json
import sys
import os
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from dreamos.capabilities.trading.evaluator import TradingAnalysisEvaluator


def load_execution_feedback(file_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """加载执行反馈数据"""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_orchestration_memory(file_path: str) -> Dict[str, Any]:
    """加载编排记忆数据"""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def transform_trade_data(feedback: Dict[str, List[Dict[str, Any]]],
                         memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    """将反馈数据转换为评估器所需格式"""
    trades = []
    trade_id = 0

    for scenario, scenario_trades in feedback.items():
        scenario_info = memory.get("scenarios", {}).get(scenario, {})
        best_pattern = scenario_info.get("best_pattern", "")
        nodes = scenario_info.get("nodes", [])

        for trade in scenario_trades:
            trade_id += 1
            
            entry_price = trade.get("entry_price", 0)
            exit_price = trade.get("exit_price", 0)
            if exit_price > 0 and entry_price > 0:
                if trade.get("direction", "") == "LONG":
                    pnl_percent = (exit_price - entry_price) / entry_price * 100
                else:
                    pnl_percent = (entry_price - exit_price) / entry_price * 100
            else:
                pnl_percent = trade.get("result", 0) * 100

            trades.append({
                "trade_id": f"trade_{trade_id:06d}",
                "symbol": trade.get("symbol", ""),
                "direction": trade.get("direction", ""),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl_percent / 100,
                "pnl_percent": pnl_percent,
                "holding_period": 1,
                "scenario": scenario,
                "chain_used": trade.get("pattern", best_pattern),
                "nodes_used": nodes,
                "entry_confidence": 0.65 if trade.get("direction") else 0,
                "exit_reason": "normal" if exit_price > 0 else "open",
                "stop_loss_hit": pnl_percent < -3,
                "take_profit_hit": 0 < pnl_percent < 2,
                "signal_strength": 0.6,
                "scenario_mismatch": False,
                "actual_volatility": 0.02,
                "estimated_volatility": 0.02,
                "momentum_confidence": 0.5,
                "correlation_conflict": False,
                "expected_direction": trade.get("expected_direction", ""),
                "timestamp": trade.get("timestamp", ""),
            })

    return trades


def run_evaluation(feedback_path: str, memory_path: str) -> None:
    """运行评估回测"""
    print("=" * 80)
    print("Dream OS 交易评估回测系统")
    print("=" * 80)

    print("\n[1/4] 加载数据...")
    feedback = load_execution_feedback(feedback_path)
    memory = load_orchestration_memory(memory_path)
    print(f"  - 执行反馈: {sum(len(v) for v in feedback.values())} 条交易记录")
    print(f"  - 场景数: {len(feedback.keys())}")

    print("\n[2/4] 转换数据格式...")
    trades = transform_trade_data(feedback, memory)
    print(f"  - 转换完成: {len(trades)} 条标准交易记录")

    print("\n[3/4] 运行评估器...")
    evaluator = TradingAnalysisEvaluator()
    evaluator.set_orchestration_memory(memory)
    
    print("\n  分析亏损原因...")
    analyses = evaluator.analyze_loss_reasons(trades)
    print(f"    - 分析交易数: {len(analyses)}")
    
    print("\n  评估模块能力...")
    capabilities = evaluator.evaluate_module_capabilities(trades)
    print(f"    - 评估模块数: {len(capabilities)}")

    print("\n  生成编排推荐...")
    scenarios = list(feedback.keys())
    memory_scenarios = list(memory.get("scenarios", {}).keys())
    all_scenarios = list(set(scenarios + memory_scenarios))
    recommendations = evaluator.recommend_orchestration(scenarios=all_scenarios)
    print(f"    - 生成推荐场景数: {len(recommendations)}")

    print("\n[4/4] 生成报告...")
    report = evaluator.generate_report(trades, scenarios=all_scenarios)

    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(report_dir, exist_ok=True)

    json_path = os.path.join(report_dir, f"evaluation_report_{report.report_id}.json")
    md_path = os.path.join(report_dir, f"evaluation_report_{report.report_id}.md")
    
    evaluator.save_report(report, json_path)
    evaluator.save_report_markdown(report, md_path)

    print_report_summary(report)

    print(f"\n报告已保存:")
    print(f"  - JSON: {json_path}")
    print(f"  - Markdown: {md_path}")


def print_report_summary(report) -> None:
    """打印报告摘要"""
    print("\n" + "=" * 80)
    print("评估报告摘要")
    print("=" * 80)

    print(f"\n【概览】")
    print(f"  分析交易数: {report.analyzed_trades}")
    print(f"  盈利交易数: {report.profitable_trades}")
    print(f"  胜率: {report.profitable_trades/report.analyzed_trades*100:.1f}%")
    print(f"  平均盈亏: {report.avg_pnl:.2f}%")

    print(f"\n【亏损原因 Top5】")
    for reason, count in report.top_loss_reasons:
        rate = count / report.analyzed_trades * 100
        print(f"  {reason}: {count} 次 ({rate:.1f}%)")

    print(f"\n【模块能力排名】")
    sorted_modules = sorted(report.module_capabilities.values(),
                            key=lambda x: -x.success_rate)
    for i, cap in enumerate(sorted_modules[:10], 1):
        print(f"  {i:2d}. {cap.module_id:4s} [{cap.module_name}] 胜率:{cap.success_rate*100:.1f}% 准确率:{cap.accuracy*100:.1f}% 盈亏比:{cap.profit_factor:.2f}")

    print(f"\n【场景编排推荐】")
    for scenario, rec in report.orchestration_recommendations.items():
        print(f"  {scenario}:")
        print(f"    - 推荐链路: {rec.recommended_chain}")
        print(f"    - 推荐节点: {', '.join(rec.recommended_nodes)}")
        print(f"    - 置信度: {rec.confidence*100:.1f}%")

    print(f"\n【改进建议】")
    for i, suggestion in enumerate(report.improvement_suggestions, 1):
        print(f"  {i}. {suggestion}")


if __name__ == "__main__":
    feedback_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "dreamos", "core", "memory", "execution_feedback.json"
    )
    memory_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "dreamos", "core", "memory", "orchestration_memory.json"
    )

    if not os.path.exists(feedback_path):
        print(f"错误: 找不到执行反馈文件: {feedback_path}")
        sys.exit(1)
    if not os.path.exists(memory_path):
        print(f"错误: 找不到编排记忆文件: {memory_path}")
        sys.exit(1)

    run_evaluation(feedback_path, memory_path)