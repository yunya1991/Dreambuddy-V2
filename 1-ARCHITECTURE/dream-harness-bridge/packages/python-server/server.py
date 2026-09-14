#!/usr/bin/env python3
"""dream-harness-bridge Python IPC Server

F-01: 契约版本化 + 版本握手
F-02: 协议级硬约束（constraint_passed 字段）
F-06: 原生库惰性隔离（lazy/optional import）

通信协议: stdio NDJSON (每行一个 JSON 消息)

来源: SPEC v0.3 七补.1 + 七补.2
"""

from __future__ import annotations

import json
import sys
import os
import time
import uuid
import traceback
from pathlib import Path
from typing import Any, Optional

# F-06: 原生库惰性隔离
# 重原生库（causalml/shap/cv2）必须在调用时才 import，不能在模块级 import
# 参考: 记忆 VM-1789089211280 segfault 源于 cv2/numpy ABI 不兼容
# 跨进程独立 IPC server 反而降低此风险（R-7 已修正为低风险）
_HEAVY_NATIVE_LIBS: dict[str, Any] = {}


def lazy_import_heavy(lib_name: str) -> Any:
    """惰性 import 重原生库，避免 ABI 兼容性问题导致进程崩溃

    F-06: 所有重原生库（causalml/shap/cv2）必须通过此函数 import
    """
    if lib_name not in _HEAVY_NATIVE_LIBS:
        try:
            if lib_name == "cv2":
                import cv2  # type: ignore[import]
                _HEAVY_NATIVE_LIBS[lib_name] = cv2
            elif lib_name == "causalml":
                import causalml  # type: ignore[import]
                _HEAVY_NATIVE_LIBS[lib_name] = causalml
            elif lib_name == "shap":
                import shap  # type: ignore[import]
                _HEAVY_NATIVE_LIBS[lib_name] = shap
            else:
                # 尝试通用 import
                _HEAVY_NATIVE_LIBS[lib_name] = __import__(lib_name)
        except Exception as e:
            # FAIL-OPEN: 原生库不可用时降级，不崩溃
            _send_stderr(
                "WARN",
                f"F-06 lazy_import_heavy({lib_name}) 失败: {type(e).__name__}: {e}",
            )
            return None
    return _HEAVY_NATIVE_LIBS.get(lib_name)


def _send_stdout(message: dict[str, Any]) -> None:
    """发送 NDJSON 消息到 stdout"""
    line = json.dumps(message, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _send_stderr(level: str, message: str) -> None:
    """发送结构化日志到 stderr（F-14 调试工具配套）"""
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": level,
        "message": message,
        "pid": os.getpid(),
    }
    sys.stderr.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    sys.stderr.flush()


# F-01: 协议 server
# 兼容直接运行和模块运行两种模式
try:
    from .sdk import (
        create_protocol_server,
        ProtocolHandshakeError,
        CURRENT_SCHEMA_VERSION,
    )
except ImportError:
    # 直接运行 python server.py 时，相对导入不可用
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sdk import (
        create_protocol_server,
        ProtocolHandshakeError,
        CURRENT_SCHEMA_VERSION,
    )


# F-02: DreamBuddy 硬约束检查（占位，Phase 0 POC 时接入真实 DreamBuddy）
def check_hard_constraints(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """F-02: 协议级硬约束检查

    交易路径必须通过硬约束检查：
    - BDSM direction_constraint (LONG_ONLY/SHORT_ONLY/NEUTRAL)
    - MAX_TRIAL_POSITIONS = 2
    - SL/TP 价格空间下限 (SL≥4%/TP≥12%)
    - SL 爆仓安全边际约束
    - 方案C 8 开关

    返回: {"passed": bool, "violations": list[str]}
    """
    violations: list[str] = []

    # 交易路径方法列表（需要强制 constraint_passed）
    TRADING_METHODS = {
        "execute_node",
        "open_position",
        "close_position",
        "modify_position",
    }

    if method not in TRADING_METHODS:
        # 非交易路径：不需要 constraint_passed
        return {"passed": True, "violations": [], "is_trading": False}

    # 交易路径：需要检查硬约束
    # Phase 0 POC: 简化版，Phase 1 接入真实 DreamBuddy 硬约束
    is_trading = True

    # 模拟硬约束检查（Phase 0 占位）
    node_id = params.get("node_id", "")
    if "MAX_TRIAL_POSITIONS" in str(params.get("check", "")):
        # BCRM2.0 测试仓上限检查
        trial_count = params.get("trial_count", 0)
        if trial_count >= 2:
            violations.append(
                f"MAX_TRIAL_POSITIONS exceeded: {trial_count} >= 2"
            )

    if "direction_constraint" in params:
        # BDSM direction_constraint 检查
        constraint = params["direction_constraint"]
        direction = params.get("direction", "")
        if constraint == "LONG_ONLY" and direction == "SHORT":
            violations.append(
                f"BDSM direction_constraint=LONG_ONLY, but direction=SHORT"
            )
        elif constraint == "SHORT_ONLY" and direction == "LONG":
            violations.append(
                f"BDSM direction_constraint=SHORT_ONLY, but direction=LONG"
            )

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "is_trading": is_trading,
    }


def _handle_c1_scan(params: dict[str, Any]) -> dict[str, Any]:
    """C1 技术扫描节点（Phase 0 POC 模拟实现）

    Phase 1: 通过 import DreamBuddy 的 NodeRegistry 调用真实技术扫描
    Phase 0: 返回模拟技术指标数据，验证 IPC 链路和 session log 记录

    参数:
        symbol: 交易对（如 "BTC"）
        timeframe: K线周期（如 "4H"）

    返回: 技术扫描结果 dict
    """
    symbol = params.get("symbol", "BTC")
    timeframe = params.get("timeframe", "4H")

    # V0-3 测试：symbol=ERROR 时抛出异常，验证 Harness fallback 行为
    if symbol.upper() == "ERROR":
        raise RuntimeError("V0-3 test: simulated C1 node failure")

    # Phase 0 POC: 模拟技术扫描结果
    # Phase 1: 调用 DreamBuddy 真实技术指标系统 (http://127.0.0.1:8092)
    return {
        "node_id": "C1_technical_scan",
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "indicators": {
            "ma200": {"value": 67500.0, "price_above": True, "signal": "bullish"},
            "rsi": {"value": 65.0, "zone": "neutral", "signal": "neutral"},
            "macd": {"histogram": 120.0, "signal": "bullish"},
            "volume": {"current": 1.2, "avg_20": 1.0, "ratio": 1.2, "signal": "above_average"},
            "atr": {"value": 850.0, "percentile": 45.0},
        },
        "overall_signal": "bullish",
        "confidence": 0.68,
        "data_quality": "sufficient",
        "phase": "POC_mock",
        "note": "Phase 0 POC: 模拟数据，Phase 1 接入真实 DreamBuddy 技术扫描",
    }


