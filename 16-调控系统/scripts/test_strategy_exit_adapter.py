#!/usr/bin/env python3
"""
策略离场设计适配层测试

验证不同策略在相同市场环境下的离场评估差异，
确保策略设计原则被正确应用。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from strategy_exit_adapter import (
    get_strategy_exit_design,
    evaluate_exit_rationality,
    STRATEGY_EXIT_DESIGNS,
    ExitDesignPhilosophy,
    MacroExitInfluenceLevel,
)
from technical_exit_adapter import (
    TechnicalExitSignal,
    fuse_macro_technical,
    _calc_simple_technical_signals,
)


def test_strategy_design_overview():
    """测试1：各策略离场设计概览"""
    print("=" * 70)
    print("  测试 1：6 策略离场设计原则概览")
    print("=" * 70)
    print()

    print(f"{'策略':<25} {'哲学':<12} {'宏观影响':<10} {'技术权重':>8} {'宏观权重':>8}")
    print("-" * 70)

    for sid, design in sorted(STRATEGY_EXIT_DESIGNS.items()):
        philo_map = {
            "martingale": "马丁格尔",
            "trend_following": "趋势跟踪",
            "mean_reversion": "均值回归",
            "sentiment": "情绪驱动",
            "fundamental": "基本面",
        }
        influence_map = {
            "dominant": "宏观主导",
            "important": "重要参考",
            "supplementary": "补充参考",
            "minimal": "仅观察",
            "none": "不干预",
        }
        philo = philo_map.get(design.philosophy.value, design.philosophy.value)
        influence = influence_map.get(design.macro_influence_level.value, design.macro_influence_level.value)
        print(f"{design.strategy_name:<25} {philo:<12} {influence:<10} "
              f"{design.technical_signal_weight:>8.0%} {design.macro_signal_weight:>8.0%}")

    print()
    print("✅ 6 个策略的离场设计原则已定义")
    print()


def test_martin_floating_loss():
    """测试2：马丁策略浮亏场景
    
    核心验证：马丁策略浮亏时，宏观建议平仓应该被否决，
    因为浮亏是马丁策略的正常组成部分。
    """
    print("=" * 70)
    print("  测试 2：马丁策略浮亏场景（核心验证点）")
    print("=" * 70)
    print()
    print("场景：BTC 马丁多单，浮亏 12%，加仓 1 次，持仓 6 小时")
    print("      宏观建议：CLOSE（因为趋势向下）")
    print()

    strategy_id = "v15_martin"
    position_info = {
        "pnl_pct": -12.0,
        "hold_hours": 6,
        "addon_count": 1,
        "direction": "LONG",
    }
    macro_analysis = {
        "suggested_action": "close",
        "confidence": 0.7,
        "reduce_fraction": 0.5,
    }
    technical_signals = {
        "confidence": 0.5,
        "p0_triggered": False,
    }

    result = evaluate_exit_rationality(
        strategy_id, position_info, macro_analysis, technical_signals
    )

    print(f"原始宏观建议: {result['original_action'].upper()} (置信度 {result['original_confidence']:.0%})")
    print(f"调整后建议:   {result['adjusted_action'].upper()} (置信度 {result['adjusted_confidence']:.0%})")
    print(f"是否合理:     {'✅ 合理' if result['is_rational'] else '⚠️ 被调整'}")
    print()
    print("调整原因:")
    for reason in result["reasons"]:
        print(f"  • {reason}")
    print()

    # 验证：马丁浮亏不应该建议平仓
    assert not result["is_rational"], "马丁浮亏应该被标记为需要调整"
    assert result["adjusted_action"] == "hold", "马丁浮亏应该调整为持有"
    print("✅ 验证通过：马丁浮亏被正确识别为策略正常设计，不建议平仓")
    print()


def test_martin_golden_window():
    """测试3：马丁黄金窗口期
    
    核心验证：加仓后 12 小时内的黄金窗口期，
    即使宏观看空也不应该建议离场。
    """
    print("=" * 70)
    print("  测试 3：马丁黄金窗口期")
    print("=" * 70)
    print()
    print("场景：ETH 马丁多单，加仓后 3 小时（黄金窗口期内）")
    print("      宏观建议：REDUCE（短期看空）")
    print()

    strategy_id = "v15_martin"
    position_info = {
        "pnl_pct": -5.0,
        "hold_hours": 3,
        "addon_count": 2,
        "direction": "LONG",
    }
    macro_analysis = {
        "suggested_action": "reduce",
        "confidence": 0.6,
        "reduce_fraction": 0.3,
    }
    technical_signals = {
        "confidence": 0.4,
        "p0_triggered": False,
    }

    result = evaluate_exit_rationality(
        strategy_id, position_info, macro_analysis, technical_signals
    )

    print(f"原始宏观建议: {result['original_action'].upper()} (置信度 {result['original_confidence']:.0%})")
    print(f"调整后建议:   {result['adjusted_action'].upper()} (置信度 {result['adjusted_confidence']:.0%})")
    print(f"是否合理:     {'✅ 合理' if result['is_rational'] else '⚠️ 被调整'}")
    print()
    print("调整原因:")
    for reason in result["reasons"]:
        print(f"  • {reason}")
    print()

    assert not result["is_rational"], "黄金窗口期应该被标记为需要调整"
    assert result["adjusted_action"] == "hold", "黄金窗口期应该调整为持有"
    print("✅ 验证通过：马丁黄金窗口期内不建议离场")
    print()


def test_trend_following_tech_exit():
    """测试4：趋势跟踪策略的技术离场
    
    核心验证：三屏趋势系统的技术离场信号权重高，
    宏观建议不能轻易覆盖技术止损。
    """
    print("=" * 70)
    print("  测试 4：趋势跟踪策略技术离场")
    print("=" * 70)
    print()
    print("场景：BTC 三屏趋势多单，技术面触发 ATR 止损")
    print("      宏观建议：HOLD（长期仍看好）")
    print()

    strategy_id = "screen_trend"

    tech_signal = TechnicalExitSignal(
        action="CLOSE",
        urgency="HIGH",
        confidence=0.75,
        reason="ATR 止损触发",
        source_layers={"p0_triggered": True, "p1_triggered": True, "all_signals": []},
    )

    macro_eval = {
        "recommended_action": "HOLD",
        "urgency": "LOW",
        "confidence": 0.55,
        "parameters": {"reduce_fraction": 0.3},
    }

    pos_info = {
        "symbol": "BTC",
        "system": "screen_trend",
        "direction": "LONG",
        "upl_ratio": -8.0,
        "leverage": 3,
    }

    fused = fuse_macro_technical(macro_eval, tech_signal, pos_info, strategy_id)

    print(f"宏观建议:     {macro_eval['recommended_action']} (置信度 {macro_eval['confidence']:.0%})")
    print(f"技术建议:     {tech_signal.action} (置信度 {tech_signal.confidence:.0%})")
    print(f"融合后建议:   {fused['recommended_action']} (置信度 {fused['confidence']:.0%})")
    print(f"融合模式:     {fused['fusion_mode']}")
    print()

    strategy_ctx = fused.get("strategy_context", {})
    print(f"策略哲学:     {strategy_ctx.get('philosophy', 'N/A')}")
    print(f"宏观影响力:   {strategy_ctx.get('macro_influence_level', 'N/A')}")
    print(f"技术权重:     {strategy_ctx.get('technical_weight', 0):.0%}")
    print(f"宏观权重:     {strategy_ctx.get('macro_weight', 0):.0%}")
    print()

    assert fused["recommended_action"] == "CLOSE", "P0 技术止损应该一票否决"
    assert fused["fusion_mode"] == "technical_p0_veto", "应该是 P0 否决模式"
    print("✅ 验证通过：趋势跟踪策略的技术 P0 止损被正确执行，宏观无法覆盖")
    print()


def test_weighted_confidence():
    """测试5：不同策略的置信度权重差异
    
    核心验证：
    - 马丁策略：技术权重 80%，宏观权重 20%
    - Agent B：技术权重 40%，宏观权重 60%
    """
    print("=" * 70)
    print("  测试 5：不同策略的置信度权重差异")
    print("=" * 70)
    print()
    print("场景：相同的宏观(70%)和技术(60%)信号，不同策略")
    print()

    macro_eval = {
        "recommended_action": "REDUCE",
        "urgency": "MEDIUM",
        "confidence": 0.7,
        "parameters": {"reduce_fraction": 0.3},
    }

    tech_signal = TechnicalExitSignal(
        action="HOLD",
        urgency="LOW",
        confidence=0.6,
        reason="无明确技术信号",
        source_layers={"p0_triggered": False, "p1_triggered": False, "all_signals": []},
    )

    strategies = ["v15_martin", "screen_trend", "yijing_bcrm", "agent_b"]

    print(f"{'策略':<20} {'宏观权重':>8} {'技术权重':>8} {'加权后置信度':>14} {'最终动作':>10}")
    print("-" * 70)

    results = {}
    for sid in strategies:
        pos_info = {
            "symbol": "BTC",
            "system": sid,
            "direction": "LONG",
            "upl_ratio": 5.0,
            "leverage": 2,
            "addon_count": 0,
        }

        fused = fuse_macro_technical(macro_eval, tech_signal, pos_info, sid)
        strategy_ctx = fused.get("strategy_context", {})
        macro_w = strategy_ctx.get("macro_weight", 0.5)
        tech_w = strategy_ctx.get("technical_weight", 0.5)
        results[sid] = fused

        design = get_strategy_exit_design(sid)
        print(f"{design.strategy_name:<20} {macro_w:>8.0%} {tech_w:>8.0%} "
              f"{fused['confidence']:>14.0%} {fused['recommended_action']:>10}")

    print()

    # 验证：马丁策略的宏观影响最小，Agent B 的宏观影响最大
    martin_conf = results["v15_martin"]["confidence"]
    agentb_conf = results["agent_b"]["confidence"]
    assert martin_conf < agentb_conf, "马丁策略的加权置信度应该低于 Agent B"
    print("✅ 验证通过：不同策略的权重差异正确体现（马丁宏观权重最低，Agent B 最高）")
    print()


def test_p0_no_override():
    """测试6：P0 硬退出不可被宏观覆盖
    
    核心验证：所有策略的 P0 硬退出都不允许宏观覆盖（默认配置）。
    """
    print("=" * 70)
    print("  测试 6：P0 硬退出不可被宏观覆盖")
    print("=" * 70)
    print()

    tech_signal = TechnicalExitSignal(
        action="CLOSE",
        urgency="CRITICAL",
        confidence=0.95,
        reason="最大亏损触发",
        source_layers={"p0_triggered": True, "p1_triggered": True, "all_signals": []},
    )

    macro_eval = {
        "recommended_action": "HOLD",
        "urgency": "LOW",
        "confidence": 0.85,
        "parameters": {"reduce_fraction": 0.3},
    }

    all_pass = True
    for sid in STRATEGY_EXIT_DESIGNS.keys():
        design = get_strategy_exit_design(sid)
        pos_info = {
            "symbol": "BTC",
            "system": sid,
            "direction": "LONG",
            "upl_ratio": -20.0,
            "leverage": 3,
        }

        fused = fuse_macro_technical(macro_eval, tech_signal, pos_info, sid)

        if fused["recommended_action"] != "CLOSE":
            print(f"❌ {design.strategy_name}: P0 被宏观覆盖了（不应该）")
            all_pass = False
        else:
            print(f"✅ {design.strategy_name}: P0 正确执行，宏观无法覆盖")

    print()
    assert all_pass, "所有策略的 P0 都不应该被宏观覆盖"
    print("✅ 验证通过：所有策略的 P0 硬退出都不允许宏观覆盖")
    print()


def test_max_reduce_fraction():
    """测试7：最大减仓比例限制
    
    核心验证：马丁策略最多只能减仓 30%，
    而 Agent B 可以减仓 70%。
    """
    print("=" * 70)
    print("  测试 7：最大减仓比例限制")
    print("=" * 70)
    print()

    macro_eval = {
        "recommended_action": "REDUCE",
        "urgency": "HIGH",
        "confidence": 0.75,
        "parameters": {"reduce_fraction": 0.6},
    }

    tech_signal = TechnicalExitSignal(
        action="REDUCE",
        urgency="MEDIUM",
        confidence=0.6,
        reason="RSI 超买",
        source_layers={"p0_triggered": False, "p1_triggered": True, "all_signals": []},
    )

    strategies = ["v15_martin", "yijing_bcrm", "agent_b"]

    print(f"{'策略':<20} {'宏观建议减仓':>12} {'技术建议减仓':>12} {'最终减仓比例':>14} {'限制':>10}")
    print("-" * 70)

    for sid in strategies:
        design = get_strategy_exit_design(sid)
        pos_info = {
            "symbol": "BTC",
            "system": sid,
            "direction": "LONG",
            "upl_ratio": 10.0,
            "leverage": 2,
            "addon_count": 0,
        }

        fused = fuse_macro_technical(macro_eval, tech_signal, pos_info, sid)
        final_reduce = fused.get("parameters", {}).get("reduce_fraction", 0)

        print(f"{design.strategy_name:<20} {0.6:>12.0%} {0.3:>12.0%} "
              f"{final_reduce:>14.0%} {design.max_macro_reduce_fraction:>10.0%}")

        assert final_reduce <= design.max_macro_reduce_fraction, \
            f"{design.strategy_name} 的减仓比例超过限制"

    print()
    print("✅ 验证通过：所有策略的减仓比例都不超过各自的限制")
    print()


def main():
    print()
    print("🚀 策略离场设计适配层 - 完整测试套件")
    print()

    all_passed = True
    tests = [
        ("策略设计概览", test_strategy_design_overview),
        ("马丁浮亏场景", test_martin_floating_loss),
        ("马丁黄金窗口期", test_martin_golden_window),
        ("趋势跟踪技术离场", test_trend_following_tech_exit),
        ("权重差异验证", test_weighted_confidence),
        ("P0 不可覆盖", test_p0_no_override),
        ("减仓比例限制", test_max_reduce_fraction),
    ]

    passed_count = 0
    for name, test_func in tests:
        try:
            test_func()
            passed_count += 1
        except AssertionError as e:
            print(f"❌ 测试失败 [{name}]: {e}")
            print()
            all_passed = False
        except Exception as e:
            print(f"💥 测试异常 [{name}]: {e}")
            import traceback
            traceback.print_exc()
            print()
            all_passed = False

    print("=" * 70)
    print(f"  测试结果: {passed_count}/{len(tests)} 通过")
    print("=" * 70)

    if all_passed:
        print()
        print("🎉 所有测试通过！策略离场适配层工作正常。")
        print()
        print("核心设计原则验证：")
        print("  ✅ 马丁策略浮亏是正常设计，不建议平仓")
        print("  ✅ 马丁黄金窗口期内不建议离场")
        print("  ✅ 趋势跟踪以技术面为准，P0 不可覆盖")
        print("  ✅ 不同策略有不同的宏观/技术权重")
        print("  ✅ 各策略有不同的最大减仓比例限制")
        print()
    else:
        print()
        print("⚠️ 部分测试失败，请检查上方错误信息")
        print()

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
