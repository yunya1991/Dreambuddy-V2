"""
25-用户策略生成系统 - 策略生成流水线编排

编排: intent → LLM生成策略 → 语法检查 → lookahead检测 → 回测验证 → 检查清单

前端 S1-S5 流水线节点：
  S1_RESEARCH  → 市场调研（LLM 理解意图）
  S2_ANALYSIS  → 策略分析
  S3_DESIGN    → 策略代码生成
  S4_VALIDATE  → 回测验证 + 未来函数检测
  S5_EXECUTE   → 检查清单 + 策略保存
"""
from typing import Any, Dict, Optional
import time

from .intent import generate_from_intent


def run_pipeline(intent: str, **kwargs) -> Dict[str, Any]:
    """执行完整策略生成流水线。

    Args:
        intent: 用户策略意图
        **kwargs: symbol, timeframe, run_backtest_flag 等

    Returns:
        {
            ok, stage, intent,
            steps: {S1..S5: {status, detail}},
            strategy: {...},
            backtest: {...},
            checks: {...}
        }
    """
    start_ts = time.time()
    steps: Dict[str, Any] = {}

    # S1: 调研 — 理解用户意图
    steps["S1_RESEARCH"] = {"status": "done", "detail": f"解析意图: {intent[:50]}"}

    # S2: 分析 — 由 LLM 在生成时完成
    steps["S2_ANALYSIS"] = {"status": "done", "detail": "LLM 分析策略要素"}

    # S3-S5: 调用 generate_from_intent 完成设计+验证+执行
    try:
        result = generate_from_intent(
            intent=intent,
            symbol=kwargs.get("symbol"),
            timeframe=kwargs.get("timeframe"),
            run_backtest_flag=kwargs.get("run_backtest_flag", True),
            save_strategy=kwargs.get("save_strategy", True),
        )
    except Exception as e:
        steps["S3_DESIGN"] = {"status": "error", "detail": str(e)}
        return {
            "ok": False,
            "stage": "failed",
            "intent": intent,
            "steps": steps,
            "error": str(e),
        }

    # S3: 设计 — 策略代码生成
    strategy = result.get("strategy", {})
    s3_detail = f"生成策略: {strategy.get('name', '?')}"
    if not strategy.get("syntax_valid"):
        steps["S3_DESIGN"] = {"status": "error", "detail": f"语法错误: {strategy.get('syntax_error', '')}"}
        return {
            "ok": False,
            "stage": "design_failed",
            "intent": intent,
            "steps": steps,
            "strategy": strategy,
        }
    steps["S3_DESIGN"] = {"status": "done", "detail": s3_detail}

    # S4: 验证 — 回测 + 未来函数检测
    backtest = result.get("backtest", {})
    checks = result.get("checks", {})
    lookahead = strategy.get("lookahead_issues", [])
    s4_parts = []
    if lookahead:
        s4_parts.append(f"未来函数警告: {len(lookahead)}处")
    if backtest.get("ok"):
        m = backtest.get("metrics_summary", {})
        s4_parts.append(f"回测: {m.get('trades', 0)}笔, 胜率{m.get('winrate', 0):.1%}")
    elif backtest:
        s4_parts.append("回测失败")
    steps["S4_VALIDATE"] = {
        "status": "done" if checks.get("no_lookahead") else "warning",
        "detail": " | ".join(s4_parts) or "验证完成",
    }

    # S5: 执行 — 检查清单
    all_checks_pass = all(
        v for k, v in checks.items() if v is not None
    )
    s5_parts = [f"{'✓' if v else '✗'}{k}" for k, v in checks.items()]
    steps["S5_EXECUTE"] = {
        "status": "done" if all_checks_pass else "warning",
        "detail": " ".join(s5_parts),
    }

    elapsed = round(time.time() - start_ts, 2)

    return {
        "ok": result.get("ok", False),
        "stage": "completed" if all_checks_pass else "completed_with_warnings",
        "intent": intent,
        "steps": steps,
        "strategy": strategy,
        "backtest": backtest,
        "checks": checks,
        "elapsed_sec": elapsed,
        "trace_id": result.get("trace_id"),
    }