def _handle_c2_momentum(params: dict[str, Any]) -> dict[str, Any]:
    """C2 动量分析节点 — 调用真实 DreamOS C2MomentumNode

    Phase 2: 直接调用 dreamos.capabilities.trading.nodes.c2_momentum.C2MomentumNode
    输入市场数据快照，返回 direction / confidence / momentum_score / divergence。

    参数:
        market_data: 市场数据 dict（price, change_1h/4h/24h, rsi14, macd, macd_signal,
                     macd_hist, ema20, ema50, ema200 等）
        symbol: 交易对符号（可选，仅用于日志）
    """
    market_data = params.get("market_data") or params.get("mkt") or {}
    symbol = params.get("symbol", "")

    if _DREAMOS_ARCH_DIR not in sys.path:
        sys.path.insert(0, _DREAMOS_ARCH_DIR)
    from dreamos.capabilities.trading.nodes.c2_momentum import C2MomentumNode
    from dreamos.shared.state import State

    state = State(market=market_data)
    node = C2MomentumNode()
    node_result = node.execute_core(state)

    return {
        "node_id": "C2_momentum",
        "symbol": symbol,
        "direction": node_result.direction,
        "confidence": node_result.confidence,
        "outputs": node_result.outputs,
        "phase": "real_dreamos_node",
    }


def _handle_c3_volatility(params: dict[str, Any]) -> dict[str, Any]:
    """C3 波动率分析节点 — 调用真实 DreamOS C3VolatilityNode

    Phase 2: 直接调用 dreamos.capabilities.trading.nodes.c3_volatility.C3VolatilityNode
    输入市场数据快照，返回 direction / confidence / volatility_level / squeeze。

    参数:
        market_data: 市场数据 dict（price, atr, atr_pct, bb_upper/middle/lower/width,
                     vol_ratio, change_24h, atr_change 等）
        symbol: 交易对符号（可选，仅用于日志）
    """
    market_data = params.get("market_data") or params.get("mkt") or {}
    symbol = params.get("symbol", "")

    if _DREAMOS_ARCH_DIR not in sys.path:
        sys.path.insert(0, _DREAMOS_ARCH_DIR)
    from dreamos.capabilities.trading.nodes.c3_volatility import C3VolatilityNode
    from dreamos.shared.state import State

    state = State(market=market_data)
    node = C3VolatilityNode()
    node_result = node.execute_core(state)

    return {
        "node_id": "C3_volatility",
        "symbol": symbol,
        "direction": node_result.direction,
        "confidence": node_result.confidence,
        "outputs": node_result.outputs,
        "volatility_level": node_result.outputs.get("volatility_level"),
        "squeeze": node_result.outputs.get("squeeze"),
        "phase": "real_dreamos_node",
    }


def _handle_execute_c_chain(params: dict[str, Any]) -> dict[str, Any]:
    """C 层（OS 执行层）能力接口 — 通过 GraphExecutor 调度执行 C 链

    设计边界（架构硬约束）:
        - C 层 = OS 内核执行层，对外暴露的是 GraphExecutor 的**调度执行能力**
        - C1/C2/C3 = C_domain（经典量化能力域）的内部业务节点，不直接暴露
        - 本方法内部: 获取数据 → 构造 SequentialGraph → GraphExecutor.execute() → 聚合结果
        - 不走直接调用 node.execute_core() 的捷径，遵守 OS 内核标准调度流程

    参数:
        symbol: 交易对符号（如 "BTC"）
        timeframe: 时间周期（如 "4H"）
        market_data: 可选，外部提供的市场数据

    返回:
        capability / direction / confidence / details / phase / reflect_decisions
    """
    if _DREAMOS_ARCH_DIR not in sys.path:
        sys.path.insert(0, _DREAMOS_ARCH_DIR)
    from dreamos.capabilities.trading.nodes.c1_tech_scan import C1TechScanNode
    from dreamos.capabilities.trading.nodes.c2_momentum import C2MomentumNode
    from dreamos.capabilities.trading.nodes.c3_volatility import C3VolatilityNode
    from dreamos.core.arrange.execution_graph import SequentialGraph
    from dreamos.core.compute.graph_executor import GraphExecutor
    from dreamos.shared.state import State

    symbol = params.get("symbol", "BTC")
    timeframe = params.get("timeframe", "4H")
    market_data = params.get("market_data")

    # 1. 获取市场数据（优先外部传入 → indicators API → 默认值 FAIL-OPEN）
    if not market_data:
        market_data = _get_market_data_for_chain(symbol)

    # 2. 构造 State + SequentialGraph（C1 → C2 → C3）
    state = State(market=market_data)
    graph = SequentialGraph()
    graph.add_node(C1TechScanNode())
    graph.add_node(C2MomentumNode())
    graph.add_node(C3VolatilityNode())

    # 3. 通过 OS 内核 C 层 GraphExecutor 调度执行（含 Reflector 反射决策）
    executor = GraphExecutor(enable_reflect=True, max_retries=1)
    report = executor.execute(graph, state)

    # 4. 从 ExecutionReport 提取结果
    direction = report.final_action or "HOLD"
    confidence = round(report.final_confidence, 4)

    # 从 records 中提取各节点详情
    details = {}
    for record in report.records:
        nid = record.node_id
        details[nid] = {
            "direction": record.direction,
            "confidence": record.confidence,
            "status": record.status,
        }

    return {
        "capability": "os.c_layer.execute_c_chain",
        "symbol": symbol,
        "timeframe": timeframe,
        "direction": direction,
        "confidence": confidence,
        "details": details,
        "reflect_decisions": [
            {"node_id": d.get("node_id"), "action": d.get("action")}
            for d in report.reflect_history
        ],
        "execution_stats": {
            "total_nodes": report.total_nodes,
            "executed_nodes": report.executed_nodes,
            "success_nodes": report.success_nodes,
            "early_terminated": report.early_terminated,
        },
        "phase": "os_c_layer_via_graph_executor",
    }


def _get_market_data_for_chain(symbol: str) -> dict[str, Any]:
    """获取市场数据用于 C 链执行

    策略（优先级递减，FAIL-OPEN）:
        1. DAL 查询: 从数据访问层查询最新指标（fear_greed/funding 等）
        2. CCXT 获取: 通过 ccxt 库获取最新 ticker（price/volume）
        3. indicators API (8092): 尝试经典指标系统 API
        4. per-symbol 差异化默认值: 基于符号 hash 生成不同默认值
    """
    market_data = {}

    # 1. DAL 查询（如果数据访问层可用）
    dal_data = _query_dal_for_market_data(symbol)
    if dal_data:
        market_data.update(dal_data)

    # 2. CCXT 获取最新 ticker
    ccxt_data = _fetch_ticker_via_ccxt(symbol)
    if ccxt_data:
        market_data.update(ccxt_data)

    # 3. indicators API (8092)
    if "price" not in market_data:
        ind_data = _fetch_from_indicators_api(symbol)
        if ind_data:
            market_data.update(ind_data)

    # 4. per-symbol 差异化默认值（FAIL-OPEN）
    if not market_data or "price" not in market_data:
        market_data = _generate_symbol_specific_defaults(symbol)

    return market_data


def _query_dal_for_market_data(symbol: str) -> dict[str, Any]:
    """从数据访问层（DAL）查询最新市场指标

    查询路径: 19-数据访问层/dreambuddy_dal/
    查询内容: fear_greed/funding_rate/open_interest/long_short_ratio/taker_volume
    """
    try:
        dal_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..",
            "19-数据访问层"
        )
        if dal_path not in sys.path:
            sys.path.insert(0, dal_path)
        from dreambuddy_dal.connection import get_connection
        from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import MarketMacroRepo

        conn = get_connection()
        repo = MarketMacroRepo(conn)

        result = {}
        # 查询 fear_greed
        try:
            fg = repo.query_latest_metric("fear_greed", "value")
            if fg:
                result["fear_greed"] = float(fg[1])
        except Exception:
            pass

        # 查询 funding rate
        try:
            from datetime import datetime, timedelta
            now = datetime.utcnow()
            start = now - timedelta(hours=24)
            fr = repo.query_funding_by_time(symbol, start, now)
            if fr:
                result["funding_rate"] = float(fr[-1][1])
        except Exception:
            pass

        # 查询 open_interest
        try:
            oi = repo.query_open_interest_by_time(symbol, start, now)
            if oi:
                result["open_interest"] = float(oi[-1][1])
        except Exception:
            pass

        # 查询 long_short_ratio
        try:
            ls = repo.query_long_short_ratio_by_time(symbol, start, now)
            if ls:
                result["long_short_ratio"] = float(ls[-1][3])
        except Exception:
            pass

        return result if result else {}
    except Exception:
        return {}  # FAIL-OPEN


