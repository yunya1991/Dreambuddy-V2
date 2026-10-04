"""
25-用户策略生成系统 - DSH 节点封装

提供三个 DSH 节点函数，供 DreamOS C-Drive Agent 通过 IPC 调用：

- S25_intent:    用户意图 → 策略设计（S1-S5 链）
- S25_backtest:  策略 → 回测验证
- S25_compare:   用户策略 vs 基线对比 + 推荐

设计原则（依据 DSH_SUBAGENT_ARCHITECTURE_SPEC §1.2 数据驱动避幻觉）：
- 节点函数为纯计算 + 已验证数据流，不生成原始数据
- LLM 只做提炼和图表生成，不参与节点核心逻辑
- 节点输出是结构化 SubagentOutput 摘要（压缩格式）

调用契约（DSH stdin NDJSON）：
    {"method": "s25_intent", "params": {...}} → S25_intent(params)
    {"method": "s25_backtest", "params": {...}} → S25_backtest(params)
    {"method": "s25_compare", "params": {...}} → S25_compare(params)
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# 确保模块可导入
import os
import sys

_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from strategy_gen.backtest_engine import run_backtest
from strategy_gen.baseline import baseline_get, baseline_list, baseline_metrics
from strategy_gen.compare import compare_with_baseline, compute_score
from strategy_gen.intent import generate_from_intent


__all__ = [
    "S25_intent",
    "S25_backtest",
    "S25_compare",
    "DSH_NODE_REGISTRY",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _make_output(
    node: str,
    trace_id: str,
    ok: bool,
    result: Dict[str, Any],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """构造 DSH SubagentOutput 摘要（压缩格式）。

    依据 DSH_SUBAGENT_ARCHITECTURE_SPEC §1.4 - Subagent 返回压缩摘要，
    不携带完整执行过程。C-Drive-Agent 持有所有摘要做聚合决策。
    """
    return {
        "node": node,
        "trace_id": trace_id,
        "ok": ok,
        "result": result,
        "error": error,
        "ts": _now_ms(),
    }


def _gen_trace_id(prefix: str = "s25") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# S25_intent - 用户意图 → 策略设计
# ---------------------------------------------------------------------------

def S25_intent(params: Dict[str, Any]) -> Dict[str, Any]:
    """S25_intent 节点：用户意图 → S1-S5 策略链生成策略设计。

    Params:
        intent: 用户意图描述（必填）
        symbol: 交易对（可选）
        timeframe: 周期（可选）
        trace_id: 调用方传入的 trace_id（可选，自动生成）

    Returns (SubagentOutput):
        ok=True:
            result = {
                trace_id, regime, baseline_candidates, ai_design{config_patch, reason}
            }
        ok=False:
            error: 错误描述
    """
    intent = str(params.get("intent") or "").strip()
    if not intent:
        return _make_output("S25_intent", str(params.get("trace_id") or _gen_trace_id()),
                            ok=False, result={}, error="missing_intent")
    symbol = params.get("symbol")
    timeframe = params.get("timeframe")
    trace_id = str(params.get("trace_id") or _gen_trace_id())
    try:
        result = generate_from_intent(intent, symbol=symbol, timeframe=timeframe)
        # 注入调用方 trace_id（保持链路）
        if isinstance(result, dict):
            result["trace_id"] = trace_id
        return _make_output("S25_intent", trace_id, ok=True, result=result)
    except Exception as e:
        return _make_output("S25_intent", trace_id, ok=False, result={}, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# S25_backtest - 策略回测
# ---------------------------------------------------------------------------

def S25_backtest(params: Dict[str, Any]) -> Dict[str, Any]:
    """S25_backtest 节点：策略 → 回测验证。

    Params:
        strategy_id: 策略 ID（必填）
        source_zip: 策略 zip 路径（可选）
        config_patch: 配置补丁（可选）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {strategy_id, metrics_summary, ...}
        ok=False:
            error: 错误描述
    """
    strategy_id = str(params.get("strategy_id") or "").strip()
    if not strategy_id:
        return _make_output("S25_backtest", str(params.get("trace_id") or _gen_trace_id("s25bt")),
                            ok=False, result={}, error="missing_strategy_id")
    source_zip = str(params.get("source_zip") or "").strip() or None
    trace_id = str(params.get("trace_id") or _gen_trace_id("s25bt"))
    # 透传其他参数
    kwargs = {k: v for k, v in params.items()
              if k not in ("strategy_id", "source_zip", "trace_id")}
    try:
        result = run_backtest(strategy_id, source_zip, **kwargs)
        if isinstance(result, dict):
            result["trace_id"] = trace_id
        return _make_output("S25_backtest", trace_id, ok=True, result=result)
    except Exception as e:
        return _make_output("S25_backtest", trace_id, ok=False, result={}, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# S25_compare - 基线对比
# ---------------------------------------------------------------------------

def S25_compare(params: Dict[str, Any]) -> Dict[str, Any]:
    """S25_compare 节点：用户策略 vs 基线对比。

    Params:
        user_metrics: 用户策略回测指标（必填）
        baseline_metrics: 基线策略回测指标（必填）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {
                winner, user_score, baseline_score, delta, recommendation, reason
            }
        ok=False:
            error: 错误描述
    """
    user_metrics = params.get("user_metrics") if isinstance(params.get("user_metrics"), dict) else {}
    baseline_metrics = params.get("baseline_metrics") if isinstance(params.get("baseline_metrics"), dict) else {}
    trace_id = str(params.get("trace_id") or _gen_trace_id("s25cmp"))
    if not user_metrics or not baseline_metrics:
        return _make_output("S25_compare", trace_id,
                            ok=False, result={}, error="missing_metrics")
    try:
        result = compare_with_baseline(user_metrics, baseline_metrics)
        if isinstance(result, dict):
            result["trace_id"] = trace_id
        return _make_output("S25_compare", trace_id, ok=True, result=result)
    except Exception as e:
        return _make_output("S25_compare", trace_id, ok=False, result={}, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# DSH 节点注册表 - 供 DSH server.py 注册路由
# ---------------------------------------------------------------------------

DSH_NODE_REGISTRY: Dict[str, Any] = {
    "s25_intent": S25_intent,
    "s25_backtest": S25_backtest,
    "s25_compare": S25_compare,
}


def dispatch(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """DSH 调度入口：根据 method 路由到对应节点。

    用法（在 DSH server.py 主循环中）：
        if method.startswith("s25_"):
            result = dispatch(method, params)
    """
    fn = DSH_NODE_REGISTRY.get(method)
    if fn is None:
        return _make_output(
            "S25_unknown", str(params.get("trace_id") or _gen_trace_id()),
            ok=False, result={}, error=f"unknown_method: {method}",
        )
    try:
        return fn(params)
    except Exception as e:
        return _make_output(
            "S25_error", str(params.get("trace_id") or _gen_trace_id()),
            ok=False, result={}, error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# 命令行自检（可选）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 自检：调用三个节点，验证基本契约
    print("=== S25_intent self-test ===")
    r1 = S25_intent({"intent": "做多 BTC，回撤<10%", "symbol": "BTC/USDT"})
    print(r1)
    print("=== S25_backtest self-test ===")
    r2 = S25_backtest({"strategy_id": "test_strat_001"})
    print(r2)
    print("=== S25_compare self-test ===")
    r3 = S25_compare({
        "user_metrics": {"profit_factor": 1.5, "max_drawdown_pct": 8.0, "winrate": 55.0,
                          "sharpe_ratio": 1.2, "trades": 100},
        "baseline_metrics": {"profit_factor": 1.3, "max_drawdown_pct": 10.0, "winrate": 50.0,
                               "sharpe_ratio": 1.0, "trades": 100},
    })
    print(r3)
