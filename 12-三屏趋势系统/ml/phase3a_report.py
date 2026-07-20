"""Phase 3A: 抄底与逃顶策略验证报告

验证两个策略假设：
1. DIP_BUY优化：轻仓试探 + 越跌越买 + MA200抄底结束
2. TOP_EXIT优化：MA128破位分批卖 + 反弹卖出

结论：存入闭环管理器，更新假设状态。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ml.closed_loop_manager import ClosedLoopManager, HypothesisStatus


def main():
    mgr = ClosedLoopManager()

    print("=" * 80)
    print("  Phase 3A: 抄底与逃顶策略验证报告")
    print("=" * 80)
    print()

    # 查找相关假设
    all_hypos = mgr.list_hypotheses()

    dip_hypo = None
    top_hypo = None
    for h in all_hypos:
        if "DIP_BUY" in h.title and "抄底" in h.title:
            dip_hypo = h
        elif "TOP_EXIT" in h.title and "离场" in h.title:
            top_hypo = h

    print("📋 相关假设状态：")
    if dip_hypo:
        print(f"  DIP_BUY假设: {dip_hypo.hypo_id} - {dip_hypo.title} [{dip_hypo.status}]")
    if top_hypo:
        print(f"  TOP_EXIT假设: {top_hypo.hypo_id} - {top_hypo.title} [{top_hypo.status}]")
    print()

    # 实验结果摘要
    print("=" * 80)
    print("  实验结果摘要")
    print("=" * 80)
    print()

    print("""
【实验1：完整v3（抄底+逃顶都优化）】
  综合评分: 1.000 → 0.975 (-0.025) ❌ 未超越基线
  夏普比率: 0.600 → 0.570 (-0.030)
  DIP_BUY胜率: 47.62% → 55.81% (+8.19%) ✅
  DIP_BUY收益: -0.07% → 1.95% (+2.02%) ✅
  TOP_EXIT胜率: 57.14% → 44.19% (-12.96%) ❌
  TOP_EXIT收益: 1.63% → -1.82% (-3.45%) ❌
  结论：抄底改善明显，但逃顶拖了后腿

【实验2：仅抄底优化（v3.1）】
  综合评分: 1.000 → 0.973 (-0.027) ❌ 未超越基线
  夏普比率: 0.600 → 0.580 (-0.020)
  DIP_BUY胜率: 47.62% → 51.28% (+3.66%) ✅
  DIP_BUY收益: -0.07% → 0.90% (+0.97%) ✅
  结论：抄底准确率提升了，但整体收益反而下降

【核心发现：准确率 vs 仓位弹性的矛盾】
  v2  模式：跌了就重仓抄（第1档就80%仓位）
         → 胜率低（47.62%），但仓位重，反弹时赚得多

  v3.1模式：轻仓试探+越跌越买（第1档13.5%，6档加到90%）
         → 胜率高（51.28%），但仓位加得慢，反弹时仓位还轻

  关键洞察：
  ✅ "轻仓试探+精细加仓"确实提高了抄底准确率
  ❌ 但"仓位加得太慢"导致错过底部反弹的beta收益
  💡 下一步：需要"抄底确认后加速加仓"的机制
     比如出现反转信号（RSI底背离/大阳线/放量）时，直接加满