def _fetch_ticker_via_ccxt(symbol: str) -> dict[str, Any]:
    """通过 CCXT 获取最新 ticker 数据"""
    try:
        import ccxt
    except ImportError:
        return {}

    try:
        exchange = ccxt.binance({"enableRateLimit": True})
        pair = f"{symbol}/USDT"
        ticker = exchange.fetch_ticker(pair)
        result = {
            "price": float(ticker.get("last", 0)),
            "change_1h": 0.0,  # ccxt ticker 不含 1h 变化
            "change_24h": float(ticker.get("percentage", 0)),
            "vol_ratio": float(ticker.get("quoteVolume", 0)) / 1e9 if ticker.get("quoteVolume") else 1.0,
        }
        # 获取 OHLCV 计算简单指标
        ohlcv = exchange.fetch_ohlcv(pair, "1h", limit=200)
        if ohlcv and len(ohlcv) >= 50:
            import numpy as np
            closes = np.array([c[4] for c in ohlcv], dtype=float)
            highs = np.array([c[2] for c in ohlcv], dtype=float)
            lows = np.array([c[3] for c in ohlcv], dtype=float)
            volumes = np.array([c[5] for c in ohlcv], dtype=float)

            # EMA
            result["ema20"] = float(closes[-20:].mean())
            result["ema50"] = float(closes[-50:].mean())
            result["ema200"] = float(closes[-200:].mean()) if len(closes) >= 200 else float(closes.mean())

            # RSI 14
            deltas = np.diff(closes)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = gains[-14:].mean() if len(gains) >= 14 else 0
            avg_loss = losses[-14:].mean() if len(losses) >= 14 else 0
            rs = avg_gain / (avg_loss + 1e-10)
            result["rsi14"] = float(100 - 100 / (1 + rs))

            # MACD
            ema12 = closes[-12:].mean()
            ema26 = closes[-26:].mean()
            macd_line = ema12 - ema26
            result["macd"] = float(macd_line)
            result["macd_signal"] = float(macd_line * 0.9)  # 简化
            result["macd_hist"] = float(macd_line - result["macd_signal"])

            # Bollinger Bands
            std = closes[-20:].std()
            result["bb_upper"] = float(result["ema20"] + 2 * std)
            result["bb_middle"] = float(result["ema20"])
            result["bb_lower"] = float(result["ema20"] - 2 * std)
            result["bb_width"] = float(4 * std / result["ema20"])

            # ATR
            tr = np.maximum(highs[-14:] - lows[-14:],
                           np.maximum(np.abs(highs[-14:] - np.roll(closes, 1)[-14:]),
                                      np.abs(lows[-14:] - np.roll(closes, 1)[-14:])))
            atr = tr.mean()
            result["atr"] = float(atr)
            result["atr_pct"] = float(atr / result["price"]) if result["price"] else 0.01
            result["atr_change"] = 0.0

            # 4h 变化
            if len(closes) >= 4:
                result["change_4h"] = float((closes[-1] - closes[-4]) / closes[-4] * 100)

        return result
    except Exception:
        return {}  # FAIL-OPEN


def _fetch_from_indicators_api(symbol: str) -> dict[str, Any]:
    """尝试从经典指标系统 API (8092) 获取数据"""
    import urllib.request
    try:
        url = "http://127.0.0.1:8092/signals/recent?limit=1"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            mkt = _extract_market_data_from_indicators(data)
            if mkt and "price" in mkt:
                return mkt
    except Exception:
        pass
    return {}


def _generate_symbol_specific_defaults(symbol: str) -> dict[str, Any]:
    """基于符号生成差异化默认值（FAIL-OPEN）

    解决问题: 之前所有 symbol 使用相同默认值，导致分析结果相同
    方案: 用符号 hash 生成确定性的差异化数据
    """
    import hashlib
    h = int(hashlib.md5(symbol.encode()).hexdigest(), 16)
    # 基础价格根据符号不同（BTC ~67000, ETH ~3500, SOL ~150, etc.）
    price_map = {"BTC": 67000, "ETH": 3500, "SOL": 150, "BNB": 600, "DOGE": 0.12}
    base_price = price_map.get(symbol.upper(), 100 + (h % 1000))

    # 使用 hash 生成确定性的小幅变化
    variation = ((h % 100) - 50) / 1000.0  # -5% ~ +5%
    price = base_price * (1 + variation)

    # RSI: 30-70 之间
    rsi = 30 + (h % 40)
    # MACD: 正负之间
    macd_val = ((h % 200) - 100) / 10.0
    # EMA 排列: 根据 hash 决定多头/空头排列
    trend_up = (h % 2) == 0
    ema_offset = base_price * 0.01

    return {
        "price": round(price, 2),
        "change_1h": round(variation * 100, 2),
        "change_4h": round(variation * 200, 2),
        "change_24h": round(variation * 500, 2),
        "rsi14": float(rsi),
        "macd": macd_val,
        "macd_signal": macd_val * 0.9,
        "macd_hist": macd_val * 0.1,
        "ema20": round(price * (1 + (0.005 if trend_up else -0.005)), 2),
        "ema50": round(price * (1 + (0.01 if trend_up else -0.01)), 2),
        "ema200": round(price * (1 + (0.02 if trend_up else -0.02)), 2),
        "atr": round(price * 0.015, 2),
        "atr_pct": 0.015,
        "bb_upper": round(price * 1.03, 2),
        "bb_middle": round(price, 2),
        "bb_lower": round(price * 0.97, 2),
        "bb_width": 0.06,
        "vol_ratio": 0.8 + (h % 10) * 0.1,
        "atr_change": round(((h % 20) - 10) * 0.01, 2),
    }


def _extract_market_data_from_indicators(data: Any) -> Optional[dict[str, Any]]:
    """从 indicators API 返回数据中提取 market_data"""
    if not isinstance(data, dict):
        return None
    # 尝试常见的字段路径
    for key in ["market", "mkt", "data", "result"]:
        if isinstance(data.get(key), dict):
            inner = data[key]
            if "price" in inner:
                return inner
    if "price" in data:
        return data
    return None


