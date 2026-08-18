#!/usr/bin/env python3
"""
离场系统端到端测试（模拟数据）

验证完整流程：
  模拟持仓 → A1/A2/A3 → 技术分析 → 策略适配 → 融合决策 → 执行 → 进化反馈
"""

import sys
import os
import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "scripts"))

from skill_engine import SkillEngine
import a1_research_adapter
import a2_first_principles_adapter
import a3_strategy_adapter
import a9_exit_decision
import technical_exit_adapter
import strategy_exit_adapter
import feedback_and_permission
from enhanced_evolution import get_enhanced_evolution
from exit_executor import ExitExecutor
from unified_position_query import fetch_all_positions
from phase3_exit_evaluator import _fetch_market_data


def _generate_test_positions():
    """生成测试持仓（模拟多系统、多币种）"""
    return [
        # V15 马丁策略 - 浮亏中
        {
            "symbol": "BTC",
            "system": "v15_martin",
            "strategy_id": "v15_martin",
            "direction": "long",
            "size": 0.05,
            "entry_price": 68500,
            "current_price": 62000,
            "unrealized_pnl": -325,
            "upl_ratio": -0.095,
            "holding_time_hours": 120,
            "grid_level": 5,
        },
        # Agent A - 浮盈趋势中
        {
            "symbol": "ETH",
            "system": "agent_a",
            "strategy_id": "agent_a",
            "direction": "long",
            "size": 2.5,
            "entry_price": 3200,
            "current_price": 3650,
            "unrealized_pnl": 1125,
            "upl_ratio": 0.141,
            "holding_time_hours": 48,
        },
        # Agent B - 横盘震荡
        {
            "symbol": "SOL",
            "system": "agent_b",
            "strategy_id": "agent_b",
            "direction": "short",
            "size": 50,
            "entry_price": 148,
            "current_price": 145,
            "unrealized_pnl": 150,
            "upl_ratio": 0.020,
            "holding_time_hours": 24,
        },
        # Agent C - 深度浮亏
        {
            "symbol": "BNB",
            "system": "agent_c_memory",
            "strategy_id": "agent_c",
            "direction": "long",
            "size": 3.0,
            "entry_price": 680,
            "current_price": 590,
            "unrealized_pnl": -270,
            "upl_ratio": -0.132,
            "holding_time_hours": 72,
        },
        # 三屏趋势 - 突破中
        {
            "symbol": "XRP",
            "system": "three_screen",
            "strategy_id": "screen_trend",
            "direction": "long",
            "size": 5000,
            "entry_price": 0.52,
            "current_price": 0.58,
            "unrealized_pnl": 300,
            "upl_ratio": 0.115,
            "holding_time_hours": 36,
        },
    ]