""")

    # 创建新的实验记录
    print()
    print("=" * 80)
    print("  存入闭环管理器")
    print("=" * 80)
    print()

    # 记录实验1：完整v3
    if dip_hypo:
        exp1 = mgr.create_experiment(
            name="v3完整优化_抄底+逃顶",
            hypo_id=dip_hypo.hypo_id,
            objective="all",
            strategy_name="EnhancedMA200V3",
            config={
                "dip_buy_enhanced": True,
                "exit_enhanced": True,
                "dip_levels": 6,
                "dip_step_pct": 3.0,
                "ma128_exit": True,
                "bounce_sell": True,
            },
        )
        mgr.record_experiment_result(
            exp_id=exp1.exp_id,
            result_data={
                "overall": {
                    "sharpe": 0.570,
                    "total_return": 5.717,
                    "max_drawdown": 0.732,
                    "composite_score": 0.975,
                },
                "dip_buy": {
                    "win_rate": 0.5581,
                    "avg_return": 0.0195,
                    "f1": 0.016,
                },
                "top_exit": {
                    "win_rate": 0.4419,
                    "avg_return": -0.0182,
                    "f1": 0.021,
                },
            },
            composite_score=0.975,
            conclusion="抄底准确率提升明显，但逃顶逻辑反向拖累，整体未超越基线",
            lessons_learned="MA128破位+反弹卖出的逃顶逻辑过于激进，牛市回调中过早卖出导致卖飞。逃顶需要更严格的触发条件（如大顶确认）。",
        )
        print(f"✅ 实验已记录: {exp1.exp_id} - v3完整优化")

    # 记录实验2：仅抄底优化
    if dip_hypo:
        exp2 = mgr.create_experiment(
            name="v3.1仅抄底优化",
            hypo_id=dip_hypo.hypo_id,
            objective="dip_buy",
            strategy_name="EnhancedMA200V31",
            config={
                "dip_buy_enhanced": True,
                "exit_enhanced": False,
                "dip_levels": 6,
                "dip_step_pct": 3.0,
                "dip_initial_ratio": 0.15,
            },
        )
        mgr.record_experiment_result(
            exp_id=exp2.exp_id,
            result_data={
                "overall": {
                    "sharpe": 0.580,
                    "total_return": 6.165,
                    "max_drawdown": 0.7785,
                    "composite_score": 0.973,
                },
                "dip_buy": {
                    "win_rate": 0.5128,
                    "avg_return": 0.0090,
                    "f1": 0.010,
                    "signals": 40,
                },
            },
            composite_score=0.973,
            conclusion="抄底准确率提升（胜率+3.66%，收益转正），但整体收益因仓位弹性下降而略低于基线",
            lessons_learned=(
                "发现核心矛盾：轻仓试探提高了准确率，但仓位加得太慢导致错过反弹beta。\n"
                "下一步方向：增加抄底确认后的加速加仓机制（如RSI底背离/放量反转信号触发加满）。"
            ),
        )
        print(f"✅ 实验已记录: {exp2.exp_id} - v3.1仅抄底优化")

    # 记录实验3：逃顶验证（失败的）
    if top_hypo:
        exp3 = mgr.create_experiment(
            name="逃顶_MA128+反弹卖出",
            hypo_id=top_hypo.hypo_id,
            objective="top_exit",
            strategy_name="EnhancedMA200V3_exit_only",
            config={
                "ma128_exit": True,
                "bounce_sell": True,
                "exit_drawdown_threshold": 0.15,
            },
        )
        mgr.record_experiment_result(
            exp_id=exp3.exp_id,
            result_data={
                "overall": {
                    "sharpe": 0.450,
                    "total_return": 3.526,
                    "max_drawdown": 0.732,
                    "composite_score": 0.786,
                },
                "top_exit": {
                    "win_rate": 0.5294,
                    "avg_return": -0.0036,
                    "f1": 0.021,
                },
            },
            composite_score=0.786,
            conclusion="MA128破位+反弹卖出的逃顶逻辑效果不佳，显著低于基线",
            lessons_learned=(
                "逃顶逻辑过于激进：\n"
                "1. MA128在牛市中经常被跌破后又收回，导致卖飞\n"
                "2. 反弹卖出在震荡市中反复触发，反复卖飞\n"
                "3. 逃顶需要更大级别的确认信号（如跌破MA200、高点回撤30%+等）\n"
                "4. 可以考虑加入减半周期时间窗口作为辅助判断"
            ),
        )
        print(f"✅ 实验已记录: {exp3.exp_id} - 逃顶MA128+反弹卖出")

        # 更新TOP_EXIT假设状态为REJECTED（当前方案被否决）
        mgr.update_hypothesis_status(
            top_hypo.hypo_id,
            HypothesisStatus.REJECTED.value,
            notes="MA128破位+反弹卖出的逃顶方案效果不佳，整体收益和胜率都下降。需要重新设计更保守的逃顶逻辑。",
        )
        print(f"🔄 TOP_EXIT假设状态更新: pending → rejected")

    print()
    print("=" * 80)
    print("  📊 当前状态总览")
    print("=" * 80)
    print()
    mgr.print_summary()

    print()
    print("=" * 80)
    print("  🎯 下一步建议")
    print("=" * 80)
    print()
    print("""
方向A：优化抄底加仓节奏（高优先级）
  - 保留"轻仓试探+越跌越买"的准确率优势
  - 增加"反转确认信号"触发加速加仓
  - 信号候选：RSI底背离、MACD金叉、放量长阳、突破5日均线
  - 目标：既保持高胜率，又不错过反弹beta

方向B：重新设计逃顶逻辑（中优先级）
  - 当前MA128方案被否决，需更保守的设计
  - 候选方案：
    1. 仅在跌破MA200后才启动逃顶（大级别确认）
    2. 从高点回撤30%+后才启动分批卖出
    3. 减半周期+价格泡沫度（如MVRV、Puell Multiple）作为时间锚定
    4. 简化为：跌破MA200才卖，中间不做逃顶操作

方向C：提取特征用于ML（并行推进）
  - 把这些策略逻辑转化为特征
  - 用LightGBM学习最优的抄底/逃顶时机
  - 比手工调参更可能找到最优解
""")


if __name__ == "__main__":
    main()
