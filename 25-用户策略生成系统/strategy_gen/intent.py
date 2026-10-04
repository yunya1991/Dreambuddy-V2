"""
25-用户策略生成系统 - 用户意图 + AI辅助策略生成

用户提供策略意图，系统通过 S1-S5 策略链辅助生成策略：
S1 调研(市场环境) → S2 分析 → S3 基于基线策略设计 config_patch → S4 回测 → S5 检查清单

核心能力：
- 调用 LLM（千问/DeepSeek/Claude）基于成熟策略模板生成可执行策略代码
- 自动语法检查 + lookahead 未来函数检测
- 自动回测验证，返回 metrics_summary
- 与 10-经典指标系统 共享策略目录，生成的策略可直接被回测/实盘使用
"""
from typing import Any, Dict, Optional
import uuid
import time

from .generator import generate_strategy
from .backtest_engine import run_backtest
from .llm_client import llm_available


def generate_from_intent(
    intent: str,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    *,
    run_backtest_flag: bool = True,
    save_strategy: bool = True,
) -> Dict[str, Any]:
    """
    接收用户意图，调用 LLM 生成策略并回测验证。

    流程：
    1. LLM 基于成熟策略模板生成策略代码
    2. 语法检查 + lookahead 未来函数检测
    3. 保存到 10-经典指标系统/user_data/strategies/
    4. 自动回测验证（可选）

    Args:
        intent: 用户策略意图描述
        symbol: 交易标的（如 BTC/USDT）
        timeframe: K线周期（默认 1h）
        run_backtest_flag: 是否自动回测
        save_strategy: 是否保存策略文件

    Returns:
        {
            ok, trace_id,
            strategy: {name, file_path, syntax_valid, lookahead_issues},
            backtest: {ok, metrics_summary, trades_count} (仅 run_backtest_flag=True),
            ai_design: {reason}
        }
    """
    trace_id = str(uuid.uuid4())
    tf = timeframe or "1h"
    start_ts = time.time()

    # ── S1-S3: 调用 LLM 生成策略 ──────────────────────────────────
    if not llm_available():
        return {
            "ok": False,
            "trace_id": trace_id,
            "error": "llm_not_available",
            "strategy": {},
            "backtest": {},
            "ai_design": {"reason": "LLM 不可用，请配置 QWEN_API_KEY 或 DEEPSEEK_API_KEY"},
        }

    gen_result = generate_strategy(
        intent=intent,
        symbol=symbol or "",
        timeframe=tf,
        save=save_strategy,
    )

    strategy_info = {
        "name": gen_result["strategy_name"],
        "file_path": gen_result["file_path"],
        "syntax_valid": gen_result["syntax_valid"],
        "syntax_error": gen_result["syntax_error"],
        "lookahead_issues": gen_result["lookahead_issues"],
    }

    # 如果语法无效，直接返回
    if not gen_result["syntax_valid"]:
        return {
            "ok": False,
            "trace_id": trace_id,
            "error": "strategy_syntax_error",
            "strategy": strategy_info,
            "backtest": {},
            "ai_design": {"reason": f"策略语法错误: {gen_result['syntax_error']}"},
        }

    # ── S4: 回测验证 ─────────────────────────────────────────────
    backtest_info: Dict[str, Any] = {}
    if run_backtest_flag and gen_result["file_path"]:
        bt_result = run_backtest(
            gen_result["strategy_name"],
            timeframe=tf,
        )
        backtest_info = {
            "ok": bt_result.get("ok", False),
            "metrics_summary": bt_result.get("metrics_summary", {}),
            "trades_count": bt_result.get("trades_count", 0),
            "error": bt_result.get("error", ""),
        }

    # ── S5: 检查清单 ─────────────────────────────────────────────
    elapsed = round(time.time() - start_ts, 2)
    checks = {
        "syntax_valid": gen_result["syntax_valid"],
        "no_lookahead": len(gen_result["lookahead_issues"]) == 0,
        "backtest_ok": backtest_info.get("ok", False) if run_backtest_flag else None,
        "has_trades": (backtest_info.get("trades_count", 0) > 0) if run_backtest_flag else None,
    }

    return {
        "ok": True,
        "trace_id": trace_id,
        "regime": {"trend": "auto", "volatility": "auto"},
        "baseline_candidates": [],
        "strategy": strategy_info,
        "backtest": backtest_info,
        "checks": checks,
        "elapsed_sec": elapsed,
        "ai_design": {
            "reason": f"基于意图 '{intent}' 由 LLM 生成趋势跟随策略，"
                      f"已通过语法检查{'、未来函数检测' if checks['no_lookahead'] else ''}"
                      f"{'、回测验证' if run_backtest_flag and checks.get('backtest_ok') else ''}",
        },
    }
