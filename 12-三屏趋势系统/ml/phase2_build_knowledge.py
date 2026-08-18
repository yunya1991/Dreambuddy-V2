"""Phase 2 结果汇总与知识库建立

将Phase 2的所有结果整理成结构化报告，存入闭环管理器，形成初始知识库。
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ml.closed_loop_manager import ClosedLoopManager, HypothesisStatus


def setup_phase2_knowledge():
    """建立Phase 2知识库"""
    mgr = ClosedLoopManager()

    print("=" * 80)
    print("  Phase 2: 建立初始知识库")
    print("=" * 80)
    print()

    # 1. 创建基线假设（如果不存在）
    hypo = mgr.get_hypothesis("HYP-BASELINE-V2")
    if not hypo:
        hypo = mgr.create_hypothesis(
            title="v2增强版MA200策略基线",
            description=
            "EnhancedMA200Strategy v2作为后续所有优化的对比基线。"
            "核心特征：周线MA200抄底、BTC分级做空、斐波那契止盈、小币双牛过滤。"
            "基线锚定：任何新策略必须综合评分>1.0才被采纳。",
            theory_source=
            "MA200牛熊经验法则 + 三重滤网思想 + 斐波那契回调理论 + 最小阻力方向",
            objective="all",
            expected_effect="作为后续所有优化的对比基准",
            expected_improvement=0.0,
            tags=["baseline", "v2"],
        )
        mgr.update_hypothesis_status(hypo.hypo_id, HypothesisStatus.ACCEPTED.value)
        print(f"✅ 基线假设已创建: {hypo.hypo_id}")
    else:
        print(f"ℹ️  基线假设已存在: {hypo.hypo_id}")

    # 2. 创建特征贡献假设
    hypo2 = mgr.get_hypothesis("HYP-FEATURE-IMPORTANCE")
    if not hypo2:
        hypo2 = mgr.create_hypothesis(
            title="v2核心特征贡献度排序",
            description=
            "基于消融实验，v2策略各核心特征的贡献度排序为："
            "周线MA200抄底 > BTC分级做空 > 斐波那契止盈。"
            "后续优化应优先加强高贡献特征，谨慎改动低贡献特征。",
            theory_source="特征消融实验 + 反事实推理",
            objective="all",
            expected_effect="指导后续特征工程的优先级",
            expected_improvement=0.05,
            tags=["feature_importance", "ablation"],
        )
        mgr.update_hypothesis_status(hypo2.hypo_id, HypothesisStatus.PENDING.value)
        print(f"✅ 特征贡献假设已创建: {hypo2.hypo_id}")
    else:
        print(f"ℹ️  特征贡献假设已存在: {hypo2.hypo_id}")

    # 3. 创建四类目的的优化方向假设
    opt_hypos = [
        {
            "title": "DIP_BUY优化：提高牛市抄底精准度",
            "description":
            "当前v2的DIP_BUY胜率仅47.62%，平均收益-0.07%，是四类目的中最弱的。"
            "假设通过加入RSI超卖、MACD底背离、成交量放大等确认特征，"
            "可以将抄底胜率提升至55%+，平均收益提升至2%+。",
            "theory_source": "超卖反转理论 + 量价确认理论 + 多周期共振",
            "objective": "dip_buy",
            "expected_effect": "抄底胜率从47.6%提升至55%+，平均收益转正",
            "expected_improvement": 0.15,
            "tags": ["dip_buy", "optimization", "high_priority"],
        },
        {
            "title": "BEAR_EXIT优化：提高熊市空平收益",
            "description":
            "当前v2的BEAR_EXIT平均收益仅0.27%，虽然Precision不错（0.417），"
            "但空平时机偏晚。假设通过加入下跌衰竭、成交量萎缩、RSI底背离等特征，"
            "可以更早识别熊市底部，将平均收益提升至2%+。",
            "theory_source": "下跌衰竭理论 + 成交量萎缩确认 + 背离理论",
            "objective": "bear_exit",
            "expected_effect": "空平平均收益从0.27%提升至2%+",
            "expected_improvement": 0.10,
            "tags": ["bear_exit", "optimization", "high_priority"],
        },
        {
            "title": "TOP_EXIT优化：提高牛市离场收益",
            "description":
            "当前v2的TOP_EXIT胜率57.14%，平均收益1.63%，表现中等。"
            "假设通过加入超买指标、顶部背离、资金流出等特征，"
            "可以更精准识别顶部，将平均收益提升至3%+。",
            "theory_source": "超买见顶理论 + 顶背离理论 + 资金流向理论",
            "objective": "top_exit",
            "expected_effect": "离场平均收益从1.63%提升至3%+",
            "expected_improvement": 0.08,
            "tags": ["top_exit", "optimization", "medium_priority"],
        },
        {
            "title": "BEAR_SHORT优化：扩大做空机会同时保持胜率",
            "description":
            "当前v2的BEAR_SHORT表现最好（胜率61.22%，平均收益2.63%），"
            "但Recall仅0.026，错过很多做空机会。假设通过优化入场条件，"
            "在保持胜率>55%的前提下，将Recall提升至0.05+。",
            "theory_source": "趋势延续理论 + 分级入场策略",
            "objective": "bear_short",
            "expected_effect": "Recall从0.026提升至0.05+，胜率保持>55%",
            "expected_improvement": 0.05,
            "tags": ["bear_short", "optimization", "medium_priority"],
        },
    ]

    print()
    print("🧠 正在创建优化方向假设...")
    for h in opt_hypos:
        existing = mgr.list_hypotheses(objective=h["objective"])
        found = any(e.title == h["title"] for e in existing)
        if not found:
            new_h = mgr.create_hypothesis(**h)
            print(f"  ✅ {h['title']}")
        else:
            print(f"  ℹ️  {h['title']} (已存在)")

    # 4. 确保v2基线已注册
    print()
    print("📌 确保v2基线已注册...")
    baselines = mgr.list_baselines()
    v2_exists = any(b.version == "v2" for b in baselines)
    if not v2_exists:
        mgr.promote_to_baseline(
            version="v2",
            name="v2增强版MA200",
            description="技术分析最佳版本，三屏趋势系统基线",
            strategy_class="EnhancedMA200Strategy",
            config_path="ml/enhanced_ma200_v2_config.json",
            metrics={
                "sharpe_ratio": 0.600,
                "calmar_ratio": 8.124,
                "max_drawdown": 0.7785,
                "total_return": 6.3247,
                "win_rate": 0.5217,
                "trade_count": 92,
            },
            release_notes="Phase 2基线验证完成，正式确立v2为基线版本",
        )
    else:
        print(f"  ℹ️  v2基线已存在 (共 {len(baselines)} 个版本)")

    print()
    print("=" * 80)
    print("  Phase 2 完成！知识库摘要")
    print("=" * 80)
    print()

    mgr.print_summary()

    print()
    print("=" * 80)
    print("  📊 Phase 2 核心发现")
    print("=" * 80)
    print()
    print("  【整体表现】")
    print("    v2策略BTC：夏普0.600，最大回撤77.85%，总收益632.47%")
    print("    v2策略ETH：夏普0.430，最大回撤65.09%，总收益379.19%")
    print("    v2策略SOL：夏普0.850，最大回撤54.81%，总收益394.65% ✅ 最佳")
    print("    v2策略UNI：夏普0.190，最大回撤62.02%，总收益45.52%")
    print()
    print("  【四类目的基线（BTC）】")
    print("    DIP_BUY  牛市抄底：胜率47.62%，平均收益-0.07%  🔴 最弱，首要优化")
    print("    TOP_EXIT 牛市离场：胜率57.14%，平均收益 1.63%  🟡 中等")
    print("    BEAR_SHORT熊市做空：胜率61.22%，平均收益 2.63%  🟢 最佳")
    print("    BEAR_EXIT 熊市空平：胜率52.08%，平均收益 0.27%  🔴 偏弱")
    print()
    print("  【特征贡献排序（消融实验）】")
    print("    ⭐⭐⭐⭐⭐ 周线MA200抄底：夏普贡献+0.190，收益贡献+330%")
    print("    ⭐⭐⭐      BTC分级做空：夏普贡献+0.030，收益贡献+127%")
    print("    ⭐⭐       斐波那契止盈：夏普贡献+0.020，收益贡献+10.5%")
    print()
    print("  【优化优先级】")
    print("    高：DIP_BUY牛市抄底（胜率低、收益负，提升空间最大）")
    print("    高：BEAR_EXIT熊市空平（收益偏低，改善空平时机）")
    print("    中：TOP_EXIT牛市离场（收益尚可，进一步提高）")
    print("    中：BEAR_SHORT熊市做空（表现最佳，扩大机会）")

if __name__ == "__main__":
    setup_phase2_knowledge()