def _handle_intent_gateway(params: dict[str, Any]) -> dict[str, Any]:
    """S 层 IntentGateway（Phase 0 POC 模拟实现）

    Phase 1: 通过 import DreamBuddy 的 IntentGateway 调用真实意图识别
    Phase 0: 返回模拟意图识别和风险评估结果

    参数:
        user_input: 用户输入文本
        step: agent step 编号
        agent_id: agent 标识符

    返回: 意图识别和风险评估结果 dict
    """
    user_input = params.get("user_input", "")
    step = params.get("step", 0)
    agent_id = params.get("agent_id", "unknown")

    # Phase 0 POC: 简单关键词匹配模拟意图识别
    # Phase 1: 调用 DreamBuddy 真实 IntentGateway (S 层)
    risk_level = "low"
    advisory = None

    # 简单风险关键词检测
    high_risk_keywords = ["all in", "全仓", "杠杆", "高杠杆", "满仓"]
    medium_risk_keywords = ["加仓", "止损", "止盈", "开仓"]

    input_lower = user_input.lower()
    for kw in high_risk_keywords:
        if kw in input_lower or kw in user_input:
            risk_level = "high"
            advisory = f"检测到高风险关键词 '{kw}'，建议谨慎操作"
            break

    if risk_level == "low":
        for kw in medium_risk_keywords:
            if kw in user_input:
                risk_level = "medium"
                advisory = f"检测到交易操作关键词 '{kw}'，请确认风险参数"
                break

    # 意图分类
    intent = "general"
    if any(kw in user_input for kw in ["扫描", "分析", "行情", "scan"]):
        intent = "market_analysis"
    elif any(kw in user_input for kw in ["开仓", "买入", "卖出", "trade"]):
        intent = "trade_execution"
    elif any(kw in user_input for kw in ["查询", "状态", "持仓", "balance"]):
        intent = "position_query"

    return {
        "node_id": "S_intent_gateway",
        "agent_id": agent_id,
        "step": step,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "intent": intent,
        "risk_level": risk_level,
        "advisory": advisory,
        "user_input_preview": user_input[:100] if user_input else "",
        "phase": "POC_mock",
        "note": "Phase 0 POC: 模拟意图识别，Phase 1 接入真实 DreamBuddy IntentGateway",
    }


def _handle_technical_indicators(params: dict[str, Any]) -> dict[str, Any]:
    """经典指标系统接入 (Phase 1)

    调用 http://127.0.0.1:8092 获取技术指标信号。
    FAIL-OPEN: 不可达时返回中性默认值 + 6 层堆栈日志。

    参数:
        symbol: 交易对（如 "BTC"）
        endpoint: 可选，指定具体端点（默认 /signals/recent）

    返回: 技术指标结果 dict
    """
    import urllib.request

    symbol = params.get("symbol", "BTC")
    endpoint = params.get("endpoint", "/signals/recent")
    base_url = "http://127.0.0.1:8092"

    try:
        url = f"{base_url}{endpoint}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "node_id": "technical_indicators",
                "symbol": symbol,
                "endpoint": endpoint,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data": data,
                "status": "ok",
            }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"经典指标系统(8092)不可达: {e}\n{stack}")
        return {
            "node_id": "technical_indicators",
            "symbol": symbol,
            "endpoint": endpoint,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "degraded",
            "neutral_default": {"signal": "neutral", "confidence": 0.0},
            "error": f"{type(e).__name__}: {e}",
        }


def _handle_fundamental_analysis(params: dict[str, Any]) -> dict[str, Any]:
    """基本面 API 接入 (Phase 1)

    调用 http://49.233.123.96:3456 获取基本面分析数据。
    FAIL-OPEN: 不可达时返回中性默认值 + 6 层堆栈日志。

    参数:
        symbol: 交易对（如 "BTC"）
        endpoint: 可选，指定具体端点（默认 /fundamental/overview）

    返回: 基本面分析结果 dict
    """
    import urllib.request

    symbol = params.get("symbol", "BTC")
    endpoint = params.get("endpoint", "/fundamental/overview")
    base_url = "http://49.233.123.96:3456"

    try:
        url = f"{base_url}{endpoint}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "node_id": "fundamental_analysis",
                "symbol": symbol,
                "endpoint": endpoint,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data": data,
                "status": "ok",
            }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"基本面API(3456)不可达: {e}\n{stack}")
        return {
            "node_id": "fundamental_analysis",
            "symbol": symbol,
            "endpoint": endpoint,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "degraded",
            "neutral_default": {"signal": "neutral", "confidence": 0.0},
            "error": f"{type(e).__name__}: {e}",
        }


# G 层 session log consumer 投影文件路径
_SESSION_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    ".session-projections",
    "g_layer_events.jsonl",
)


def _trigger_cognitive_record(event_entry: dict[str, Any]) -> None:
    """Phase 5: Harness Session Log → 认知系统

    在 G 层事件写入 g_layer_events.jsonl 后，同步触发认知系统 record。
    将 OS 运行事件作为认知系统的结构化输入源。

    设计边界:
        - FAIL-OPEN: record 失败不影响 G 层写入（已写入）
        - HC-11: 交易领域事件过滤——只 record 有意义的事件类型
        - 不阻塞主流程（非阻塞调用）

    事件类型 → 认知 tags 映射:
        intent_gate     → OS.S层,意图识别,Harness事件
        graph_node      → OS.A层,图编排,Harness事件
        node_execution  → OS.C层,节点执行,Harness事件
        node_result     → OS.C层,节点结果,Harness事件
    """
    try:
        event_type = event_entry.get("event_type", "unknown")
        session_id = event_entry.get("session_id", "unknown")
        event_data = event_entry.get("event_data", {})

        # HC-11: 过滤噪音事件（只 record 有意义的事件）
        meaningful_types = {"intent_gate", "node_result", "graph_node"}
        if event_type not in meaningful_types:
            return

        # 构建认知记忆内容
        tag_map = {
            "intent_gate": "OS.S层,意图识别,Harness事件",
            "graph_node": "OS.A层,图编排,Harness事件",
            "node_execution": "OS.C层,节点执行,Harness事件",
            "node_result": "OS.C层,节点结果,Harness事件",
        }
        tags = tag_map.get(event_type, f"OS.G层,{event_type},Harness事件")

        # 提取关键信息
        content_parts = [f"[Harness事件][{event_type}] session={session_id}"]
        for k, v in event_data.items():
            val_str = str(v)
            if len(val_str) > 100:
                val_str = val_str[:100] + "..."
            content_parts.append(f"{k}={val_str}")
        content = " | ".join(content_parts)[:300]

        # 尝试调用认知系统 MCP record
        # 通过子进程调用 cognitive_mcp_server 的 record 工具
        import subprocess
        record_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "record",
                "arguments": {
                    "content": content,
                    "quality_level": "C",
                    "tags": tags,
                },
            },
            "id": f"g-layer-record-{time.time()}",
        }

        # 非阻塞调用：启动子进程但不等待
        cognitive_server = str(
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / "4-MEMORY" / "9-工具与接口" / "cognitive_mcp_server.py"
        )
        if Path(cognitive_server).exists():
            subprocess.Popen(
                [sys.executable, cognitive_server],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,  # 不阻塞父进程
            )

        # 也通过 MCP 直接调用（如果可用）
        _try_mcp_record(content, tags)

    except Exception:
        return  # FAIL-OPEN


def _try_mcp_record(content: str, tags: str) -> None:
    """尝试通过认知系统 MCP 工具 record（FAIL-OPEN）"""
    try:
        # 直接导入认知闭环
        cog_path = str(
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / "4-MEMORY" / "9-工具与接口"
        )
        if cog_path not in sys.path:
            sys.path.insert(0, cog_path)
        from cognitive_loop_entry import get_cle
        cle = get_cle()
        cle.record(content=content, quality_level="C", tags=tags)
    except Exception:
        return  # FAIL-OPEN


# ============================================================
# G6+G7: 产物索引 IPC 方法
# ============================================================

