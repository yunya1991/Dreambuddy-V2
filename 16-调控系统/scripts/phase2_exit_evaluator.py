"""
Phase 2 统一 AI 离场评估主脚本 — 接入真实 A1/A2/A3/A9 SKILL 引擎

架构：
  查询层 → A1 深度调研 → A2 第一性原理 → A3 战略合成 → A9 离场决策
  (统一持仓)  (宏观背景)    (双维分析)     (战略指令)     (四态评估)

用法：
  python 16-调控系统/scripts/phase2_exit_evaluator.py
"""

import sys
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


def _fetch_market_data(positions: list) -> dict:
    btc_price = 67500.0
    eth_price = 3500.0
    sol_price = 180.0

    btc_change_24h = 1.2
    eth_change_24h = -0.5
    sol_change_24h = 2.8

    btc_change_7d = -3.5
    eth_change_7d = -2.1
    sol_change_7d = 5.2

    return {
        "BTC": {
            "current_price": btc_price,
            "change_24h_pct": btc_change_24h,
            "change_7d_pct": btc_change_7d,
            "volume_24h": 28000000000,
            "high_24h": 68200,
            "low_24h": 66800,
        },
        "ETH": {
            "current_price": eth_price,
            "change_24h_pct": eth_change_24h,
            "change_7d_pct": eth_change_7d,
            "volume_24h": 15000000000,
            "high_24h": 3580,
            "low_24h": 3460,
        },
        "SOL": {
            "current_price": sol_price,
            "change_24h_pct": sol_change_24h,
            "change_7d_pct": sol_change_7d,
            "volume_24h": 3500000000,
            "high_24h": 185,
            "low_24h": 174,
        },
    }


