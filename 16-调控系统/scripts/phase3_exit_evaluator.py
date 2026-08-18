#!/usr/bin/env python3
"""
Phase 3 统一 AI 离场评估主脚本 — 决策执行层完整版

整合所有 Phase 2+ 和 Phase 3 功能：
  ✅ A1/A2/A3 深度宏观分析（SKILL 引擎）
  ✅ 真实市场数据（Hyperliquid + CoinGecko）
  ✅ 做梦产物集成（dream_journal / dream_brainstorm）
  ✅ 历史档案集成（Archive Center）
  ✅ LLM Bridge 增强（可选，USE_LLM=1）
  ✅ 实时数据流（可选，USE_REALTIME=1）
  ✅ 技术离场适配器（ClassicExitSystem 简化版）
  ✅ 宏观+技术融合决策引擎
  ✅ AAM 产物双通道投递（秘书邮箱 + 前端产物中心）
  ✅ 建议反馈机制 + 风险控制权限管理
  ✅ 回测验证框架

用法：
  python 16-调控系统/scripts/phase3_exit_evaluator.py
  USE_LLM=1 python 16-调控系统/scripts/phase3_exit_evaluator.py
  DELIVER=1 python 16-调控系统/scripts/phase3_exit_evaluator.py
  BACKTEST=1 python 16-调控系统/scripts/phase3_exit_evaluator.py
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime, timezone

MODULE_DIR = Path(__file__).parent.parent
ARTIFACTS_DIR = MODULE_DIR / "artifacts" / "exit-evaluations"
CORE_DIR = MODULE_DIR / "core"

sys.path.insert(0, str(CORE_DIR))

from unified_position_query import fetch_all_positions, get_position_summary
from skill_engine import SkillEngine

import a1_research_adapter
import a2_first_principles_adapter
import a3_strategy_adapter
import a9_exit_decision
import technical_exit_adapter
import aam_deliverer
import feedback_and_permission
import strategy_exit_adapter
from enhanced_evolution import get_enhanced_evolution
from backtest_framework import (
    generate_simulated_bars, compare_strategies, save_backtest_results,
)

USE_LLM = os.environ.get("USE_LLM", "").lower() in ("1", "true", "yes", "on")
USE_REALTIME = os.environ.get("USE_REALTIME", "").lower() in ("1", "true", "yes", "on")
SHOULD_DELIVER = os.environ.get("DELIVER", "").lower() in ("1", "true", "yes", "on")
RUN_BACKTEST = os.environ.get("BACKTEST", "").lower() in ("1", "true", "yes", "on")
RUN_EVOLUTION = os.environ.get("EVOLUTION", "").lower() in ("1", "true", "yes", "on", RUN_BACKTEST)


def _fetch_market_data(positions: list) -> dict:
    if USE_REALTIME:
        try:
            from realtime_market_stream import get_realtime_snapshot, start_realtime_stream, stop_realtime_stream
            symbols = []
            for p in positions:
                sym = p.get("symbol", "").upper()
                if sym and sym not in symbols:
                    symbols.append(sym)
            if not symbols:
                symbols = ["BTC", "ETH", "SOL"]
            start_realtime_stream(symbols)
            import time
            time.sleep(2)
            snapshot = get_realtime_snapshot(symbols)
            if snapshot:
                stop_realtime_stream()
                return snapshot
        except Exception:
            pass

    from market_data_fetcher import fetch_market_data
    return fetch_market_data(positions)


def _fuse_all_evaluations(macro_evals: list, positions: list, market: dict, a1_result) -> list:
    """融合宏观+技术，生成最终离场建议（增强版进化系统）"""
    research = a1_result.data.get("research_report", {}) if a1_result.data else {}
    market_state = research.get("market_state", {})
    
    evolution = get_enhanced_evolution()

    fused = []
    for i, pos in enumerate(positions):
        macro_eval = macro_evals[i] if i < len(macro_evals) else {}

        tech_signal = technical_exit_adapter._calc_simple_technical_signals(
            pos, market, market_state
        )

        system_name = pos.get("system", "unknown")
        strategy_id = _map_system_to_strategy_id(system_name)

        # 获取进化后的参数
        evolved_params = evolution.get_evolved_params(strategy_id)
        
        fused_eval = technical_exit_adapter.fuse_macro_technical(
            macro_eval, tech_signal,
            position_info=pos,
            strategy_id=strategy_id,
        )
        
        # 置信度门槛检查（使用进化后的参数）
        action = fused_eval.get("recommended_action", "HOLD")
        confidence = fused_eval.get("confidence", 0.5)
        p0_triggered = fused_eval.get("technical_input", {}).get("p0_triggered", False)
        
        if not p0_triggered:
            threshold_close = evolved_params.get("confidence_threshold_close", 0.70)
            threshold_reduce = evolved_params.get("confidence_threshold_reduce", 0.60)
            
            if action == "CLOSE" and confidence < threshold_close:
                fused_eval["recommended_action"] = "OBSERVE"
                fused_eval["confidence_gated"] = True
                fused_eval["gating_reason"] = (
                    f"置信度 {confidence:.0%} 低于平仓门槛 {threshold_close:.0%}，降级为观察"
                )
            elif action == "REDUCE" and confidence < threshold_reduce:
                fused_eval["recommended_action"] = "OBSERVE"
                fused_eval["confidence_gated"] = True
                fused_eval["gating_reason"] = (
                    f"置信度 {confidence:.0%} 低于减仓门槛 {threshold_reduce:.0%}，降级为观察"
                )
            else:
                fused_eval["confidence_gated"] = False
        else:
            fused_eval["confidence_gated"] = False
        
        final_action = fused_eval.get("recommended_action", "HOLD")
        final_urgency = fused_eval.get("urgency", "LOW")
        perm_check = feedback_and_permission.can_auto_execute(system_name, final_action, final_urgency)

        fused_eval["position"] = {
            "symbol": pos.get("symbol", ""),
            "system": system_name,
            "strategy_id": strategy_id,
            "direction": pos.get("direction", ""),
            "size": pos.get("size", 0),
            "entry_price": pos.get("entry_price", 0),
            "unrealized_pnl": pos.get("unrealized_pnl", 0),
            "upl_ratio": pos.get("upl_ratio", 0),
        }
        fused_eval["permission_check"] = perm_check
        fused_eval["evolution_params"] = evolved_params
        
        try:
            decision_id = evolution.record_decision(fused_eval)
            fused_eval["decision_id"] = decision_id
        except Exception:
            fused_eval["decision_id"] = ""

        fused.append(fused_eval)

    return fused


def _map_system_to_strategy_id(system_name: str) -> str:
    """将系统名称映射到策略ID"""
    mapping = {
        "agent_a": "agent_a",
        "agent_b": "agent_b",
        "agent_c": "agent_c",
        "v15_martin": "v15_martin",
        "screen_trend": "screen_trend",
        "yijing_bcrm": "yijing_bcrm",
    }
    return mapping.get(system_name, "agent_a")


def _generate_phase3_report(
    positions_data: dict,
    market: dict,
    a1_result,
    a2_result,
    a3_result,
    a9_result,
    tech_result,
    fused_evaluations: list,
    backtest_results: dict = None,
) -> str:
    """生成 Phase 3 Markdown 报告"""
    lines = []

    lines.append(f"# 离场战略评估报告（Phase 3 完整版）")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"**评估版本**: Phase 3 — 宏观+技术融合决策 + AAM投递")
    lines.append("")

    summary = a9_result.data.get("overall_summary", {}) if a9_result.data else {}
    overall_stance = summary.get("overall_stance", "UNKNOWN")

    fused_stats = _calc_fused_stats(fused_evaluations)

    lines.append("## 一、核心结论")
    lines.append("")
    lines.append(f"- **整体立场**: {overall_stance}")
    lines.append(f"- **总持仓数**: {len(fused_evaluations)}")
    lines.append(f"- **建议平仓**: {fused_stats['close_count']} 个")
    lines.append(f"- **建议减仓**: {fused_stats['reduce_count']} 个")
    lines.append(f"- **建议持有**: {fused_stats['hold_count']} 个")
    lines.append(f"- **建议提止盈**: {fused_stats['raise_tp_count']} 个")
    lines.append("")

    lines.append("## 二、宏观分析摘要")
    lines.append("")
    a1_report = a1_result.data.get("research_report", {}) if a1_result.data else {}
    ms = a1_report.get("market_state", {})
    sig = a1_report.get("signal_sufficiency", {})
    lines.append(f"- **A1 趋势方向**: {ms.get('trend_direction', 'N/A')}")
    lines.append(f"- **A1 信号充分性**: {sig.get('level', 'N/A')}")
    lines.append(f"- **A1 BTC RSI**: {ms.get('rsi_1h', 0):.1f}")

    a2_fp = a2_result.data.get("first_principles_analysis", {}) if a2_result.data else {}
    syn = a2_fp.get("synthesis", {})
    regime = a2_result.data.get("market_regime_classification", {}) if a2_result.data else {}
    lines.append(f"- **A2 阻力最小路径**: {syn.get('least_resistance_path', 'N/A')}")
    lines.append(f"- **A2 路径置信度**: {syn.get('path_confidence', 0):.0%}")
    lines.append(f"- **A2 市场状态**: {regime.get('regime', 'N/A')}")

    a3_sd = a3_result.data.get("strategy_directive", {}) if a3_result.data else {}
    lines.append(f"- **A3 战略方向**: {a3_sd.get('directive_bias', 'N/A')}")
    lines.append(f"- **A3 仓位修正**: {a3_sd.get('position_modifier', 0):.2f}x")

    dream = a1_report.get("dream_insights", {})
    if isinstance(dream, dict) and dream.get("incorporated"):
        lines.append(f"- **🌙 做梦产物**: 已集成（最新 {dream.get('latest_date', 'N/A')}）")

    archives = a1_report.get("archive_findings", [])
    if isinstance(archives, list) and archives:
        lines.append(f"- **📚 历史档案**: {len(archives)} 个相似案例")

    lines.append("")

    lines.append("## 三、技术离场摘要")
    lines.append("")
    tech_summary = tech_result.get("summary", {})
    lines.append(f"- **P0 硬退出触发**: {tech_summary.get('p0_triggered_count', 0)} 个")
    lines.append(f"- **P1 技术信号触发**: {tech_summary.get('p1_triggered_count', 0)} 个")
    lines.append(f"- **技术平仓建议**: {tech_summary.get('close_count', 0)} 个")
    lines.append(f"- **技术减仓建议**: {tech_summary.get('reduce_count', 0)} 个")
    lines.append("")

    lines.append("## 四、策略离场设计原则")
    lines.append("")
    lines.append("每个策略有自己的离场设计哲学，宏观评估尊重策略自身设计，仅在合理边界内提供建议：")
    lines.append("")
    lines.append("| 策略 | 设计哲学 | 宏观影响力 | 技术权重 | 宏观权重 | 关键原则 |")
    lines.append("|------|----------|-----------|---------|---------|---------|")

    from strategy_exit_adapter import get_all_strategy_designs, ExitDesignPhilosophy, MacroExitInfluenceLevel
    all_designs = get_all_strategy_designs()
    for sid, design in sorted(all_designs.items()):
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
        key_principle = design.macro_should_not_intervene[0] if design.macro_should_not_intervene else "—"
        lines.append(
            f"| {design.strategy_name} | {philo} | {influence} | "
            f"{design.technical_signal_weight:.0%} | {design.macro_signal_weight:.0%} | "
            f"{key_principle[:30]}... |"
        )

    lines.append("")
    lines.append("> **核心原则**：宏观离场是「增强」而非「替代」策略原生离场机制。"
                 "马丁策略浮亏是正常设计，不应因浮亏建议平仓；"
                 "趋势跟踪以技术面为准，宏观仅作补充。")
    lines.append("")

    lines.append("## 五、融合决策（逐持仓）")
    lines.append("")
    lines.append("| 系统 | 币种 | 方向 | 宏观建议 | 调整后宏观 | 技术建议 | 融合建议 | 置信度 | 合理性 |")
    lines.append("|------|------|------|----------|-----------|----------|----------|--------|--------|")

    for ev in fused_evaluations:
        pos = ev.get("position", {})
        sys_name = pos.get("system", "")
        symbol = pos.get("symbol", "")
        direction = pos.get("direction", "")
        macro_orig = ev.get("macro_input", {}).get("original_action", "N/A")
        macro_adj = ev.get("macro_input", {}).get("adjusted_action", "N/A")
        tech_act = ev.get("technical_input", {}).get("action", "N/A")
        final_act = ev.get("recommended_action", "N/A")
        conf = ev.get("confidence", 0)
        rational = ev.get("rationality_check", {})
        is_rational = rational.get("is_rational", True) if rational else True
        rational_icon = "✅" if is_rational else "⚠️"
        macro_changed = macro_orig != macro_adj
        macro_display = f"~~{macro_orig}~~ → **{macro_adj}**" if macro_changed else macro_orig
        lines.append(
            f"| {sys_name} | {symbol} | {direction} | {macro_orig} | "
            f"{macro_display} | {tech_act} | **{final_act}** | {conf:.0%} | {rational_icon} |"
        )

    lines.append("")
    lines.append("说明：")
    lines.append("- **调整后宏观**：经过策略合理性检查后的宏观建议（如马丁浮亏不建议平仓）")
    lines.append("- **合理性**：⚠️ 表示原始宏观建议被策略设计原则调整过")
    lines.append("")

    lines.append("## 六、策略设计调整详情")
    lines.append("")
    adjusted_count = 0
    for ev in fused_evaluations:
        rational = ev.get("rationality_check", {})
        if rational and not rational.get("is_rational", True):
            adjusted_count += 1
            pos = ev.get("position", {})
            lines.append(f"### {pos.get('system', '')} / {pos.get('symbol', '')}")
            lines.append("")
            lines.append(f"- **原始建议**: {rational.get('original_action', 'N/A')}")
            lines.append(f"- **调整后建议**: **{rational.get('adjusted_action', 'N/A')}**")
            lines.append(f"- **策略哲学**: {rational.get('philosophy', 'N/A')}")
            lines.append(f"- **调整原因**:")
            for reason in rational.get("reasons", []):
                lines.append(f"  - {reason}")
            lines.append("")

    if adjusted_count == 0:
        lines.append("所有宏观建议均通过策略合理性检查，无需调整。")
        lines.append("")

    lines.append("## 七、权限与执行说明")
    lines.append("")
    perm_config = feedback_and_permission.load_permission_config()
    lines.append("| 系统 | 权限等级 | 自动执行阈值 | 最大减仓比例 |")
    lines.append("|------|----------|------------|------------|")
    for sys_name, perm in perm_config.get("systems", {}).items():
        lines.append(f"| {sys_name} | {perm.get('permission_level', 'N/A')} | {perm.get('auto_execute_urgency', 'N/A')} | {perm.get('max_auto_reduce_pct', 0):.0%} |")
    lines.append("")
    lines.append("> 说明：当前为建议制，所有建议需人工确认后执行。"
                 "如需自动执行，请在 `config/permission_config.json` 中调整权限等级。")
    lines.append("")

    if backtest_results:
        lines.append("## 八、回测验证摘要")
        lines.append("")
        baseline = backtest_results.get("baseline")
        macro = backtest_results.get("macro_enhanced")
        if baseline and macro:
            lines.append(f"- **纯技术离场**: 胜率 {baseline.win_rate:.1%}, 收益 {baseline.total_return_pct:+.2f}%, 回撤 {baseline.max_drawdown_pct:.2f}%")
            lines.append(f"- **宏观+技术融合**: 胜率 {macro.win_rate:.1%}, 收益 {macro.total_return_pct:+.2f}%, 回撤 {macro.max_drawdown_pct:.2f}%")
            ret_diff = macro.total_return_pct - baseline.total_return_pct
            lines.append(f"- **效果**: {'宏观胜出' if ret_diff > 0 else '技术胜出'} (收益差 {ret_diff:+.2f}%)")
        lines.append("")

    lines.append("## 九、免责声明")
    lines.append("")
    lines.append("- 本报告仅供参考，不构成投资建议")
    lines.append("- 宏观评估为战略级别，各系统技术离场仍为第一道防线")
    lines.append("- 建议制模式，不自动执行任何交易操作")
    lines.append("- 投资有风险，入市需谨慎")

    return "\n".join(lines)


def _calc_fused_stats(evaluations: list) -> dict:
    close_count = sum(1 for e in evaluations if e.get("recommended_action") == "CLOSE")
    reduce_count = sum(1 for e in evaluations if e.get("recommended_action") == "REDUCE")
    hold_count = sum(1 for e in evaluations if e.get("recommended_action") == "HOLD")
    observe_count = sum(1 for e in evaluations if e.get("recommended_action") == "OBSERVE")
    raise_tp_count = sum(1 for e in evaluations if e.get("recommended_action") == "RAISE_TP")
    gated_count = sum(1 for e in evaluations if e.get("confidence_gated"))
    auto_count = sum(1 for e in evaluations if e.get("permission_check", {}).get("can_execute"))
    return {
        "close_count": close_count,
        "reduce_count": reduce_count,
        "hold_count": hold_count,
        "observe_count": observe_count,
        "raise_tp_count": raise_tp_count,
        "gated_count": gated_count,
        "auto_executable_count": auto_count,
    }


def main():
    print("=" * 70)
    print("  Phase 3 — 统一 AI 离场评估系统（决策执行层完整版）")
    print("=" * 70)
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  LLM增强: {'启用' if USE_LLM else '未启用'}")
    print(f"  实时数据: {'启用' if USE_REALTIME else 'REST模式'}")
    print(f"  AAM投递: {'启用' if SHOULD_DELIVER else '本地产物'}")
    print(f"  回测验证: {'启用' if RUN_BACKTEST else '跳过'}")
    print("=" * 70)

    engine = SkillEngine()

    print("\n[步骤 1/9] 查询聚合持仓...")
    positions_data = fetch_all_positions()
    all_positions = positions_data.get("all_positions", [])
    print(f"  → 共 {len(all_positions)} 个持仓，{positions_data.get('total_systems', 0)} 个系统")
    sys_status = positions_data.get("system_status", {})
    for sys_name, status in sys_status.items():
        print(f"    · {sys_name}: {status}")

    print("\n[步骤 2/9] 获取市场数据...")
    market = _fetch_market_data(all_positions)
    btc_price = market.get("BTC", {}).get("current_price", 0)
    btc_change = market.get("BTC", {}).get("change_24h_pct", 0)
    print(f"  → BTC: ${btc_price:,.2f} ({btc_change:+.2f}%)")
    print(f"  → 数据来源: {market.get('BTC', {}).get('source', 'unknown')}")

    print("\n[步骤 3/9] A1 深度调研（dream-strategy-research）...")
    a1_result = engine.execute("dream-strategy-research", {
        "market": market,
        "positions": all_positions,
        "use_llm": USE_LLM,
    })
    a1_report = a1_result.data.get("research_report", {}) if a1_result.data else {}
    ms = a1_report.get("market_state", {})
    sig = a1_report.get("signal_sufficiency", {})
    print(f"  → 趋势方向: {ms.get('trend_direction', 'N/A')}")
    print(f"  → 信号充分性: {sig.get('level', 'N/A')}")
    print(f"  → BTC RSI: {ms.get('rsi_1h', 0):.1f}")

    dream = a1_report.get("dream_insights", {})
    if isinstance(dream, dict) and dream.get("incorporated"):
        print(f"  → 🌙 做梦产物: 已集成 (最新 {dream.get('latest_date', 'N/A')})")
    else:
        reason = dream.get("note", dream.get("reason", "未找到")) if isinstance(dream, dict) else "无"
        print(f"  → 🌙 做梦产物: 未集成 ({reason})")

    archives = a1_report.get("archive_findings", [])
    if isinstance(archives, list) and archives:
        print(f"  → 📚 历史档案: {len(archives)} 个相似案例")

    llm_enh = a1_report.get("llm_enhancement")
    if isinstance(llm_enh, dict) and llm_enh.get("used"):
        fb = " (规则降级)" if llm_enh.get("fallback") else ""
        print(f"  → 🤖 LLM增强: 已启用{fb}")

    print("\n[步骤 4/9] A2 第一性原理分析（dream-first-principles）...")
    a2_result = engine.execute("dream-first-principles", {
        "market": market,
        "a1_result": a1_result.data,
        "positions": all_positions,
        "use_llm": USE_LLM,
    })
    fp = a2_result.data.get("first_principles_analysis", {}) if a2_result.data else {}
    syn = fp.get("synthesis", {})
    regime = a2_result.data.get("market_regime_classification", {}) if a2_result.data else {}
    print(f"  → 阻力最小路径: {syn.get('least_resistance_path', 'N/A')}")
    print(f"  → 路径置信度: {syn.get('path_confidence', 0):.2f}")
    print(f"  → 市场状态: {regime.get('regime', 'N/A')}")

    llm_enh2 = a2_result.data.get("llm_enhancement") if a2_result.data else None
    if isinstance(llm_enh2, dict) and llm_enh2.get("used"):
        fb = " (规则降级)" if llm_enh2.get("fallback") else ""
        print(f"  → 🤖 LLM增强: 已启用{fb}")

    print("\n[步骤 5/9] A3 战略合成（dream-strategy-designer）...")
    a3_result = engine.execute("dream-strategy-designer", {
        "a1_result": a1_result.data,
        "a2_result": a2_result.data,
        "positions": all_positions,
        "market": market,
        "use_llm": USE_LLM,
    })
    sd = a3_result.data.get("strategy_directive", {}) if a3_result.data else {}
    print(f"  → 战略方向: {sd.get('directive_bias', 'N/A')}")
    print(f"  → 仓位修正: {sd.get('position_modifier', 0):.2f}x")
    print(f"  → 杠杆上限: {sd.get('leverage_cap', 1)}x")

    llm_enh3 = a3_result.data.get("llm_enhancement") if a3_result.data else None
    if isinstance(llm_enh3, dict) and llm_enh3.get("used"):
        fb = " (规则降级)" if llm_enh3.get("fallback") else ""
        print(f"  → 🤖 LLM增强: 已启用{fb}")

    print("\n[步骤 6/9] 技术离场分析（technical-exit-adapter）...")
    tech_result = technical_exit_adapter.technical_exit_handler({
        "positions": all_positions,
        "market": market,
        "a1_result": a1_result.data,
    }, engine)
    tech_summary = tech_result.get("summary", {})
    print(f"  → P0硬退出触发: {tech_summary.get('p0_triggered_count', 0)} 个")
    print(f"  → P1技术信号: {tech_summary.get('p1_triggered_count', 0)} 个")
    print(f"  → 技术平仓: {tech_summary.get('close_count', 0)} 个")
    print(f"  → 技术减仓: {tech_summary.get('reduce_count', 0)} 个")

    print("\n[步骤 7/9] A9 宏观离场决策 + 宏观技术融合...")
    a9_result = engine.execute("dream-exit-skill-v2", {
        "positions": all_positions,
        "a1_result": a1_result.data,
        "a2_result": a2_result.data,
        "a3_result": a3_result.data,
        "market": market,
    })
    a9_evals = a9_result.data.get("exit_evaluations", []) if a9_result.data else []

    fused_evals = _fuse_all_evaluations(a9_evals, all_positions, market, a1_result)
    fused_stats = _calc_fused_stats(fused_evals)
    print(f"  → 融合后建议: CLOSE={fused_stats['close_count']}, "
          f"REDUCE={fused_stats['reduce_count']}, "
          f"HOLD={fused_stats['hold_count']}, "
          f"OBSERVE={fused_stats['observe_count']}, "
          f"RAISE_TP={fused_stats['raise_tp_count']}")
    print(f"  → 置信度门槛拦截: {fused_stats['gated_count']} 个（降级为观察）")
    print(f"  → 可自动执行: {fused_stats['auto_executable_count']} 个")

    # ==========================================
    # 进化闭环
    # ==========================================
    evolution = get_enhanced_evolution()
    evolution_summary = evolution.get_summary()
    print(f"\n  📈 进化系统状态:")
    print(f"    总决策: {evolution_summary.get('total_decisions', 0)}")
    print(f"    已评估: {evolution_summary.get('total_evaluated', 0)}")
    print(f"    整体准确率: {evolution_summary.get('overall_accuracy', 0):.1%}")
    print(f"    已采纳提议: {evolution_summary.get('adopted_proposals', 0)}")
    print(f"    策略数: {evolution_summary.get('strategies', 0)}")

    backtest_results = None
    evolution_cycle_report = None
    if RUN_BACKTEST:
        print("\n[步骤 8/11] 回测验证...")
        bars = generate_simulated_bars(start_price=btc_price or 60000, num_bars=300, seed=42)
        backtest_results_map = compare_strategies(bars, leverage=1.0)
        backtest_results = backtest_results_map
        report_path = save_backtest_results(backtest_results_map, bars)
        baseline = backtest_results_map.get("baseline")
        macro = backtest_results_map.get("macro_enhanced")
        print(f"  → 纯技术: 胜率{baseline.win_rate:.1%}, 收益{baseline.total_return_pct:+.2f}%")
        print(f"  → 宏观+技术: 胜率{macro.win_rate:.1%}, 收益{macro.total_return_pct:+.2f}%")
        print(f"  → 回测报告: {report_path}")
    else:
        print("\n[步骤 8/11] 回测验证: 跳过（设置 BACKTEST=1 启用）")
    
    if RUN_EVOLUTION:
        print("\n[步骤 9/11] 三层进化闭环...")
        print(f"  Layer 1: A8 理论实践验证...")
        a8_result = evolution.run_a8_inspection()
        a8_contradictions = len(a8_result.get("contradictions", []))
        a8_proposals = len(a8_result.get("evolution_proposals", []))
        print(f"    → 发现矛盾: {a8_contradictions} 个, 生成提议: {a8_proposals} 个")
        
        print(f"  Layer 2: 做梦部潜意识分析...")
        dream_result = evolution.run_dream_analysis()
        dream_proposals = len(dream_result.get("evolution_proposals", []))
        print(f"    → 生成提议: {dream_proposals} 个")
        
        print(f"  Layer 3: 数据驱动调优...")
        dd_count = 0
        for sid in ["v15_martin", "screen_trend", "yijing_bcrm", "agent_a", "agent_b", "agent_c"]:
            dd = evolution.propose_data_driven_adjustment(sid, min_samples=3)
            if dd:
                dd_count += 1
        print(f"    → 数据驱动提议: {dd_count} 个")
        
        print(f"\n  回测验证 + 采纳...")
        cycle_report = evolution.run_full_evolution_cycle(min_samples=3, run_backtest=True)
        evolution_cycle_report = cycle_report
        print(f"    → 总提议: {cycle_report.get('proposals_generated', 0)} 个")
        print(f"    → 回测验证: {cycle_report.get('proposals_backtested', 0)} 个")
        print(f"    → 采纳: {cycle_report.get('proposals_adopted', 0)} 个")
        
        layer_stats = evolution_summary.get("layer_stats", {})
        print(f"\n  各进化层统计:")
        for layer, stats in layer_stats.items():
            layer_name = {
                "a8_theory_practice": "A8理论实践",
                "dream_oneirology": "做梦部",
                "data_driven": "数据驱动",
            }.get(layer, layer)
            print(f"    {layer_name}: 提议{stats.get('proposed',0)} 采纳{stats.get('adopted',0)} 拒绝{stats.get('rejected',0)}")
    else:
        print("\n[步骤 9/11] 进化闭环: 跳过（设置 EVOLUTION=1 或 BACKTEST=1 启用）")

    print("\n[步骤 10/11] 生成产物...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    evaluation_id = f"phase3_{timestamp}"

    report = _generate_phase3_report(
        positions_data, market, a1_result, a2_result, a3_result,
        a9_result, tech_result, fused_evals, backtest_results
    )

    full_data = {
        "version": "3.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "phase3",
        "positions_overview": {
            "total_systems": positions_data.get("total_systems", 0),
            "total_positions": len(all_positions),
            "system_status": positions_data.get("system_status", {}),
        },
        "market_snapshot": market,
        "a1_research": a1_result.data,
        "a2_first_principles": a2_result.data,
        "a3_strategy": a3_result.data,
        "a9_macro_exit": a9_result.data,
        "technical_exit": tech_result,
        "fused_evaluations": fused_evals,
        "fused_summary": fused_stats,
        "permission_config": feedback_and_permission.load_permission_config(),
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACTS_DIR / f"phase3_exit_evaluation_{timestamp}.json"
    md_path = ARTIFACTS_DIR / f"phase3_exit_evaluation_{timestamp}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_data, f, ensure_ascii=False, indent=2, default=str)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"  → JSON: {json_path}")
    print(f"  → Markdown: {md_path}")

    if SHOULD_DELIVER:
        print("\n[AAM投递] 双通道投递中...")
        delivery_result = aam_deliverer.deliver_exit_evaluation(
            markdown_content=report,
            json_data=full_data,
            evaluation_id=evaluation_id,
        )
        print(f"  → 投递成功: {delivery_result.success}")
        for ch, ok in delivery_result.channels.items():
            status = "✅" if ok else "❌"
            print(f"    · {ch}: {status}")
        if delivery_result.index_updated:
            print(f"  → Index 更新: ✅")
        if delivery_result.errors:
            for err in delivery_result.errors:
                print(f"  → 错误: {err}")
    else:
        print("\n[AAM投递] 跳过（设置 DELIVER=1 启用双通道投递）")

    print("\n" + "=" * 70)
    print("  ✅ Phase 3 评估完成！")
    print("=" * 70)
    print(f"\n  核心结论:")
    overall = a9_result.data.get("overall_summary", {}).get("overall_stance", "UNKNOWN") if a9_result.data else "UNKNOWN"
    print(f"    整体立场: {overall}")
    print(f"    持仓总数: {len(fused_evals)}")
    print(f"    建议平仓: {fused_stats['close_count']} 个")
    print(f"    建议减仓: {fused_stats['reduce_count']} 个")
    print(f"    可自动执行: {fused_stats['auto_executable_count']} 个")
    print(f"\n  产物文件:")
    print(f"    {json_path}")
    print(f"    {md_path}")


if __name__ == "__main__":
    main()