_ARTIFACTS_ROOT = os.path.expanduser("~/.workbuddy/artifacts")


def _handle_artifact_index(params: dict[str, Any]) -> dict[str, Any]:
    """G6+G7: 产物索引查询 — 暴露给 Harness agent 和 A7/A8

    params:
        action: "list" | "detail" | "relations" | "phase_groups" | "search"
        slug: (detail) 产物 slug
        limit: (phase_groups) 每阶段最大数量，默认3
        query: (search) 搜索关键词
        category: 过滤类别

    返回: 产物索引数据（FAIL-OPEN: 产物目录不存在返回空）
    """
    action = params.get("action", "list")

    try:
        if not os.path.isdir(_ARTIFACTS_ROOT):
            return {"node_id": "artifact_index", "status": "degraded",
                    "reason": "artifacts_root_not_found", "items": []}

        if action == "list":
            items = _scan_artifacts_index()
            return {"node_id": "artifact_index", "status": "ok",
                    "total": len(items), "items": items}

        elif action == "detail":
            slug = params.get("slug", "")
            detail = _get_artifact_detail(slug)
            return {"node_id": "artifact_index", "status": "ok", "detail": detail}

        elif action == "relations":
            items = _scan_artifacts_index()
            relations = _build_artifact_relations(items)
            return {"node_id": "artifact_index", "status": "ok",
                    "relations": relations}

        elif action == "phase_groups":
            limit = params.get("limit", 3)
            items = _scan_artifacts_index()
            relations = _build_artifact_relations(items)
            groups = _group_by_phase(relations, limit)
            return {"node_id": "artifact_index", "status": "ok",
                    "phase_groups": groups}

        elif action == "search":
            query = params.get("query", "").lower()
            category = params.get("category", "")
            items = _scan_artifacts_index()
            filtered = [
                item for item in items
                if (not query or query in item.get("title", "").lower()
                    or query in item.get("category", "").lower())
                and (not category or item.get("category") == category)
            ]
            return {"node_id": "artifact_index", "status": "ok",
                    "total": len(filtered), "items": filtered}

        return {"node_id": "artifact_index", "status": "error",
                "reason": f"unknown_action: {action}"}

    except Exception as e:
        return {"node_id": "artifact_index", "status": "degraded",
                "reason": str(e)[:100], "items": []}


def _scan_artifacts_index() -> list[dict[str, Any]]:
    """扫描 artifacts 目录构建索引（Python 版 ContentRepository）"""
    items: list[dict[str, Any]] = []
    try:
        for entry in os.scandir(_ARTIFACTS_ROOT):
            if not entry.is_dir() or entry.name.startswith("_") or entry.name.startswith("."):
                continue
            category = entry.name
            # 查找 index.json
            idx_path = os.path.join(entry.path, "index.json")
            if os.path.exists(idx_path):
                with open(idx_path, "r", encoding="utf-8") as f:
                    try:
                        data = json.load(f)
                        if isinstance(data, list):
                            for rec in data:
                                items.append({
                                    "category": category,
                                    "artifact_id": rec.get("id", rec.get("artifactId", "")),
                                    "title": rec.get("title", ""),
                                    "type": rec.get("type", ""),
                                    "phase": rec.get("phase", ""),
                                    "tags": rec.get("tags", []),
                                    "updated": rec.get("updated", rec.get("last_updated", "")),
                                })
                    except json.JSONDecodeError:
                        pass
            # 也扫描 .md 文件
            for sub in os.scandir(entry.path):
                if sub.is_file() and sub.name.endswith(".md"):
                    items.append({
                        "category": category,
                        "artifact_id": sub.name.replace(".md", ""),
                        "title": sub.name.replace(".md", "").replace("_", " "),
                        "type": "markdown",
                        "phase": "",
                        "tags": [],
                        "updated": "",
                    })
    except Exception:
        pass
    return items


def _get_artifact_detail(slug: str) -> dict[str, Any]:
    """获取产物详情"""
    try:
        parts = slug.split("/", 1)
        if len(parts) != 2:
            return {"slug": slug, "found": False}
        category, filename = parts
        filepath = os.path.join(_ARTIFACTS_ROOT, category, f"{filename}.md")
        if not os.path.exists(filepath):
            filepath = os.path.join(_ARTIFACTS_ROOT, category, filename)
        if not os.path.exists(filepath):
            return {"slug": slug, "found": False}
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return {"slug": slug, "found": True, "content": content[:2000],
                "size": len(content)}
    except Exception:
        return {"slug": slug, "found": False}


def _build_artifact_relations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """构建产物间关系（简化版）"""
    relations: list[dict[str, Any]] = []
    by_phase: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        phase = item.get("phase", "")
        if phase:
            by_phase.setdefault(phase, []).append(item)
    for phase, group in by_phase.items():
        for i, item in enumerate(group):
            relations.append({
                "artifact_id": item.get("artifact_id", ""),
                "category": item.get("category", ""),
                "phase": phase,
                "position": i,
                "total_in_phase": len(group),
            })
    return relations


def _group_by_phase(relations: list[dict[str, Any]], limit: int) -> dict[str, list]:
    """按阶段分组"""
    groups: dict[str, list] = {}
    for rel in relations:
        phase = rel.get("phase", "unknown")
        if phase not in groups:
            groups[phase] = []
        if len(groups[phase]) < limit:
            groups[phase].append(rel)
    return groups


# ============================================================
# G8+G9: 交易索引 IPC 方法
# ============================================================

def _handle_trade_index(params: dict[str, Any]) -> dict[str, Any]:
    """G8+G9: 交易索引查询 — A7/A8 反思输入 + 认知回流

    params:
        action: "query" | "stats" | "record_to_cognitive"
        symbol: (query) 过滤交易对
        direction: (query) 过滤方向
        limit: (query) 返回数量，默认50
        source: (query) 过滤来源子系统

    返回: 交易索引数据（FAIL-OPEN: 索引库不存在返回空）
    """
    action = params.get("action", "query")

    try:
        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        index_path = project_root / ".workbuddy" / "trade_index" / "all_trades_index.jsonl"

        if action == "record_to_cognitive":
            return _record_trades_to_cognitive(index_path, params)

        if not index_path.exists():
            return {"node_id": "trade_index", "status": "degraded",
                    "reason": "index_not_found", "trades": [], "total": 0}

        trades = _load_trade_index(index_path)

        if action == "stats":
            return _compute_trade_stats(trades)

        # action == "query"
        symbol = params.get("symbol", "")
        direction = params.get("direction", "")
        source = params.get("source", "")
        limit = params.get("limit", 50)

        filtered = trades
        if symbol:
            filtered = [t for t in filtered if t.get("coin", "").upper() == symbol.upper()
                        or t.get("symbol", "").upper() == symbol.upper()]
        if direction:
            filtered = [t for t in filtered if t.get("direction", "").upper() == direction.upper()]
        if source:
            filtered = [t for t in filtered if t.get("source_system", "") == source]

        return {"node_id": "trade_index", "status": "ok",
                "total": len(filtered), "trades": filtered[:limit]}

    except Exception as e:
        return {"node_id": "trade_index", "status": "degraded",
                "reason": str(e)[:100], "trades": [], "total": 0}


def _load_trade_index(index_path: Path) -> list[dict[str, Any]]:
    """加载交易索引 JSONL"""
    trades: list[dict[str, Any]] = []
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return trades


