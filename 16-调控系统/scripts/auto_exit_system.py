#!/usr/bin/env python3
"""
AI 驱动离场系统 — 自动化调度主脚本

可被 TRAE Schedule / cron 定时调用，形成完整的自动化离场系统。

完整流程：
  1. 查询所有持仓
  2. 获取市场数据
  3. A1/A2/A3 宏观分析
  4. 技术离场分析
  5. 策略适配 + 置信度门槛 + 融合决策
  6. 权限检查
  7. 执行交易（dry_run / simulated / real）
  8. 记录决策 + 结果回填 + 进化闭环
  9. 生成报告 + AAM 投递

环境变量配置：
  EXIT_MODE: dry_run / simulated / real（默认 dry_run）
  USE_LLM: 1/0（默认 0）
  DELIVER: 1/0（默认 0，是否投递到 AAM）
  MAX_EXECUTIONS: 单周期最大执行笔数（默认 5）
  MIN_POSITION_USDT: 最小执行仓位 USDT（默认 1.0）
  EVOLUTION: 1/0（默认 1，是否运行进化）
  BACKFILL: 1/0（默认 0，是否回填历史决策结果）
"""

import sys
import os
import json
import traceback
from typing import Optional
from datetime import datetime, timezone
from pathlib import Path

# 确保 core 目录在路径中
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "scripts"))

# ==========================================
# 日志工具
# ==========================================

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def _log(msg: str, level: str = "INFO"):
    """记录日志（控制台 + 文件）"""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    log_file = LOG_DIR / f"exit_system_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ==========================================
# 主流程
# ==========================================