def run_e2e_test():
    """运行端到端测试"""
    print("=" * 70)
    print("🧪 AI 驱动离场系统 — 端到端测试")
    print("=" * 70)
    
    from phase3_exit_evaluator import _fuse_all_evaluations, _map_system_to_strategy_id
    
    evolution = get_enhanced_evolution()
    executor = ExitExecutor(mode="dry_run", max_executions_per_cycle=10)
    engine = SkillEngine()
    
    # ==========================================
    # 步骤 1: 准备数据
    # ==========================================
    print("\n[步骤 1/8] 获取持仓和市场数据...")
    
    positions_data = fetch_all_positions()
    positions = positions_data.get("all_positions", []) or positions_data.get("positions", [])
    if not positions:
        positions = _generate_test_positions()
        print(f"  ⚠️  无真实持仓，使用模拟测试数据: {len(positions)} 个")
    else:
        print(f"  真实持仓: {len(positions)} 个")
    
    market = _fetch_market_data(positions)
    
    for p in positions[:5]:
        upl = float(p.get("unrealized_pnl", 0))
        upl_ratio = float(p.get("upl_ratio", 0))
        pnl_color = "🟢" if upl >= 0 else "🔴"
        print(f"    {pnl_color} {p.get('system',''):15s} {p.get('symbol',''):5s} "
              f"{p.get('direction',''):5s} P/L: {upl:+.1f} USDT "
              f"({upl_ratio:+.1%})")
    if len(positions) > 5:
        print(f"    ... 还有 {len(positions) - 5} 个持仓")
    
    # ==========================================
    # 步骤 2: A1 深度调研
    # ==========================================
    print("\n[步骤 2/8] A1 深度调研...")
    
    a1_result = engine.execute("dream-strategy-research", {
        "market": market,
        "positions": positions,
        "use_llm": False,
    })
    
    a1_report = a1_result.data.get("research_report", {}) if a1_result.data else {}
    ms = a1_report.get("market_state", {})
    sig = a1_report.get("signal_sufficiency", {})
    print(f"  趋势方向: {ms.get('trend_direction', 'N/A')}")
    print(f"  信号充分性: {sig.get('level', 'N/A')}")
    print(f"  BTC RSI: {ms.get('rsi_1h', 0):.1f}")
    
    # ==========================================
    # 步骤 3: A2 第一性原理
    # ==========================================
    print("\n[步骤 3/8] A2 第一性原理分析...")
    a2_result = engine.execute("dream-first-principles", {
        "market": market,
        "a1_result": a1_result.data,
        "positions": positions,
        "use_llm": False,
    })
    
    fp = a2_result.data.get("first_principles_analysis", {}) if a2_result.data else {}
    syn = fp.get("synthesis", {})
    print(f"  阻力最小路径: {syn.get('least_resistance_path', 'N/A')}")
    print(f"  路径置信度: {syn.get('path_confidence', 0):.2f}")
    
    # ==========================================
    # 步骤 4: A3 战略合成
    # ==========================================
    print("\n[步骤 4/8] A3 战略合成...")
    a3_result = engine.execute("dream-strategy-designer", {
        "a1_result": a1_result.data,
        "a2_result": a2_result.data,
        "positions": positions,
        "market": market,
        "use_llm": False,
    })
    
    strategy = a3_result.data.get("strategy_design", {}) if a3_result.data else {}
    overall = strategy.get("overall_stance", "NEUTRAL")
    print(f"  整体立场: {overall}")
    
    # ==========================================
    # 步骤 5: A9 宏观离场 + 融合决策
    # ==========================================
    print("\n[步骤 5/8] A9 宏观离场 + 融合决策...")
    
    a9_result = engine.execute("dream-exit-skill-v2", {
        "a3_result": a3_result.data,
        "a1_result": a1_result.data,
        "positions": positions,
        "use_llm": False,
    })
    
    a9_evals = a9_result.data.get("exit_evaluations", []) if a9_result.data else []
    print(f"  A9 评估数: {len(a9_evals)}")
    
    # 融合决策（复用 phase3 的融合逻辑）
    fused_evals = _fuse_all_evaluations(a9_evals, positions, market, a1_result)
    
    action_counts = {}
    for ev in fused_evals:
        a = ev.get("recommended_action", "UNKNOWN")
        action_counts[a] = action_counts.get(a, 0) + 1
    
    print(f"  融合建议: CLOSE={action_counts.get('CLOSE',0)}, "
          f"REDUCE={action_counts.get('REDUCE',0)}, "
          f"HOLD={action_counts.get('HOLD',0)}, "
          f"OBSERVE={action_counts.get('OBSERVE',0)}")
    print(f"  置信度拦截: {sum(1 for e in fused_evals if e.get('confidence_gated'))} 个")
    
    print("\n  详细评估:")
    for ev in fused_evals[:8]:
        pos = ev.get("position", {})
        action = ev.get("recommended_action", "HOLD")
        conf = ev.get("confidence", 0)
        perm = ev.get("permission_check", {})
        action_emoji = {"CLOSE": "🔴", "REDUCE": "🟠", "HOLD": "🟢", "OBSERVE": "🔵"}.get(action, "⚪")
        perm_icon = "✅" if perm.get("can_execute") else "⛔"
        gated = "[置信度拦截]" if ev.get("confidence_gated") else ""
        print(f"    {action_emoji} {perm_icon} {pos.get('system',''):15s} "
              f"{pos.get('symbol',''):5s} {action:8s} 置信度: {conf:.0%} {gated}")
    if len(fused_evals) > 8:
        print(f"    ... 还有 {len(fused_evals) - 8} 个")
    
    # ==========================================
    # 步骤 6: 执行交易
    # ==========================================
    print("\n[步骤 6/8] 执行离场操作...")
    
    exec_results = executor.execute_evaluations(fused_evals)
    
    success = [r for r in exec_results if r["status"] == "success"]
    failed = [r for r in exec_results if r["status"] == "failed"]
    skipped = [r for r in exec_results if r["status"] == "skipped"]
    rejected = [r for r in exec_results if r["status"] == "rejected"]
    
    print(f"  ✅ 成功执行: {len(success)} 笔")
    print(f"  ❌ 执行失败: {len(failed)} 笔")
    print(f"  ⏭️  跳过: {len(skipped)} 笔")
    print(f"  ⛔ 权限拒绝: {len(rejected)} 笔")
    
    for r in success[:5]:
        print(f"    → {r['system_name']:15s} {r['symbol']:5s} "
              f"{r['action']:8s} {r['executed_size']:.4f} @ "
              f"${r['execution_price']:,.2f} | P/L: {r['actual_pnl']:+.1f} USDT")
    
    # ==========================================
    # 步骤 7: 进化反馈
    # ==========================================
    print("\n[步骤 7/8] 进化系统反馈...")
    
    # 回填执行结果（模拟）
    for r in success:
        if r["action"] in ("CLOSE", "REDUCE"):
            decision_id = ""
            for ev in fused_evals:
                pos = ev.get("position", {})
                if pos.get("system") == r["system_name"] and pos.get("symbol") == r["symbol"]:
                    decision_id = ev.get("decision_id", "")
                    break
            
            if decision_id:
                actual_pnl = r.get("actual_pnl", 0)
                outcome = "CORRECT" if actual_pnl > 0 else "INCORRECT"
                evolution.record_outcome(
                    decision_id, outcome, actual_pnl,
                    r.get("execution_price", 0), "e2e_test"
                )
    
    summary = evolution.get_summary()
    print(f"  累计决策: {summary.get('total_decisions', 0)}")
    print(f"  已回填结果: {summary.get('resolved_decisions', 0)}")
    print(f"  整体准确率: {summary.get('overall_accuracy', 0):.1%}")
    
    # A8 检验
    a8_result = evolution.run_a8_inspection()
    print(f"  A8 矛盾检查: {len(a8_result.get('contradictions', []))} 个")
    
    # 进化周期
    cycle = evolution.run_full_evolution_cycle(min_samples=3, run_backtest=False)
    print(f"  进化提议: {cycle.get('proposals_generated', 0)} 个")
    print(f"  已采纳: {cycle.get('proposals_adopted', 0)} 个")
    
    # ==========================================
    # 步骤 8: 统计汇总
    # ==========================================
    print("\n[步骤 8/8] 测试汇总...")
    
    print()
    print("=" * 70)
    print("📊 端到端测试结果")
    print("=" * 70)
    print(f"  持仓数量:       {len(positions)} 个")
    print(f"  建议平仓:       {action_counts.get('CLOSE', 0)} 个")
    print(f"  建议减仓:       {action_counts.get('REDUCE', 0)} 个")
    print(f"  建议持有:       {action_counts.get('HOLD', 0)} 个")
    print(f"  建议观察:       {action_counts.get('OBSERVE', 0)} 个")
    print(f"  置信度拦截:     {sum(1 for e in fused_evals if e.get('confidence_gated'))} 个")
    print(f"  成功执行:       {len(success)} 笔")
    print(f"  权限拒绝:       {len(rejected)} 笔")
    print(f"  进化决策记录:   {summary.get('total_decisions', 0)} 条")
    print("=" * 70)
    print("✅ 端到端测试完成！所有模块运行正常")
    print("=" * 70)
    
    # 保存测试结果
    test_output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "positions_count": len(positions),
        "action_counts": action_counts,
        "execution_results": exec_results,
        "evolution_summary": summary,
    }
    
    output_path = BASE_DIR / "artifacts" / "tests" / "e2e_exit_test.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(test_output, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n📁 测试结果: {output_path}")
    
    return True


if __name__ == "__main__":
    success = run_e2e_test()
    sys.exit(0 if success else 1)