def _compute_trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """计算交易统计"""
    if not trades:
        return {"node_id": "trade_index", "status": "ok", "stats": {
            "total": 0, "wins": 0, "losses": 0, "win_rate": 0.0}}

    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    losses = sum(1 for t in trades if t.get("pnl", 0) < 0)
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    by_symbol: dict[str, int] = {}
    by_direction: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for t in trades:
        sym = t.get("coin", t.get("symbol", "unknown"))
        by_symbol[sym] = by_symbol.get(sym, 0) + 1
        d = t.get("direction", "unknown")
        by_direction[d] = by_direction.get(d, 0) + 1
        s = t.get("source_system", "unknown")
        by_source[s] = by_source.get(s, 0) + 1

    return {"node_id": "trade_index", "status": "ok", "stats": {
        "total": len(trades), "wins": wins, "losses": losses,
        "win_rate": wins / len(trades) if trades else 0.0,
        "total_pnl": round(total_pnl, 2),
        "by_symbol": by_symbol, "by_direction": by_direction,
        "by_source": by_source}}


def _record_trades_to_cognitive(index_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """G9: 交易经验回流认知系统"""
    try:
        trades = _load_trade_index(index_path) if index_path.exists() else []
        if not trades:
            return {"node_id": "trade_index", "status": "degraded",
                    "reason": "no_trades_to_record"}

        recorded = 0
        try:
            cog_path = str(
                Path(__file__).resolve().parent.parent.parent.parent.parent
                / "4-MEMORY" / "9-工具与接口"
            )
            if cog_path not in sys.path:
                sys.path.insert(0, cog_path)
            from cognitive_loop_entry import get_cle
            cle = get_cle()

            for t in trades[-20:]:  # 最近20条
                pnl = t.get("pnl", 0)
                coin = t.get("coin", t.get("symbol", ""))
                direction = t.get("direction", "")
                result = "win" if pnl > 0 else "loss" if pnl < 0 else "break_even"
                content = f"[交易经验] {coin} {direction} {result} pnl={pnl}"
                tags = f"交易经验,{result},{direction},{coin}"
                cle.record(content=content[:200], quality_level="C", tags=tags)
                recorded += 1
        except Exception:
            pass  # FAIL-OPEN

        return {"node_id": "trade_index", "status": "ok",
                "recorded": recorded, "total_trades": len(trades)}

    except Exception as e:
        return {"node_id": "trade_index", "status": "degraded",
                "reason": str(e)[:100]}


# ============================================================
# G10: 向量索引构建 IPC 方法
# ============================================================

def _handle_build_vector_index(params: dict[str, Any]) -> dict[str, Any]:
    """G10: 触发知识库向量索引增量构建

    params:
        force: True 强制全量重建（默认 False 增量）
        target_dir: 指定目录（默认知识库根目录）

    返回: 构建统计（FAIL-OPEN: ChromaDB 不可用时返回 degraded）
    """
    force = params.get("force", False)

    try:
        kb_path = str(
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / "2-KNOWLEDGE"
        )
        if not os.path.isdir(kb_path):
            return {"node_id": "vector_index", "status": "degraded",
                    "reason": "knowledge_base_not_found"}

        # 尝试调用 build_index
        vs_path = str(
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / "2-KNOWLEDGE" / "9-RAG-INFRA" / "vector_store"
        )
        if vs_path not in sys.path:
            sys.path.insert(0, vs_path)

        try:
            from build_index import build_index
            stats = build_index(kb_path, force=force)
            return {"node_id": "vector_index", "status": "ok",
                    "stats": stats, "force": force}
        except ImportError:
            # ChromaDB 可能未安装 — 降级为文件扫描统计
            md_count = 0
            for root, dirs, files in os.walk(kb_path):
                for f in files:
                    if f.endswith(".md"):
                        md_count += 1
            return {"node_id": "vector_index", "status": "degraded",
                    "reason": "chromadb_not_available",
                    "total_md_files": md_count, "force": force}

    except Exception as e:
        return {"node_id": "vector_index", "status": "degraded",
                "reason": str(e)[:100]}


def _handle_session_consumer(params: dict[str, Any]) -> dict[str, Any]:
    """G 层 session log consumer (Phase 1)

    接收 Harness session 事件投影，写入 JSONL 文件供 DreamBuddy G 层消费。

    投影规则（TS 侧完成投影，Python 侧仅存储）:
      tool/call → node_execution
      tool/result → node_result
      step/* → graph_node
      agent/pre-step → intent_gate

    HC-3: 不持有交易状态，仅消费事件流

    参数:
        event_type: 事件类型（node_execution/node_result/graph_node/intent_gate）
        event_data: 事件数据 dict
        session_id: session 标识

    返回: 写入确认 dict
    """
    event_type = params.get("event_type", "unknown")
    event_data = params.get("event_data", {})
    session_id = params.get("session_id", "unknown")

    try:
        os.makedirs(os.path.dirname(_SESSION_LOG_PATH), exist_ok=True)
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": session_id,
            "event_type": event_type,
            "event_data": event_data,
        }
        with open(_SESSION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Phase 5: 同步触发认知系统 record（FAIL-OPEN）
        _trigger_cognitive_record(entry)

        return {
            "node_id": "session_consumer",
            "status": "ok",
            "event_type": event_type,
            "written": True,
        }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"session_consumer 写入失败: {e}\n{stack}")
        return {
            "node_id": "session_consumer",
            "status": "degraded",
            "event_type": event_type,
            "written": False,
            "error": f"{type(e).__name__}: {e}",
        }


# A 层 GraphPlanner 模块路径
# server.py 位于 1-ARCHITECTURE/dream-harness-bridge/packages/python-server/
# dreamos 位于 1-ARCHITECTURE/dreamos/ → 需上溯 4 级到 1-ARCHITECTURE/
_DREAMOS_ARCH_DIR = str(Path(__file__).resolve().parent.parent.parent.parent)