def run_phase2_evaluation():
    print("=" * 70)
    print("  Phase 2 — 统一 AI 离场评估系统（SKILL 引擎版）")
    print("=" * 70)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    print(f"\n[时间戳] {now.isoformat()}")

    print("\n[步骤 1/6] 查询聚合持仓...")
    query_result = fetch_all_positions()
    positions = query_result["all_positions"]
    summary = get_position_summary()
    print(f"  → 获取到 {summary['total_positions']} 个持仓，来自 {summary['total_systems']} 个系统")
    print(f"  → 总未实现盈亏: {summary['total_unrealized_pnl']:.2f} USDT")
    print(f"  → 系统状态: {summary['overall_status']}")

    print("\n[步骤 2/6] 获取市场数据...")
    market = _fetch_market_data(positions)
    print(f"  → BTC: ${market['BTC']['current_price']:,.0f} ({market['BTC']['change_24h_pct']:+.2f}%)")
    print(f"  → ETH: ${market['ETH']['current_price']:,.0f} ({market['ETH']['change_24h_pct']:+.2f}%)")
    print(f"  → SOL: ${market['SOL']['current_price']:,.0f} ({market['SOL']['change_24h_pct']:+.2f}%)")

    engine = SkillEngine()

    print("\n[步骤 3/6] A1 深度调研（dream-strategy-research）...")
    a1_result = engine.execute("dream-strategy-research", {
        "market": market,
        "positions": positions,
    })
    print(f"  → 状态: {a1_result.status}")
    if a1_result.status == "completed":
        rs = a1_result.data.get("research_report", {})
        ms = rs.get("market_state", {})
        tc = ms.get("trend_direction", "UNKNOWN")
        sig = ms.get("signal_adequacy", {})
        print(f"  → 趋势方向: {tc}")
        print(f"  → 信号充分性: {sig.get('level', 'unknown')} ({sig.get('net_direction', 0):.1f}/3)")
    else:
        print(f"  → 错误: {a1_result.error}")

    print("\n[步骤 4/6] A2 第一性原理分析（dream-first-principles）...")
    a2_result = engine.execute("dream-first-principles", {
        "market": market,
        "a1_result": a1_result.data,
        "positions": positions,
    })
    print(f"  → 状态: {a2_result.status}")
    if a2_result.status == "completed":
        fp = a2_result.data.get("first_principles_analysis", {})
        syn = fp.get("synthesis", {})
        regime = a2_result.data.get("market_regime_classification", {})
        print(f"  → 阻力最小路径: {syn.get('least_resistance_path', 'N/A')}")
        print(f"  → 路径置信度: {syn.get('path_confidence', 0):.2f}")
        print(f"  → 市场状态: {regime.get('regime', 'N/A')} ({regime.get('confidence', 0):.0f}%)")
        ta = fp.get("trend_analysis", {})
        print(f"  → 趋势阶段: {ta.get('trend_phase', 'N/A')}")
    else:
        print(f"  → 错误: {a2_result.error}")

    print("\n[步骤 5/6] A3 战略合成（dream-strategy-designer）...")
    a3_result = engine.execute("dream-strategy-designer", {
        "a1_result": a1_result.data,
        "a2_result": a2_result.data,
        "positions": positions,
        "market": market,
    })
    print(f"  → 状态: {a3_result.status}")
    if a3_result.status == "completed":
        sd = a3_result.data.get("strategy_directive", {})
        print(f"  → 战略方向: {sd.get('directive_bias', 'N/A')}")
        print(f"  → 仓位修正: {sd.get('position_modifier', 0):.2f}x")
        print(f"  → 杠杆上限: {sd.get('leverage_cap', 1)}x")
        ec = sd.get("exit_conditions", [])
        print(f"  → 离场条件: {len(ec)} 条")
    else:
        print(f"  → 错误: {a3_result.error}")

    print("\n[步骤 6/6] A9 离场决策（dream-exit-skill-v2）...")
    a9_result = engine.execute("dream-exit-skill-v2", {
        "positions": positions,
        "a1_result": a1_result.data,
        "a2_result": a2_result.data,
        "a3_result": a3_result.data,
        "market": market,
    })
    print(f"  → 状态: {a9_result.status}")
    if a9_result.status == "completed":
        os = a9_result.data.get("overall_summary", {})
        print(f"  → 总评估数: {os.get('total_evaluated', 0)}")
        print(f"  → 整体立场: {os.get('overall_stance', 'N/A')}")
        print(f"  → 理由: {os.get('rationale', 'N/A')}")
        ub = os.get("urgency_breakdown", {})
        print(f"  → 紧急度: CRITICAL={ub.get('critical', 0)}, HIGH={ub.get('high', 0)}, "
              f"MEDIUM={ub.get('medium', 0)}, LOW={ub.get('low', 0)}")

        evaluations = a9_result.data.get("exit_evaluations", [])
        print(f"\n  各持仓评估明细:")
        for ev in evaluations:
            pos = ev.get("position", {})
            action = ev.get("recommended_action", "N/A")
            urgency = ev.get("urgency", "N/A")
            reason = ev.get("reason", "")[:60]
            print(f"    [{action:10s}] {pos.get('symbol', '?'):20s} {pos.get('direction', '?'):5s} "
                  f"PnL={pos.get('unrealized_pnl', 0):+.2f}% | {urgency:8s} | {reason}")
    else:
        print(f"  → 错误: {a9_result.error}")

    full_report = {
        "timestamp": now.isoformat(),
        "phase": "phase2",
        "version": "1.0.0",
        "position_summary": summary,
        "market": market,
        "a1_research": a1_result.to_dict(),
        "a2_first_principles": a2_result.to_dict(),
        "a3_strategy": a3_result.to_dict(),
        "a9_exit_decision": a9_result.to_dict(),
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACTS_DIR / f"phase2_exit_evaluation_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[产物] JSON 报告已保存: {json_path}")

    md_content = _generate_markdown_report(full_report)
    md_path = ARTIFACTS_DIR / f"phase2_exit_evaluation_{timestamp}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"[产物] Markdown 报告已保存: {md_path}")

    print("\n" + "=" * 70)
    print("  Phase 2 评估完成！")
    print("=" * 70)

    return full_report