def run_exit_evaluation_cycle():
    """执行一次完整的离场评估周期"""
    _log("=" * 60)
    _log("🚀 AI 驱动离场系统 — 新周期开始")
    _log("=" * 60)
    
    # 环境变量
    exit_mode = os.environ.get("EXIT_MODE", "dry_run").lower()
    use_llm = os.environ.get("USE_LLM", "0") == "1"
    deliver = os.environ.get("DELIVER", "0") == "1"
    run_evolution = os.environ.get("EVOLUTION", "1") == "1"
    backfill = os.environ.get("BACKFILL", "0") == "1"
    
    _log(f"执行模式: {exit_mode}")
    _log(f"LLM 增强: {'开启' if use_llm else '关闭'}")
    _log(f"AAM 投递: {'开启' if deliver else '关闭'}")
    _log(f"进化系统: {'开启' if run_evolution else '关闭'}")
    
    cycle_start = datetime.now(timezone.utc)
    
    try:
        # ==========================================
        # 0. 初始化
        # ==========================================
        _log("\n[步骤 0/10] 初始化模块...")
        
        from unified_position_query import fetch_all_positions
        from enhanced_evolution import get_enhanced_evolution
        from exit_executor import create_executor_from_env
        import a1_research_adapter
        import a2_first_principles_adapter
        import a3_strategy_adapter
        import a9_exit_decision
        import technical_exit_adapter
        import aam_deliverer
        import feedback_and_permission
        
        evolution = get_enhanced_evolution()
        executor = create_executor_from_env()
        
        _log("模块初始化完成")
        
        # ==========================================
        # 1. 查询持仓
        # ==========================================
        _log("\n[步骤 1/10] 查询聚合持仓...")
        positions_data = fetch_all_positions()
        all_positions = positions_data.get("positions", [])
        
        _log(f"共 {len(all_positions)} 个持仓，{positions_data.get('total_systems', 0)} 个系统")

        # ==========================================
        # 1.5 资金调控评估（一期：只读监控 / 二期：注入 A9 Layer 5）
        # ==========================================
        _log("\n[步骤 1.5/10] 资金调控评估...")
        capital_snapshot = None
        capital_advice = {}
        try:
            from capital_control import CapitalControlComponent, CapitalMode

            capital_component = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
            capital_snapshot = capital_component.evaluate()
            _log(
                f"  资金健康: {capital_snapshot.health.value}, "
                f"总权益: ${capital_snapshot.total_equity:,.2f}, "
                f"使用率: {capital_snapshot.overall_used_pct:.1f}%"
            )
            for sys_name, r in capital_snapshot.by_system.items():
                tag = "降级" if r.fallback_used else "正常"
                _log(
                    f"    - {sys_name}: ${r.total_eq:,.2f} ({tag}, {r.account_type.value})"
                )
            # 构建各系统的资金建议字典（供 A9 Layer 5 使用）
            for sys_name in capital_snapshot.by_system.keys():
                try:
                    advice = capital_component.get_capital_advice(sys_name, "RAISE_TP")
                    capital_advice[sys_name] = advice
                except Exception:
                    pass
            phase2_on = bool(capital_component._config.get("phase2", {}).get("enabled", False))
            high_pressure_sys = [
                s for s, a in capital_advice.items()
                if a.get("margin_pressure") == "HIGH"
            ]
            if phase2_on:
                _log(f"  二期已启用，高压系统: {high_pressure_sys or '无'}")
            else:
                _log("  二期未启用（phase2.enabled=false），仅只读监控")
            # 写入调控报告产物
            _write_capital_report(capital_snapshot, positions_data)
        except Exception as e:
            _log(f"  资金调控评估失败（不影响主流程）: {e}", "WARN")

        # ==========================================
        # 1.6 移动止盈评估（ATR自适应法）
        # ==========================================
        _log("\n[步骤 1.6/10] 移动止盈评估...")
        trailing_snapshot = None
        trailing_triggers = []  # 收集 TRIGGER_CLOSE 结果用于直接执行
        try:
            from trailing_stop import (
                TrailingStopComponent,
                TrailingAction,
            )

            trailing_component = TrailingStopComponent()
            trailing_snapshot = trailing_component.evaluate()
            stats = trailing_snapshot.stats
            _log(
                f"  总持仓: {stats.total_positions}, "
                f"已激活: {stats.armed_count}, 已触发: {stats.triggered_count}, "
                f"历史触发累计: {stats.triggered_total}"
            )
            for sk, r in trailing_snapshot.by_state.items():
                tag = ""
                if r.action == TrailingAction.ARM:
                    tag = " ⚡ARM"
                elif r.action == TrailingAction.TRIGGER_CLOSE:
                    tag = " 🔴TRIGGER"
                    trailing_triggers.append({
                        "state_key": sk,
                        "system": r.system,
                        "symbol": r.coin,
                        "direction": r.side.upper(),
                        "recommended_action": "CLOSE",
                        "reason": r.reason,
                        "confidence": 0.95,
                        "urgency": "HIGH",
                        "source": "trailing_stop",
                        "locked_profit_pct": r.locked_profit_pct,
                    })
                elif r.status.value == "ARMED":
                    tag = f" 🎯({r.trail_distance_pct:.1%}触发)"
                if tag or r.action != TrailingAction.HOLD:
                    _log(f"    - {sk}: {r.status.value}{tag} → {r.reason[:80]}")
            # 写入移动止盈报告
            _write_trailing_report(trailing_snapshot, positions_data)
        except Exception as e:
            _log(f"  移动止盈评估失败（不影响主流程）: {e}", "WARN")
            import traceback as _tb
            _log(_tb.format_exc(), "DEBUG")

        if not all_positions:
            _log("无持仓，跳过本次评估", "WARN")
            return {"status": "success", "reason": "no_positions"}
        
        # ==========================================
        # 2. 获取市场数据
        # ==========================================
        _log("\n[步骤 2/10] 获取市场数据...")
        from market_data_fetcher import fetch_market_data
        market = fetch_market_data(all_positions)
        btc_price = market.get("btc", {}).get("price", 0)
        _log(f"BTC 价格: ${btc_price:,.2f}")
        
        # ==========================================
        # 3. A1 深度调研
        # ==========================================
        _log("\n[步骤 3/10] A1 深度调研...")
        from skill_engine import SkillEngine
        engine = SkillEngine()
        
        symbols = list(set(p.get("symbol", "BTC") for p in all_positions))
        a1_result = engine.execute("dream-strategy-research", {
            "symbol": "BTC",
            "symbols": symbols[:3],
            "market_type": "crypto",
            "use_llm": use_llm,
        })
        
        if a1_result.fallback_used:
            _log(f"A1 使用降级模式: {a1_result.fallback_reason}", "WARN")
        
        # ==========================================
        # 4. A2 第一性原理
        # ==========================================
        _log("\n[步骤 4/10] A2 第一性原理分析...")
        a2_result = engine.execute("dream-first-principles", {
            "research_result": a1_result.data,
            "use_llm": use_llm,
        })
        
        # ==========================================
        # 5. A3 战略合成
        # ==========================================
        _log("\n[步骤 5/10] A3 战略合成...")
        a3_result = engine.execute("dream-strategy-designer", {
            "research_result": a1_result.data,
            "first_principles_result": a2_result.data,
            "use_llm": use_llm,
        })
        
        # ==========================================
        # 6. 技术离场分析
        # ==========================================
        _log("\n[步骤 6/10] 技术离场分析...")
        tech_result = technical_exit_adapter.analyze_positions(
            all_positions, market, a1_result.data.get("research_report", {}).get("market_state", {})
        )
        
        p0_count = sum(1 for p in all_positions if any(
            s.get("layer") == "P0" for s in tech_result.get("by_position", {}).get(p.get("symbol", ""), {}).get("signals", [])
        ))
        _log(f"P0 硬退出: {p0_count} 个")
        
        # ==========================================
        # 7. A9 宏观离场 + 融合决策
        # ==========================================
        _log("\n[步骤 7/10] A9 宏观离场 + 融合决策...")

        a9_result_data = a9_exit_decision.a9_exit_decision_handler({
            "positions": all_positions,
            "a1_result": a1_result.data,
            "a2_result": a2_result.data,
            "a3_result": a3_result.data,
            "market": market,
            "capital_advice": capital_advice,
        }, engine)
        a9_evals = a9_result_data.get("exit_evaluations", [])
        
        # 融合决策（含策略适配 + 置信度门槛 + 进化参数）
        fused_evals = _fuse_with_evolution(
            a9_evals, all_positions, market, a1_result, evolution
        )
        
        close_count = sum(1 for e in fused_evals if e.get("recommended_action") == "CLOSE")
        reduce_count = sum(1 for e in fused_evals if e.get("recommended_action") == "REDUCE")
        hold_count = sum(1 for e in fused_evals if e.get("recommended_action") == "HOLD")
        observe_count = sum(1 for e in fused_evals if e.get("recommended_action") == "OBSERVE")
        gated_count = sum(1 for e in fused_evals if e.get("confidence_gated"))
        
        _log(f"  融合建议: CLOSE={close_count}, REDUCE={reduce_count}, HOLD={hold_count}, OBSERVE={observe_count}")
        _log(f"  置信度拦截: {gated_count} 个")
        
        # ==========================================
        # 7.5 合并移动止盈触发（P0 级强执行）
        # ==========================================
        if trailing_triggers:
            _log(f"\n[步骤 7.5/10] 移动止盈触发: {len(trailing_triggers)} 笔 P0 级平仓...")
            # 与 fused_evals 去重：如果某 system+symbol 已在 fused_evals 里作为 CLOSE，则替换
            seen_keys = set()
            for ev in fused_evals:
                p = ev.get("position", {})
                k = (p.get("system"), p.get("symbol"))
                seen_keys.add(k)
            # 用 trailing 结果补齐/覆盖：对于 trailing_trigger 条目，强制保留 CLOSE 且不被置信度拦截
            for trig in trailing_triggers:
                k = (trig["system"], trig["symbol"])
                new_entry = dict(trig)
                new_entry["position"] = {
                    "symbol": trig["symbol"],
                    "system": trig["system"],
                    "strategy_id": _map_system_to_strategy_id(trig["system"]),
                    "direction": trig["direction"],
                    "size": 0,
                    "entry_price": 0,
                }
                new_entry["confidence_gated"] = False
                new_entry["permission_check"] = feedback_and_permission.can_auto_execute(
                    trig["system"], "CLOSE", "HIGH"
                )
                new_entry["evolution_params"] = {}
                if k in seen_keys:
                    # 替换：确保 trailing 的 CLOSE 优先
                    for idx, ev in enumerate(fused_evals):
                        p = ev.get("position", {})
                        if (p.get("system"), p.get("symbol")) == k:
                            new_entry["position"]["size"] = p.get("size", 0)
                            new_entry["position"]["entry_price"] = p.get("entry_price", 0)
                            new_entry["decision_id"] = ev.get("decision_id", "")
                            fused_evals[idx] = new_entry
                            _log(f"  覆盖: {trig['system']}/{trig['symbol']} 动作升级为 CLOSE（移动止盈）")
                            break
                else:
                    fused_evals.append(new_entry)
                    _log(f"  新增: {trig['system']}/{trig['symbol']} CLOSE（移动止盈触发）")

        # ==========================================
        # 8. 执行交易
        # ==========================================
        _log("\n[步骤 8/10] 执行交易...")
        
        exec_results = executor.execute_evaluations(fused_evals)
        
        success_count = sum(1 for r in exec_results if r["status"] == "success")
        failed_count = sum(1 for r in exec_results if r["status"] == "failed")
        skipped_count = sum(1 for r in exec_results if r["status"] == "skipped")
        rejected_count = sum(1 for r in exec_results if r["status"] == "rejected")
        
        _log(f"  成功执行: {success_count} 笔")
        _log(f"  执行失败: {failed_count} 笔")
        _log(f"  跳过: {skipped_count} 笔")
        _log(f"  权限拒绝: {rejected_count} 笔")
        
        # 回填执行结果到进化系统
        for exec_r in exec_results:
            if exec_r["status"] == "success" and exec_r.get("action") in ("CLOSE", "REDUCE"):
                decision_id = _find_decision_id(fused_evals, exec_r)
                if decision_id:
                    # 判断正确性（简化：平仓后如果继续亏损则正确，盈利则错误）
                    actual_pnl = exec_r.get("actual_pnl", 0)
                    outcome = "CORRECT" if actual_pnl < 0 else "INCORRECT"  # 离场后少亏=正确
                    evolution.record_outcome(
                        decision_id, outcome, actual_pnl,
                        exec_r.get("execution_price", 0), "executed_by_exit_system"
                    )
        
        # ==========================================
        # 9. 进化闭环
        # ==========================================
        if run_evolution:
            _log("\n[步骤 9/10] 进化闭环...")
            
            # A8 检验
            a8_result = evolution.run_a8_inspection()
            _log(f"  A8 矛盾: {len(a8_result.get('contradictions', []))} 个")
            
            # 做梦部分析
            dream_result = evolution.run_dream_analysis()
            _log(f"  做梦部提议: {len(dream_result.get('evolution_proposals', []))} 个")
            
            # 三层进化周期
            cycle_report = evolution.run_full_evolution_cycle(min_samples=5, run_backtest=False)
            _log(f"  总提议: {cycle_report.get('proposals_generated', 0)} 个")
            _log(f"  已采纳: {cycle_report.get('proposals_adopted', 0)} 个")
            
            summary = evolution.get_summary()
            _log(f"  累计决策: {summary.get('total_decisions', 0)}")
            _log(f"  整体准确率: {summary.get('overall_accuracy', 0):.1%}")
        else:
            _log("\n[步骤 9/10] 进化闭环: 跳过")
        
        # ==========================================
        # 10. 生成报告 + AAM 投递
        # ==========================================
        _log("\n[步骤 10/10] 生成报告...")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cycle_id = f"auto_exit_{timestamp}"
        
        # 生成报告（复用 phase3 的报告生成逻辑）
        from phase3_exit_evaluator import (
            _generate_phase3_report, ARTIFACTS_DIR,
        )
        
        backtest_results = None
        report = _generate_phase3_report(
            positions_data, market, a1_result, a2_result, a3_result,
            a9_result=None, tech_result=tech_result, fused_evaluations=fused_evals,
            backtest_results=backtest_results,
        )
        
        # 添加执行结果到报告
        report += f"\n\n## 十、执行结果\n\n"
        report += f"- **执行模式**: {exit_mode}\n"
        report += f"- **成功执行**: {success_count} 笔\n"
        report += f"- **执行失败**: {failed_count} 笔\n"
        report += f"- **跳过**: {skipped_count} 笔\n"
        report += f"- **权限拒绝**: {rejected_count} 笔\n\n"
        
        if success_count > 0:
            report += "### 执行明细\n\n"
            report += "| 系统 | 币种 | 动作 | 数量 | 价格 | 状态 |\n"
            report += "|------|------|------|------|------|------|\n"
            for r in exec_results:
                if r["status"] == "success":
                    report += (
                        f"| {r['system_name']} | {r['symbol']} | {r['action']} | "
                        f"{r['executed_size']:.4f} | ${r['execution_price']:,.2f} | "
                        f"✅ {r['status']} |\n"
                    )
            report += "\n"
        
        # 保存产物
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        json_path = ARTIFACTS_DIR / "exit-evaluations" / f"{cycle_id}.json"
        md_path = ARTIFACTS_DIR / "exit-evaluations" / f"{cycle_id}.md"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        
        full_data = {
            "cycle_id": cycle_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": exit_mode,
            "positions_count": len(all_positions),
            "fused_evaluations": fused_evals,
            "execution_results": exec_results,
            "evolution_summary": evolution.get_summary() if run_evolution else None,
        }
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2)
        
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report)
        
        _log(f"JSON 报告: {json_path}")
        _log(f"Markdown 报告: {md_path}")
        
        # AAM 投递
        if deliver:
            _log("  AAM 投递中...")
            try:
                aam_deliverer.deliver_exit_evaluation(full_data, report)
                _log("  AAM 投递完成")
            except Exception as e:
                _log(f"  AAM 投递失败: {e}", "ERROR")
        
        # ==========================================
        # 完成
        # ==========================================
        cycle_end = datetime.now(timezone.utc)
        duration = (cycle_end - cycle_start).total_seconds()
        
        _log("")
        _log("=" * 60)
        _log(f"✅ 周期完成，耗时 {duration:.1f}s")
        _log(f"   持仓: {len(all_positions)} → 执行: {success_count} 笔")
        _log("=" * 60)
        
        return {
            "status": "success",
            "cycle_id": cycle_id,
            "duration_seconds": duration,
            "positions_count": len(all_positions),
            "executions_success": success_count,
            "executions_failed": failed_count,
        }
    
    except Exception as e:
        _log(f"💥 周期执行失败: {e}", "ERROR")
        _log(traceback.format_exc(), "ERROR")
        return {"status": "error", "error": str(e)}