def _handle_graph_planner(params: dict[str, Any]) -> dict[str, Any]:
    """A 层 GraphPlanner — 意图 → 执行计划

    接收 S 层 intent_gateway 的输出，调用 DreamOS GraphPlanner.plan_from_intent()
    生成 ExecutionPlan，返回 JSON-serializable dict。

    映射: A层(GraphPlanner) → Python IPC 方法
    对应文档: RESEARCH_SACG_HARNESS_MAPPING.md §A层

    HC-7: 失败时降级到默认 A 链计划 (FAIL-OPEN)

    参数:
        intent_type: 意图类型 (TREND_FOLLOWING/REVERSAL/...)
        recommended_chain: S 层推荐主链 (A/C/F)
        base_chain: S 层推荐基础链节点序列
        extend_nodes: S 层推荐扩展节点
        confidence: 意图置信度 (0-1)
        scenario_id: 场景 ID

    返回: ExecutionPlan.to_dict() 或降级默认 plan
    """
    intent_type = params.get("intent_type", "UNKNOWN")
    recommended_chain = params.get("recommended_chain", "A")
    base_chain = params.get("base_chain")
    extend_nodes = params.get("extend_nodes")
    confidence = float(params.get("confidence", 0.5))
    scenario_id = params.get("scenario_id")

    try:
        # 惰性导入 DreamOS GraphPlanner (F-06 原生库隔离原则)
        if _DREAMOS_ARCH_DIR not in sys.path:
            sys.path.insert(0, _DREAMOS_ARCH_DIR)
        from dreamos.core.arrange.graph_planner import GraphPlanner
        from dreamos.core.arrange.types import STANDARD_CHAINS
        from dreamos.registry import get_default_registry

        # 尝试加载 nodes.yaml 到 registry（可能因无 PyYAML 失败，FAIL-OPEN 回退到 STANDARD_CHAINS）
        registry = get_default_registry()
        try:
            if not registry.list_nodes():
                nodes_yaml = os.path.join(_DREAMOS_ARCH_DIR, "dreamos", "config", "nodes.yaml")
                if os.path.exists(nodes_yaml):
                    from dreamos.registry import load_from_yaml
                    load_from_yaml(nodes_yaml, registry)
        except Exception:
            pass  # FAIL-OPEN: registry 为空时回退到 STANDARD_CHAINS

        planner = GraphPlanner(registry=registry)
        plan = planner.plan_from_intent(
            intent_type=intent_type,
            recommended_chain=recommended_chain,
            base_chain=base_chain,
            extend_nodes=extend_nodes,
            confidence=confidence,
            scenario_id=scenario_id,
        )
        result = plan.to_dict()

        # FAIL-OPEN: 如果 selected_nodes 为空（registry 无节点），从 STANDARD_CHAINS 回填
        if not result.get("selected_nodes"):
            chain = result.get("planned_chain") or recommended_chain or "C"
            chain_def = STANDARD_CHAINS.get(chain)
            if chain_def:
                result["selected_nodes"] = chain_def.node_ids
                result["optional_nodes"] = chain_def.optional_nodes

        result["_source"] = "dreamos_graph_planner"
        return result
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"graph_planner 失败，降级到默认 A 链: {e}\n{stack}")
        # HC-7 FAIL-OPEN: 返回默认 A 链空计划，不阻塞交易流程
        return {
            "planned_chain": recommended_chain or "A",
            "selected_nodes": [],
            "budget": {"total": 0, "per_node": {}},
            "chain_spec": None,
            "conditions": {},
            "rationale": f"[degraded] GraphPlanner 调用失败 ({type(e).__name__}), 使用默认链",
            "estimated_total_tokens": 0,
            "estimated_total_latency_ms": 0,
            "capability_id": "trading",
            "_source": "degraded_default",
        }


# reflection_handler.py 与 server.py 同目录
_REFLECTION_HANDLER_DIR = str(Path(__file__).resolve().parent)


def _handle_reflection(params: dict[str, Any]) -> dict[str, Any]:
    """C 层 Reflector — 反射决策校验与执行

    两种模式:
      mode="validate" (默认): 调用方传入 decision，校验合法性后 echo 回传
      mode="decide"  (Phase 2): 调用方传入节点上下文，调用真实 DreamOS
                                Reflector.decide() 基于置信度/预算/矛盾启发式决策

    5 种决策: CONTINUE / REDO / INSERT_BEFORE / JUMP_TO / EARLY_TERMINATE
    (+ SKIP 由 DreamOS 内部映射为 CONTINUE)

    映射: C层(Reflector) → Python IPC 方法
    对应文档: RESEARCH_SACG_HARNESS_MAPPING.md §C层

    HC-7: 异常时降级为 CONTINUE (FAIL-OPEN)
    """
    mode = params.get("mode", "validate")

    if mode == "decide":
        return _handle_reflection_decide(params)

    # mode="validate": 调用方传入 decision，校验后 echo
    decision = params.get("decision", "")
    extra_params = {k: v for k, v in params.items() if k not in ("decision", "mode")}

    try:
        if _REFLECTION_HANDLER_DIR not in sys.path:
            sys.path.insert(0, _REFLECTION_HANDLER_DIR)
        from reflection_handler import handle_reflection_safe

        ok, result = handle_reflection_safe(decision, extra_params)
        if ok:
            echoed_params = {"decision": decision, **extra_params}
            return {
                "echo": {"method": "reflection", "params": echoed_params},
                "executed": result.get("executed", True),
            }
        else:
            return {
                "echo": {"method": "reflection", "params": {}},
                "reflection_error": result,
                "executed": False,
            }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"reflection 失败，降级为 CONTINUE: {e}\n{stack}")
        return {
            "echo": {
                "method": "reflection",
                "params": {"decision": "CONTINUE", "reason": f"[degraded] {type(e).__name__}"},
            },
            "executed": True,
            "_source": "degraded_continue",
        }


# ReflectAction → reflection protocol decision 大写映射
_REFLECT_ACTION_TO_DECISION = {
    "continue": "CONTINUE",
    "redo": "REDO",
    "insert_before": "INSERT_BEFORE",
    "jump_to": "JUMP_TO",
    "early_terminate": "EARLY_TERMINATE",
    "skip": "CONTINUE",  # SKIP 映射为 CONTINUE（协议只定义 5 种决策）
}


def _handle_reflection_decide(params: dict[str, Any]) -> dict[str, Any]:
    """Phase 2: 调用真实 DreamOS Reflector.decide()

    从 IPC params 构建轻量 NodeResult / State / Graph，
    调用 Reflector.decide() 获取启发式决策。

    参数:
        current_node_id: 当前节点 ID
        confidence: 节点结果置信度 (0-1)
        direction: 方向 (LONG/SHORT/HOLD/NEUTRAL)
        status: 状态 (SUCCESS/FAILED/DEGRADED)
        error: 错误信息 (FAILED 时)
        executed_count: 已执行节点数
        max_nodes: 计划总节点数
        budget_remaining_ratio: 剩余预算比例 (0-1)
        prev_results: 前序节点结果列表 [{node_id, direction, confidence}]
        retries: 当前节点已重试次数
    """
    try:
        # 惰性导入 DreamOS Reflector + 状态类型
        if _DREAMOS_ARCH_DIR not in sys.path:
            sys.path.insert(0, _DREAMOS_ARCH_DIR)
        from dreamos.core.compute.reflector import Reflector
        from dreamos.shared.state import NodeResult, NodeStatus, State

        current_node_id = params.get("current_node_id", "unknown")
        confidence = float(params.get("confidence", 0.5))
        direction = params.get("direction")
        status_str = params.get("status", "SUCCESS").upper()
        error = params.get("error")
        executed_count = int(params.get("executed_count", 0))
        max_nodes = int(params.get("max_nodes", 5))
        budget_remaining_ratio = params.get("budget_remaining_ratio")
        if budget_remaining_ratio is not None:
            budget_remaining_ratio = float(budget_remaining_ratio)
        retries = int(params.get("retries", 0))
        prev_results = params.get("prev_results", []) or []

        # 映射 status 字符串 → NodeStatus 枚举
        status_map = {
            "SUCCESS": NodeStatus.SUCCESS,
            "FAILED": NodeStatus.FAILED,
            "DEGRADED": NodeStatus.DEGRADED,
            "PENDING": NodeStatus.PENDING,
            "SKIPPED": NodeStatus.SKIPPED,
        }
        status = status_map.get(status_str, NodeStatus.SUCCESS)

        # 构建当前节点的 NodeResult
        current_result = NodeResult(
            node_id=current_node_id,
            status=status,
            confidence=confidence,
            direction=direction,
            error=error,
        )

        # 构建 State.results（前序节点结果）
        results_dict: dict[str, NodeResult] = {}
        for pr in prev_results:
            if isinstance(pr, dict) and pr.get("node_id"):
                results_dict[pr["node_id"]] = NodeResult(
                    node_id=pr["node_id"],
                    status=NodeStatus.SUCCESS,
                    confidence=float(pr.get("confidence", 0.5)),
                    direction=pr.get("direction"),
                )
        state = State(results=results_dict)

        # 构建轻量 Graph（含当前节点、前序节点、收尾节点、矛盾补充节点）
        conflict_nodes = ["A0", "C1", "F1"]  # CONFLICT_NODE_MAP 的 value 集合
        all_node_ids = list(dict.fromkeys(
            [current_node_id] + list(results_dict.keys()) + ["A9", "G2", "C5"] + conflict_nodes
        ))
        graph = _LightweightGraph(node_ids=all_node_ids)

        # 构建执行记录（重试次数）
        record = None
        if retries > 0:
            from dreamos.core.compute.types import NodeExecutionRecord
            record = NodeExecutionRecord(node_id=current_node_id, retries=retries)

        # 调用真实 Reflector.decide()
        reflector = Reflector()
        decision = reflector.decide(
            current_node_id=current_node_id,
            result=current_result,
            state=state,
            graph=graph,
            executed_count=executed_count,
            max_nodes=max_nodes,
            record=record,
            budget_remaining_ratio=budget_remaining_ratio,
        )

        # 映射 ReflectAction → 协议 decision 字符串
        action_value = decision.action.value if hasattr(decision.action, "value") else str(decision.action)
        protocol_decision = _REFLECT_ACTION_TO_DECISION.get(action_value, "CONTINUE")

        # 构建回传参数（含 decision + 决策上下文）
        echoed_params = {
            "decision": protocol_decision,
            "reason": decision.reason,
            "confidence": decision.confidence,
        }
        if decision.insert_node_id:
            echoed_params["insert_node_id"] = decision.insert_node_id
        if decision.jump_to:
            echoed_params["target_step"] = decision.jump_to
        if decision.suggestions:
            echoed_params["suggestions"] = decision.suggestions

        return {
            "echo": {"method": "reflection", "params": echoed_params},
            "executed": True,
            "reflection_source": "dreamos_reflector_decide",
        }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"reflection(decide) 失败，降级为 CONTINUE: {e}\n{stack}")
        # HC-7 FAIL-OPEN
        return {
            "echo": {
                "method": "reflection",
                "params": {"decision": "CONTINUE", "reason": f"[degraded] {type(e).__name__}"},
            },
            "executed": True,
            "_source": "degraded_continue",
        }