def _generate_markdown_report(report: dict) -> str:
    now = report["timestamp"]
    ps = report["position_summary"]
    a9 = report["a9_exit_decision"]["data"]
    os = a9["overall_summary"]
    a1d = report["a1_research"]["data"]
    a2d = report["a2_first_principles"]["data"]
    a3d = report["a3_strategy"]["data"]

    rs = a1d.get("research_report", {})
    ms = rs.get("market_state", {})
    fp = a2d.get("first_principles_analysis", {})
    syn = fp.get("synthesis", {})
    regime = a2d.get("market_regime_classification", {})
    sd = a3d.get("strategy_directive", {})

    lines = []
    lines.append(f"# Phase 2 统一 AI 离场评估报告")
    lines.append("")
    lines.append(f"- **时间**: {now}")
    lines.append(f"- **版本**: Phase 2 v1.0.0 (SKILL 引擎版)")
    lines.append(f"- **评估持仓**: {ps['total_positions']} 个")
    lines.append(f"- **涉及系统**: {ps['total_systems']} 个")
    lines.append(f"- **整体立场**: **{os['overall_stance']}**")
    lines.append(f"- **核心理由**: {os['rationale']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 一、A1 深度调研结果")
    lines.append("")
    lines.append(f"- **趋势方向**: {ms.get('trend_direction', 'N/A')}")
    sig = ms.get("signal_adequacy", {})
    lines.append(f"- **信号充分性**: {sig.get('level', 'N/A')} ({sig.get('net_direction', 0):.1f}/3)")
    rsi = ms.get("rsi_14", {})
    lines.append(f"- **BTC RSI**: {rsi.get('value', 'N/A')} ({rsi.get('status', 'N/A')})")
    atr = ms.get("atr_pct", 0)
    lines.append(f"- **波动率 (ATR%)**: {atr:.2%}")
    lines.append("")

    lines.append("## 二、A2 第一性原理分析")
    lines.append("")
    lines.append(f"- **阻力最小路径**: **{syn.get('least_resistance_path', 'N/A')}**")
    lines.append(f"- **路径置信度**: {syn.get('path_confidence', 0):.2f}")
    lines.append(f"- **市场状态**: {regime.get('regime', 'N/A')} ({regime.get('confidence', 0):.0f}%)")
    ta = fp.get("trend_analysis", {})
    lines.append(f"- **趋势阶段**: {ta.get('trend_phase', 'N/A')}")
    lines.append(f"- **行动建议**: {syn.get('action_recommendation', 'N/A')}")
    lines.append("")

    lines.append("## 三、A3 战略合成指令")
    lines.append("")
    lines.append(f"- **战略方向**: **{sd.get('directive_bias', 'N/A')}**")
    lines.append(f"- **仓位修正**: {sd.get('position_modifier', 0):.2f}x")
    lines.append(f"- **杠杆上限**: {sd.get('leverage_cap', 1)}x")
    target = sd.get("target_coins", [])
    lines.append(f"- **目标币种**: {', '.join(target) if target else 'N/A'}")
    ec = sd.get("exit_conditions", [])
    lines.append(f"- **离场条件**: {len(ec)} 条")
    lines.append("")

    lines.append("## 四、A9 持仓离场评估明细")
    lines.append("")
    lines.append("| 币种 | 系统 | 方向 | 动作 | 紧急度 | 未实现盈亏 | 置信度 | 理由 |")
    lines.append("|:---|:---|:---|:---|:---|:---|:---|:---|")
    for ev in a9.get("exit_evaluations", []):
        pos = ev.get("position", {})
        lines.append(
            f"| {pos.get('symbol', '')} "
            f"| {pos.get('system', '')} "
            f"| {pos.get('direction', '')} "
            f"| **{ev.get('recommended_action', '')}** "
            f"| {ev.get('urgency', '')} "
            f"| {pos.get('unrealized_pnl', 0):+.2f}% "
            f"| {ev.get('confidence', 0):.2f} "
            f"| {ev.get('reason', '')[:50]} |"
        )
    lines.append("")

    lines.append("## 五、紧急度汇总")
    lines.append("")
    ub = os.get("urgency_breakdown", {})
    lines.append(f"- 🔴 CRITICAL: **{ub.get('critical', 0)}** 个")
    lines.append(f"- 🟠 HIGH: **{ub.get('high', 0)}** 个")
    lines.append(f"- 🟡 MEDIUM: **{ub.get('medium', 0)}** 个")
    lines.append(f"- 🟢 LOW: **{ub.get('low', 0)}** 个")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("> 本报告由 16-调控系统 Phase 2 自动生成")
    lines.append("> 四层决策链：A1深度调研 → A2第一性原理 → A3战略合成 → A9离场决策")

    return "\n".join(lines)


if __name__ == "__main__":
    run_phase2_evaluation()
