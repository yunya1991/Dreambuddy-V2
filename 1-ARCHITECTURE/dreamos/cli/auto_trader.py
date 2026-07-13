"""
自动化交易流程编排模块

完整自动化链路:
    定时触发 → 市场扫描 → A1-A5分析 → G1风控检查 → A5执行决策 → 交易所下单 → A9离场监控

支持 dry_run 模式进行模拟交易测试
支持 Hyperliquid 和 OKX 双交易所
"""

from __future__ import annotations

import os
import sys
import json
import time
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 加载 Dream OS 独立 .env 文件
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass


class AutoTrader:
    """自动化交易器"""

    def __init__(self, agent_id: str = "b", dry_run: bool = True, exchange: str = "hyperliquid"):
        self.agent_id = agent_id
        self.dry_run = dry_run
        self.exchange = exchange.lower()
        self._okx_client = None
        self._hl_client = None
        self._trading_agent = None
        self._enabled = True
        self._last_trade_time = {}
        self._min_trade_interval_minutes = 30
        self._scenario_classifier = None
        self._orchestration_memory = None
        self._feedback_collector = None
        # 当前分析上下文（场景+编排），供 execute_trade 回写反馈使用
        self._current_context = {"scenario_id": "UNKNOWN", "pattern": "c_chain", "expected_direction": "HOLD"}

    def get_scenario_classifier(self):
        """场景分类器（延迟初始化）"""
        if self._scenario_classifier is None:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            self._scenario_classifier = ScenarioClassifier()
        return self._scenario_classifier

    def get_orchestration_memory(self):
        """编排记忆表（延迟初始化）"""
        if self._orchestration_memory is None:
            from dreamos.core.memory.orchestration_memory import OrchestrationMemory
            self._orchestration_memory = OrchestrationMemory()
            self._orchestration_memory.load()
        return self._orchestration_memory

    def get_feedback_collector(self):
        """执行反馈收集器（延迟初始化）

        断点3修复：交易执行结果回写到反馈收集器，驱动进化引擎。
        """
        if self._feedback_collector is None:
            from dreamos.core.memory.execution_feedback import ExecutionFeedbackCollector
            memory = self.get_orchestration_memory()
            self._feedback_collector = ExecutionFeedbackCollector(memory)
        return self._feedback_collector

    def record_trade_feedback(self, trade_result: Dict[str, Any]) -> None:
        """记录交易执行反馈到收集器

        在交易执行后调用，将场景+编排+方向+收益回写，
        供 EvolutionEngine._check_orchestration_optimization() 评估。

        Args:
            trade_result: {"direction", "result"(收益率), "expected_direction", ...}
        """
        try:
            collector = self.get_feedback_collector()
            scenario_id = trade_result.get("scenario_id", self._current_context["scenario_id"])
            pattern = trade_result.get("pattern", self._current_context["pattern"])
            collector.record(
                scenario_id=scenario_id,
                pattern=pattern,
                trade_result={
                    "direction": trade_result.get("direction", "HOLD"),
                    "result": trade_result.get("result", 0.0),
                    "expected_direction": trade_result.get("expected_direction",
                                                           self._current_context["expected_direction"]),
                    "symbol": trade_result.get("symbol", ""),
                    "entry_price": trade_result.get("entry_price", 0),
                    "exit_price": trade_result.get("exit_price", 0),
                    "timestamp": datetime.now().isoformat(),
                },
            )
            logger.info(f"反馈已记录: {scenario_id} | {pattern} | dir={trade_result.get('direction')} | ret={trade_result.get('result', 0):.4f}")
        except Exception as e:
            logger.warning(f"记录交易反馈失败: {e}")

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def get_exchange_client(self):
        """获取当前交易所客户端"""
        if self.exchange == "okx":
            return self.get_okx_client()
        elif self.exchange == "hyperliquid":
            return self.get_hyperliquid_client()
        return None

    def get_hyperliquid_client(self):
        """获取 Hyperliquid 客户端"""
        if self._hl_client is None:
            try:
                dreamos_dir = Path(__file__).parent.parent
                arch_dir = dreamos_dir.parent
                root_dir = arch_dir.parent
                sys.path.insert(0, str(root_dir))
                import importlib.util
                hl_path = root_dir / "experiments" / "ab-trading" / "execution" / "aster_spot.py"
                spec = importlib.util.spec_from_file_location("aster_spot", str(hl_path))
                aster_spot = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(aster_spot)
                self._hl_client = aster_spot.HyperliquidClient(self.agent_id)
            except Exception as e:
                logger.warning(f"无法连接 Hyperliquid: {e}")
                self._hl_client = None
        return self._hl_client

    def get_okx_client(self):
        if self._okx_client is None:
            try:
                dreamos_dir = Path(__file__).parent.parent
                arch_dir = dreamos_dir.parent
                root_dir = arch_dir.parent
                sys.path.insert(0, str(root_dir))
                import importlib.util
                okx_path = root_dir / "experiments" / "ab-trading" / "execution" / "okx_spot.py"
                spec = importlib.util.spec_from_file_location("okx_spot", str(okx_path))
                okx_spot = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(okx_spot)
                self._okx_client = okx_spot.OKXSpotClient(self.agent_id)
            except Exception as e:
                logger.warning(f"无法连接OKX: {e}")
                self._okx_client = None
        return self._okx_client

    def get_trading_agent(self):
        if self._trading_agent is None:
            try:
                from dreamos.apps.trading_agent.agent import TradingAgent
                self._trading_agent = TradingAgent(budget_mode="lean")
            except Exception as e:
                logger.warning(f"无法创建TradingAgent: {e}")
                self._trading_agent = None
        return self._trading_agent

    def run_full_analysis(self, symbol: str) -> Dict[str, Any]:
        """运行完整分析链路 (S-A-C-G)

        主路径: TradingAgent.run() -> 完整 S-A-C-G 链路
        降级路径: 当主路径失败时，执行场景驱动的编排链 (无大模型依赖)

        场景识别 + 编排记忆表查询在两条路径之前完成，
        确保无论主路径还是降级路径都使用场景驱动的编排选择。
        """
        market_data = self._fetch_market_data(symbol)

        # 场景识别 + 编排选择（消除随机性，由记忆表驱动）
        classifier = self.get_scenario_classifier()
        memory = self.get_orchestration_memory()
        scenario = classifier.classify(market_data)
        choice = memory.select(scenario.scenario_id)
        logger.info(f"场景识别: {scenario.scenario_id} → 编排: {choice.pattern} (L{choice.fallback_level})")

        # 保存当前上下文，供 execute_trade / 离场检查 回写反馈使用
        self._current_context = {
            "scenario_id": scenario.scenario_id,
            "pattern": choice.pattern,
            "expected_direction": "HOLD",  # 由下方 analysis 结果更新
        }

        agent = self.get_trading_agent()
        if not agent:
            logger.warning(f"TradingAgent 不可用，降级到经典指标分析 | 场景={scenario.scenario_id} 编排={choice.pattern}")
            return self._fallback_classic_analysis(symbol, market_data, scenario, choice)

        try:
            result = agent.run(
                user_input=f"分析 {symbol} 的交易机会",
                market_data=market_data,
                context={
                    "symbol": symbol,
                    "scenario": scenario.to_dict(),
                    "recommended_orchestration": choice.to_dict(),
                },
            )
            # 标记为正常路径
            result["_path"] = "full_sacg"
            result["_scenario"] = scenario.scenario_id
            result["_orchestration"] = choice.pattern
            # 更新上下文的预期方向（用于反馈的方向准确率评估）
            a5_out = result.get("outputs", {}).get("A5", {})
            self._current_context["expected_direction"] = a5_out.get("trade_order", {}).get("action", "HOLD")
            return result
        except Exception as e:
            logger.error(f"TradingAgent 分析失败: {e}，降级到经典指标分析 | 场景={scenario.scenario_id}")
            return self._fallback_classic_analysis(symbol, market_data, scenario, choice)

    def _fallback_classic_analysis(self, symbol: str, market_data: dict = None,
                                    scenario=None, choice=None) -> Dict[str, Any]:
        """降级路径: 场景驱动编排执行 (完全不依赖大模型)

        使用编排记忆表选择的节点链替代硬编码C链。
        当记忆表无匹配时走L3默认 c_chain (C1→C2→C3)。
        """
        from dreamos.shared.state import State, new_state
        from dreamos.registry import get_default_registry
        from dreamos.core.compute.graph_executor import GraphExecutor
        from dreamos.core.arrange.execution_graph import SequentialGraph
        from dreamos.nodes import register_all

        start_time = time.time()
        registry = get_default_registry()
        register_all(registry)

        # 构建 State
        if market_data is None:
            market_data = self._fetch_market_data(symbol)
        cycle_id = f"classic_{symbol}_{int(time.time())}"
        state = new_state(cycle_id=cycle_id)
        state.market_data = market_data
        state.inputs = {"mkt": market_data, "symbol": symbol}

        # 用记忆表选的节点，替代硬编码 ["C1", "C2", "C3"]
        chain_nodes = choice.nodes if choice else ["C1", "C2", "C3"]
        pattern_name = choice.pattern if choice else "c_chain"
        graph = SequentialGraph()
        for node_id in chain_nodes:
            node = registry.get(node_id)
            if node:
                graph.add_node(node)

        # 直接执行 (C 层)
        executor = GraphExecutor()
        report = executor.execute(graph, state)

        # 收集结果
        c1_result = state.get_result("C1")
        c2_result = state.get_result("C2")
        c3_result = state.get_result("C3")

        # 综合决策 (模拟 A5 逻辑)
        direction = "HOLD"
        confidence = 0.5
        trade_order = {}

        if c1_result and c2_result:
            c1_dir = getattr(c1_result, "direction", "HOLD")
            c2_dir = getattr(c2_result, "direction", "HOLD")
            c2_conf = getattr(c2_result, "confidence", 0.5)

            # 方向一致性检查
            if c1_dir == c2_dir and c1_dir != "HOLD":
                direction = c1_dir
                confidence = c2_conf
            elif c2_conf >= 0.65:
                direction = c2_dir
                confidence = c2_conf

        price = market_data.get("price", 0)
        if price == 0:
            direction = "HOLD"
            confidence = 0.0

        if direction != "HOLD" and price > 0:
            atr_pct = 0.02
            if direction == "LONG":
                stop_loss = round(price * (1 - atr_pct * 1.5), 4)
                take_profit = round(price * (1 + atr_pct * 3.0), 4)
            else:
                stop_loss = round(price * (1 + atr_pct * 1.5), 4)
                take_profit = round(price * (1 - atr_pct * 3.0), 4)

            trade_order = {
                "action": direction,
                "coin": symbol,
                "entry_price": price,
                "position_size": 10.0,
                "leverage": 3,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_per_trade": 10.0 * atr_pct,
                "rr_ratio": round(abs(take_profit - price) / max(abs(price - stop_loss), 0.0001), 2),
            }

        # 构建与主路径兼容的输出格式
        latency_ms = (time.time() - start_time) * 1000

        rationale = ["[降级模式] 经典指标分析路径 (无大模型依赖)"]
        if c1_result and hasattr(c1_result, "outputs"):
            r = c1_result.outputs.get("rationale", [])
            rationale.extend(r if isinstance(r, list) else [r])
        if c2_result and hasattr(c2_result, "outputs"):
            r = c2_result.outputs.get("rationale", [])
            rationale.extend(r if isinstance(r, list) else [r])
        if c3_result and hasattr(c3_result, "outputs"):
            r = c3_result.outputs.get("rationale", [])
            rationale.extend(r if isinstance(r, list) else [r])

        return {
            "cycle_id": cycle_id,
            "intent": {"type": "CLASSIC_INDICATORS", "confidence": 1.0},
            "plan": {"chain": "C", "nodes": chain_nodes},
            "execution": {
                "nodes_executed": getattr(report, "executed_nodes", 0),
                "success_count": getattr(report, "success_nodes", 0),
                "total_tokens": 0,
            },
            "action": direction,
            "confidence": round(confidence, 3),
            "rationale": rationale,
            "tokens_used": 0,
            "latency_ms": round(latency_ms, 1),
            "outputs": {
                "A5": {
                    "trade_order": trade_order,
                    "confidence": confidence,
                    "gate_passed": confidence >= 0.6,
                },
                "C1": c1_result.outputs if c1_result else {},
                "C2": c2_result.outputs if c2_result else {},
                "C3": c3_result.outputs if c3_result else {},
            },
            "_path": "classic_fallback",
            "_fallback_reason": "TradingAgent 不可用或 S-A 层失败，降级到经典指标分析",
            "_scenario": scenario.scenario_id if scenario else "UNKNOWN",
            "_orchestration": pattern_name,
            "_fallback_level": choice.fallback_level if choice else "L3",
        }

    def _fetch_market_data(self, symbol: str) -> Dict[str, Any]:
        """获取市场数据（包含场景分类器所需字段）"""
        client = self.get_exchange_client()
        if not client:
            return {"symbol": symbol, "price": 0}

        try:
            if self.exchange == "hyperliquid":
                try:
                    dreamos_dir = Path(__file__).parent.parent
                    arch_dir = dreamos_dir.parent
                    root_dir = arch_dir.parent
                    sys.path.insert(0, str(root_dir))
                    import importlib.util
                    hl_path = root_dir / "experiments" / "ab-trading" / "execution" / "aster_spot.py"
                    spec = importlib.util.spec_from_file_location("aster_spot", str(hl_path))
                    aster_spot = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(aster_spot)

                    mids = aster_spot.get_all_mids(getattr(client, 'proxies', None))
                    price = mids.get(symbol, 0)
                    if price <= 0:
                        return {"symbol": symbol, "price": 0}

                    candles_1h = aster_spot.get_candles(symbol, "1h", 48, getattr(client, 'proxies', None))
                    candles_4h = aster_spot.get_candles(symbol, "4h", 14, getattr(client, 'proxies', None))

                    closes_1h = [float(c["c"]) for c in candles_1h if "c" in c]
                    closes_4h = [float(c["c"]) for c in candles_4h if "c" in c]
                    vols_1h = [float(c["v"]) for c in candles_1h if "v" in c]

                    if len(closes_1h) < 24:
                        return {"symbol": symbol, "price": price}

                    def ema(prices, n):
                        if len(prices) < n:
                            return prices[-1] if prices else 0
                        k = 2 / (n + 1)
                        e = prices[-n]
                        for p in prices[-n + 1:]:
                            e = p * k + e * (1 - k)
                        return e

                    def rsi(prices, n=14):
                        if len(prices) < n + 1:
                            return 50.0
                        deltas = [prices[i] - prices[i - 1] for i in range(1, min(n + 1, len(prices)))]
                        gains = [max(d, 0) for d in deltas]
                        losses = [max(-d, 0) for d in deltas]
                        avg_g = sum(gains) / n
                        avg_l = sum(losses) / n
                        if avg_l == 0:
                            return 100.0
                        rs = avg_g / avg_l
                        return 100 - 100 / (1 + rs)

                    def atr(raw_candles, n=14):
                        if len(raw_candles) < 2:
                            return 0
                        trs = []
                        for i in range(1, min(n + 1, len(raw_candles))):
                            h = float(raw_candles[i].get("h", 0))
                            l = float(raw_candles[i].get("l", 0))
                            c_prev = float(raw_candles[i - 1].get("c", 0))
                            trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
                        return sum(trs) / len(trs) if trs else 0

                    closes_rev = closes_1h[::-1]
                    ema20 = ema(closes_rev, 20)
                    ema50 = ema(closes_rev, min(50, len(closes_rev)))
                    ema200 = ema(closes_4h[::-1], min(20, len(closes_4h)))
                    rsi14 = rsi(closes_rev)
                    atr14 = atr(candles_1h)

                    change_1h = ((closes_1h[0] - closes_1h[1]) / closes_1h[1] * 100) if len(closes_1h) > 1 else 0
                    change_24h = ((closes_1h[0] - closes_1h[23]) / closes_1h[23] * 100) if len(closes_1h) > 23 else 0
                    change_4h = ((closes_4h[0] - closes_4h[3]) / closes_4h[3] * 100) if len(closes_4h) > 3 else 0

                    return {
                        "symbol": symbol,
                        "price": price,
                        "change_24h": round(change_24h, 3) / 100,
                        "change_4h": round(change_4h, 3) / 100,
                        "change_1h": round(change_1h, 3) / 100,
                        "ema20": round(ema20, 2),
                        "ema50": round(ema50, 2),
                        "ema200": round(ema200, 2),
                        "rsi14": round(rsi14, 1),
                        "atr_pct": round(atr14 / price, 4),
                    }
                except Exception as e:
                    logger.warning(f"获取完整市场数据失败: {e}")
                    price = client.get_mid(symbol) if hasattr(client, 'get_mid') else 0
                    return {"symbol": symbol, "price": price}

            if self.exchange == "okx":
                ticker = client.get_ticker(f"{symbol}-USDT")
                if ticker.get("ok"):
                    return {
                        "symbol": symbol,
                        "price": ticker["last"],
                        "bid": ticker["bid"],
                        "ask": ticker["ask"],
                        "vol24h": ticker["vol24h"],
                        "change_24h": ticker.get("change_24h", 0) / 100,
                        "change_1h": 0,
                        "change_4h": 0,
                        "ema20": ticker["last"],
                        "ema50": ticker["last"],
                        "ema200": ticker["last"],
                        "rsi14": 50,
                        "atr_pct": 0.02,
                    }
        except Exception as e:
            logger.warning(f"获取市场数据失败: {e}")

        return {"symbol": symbol, "price": 0}

    def check_risk_control(self, symbol: str, trade_order: Dict) -> Dict[str, Any]:
        """风险控制检查"""
        client = self.get_exchange_client()
        if not client:
            return {"passed": False, "reason": "无法连接交易所"}

        try:
            total_eq = 0.0
            if self.exchange == "hyperliquid":
                try:
                    acct = client.get_account()
                    total_eq = float(acct.get("equity", 0))
                except Exception:
                    total_eq = 0.0
            elif self.exchange == "okx":
                balance = client.get_balance()
                if not balance.get("ok"):
                    return {"passed": False, "reason": "无法获取账户余额"}
                total_eq = balance["total_eq"]

            position_size = trade_order.get("position_size", 10)
            atr_pct = trade_order.get("risk_per_trade", 0.02)

            risk_amount = position_size * atr_pct
            risk_pct = (risk_amount / total_eq) * 100 if total_eq > 0 else 100

            checks = []

            if risk_pct > 5:
                checks.append(f"单笔风险过高({risk_pct:.1f}% > 5%)")

            if total_eq > 0 and position_size > total_eq * 0.2:
                checks.append(f"仓位过大({position_size} > 账户20%)")

            if self._check_trade_interval(symbol):
                checks.append("交易间隔不足")

            return {
                "passed": len(checks) == 0,
                "reason": "; ".join(checks) if checks else "通过",
                "risk_pct": round(risk_pct, 2),
                "total_eq": round(total_eq, 2),
                "position_size": position_size,
            }
        except Exception as e:
            return {"passed": False, "reason": str(e)}

    def _check_trade_interval(self, symbol: str) -> bool:
        """检查交易间隔"""
        last_time = self._last_trade_time.get(symbol, 0)
        elapsed = (time.time() - last_time) / 60
        return elapsed < self._min_trade_interval_minutes

    def execute_trade(self, trade_order: Dict) -> Dict[str, Any]:
        """执行交易"""
        if self.dry_run:
            return {
                "dry_run": True,
                "action": trade_order.get("action"),
                "symbol": trade_order.get("coin"),
                "entry_price": trade_order.get("entry_price"),
                "position_size": trade_order.get("position_size"),
                "leverage": trade_order.get("leverage"),
                "stop_loss": trade_order.get("stop_loss"),
                "take_profit": trade_order.get("take_profit"),
                "exchange": self.exchange,
            }

        client = self.get_exchange_client()
        if not client:
            return {"error": "无法连接交易所"}

        action = trade_order.get("action", "HOLD")
        coin = trade_order.get("coin", "BTC")
        position_size = trade_order.get("position_size", 10)
        leverage = trade_order.get("leverage", 3)

        if action == "HOLD":
            return {"result": "SKIP", "reason": "方向为HOLD"}

        try:
            if self.exchange == "hyperliquid":
                if action == "LONG":
                    result = client.open_long(
                        coin=coin,
                        usdt_amount=position_size,
                        leverage=leverage,
                        tag="dreamos_auto",
                    )
                elif action == "SHORT":
                    result = client.open_short(
                        coin=coin,
                        usdt_amount=position_size,
                        leverage=leverage,
                        tag="dreamos_auto",
                    )
                elif action == "EXIT":
                    result = client.close_position(
                        coin=coin,
                        tag="dreamos_auto",
                    )
                else:
                    return {"error": f"未知动作: {action}"}

                if result.get("ok"):
                    self._last_trade_time[coin] = time.time()
                    return {
                        "result": "SUCCESS",
                        "action": action,
                        "symbol": coin,
                        "exchange": "hyperliquid",
                        "details": result,
                    }
                else:
                    return {"result": "FAILED", "error": result}

            elif self.exchange == "okx":
                inst_id = f"{coin}-USDT"
                if action == "LONG":
                    result = client.market_buy(inst_id, position_size, tag="auto_trader")
                elif action == "SHORT":
                    result = client.market_sell(inst_id, position_size / trade_order.get("price", 1), tag="auto_trader")
                else:
                    return {"error": f"未知动作: {action}"}

                if result.get("ok"):
                    self._last_trade_time[coin] = time.time()
                    return {
                        "result": "SUCCESS",
                        "action": action,
                        "symbol": coin,
                        "exchange": "okx",
                        "ord_id": result.get("ord_id"),
                        "position_size": position_size,
                    }
                else:
                    return {"result": "FAILED", "error": result.get("raw", {})}

            else:
                return {"error": f"不支持的交易所: {self.exchange}"}

        except Exception as e:
            return {"result": "ERROR", "error": str(e)}

    def check_exit(self, symbol: str, entry_price: float, direction: str) -> Dict[str, Any]:
        """检查离场条件"""
        market_data = self._fetch_market_data(symbol)
        price = market_data.get("price", 0)
        if price == 0:
            return {"exit": False, "reason": "无法获取价格"}

        atr_pct = 0.02
        sl_pct = atr_pct * 1.5
        tp_pct = atr_pct * 3.0

        if direction == "LONG":
            stop_loss = entry_price * (1 - sl_pct)
            take_profit = entry_price * (1 + tp_pct)
            if price <= stop_loss:
                return {"exit": True, "reason": f"止损触发: {price:.2f} <= {stop_loss:.2f}", "exit_price": stop_loss}
            if price >= take_profit:
                return {"exit": True, "reason": f"止盈触发: {price:.2f} >= {take_profit:.2f}", "exit_price": take_profit}
        else:
            stop_loss = entry_price * (1 + sl_pct)
            take_profit = entry_price * (1 - tp_pct)
            if price >= stop_loss:
                return {"exit": True, "reason": f"止损触发: {price:.2f} >= {stop_loss:.2f}", "exit_price": stop_loss}
            if price <= take_profit:
                return {"exit": True, "reason": f"止盈触发: {price:.2f} <= {take_profit:.2f}", "exit_price": take_profit}

        return {"exit": False, "reason": "继续持有"}

    def run_auto_trade(self, symbol: str) -> Dict[str, Any]:
        """运行完整自动化交易流程"""
        if not self.is_enabled():
            return {"result": "SKIP", "reason": "自动交易已禁用"}

        start_time = time.time()
        result = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "steps": [],
            "final_result": "SKIP",
        }

        try:
            result["steps"].append({"step": "analysis", "status": "running"})
            analysis = self.run_full_analysis(symbol)
            if analysis.get("error"):
                result["steps"].append({"step": "analysis", "status": "failed", "error": analysis["error"]})
                result["final_result"] = "ANALYSIS_FAILED"
                return result
            result["steps"].append({"step": "analysis", "status": "completed", "confidence": analysis.get("confidence")})

            a5_output = analysis.get("outputs", {}).get("A5", {})
            trade_order = a5_output.get("trade_order", {})
            direction = trade_order.get("action", "HOLD")

            if direction == "HOLD":
                result["steps"].append({"step": "decision", "status": "hold", "reason": "方向为HOLD"})
                result["final_result"] = "HOLD"
                return result

            confidence = a5_output.get("confidence", 0)
            if confidence < 0.6:
                result["steps"].append({"step": "decision", "status": "rejected", "reason": f"置信度不足({confidence:.2f} < 0.6)"})
                result["final_result"] = "CONFIDENCE_TOO_LOW"
                return result

            result["steps"].append({"step": "decision", "status": "approved", "direction": direction, "confidence": confidence})

            result["steps"].append({"step": "risk_check", "status": "running"})
            risk_result = self.check_risk_control(symbol, trade_order)
            if not risk_result["passed"]:
                result["steps"].append({"step": "risk_check", "status": "failed", "reason": risk_result["reason"]})
                result["final_result"] = "RISK_REJECTED"
                return result
            result["steps"].append({"step": "risk_check", "status": "passed"})

            result["steps"].append({"step": "execution", "status": "running"})
            exec_result = self.execute_trade(trade_order)
            if exec_result.get("result") == "SUCCESS":
                result["steps"].append({"step": "execution", "status": "completed", "ord_id": exec_result.get("ord_id")})
                result["final_result"] = "TRADE_EXECUTED"
                # 断点3修复：记录交易反馈（实盘成交，收益待离场时回填）
                self.record_trade_feedback({
                    "direction": direction,
                    "result": 0.0,  # 开仓时收益未知，离场时由 run_exit_check 回填
                    "expected_direction": self._current_context["expected_direction"],
                    "symbol": symbol,
                    "entry_price": trade_order.get("entry_price", 0),
                    "scenario_id": self._current_context["scenario_id"],
                    "pattern": self._current_context["pattern"],
                })
            elif exec_result.get("dry_run"):
                result["steps"].append({"step": "execution", "status": "dry_run", "details": exec_result})
                result["final_result"] = "DRY_RUN"
                # 模拟模式也记录反馈（用于压力测试和进化验证）
                self.record_trade_feedback({
                    "direction": direction,
                    "result": 0.0,
                    "expected_direction": self._current_context["expected_direction"],
                    "symbol": symbol,
                    "entry_price": trade_order.get("entry_price", 0),
                    "scenario_id": self._current_context["scenario_id"],
                    "pattern": self._current_context["pattern"],
                })
                self._try_trigger_evolution()
            else:
                result["steps"].append({"step": "execution", "status": "failed", "error": exec_result.get("error")})
                result["final_result"] = "EXECUTION_FAILED"

            result["execution_time"] = round(time.time() - start_time, 2)

        except Exception as e:
            result["error"] = str(e)
            result["final_result"] = "EXCEPTION"

        return result

    def run_exit_check(self, symbol: str, entry_price: float, direction: str) -> Dict[str, Any]:
        """运行离场检查"""
        exit_result = self.check_exit(symbol, entry_price, direction)

        if exit_result["exit"]:
            exec_result = self.execute_trade({
                "action": "EXIT",
                "coin": symbol,
                "entry_price": entry_price,
                "direction": direction,
            })
            exit_result["execution"] = exec_result

            # 断点3修复：离场时回填实际收益率到反馈收集器
            exit_price = exit_result.get("exit_price", entry_price)
            if entry_price > 0:
                if direction == "LONG":
                    ret = (exit_price - entry_price) / entry_price
                else:
                    ret = (entry_price - exit_price) / entry_price
                ret -= 0.0008  # 扣手续费
            else:
                ret = 0.0
            self.record_trade_feedback({
                "direction": direction,
                "result": ret,
                "expected_direction": self._current_context["expected_direction"],
                "symbol": symbol,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "scenario_id": self._current_context["scenario_id"],
                "pattern": self._current_context["pattern"],
            })
            self._try_trigger_evolution()

        return exit_result

    def _try_trigger_evolution(self):
        """检查反馈并尝试触发进化"""
        try:
            from dreamos.evolution.engine import EvolutionEngine

            engine = EvolutionEngine()
            collector = engine.get_feedback_collector()
            updates = engine._check_orchestration_optimization()
            if updates:
                logger.info(f"进化引擎触发优化: {len(updates)} 个场景更新")
                for update in updates:
                    logger.info(f"  {update['scenario_id']}: {update['old_pattern']} → {update['new_pattern']}")
        except Exception as e:
            logger.warning(f"触发进化引擎失败: {e}")

    def get_account_status(self) -> Dict[str, Any]:
        """获取账户状态"""
        client = self.get_exchange_client()
        if not client:
            return {"error": "无法连接交易所"}

        try:
            if self.exchange == "hyperliquid":
                acct = client.get_account()
                positions = acct.get("positions", {})
                position_list = []
                for coin, pos in positions.items():
                    position_list.append({
                        "coin": coin,
                        "size": pos.get("size", 0),
                        "entry_px": pos.get("entry_px", 0),
                    })
                return {
                    "exchange": "hyperliquid",
                    "total_eq": round(float(acct.get("equity", 0)), 2),
                    "margin": acct.get("margin", {}),
                    "positions": position_list,
                    "timestamp": datetime.now().isoformat(),
                }
            elif self.exchange == "okx":
                balance = client.get_balance()
                if not balance.get("ok"):
                    return {"error": balance.get("error", "未知错误")}

                return {
                    "exchange": "okx",
                    "total_eq": round(balance["total_eq"], 2),
                    "assets": {k: {"avail": round(v["avail"], 4), "total": round(v["total"], 4)}
                              for k, v in balance["assets"].items() if v["total"] > 0.0001},
                    "timestamp": datetime.now().isoformat(),
                }
            else:
                return {"error": f"不支持的交易所: {self.exchange}"}
        except Exception as e:
            return {"error": str(e)}