class _LightweightGraph:
    """轻量 Graph 实现 — 仅满足 Reflector 所需的 all_nodes() / get_node()

    Phase 2 桥接用：Reflector 只通过 graph 查找收尾节点(A9/G2/C5)和矛盾补充节点。
    不持有真实交易状态（HC-3）。
    """

    def __init__(self, node_ids: list[str]):
        self._nodes = {nid: _LightweightNode(nid) for nid in node_ids}

    def all_nodes(self):
        return list(self._nodes.values())

    def get_node(self, node_id: str):
        return self._nodes.get(node_id)


class _LightweightNode:
    """轻量 Node 占位 — 仅需 node_id 属性"""

    def __init__(self, node_id: str):
        self.node_id = node_id


def handle_request(
    raw_line: str, protocol_server
) -> Optional[dict[str, Any]]:
    """处理 IPC 请求

    返回响应 dict，或 None（不需要响应时）
    """
    try:
        req = protocol_server.parse_request(raw_line)
    except ProtocolHandshakeError as e:
        return {
            "schema_version": protocol_server.server_version,
            "message_type": "response",
            "ok": False,
            "error": {"code": e.code, "message": e.message},
            "id": str(uuid.uuid4()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    message_type = req.get("message_type", "")

    # F-01: 握手处理
    if message_type == "handshake_request":
        return protocol_server.handle_handshake(raw_line)

    # 普通请求
    if message_type == "request":
        method = req.get("method", "")
        params = req.get("params", {})
        req_id = req.get("id", str(uuid.uuid4()))

        # F-02: 硬约束检查
        constraint_result = check_hard_constraints(method, params)

        if not constraint_result["passed"]:
            # 硬约束未通过 → 拒绝执行
            return protocol_server.build_response(
                ok=False,
                result={
                    "code": "CONSTRAINT_VIOLATION",
                    "message": "; ".join(constraint_result["violations"]),
                },
                opts={"id": req_id},
            )

        # 执行方法
        # Phase 0 POC: c1_scan/intent_gateway 返回模拟结果
        # Phase 1: 接入经典指标系统(8092) + 基本面API(3456)
        if method == "c1_scan":
            result = _handle_c1_scan(params)
        elif method == "c2_momentum":
            result = _handle_c2_momentum(params)
        elif method == "c3_volatility":
            result = _handle_c3_volatility(params)
        elif method == "execute_c_chain":
            result = _handle_execute_c_chain(params)
        elif method == "intent_gateway":
            result = _handle_intent_gateway(params)
        elif method == "technical_indicators":
            result = _handle_technical_indicators(params)
        elif method == "fundamental_analysis":
            result = _handle_fundamental_analysis(params)
        elif method == "session_consumer":
            result = _handle_session_consumer(params)
        elif method == "graph_planner":
            result = _handle_graph_planner(params)
        elif method == "reflection":
            result = _handle_reflection(params)
        elif method == "artifact_index":
            result = _handle_artifact_index(params)
        elif method == "trade_index":
            result = _handle_trade_index(params)
        elif method == "build_vector_index":
            result = _handle_build_vector_index(params)
        else:
            result = {"echo": {"method": method, "params": params}}

        return protocol_server.build_response(
            ok=True,
            result=result,
            opts={
                "constraint_passed": constraint_result["is_trading"],
                "id": req_id,
            },
        )

    # 未知消息类型
    return protocol_server.build_response(
        ok=False,
        result={
            "code": "UNKNOWN_MESSAGE_TYPE",
            "message": f"未知消息类型: {message_type}",
        },
        opts={"id": req.get("id", str(uuid.uuid4()))},
    )


def main() -> int:
    """主循环：读取 stdin NDJSON，处理请求，写入 stdout NDJSON"""
    _send_stderr("INFO", f"Python IPC server 启动 (version={CURRENT_SCHEMA_VERSION}, pid={os.getpid()})")

    protocol_server = create_protocol_server()

    # F-08: 心跳机制占位（Phase 0 POC 时实现完整版）
    last_heartbeat = time.time()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        _send_stderr("DEBUG", f"收到请求: {line[:200]}")

        try:
            response = handle_request(line, protocol_server)
            if response is not None:
                _send_stdout(response)
        except Exception as e:
            # FAIL-OPEN: 异常不崩溃，返回错误响应
            stack_trace = traceback.format_exc()
            _send_stderr("ERROR", f"处理请求异常: {e}\n{stack_trace}")
            # 从请求行中提取 id，确保 IPC client 能匹配响应
            try:
                req_id = json.loads(line).get("id", str(uuid.uuid4()))
            except Exception:
                req_id = str(uuid.uuid4())
            _send_stdout({
                "schema_version": CURRENT_SCHEMA_VERSION,
                "message_type": "response",
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"{type(e).__name__}: {e}",
                },
                "id": req_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })

        # F-08: 心跳（每 5s）
        if time.time() - last_heartbeat > 5:
            _send_stderr("HEARTBEAT", f"alive (pid={os.getpid()})")
            last_heartbeat = time.time()

    _send_stderr("INFO", "Python IPC server 退出 (stdin EOF)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