def _write_capital_report(snapshot, positions_data):
    """写入资金调控报告 JSON 产物。

    产物路径: ``16-调控系统/artifacts/capital-reports/capital_YYYYMMDD_HHMMSS.json``
    结构按 Spec 5.4 节。
    """
    reports_dir = BASE_DIR / "artifacts" / "capital-reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = reports_dir / f"capital_{timestamp}.json"

    report_data = {
        "timestamp": snapshot.timestamp,
        "mode": snapshot.mode.value,
        "health": snapshot.health.value,
        "by_account": {k: v.to_dict() for k, v in snapshot.by_account.items()},
        "by_system": {k: v.to_dict() for k, v in snapshot.by_system.items()},
        "totals": {
            "total_equity": snapshot.total_equity,
            "total_avail": snapshot.total_avail,
            "total_used": snapshot.total_used,
            "overall_used_pct": snapshot.overall_used_pct,
        },
        "recommendations": dict(snapshot.recommendations),
        "positions_summary": {
            "total_positions": len(positions_data.get("positions", [])),
            "total_systems": positions_data.get("total_systems", 0),
            "total_equity_from_positions": positions_data.get("total_equity", 0),
        },
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    _log(f"  资金调控报告: {json_path}")

    # AAM 投递（可选，默认不投递；DELIVER=1 时投递）
    if os.environ.get("DELIVER", "0") == "1":
        try:
            aam_deliverer.deliver_capital_report(report_data)
            _log("  AAM 资金调控报告投递完成")
        except Exception as e:
            _log(f"  AAM 投递失败: {e}", "WARN")

    return json_path


def _write_trailing_report(snapshot, positions_data):
    """写入移动止盈评估报告 JSON 产物。

    产物路径: ``16-调控系统/artifacts/trailing-stop/reports/trailing_YYYYMMDD_HHMMSS.json``
    """
    reports_dir = BASE_DIR / "artifacts" / "trailing-stop" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = reports_dir / f"trailing_{timestamp}.json"

    stats = snapshot.stats
    by_state_serializable = {}
    for sk, r in snapshot.by_state.items():
        try:
            by_state_serializable[sk] = r.to_dict()
        except Exception:
            by_state_serializable[sk] = {
                "state_key": r.state_key,
                "system": r.system,
                "coin": r.coin,
                "side": r.side,
                "action": r.action.value if hasattr(r.action, "value") else str(r.action),
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "current_pnl_eff_pct": r.current_pnl_eff_pct,
                "peak_price": r.peak_price,
                "trailing_stop_price": r.trailing_stop_price,
                "current_atr": r.current_atr,
                "trail_distance_pct": r.trail_distance_pct,
                "locked_profit_pct": r.locked_profit_pct,
                "reason": r.reason,
            }

    report_data = {
        "timestamp": snapshot.timestamp,
        "algorithm": snapshot.extra.get("algorithm", "atr_adaptive"),
        "algorithm_params": snapshot.extra.get("algorithm_params", {}),
        "stats": {
            "total_positions": stats.total_positions,
            "idle_count": stats.idle_count,
            "armed_count": stats.armed_count,
            "triggered_count": stats.triggered_count,
            "closed_count": stats.closed_count,
            "triggered_total": stats.triggered_total,
            "avg_armed_pnl_pct": round(stats.avg_armed_pnl_pct, 4),
            "avg_locked_profit_pct": round(stats.avg_locked_profit_pct, 4),
        },
        "by_state": by_state_serializable,
        "recommendations": dict(snapshot.recommendations),
        "positions_summary": {
            "total_positions": len(positions_data.get("positions", [])),
            "total_systems": positions_data.get("total_systems", 0),
            "total_equity_from_positions": positions_data.get("total_equity", 0),
        },
        "fetch_error": snapshot.extra.get("fetch_error", ""),
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    _log(f"  移动止盈报告: {json_path}")

    # AAM 投递（可选）
    if os.environ.get("DELIVER", "0") == "1":
        try:
            import aam_deliverer as _ad
            if hasattr(_ad, "deliver_trailing_report"):
                _ad.deliver_trailing_report(report_data)
                _log("  AAM 移动止盈报告投递完成")
        except Exception as e:
            _log(f"  AAM 移动止盈投递失败: {e}", "WARN")

    return json_path


def _fuse_with_evolution(a9_evals, positions, market, a1_result, evolution) -> list:
    """融合决策（使用进化后的参数）"""
    research = a1_result.data.get("research_report", {}) if a1_result.data else {}
    market_state = research.get("market_state", {})
    
    fused = []
    for i, pos in enumerate(positions):
        macro_eval = a9_evals[i] if i < len(a9_evals) else {}
        
        tech_signal = technical_exit_adapter._calc_simple_technical_signals(
            pos, market, market_state
        )
        
        system_name = pos.get("system", "unknown")
        strategy_id = _map_system_to_strategy_id(system_name)
        
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
        
        import feedback_and_permission
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
    mapping = {
        "agent_a": "agent_a",
        "agent_b": "agent_b",
        "agent_c_memory": "agent_c",
        "v15_martin": "v15_martin",
        "screen_trend": "screen_trend",
        "three_screen": "screen_trend",
        "yijing_bcrm": "yijing_bcrm",
    }
    return mapping.get(system_name, "agent_a")


def _find_decision_id(fused_evals: list, exec_result: dict) -> Optional[str]:
    """从融合评估中找到对应的决策ID"""
    for ev in fused_evals:
        pos = ev.get("position", {})
        if (pos.get("system") == exec_result.get("system_name")
            and pos.get("symbol") == exec_result.get("symbol")):
            return ev.get("decision_id")
    return None


def main():
    """主入口"""
    import argparse

    parser = argparse.ArgumentParser(description="AI 驱动离场系统 — 自动化调度")
    parser.add_argument(
        "--dry-run", action="store_true", help="干跑模式（不执行真实交易）"
    )
    parser.add_argument(
        "--simulated", action="store_true", help="模拟模式"
    )
    parser.add_argument(
        "--real", action="store_true", help="实盘模式"
    )
    args = parser.parse_args()

    if args.dry_run:
        os.environ["EXIT_MODE"] = "dry_run"
    elif args.simulated:
        os.environ["EXIT_MODE"] = "simulated"
    elif args.real:
        os.environ["EXIT_MODE"] = "real"

    result = run_exit_evaluation_cycle()

    if result.get("status") == "success":
        _log("周期执行成功", "INFO")
        return 0
    else:
        _log(f"周期执行失败: {result.get('error', 'unknown')}", "ERROR")
        return 1


if __name__ == "__main__":
    sys.exit(main())
