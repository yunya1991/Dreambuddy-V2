"""
自动化交易流程编排模块

完整自动化链路:
    定时触发 → 市场扫描 → A1-A5分析 → G1风控检查 → A5执行决策 → 交易所下单 → A9离场监控

支持 dry_run 模式进行模拟交易测试
支持 Aster 和 OKX 双交易所
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

MIN_LEVERAGE = 1
MAX_LEVERAGE = 5
DEFAULT_LEVERAGE = 3
CONFIDENCE_THRESHOLD = float(os.environ.get("DREAMOS_CONFIDENCE_THRESHOLD", "0.4"))


def calc_dynamic_leverage(
    confidence: float,
    min_lev: int = MIN_LEVERAGE,
    max_lev: int = MAX_LEVERAGE,
    threshold: float = CONFIDENCE_THRESHOLD,
) -> int:
    """基于置信度动态计算杠杆倍数

    映射逻辑:
      - 置信度 = threshold (默认 0.4) → min_lev (1x)
      - 置信度 = 0.6 → 约 3x
      - 置信度 >= 0.8 → max_lev (5x)
    """
    if confidence <= threshold:
        return min_lev
    if confidence >= 0.8:
        return max_lev
    ratio = (confidence - threshold) / (0.8 - threshold)
    lev = min_lev + ratio * (max_lev - min_lev)
    return max(min_lev, min(max_lev, int(round(lev))))


class AutoTrader:
    """自动化交易器"""

    # P1-2: 降级路径告警阈值
    FALLBACK_SUSPEND_THRESHOLD = 3  # 连续3次降级暂停该 symbol

    def __init__(self, agent_id: str = "dream_os", dry_run: bool = True, exchange: str = "aster"):
        self.agent_id = agent_id
        self.dry_run = dry_run
        self.exchange = exchange.lower()
        self._okx_client = None
        self._hl_client = None
        self._aster_module = None
        self._trading_agent = None
        self._enabled = True
        self._last_trade_time = {}
        self._min_trade_interval_minutes = 30
        self._scenario_classifier = None
        self._orchestration_memory = None
        self._feedback_collector = None
        # 当前分析上下文（场景+编排），供 execute_trade 回写反馈使用
        self._current_context = {"scenario_id": "UNKNOWN", "pattern": "c_chain", "expected_direction": "HOLD"}
        # P1-2: 降级路径计数器 — symbol → 连续降级次数
        self._fallback_counts: Dict[str, int] = {}
        # P1-2: 暂停的 symbol 集合
        self._suspended_symbols: set = set()
        # P0-3: 4h 周期去重 — symbol → 最后开仓的 4h 周期起始时间戳
        # 1h 调度但开仓基于 4h，避免同一 4h 周期内重复开仓
        # 持久化到文件，跨实例共享（scheduler 每次扫描创建新实例）
        self._dedup_path = str(Path(__file__).parent / ".4h_dedup.json")
        self._last_trade_4h_ts: Dict[str, int] = self._load_dedup_state()

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

    def update_exit_feedback(self, symbol: str, entry_price: float,
                             exit_price: float, result: float) -> None:
        """P0-1: 平仓后回填实际结果到反馈收集器

        闭合反馈环：开仓时 record(result=0)，平仓时 update_exit_result 回填。
        这让进化引擎能获得真实收益数据，而非永久冻结。

        Args:
            symbol: 交易对
            entry_price: 开仓价
            exit_price: 平仓价
            result: 实际收益率（已扣手续费）
        """
        try:
            collector = self.get_feedback_collector()
            scenario_id = self._current_context.get("scenario_id", "UNKNOWN")
            updated = collector.update_exit_result(
                scenario_id=scenario_id,
                symbol=symbol,
                entry_price=entry_price,
                exit_price=exit_price,
                result=result,
            )
            if updated:
                logger.info(f"P0-1 平仓反馈已回填: {symbol} | result={result:.4f}")
            else:
                logger.warning(f"P0-1 平仓反馈未匹配开仓记录: {symbol} | entry={entry_price}")
        except Exception as e:
            logger.warning(f"P0-1 回填平仓反馈失败: {e}")

    def _load_dedup_state(self) -> Dict[str, int]:
        """P0-3: 加载持久化的 4h 去重表

        scheduler 每次扫描创建新 AutoTrader 实例，
        若不持久化，去重表每次为空，同一 4h 周期内会重复开仓。
        """
        try:
            if os.path.exists(self._dedup_path):
                with open(self._dedup_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 过滤掉过期的 4h 记录（只保留当前和上一个 4h 周期）
                    current_4h = (int(time.time() * 1000) // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
                    prev_4h = current_4h - (4 * 3600 * 1000)
                    return {k: v for k, v in data.items() if v >= prev_4h}
        except Exception:
            pass
        return {}

    def _save_dedup_state(self) -> None:
        """P0-3: 持久化 4h 去重表"""
        try:
            with open(self._dedup_path, "w", encoding="utf-8") as f:
                json.dump(self._last_trade_4h_ts, f)
        except Exception as e:
            logger.warning(f"P0-3 保存 4h 去重表失败: {e}")

    def _mark_4h_traded(self, coin: str) -> None:
        """P0-3: 标记 symbol 在当前 4h 周期已开仓，并持久化"""
        current_4h_ts = (int(time.time() * 1000) // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
        self._last_trade_4h_ts[coin] = current_4h_ts
        self._save_dedup_state()

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
        elif self.exchange == "aster":
            return self.get_aster_module()
        return None

    def get_aster_module(self):
        """加载 Aster 交易模块 (ml_trade_service)

        Aster 采用 v3 EVM 签名,凭证从 .env 的 ASTER_USER/SIGNER/PRIVATE_KEY 读取。
        返回 ml_trade_service 模块对象,调用方使用模块级函数:
            _aster_market_order / _aster_market_order_qty / _aster_fetch_positions 等
        """
        if self._aster_module is None:
            try:
                root_dir = Path(__file__).parent.parent.parent.parent
                ml_path = root_dir / "10-经典指标系统"
                sys.path.insert(0, str(ml_path))
                import ml_trade_service
                self._aster_module = ml_trade_service
                logger.info("Aster 模块加载成功 (v3 EVM 签名)")
            except Exception as e:
                logger.warning(f"无法加载 Aster 模块: {e}")
                self._aster_module = None
        return self._aster_module

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
        logger.info(f"场景识别: {scenario.scenario_id} → 编排: {choice.pattern} ({choice.fallback_level})")

        # 保存当前上下文，供 execute_trade / 离场检查 回写反馈使用
        self._current_context = {
            "scenario_id": scenario.scenario_id,
            "pattern": choice.pattern,
            "expected_direction": "HOLD",  # 由下方 analysis 结果更新
            "market_data": market_data,  # 缓存,供 run_auto_trade 构造 trade_order 使用
            "symbol": symbol,
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
            # 优先从顶层 action 取(TradingAgent 最终决策),其次从 outputs.A5.trade_order 取
            a5_out = result.get("outputs", {}).get("A5", {})
            expected_dir = result.get("action") or a5_out.get("trade_order", {}).get("action", "HOLD")
            self._current_context["expected_direction"] = expected_dir
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
        from dreamos.capabilities.trading.nodes import register_all

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
            else:
                # 对称门槛：多空同等置信度要求
                threshold = 0.62 if c2_dir == "SHORT" else 0.62
                if c2_conf >= threshold:
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
                "leverage": calc_dynamic_leverage(confidence),
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
                    "gate_passed": confidence >= float(os.environ.get("DREAMOS_CONFIDENCE_THRESHOLD", "0.4")),
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
                    candles_4h = aster_spot.get_candles(symbol, "4h", 52, getattr(client, 'proxies', None))

                    closes_1h = [float(c["c"]) for c in candles_1h if "c" in c]
                    closes_4h = [float(c["c"]) for c in candles_4h if "c" in c]
                    vols_1h = [float(c["v"]) for c in candles_1h if "v" in c]

                    if len(closes_4h) < 24:
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

                    closes_rev = closes_4h[::-1]
                    ema20 = ema(closes_rev, 20)
                    ema50 = ema(closes_rev, min(50, len(closes_rev)))
                    ema200 = ema(closes_rev, min(200, len(closes_rev)))
                    rsi14 = rsi(closes_rev)
                    atr14 = atr(candles_4h)

                    change_1h = ((closes_1h[0] - closes_1h[1]) / closes_1h[1] * 100) if len(closes_1h) > 1 else 0
                    change_24h = ((closes_4h[0] - closes_4h[6]) / closes_4h[6] * 100) if len(closes_4h) > 6 else 0
                    change_4h = ((closes_4h[0] - closes_4h[1]) / closes_4h[1] * 100) if len(closes_4h) > 1 else 0

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

            if self.exchange == "aster":
                # Aster 行情: _aster_mid 取价格,_aster_klines_ohlcv_rows 取K线
                # 返回行格式: [timestamp, open, high, low, close, volume]
                price = client._aster_mid(symbol)
                if price <= 0:
                    return {"symbol": symbol, "price": 0}

                rows_1h = client._aster_klines_ohlcv_rows(symbol, "1h", 50)
                rows_4h = client._aster_klines_ohlcv_rows(symbol, "4h", 20)

                # rows 按时间升序,取最后 N 根
                if len(rows_1h) < 24:
                    logger.warning(f"Aster 行情不足: {symbol} 1h K线仅 {len(rows_1h)} 根")
                    return {"symbol": symbol, "price": price}

                closes_1h = [r[4] for r in rows_1h]  # 升序,最后一个是最新
                closes_4h = [r[4] for r in rows_4h]

                def _ema(prices, n):
                    if len(prices) < n:
                        return prices[-1] if prices else 0
                    k = 2 / (n + 1)
                    e = prices[-n]
                    for p in prices[-n + 1:]:
                        e = p * k + e * (1 - k)
                    return e

                def _rsi(prices, n=14):
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

                def _atr(rows, n=14):
                    if len(rows) < 2:
                        return 0
                    trs = []
                    for i in range(1, min(n + 1, len(rows))):
                        h = rows[i][2]
                        l = rows[i][3]
                        c_prev = rows[i - 1][4]
                        trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
                    return sum(trs) / len(trs) if trs else 0

                ema20 = _ema(closes_1h, 20)
                ema50 = _ema(closes_1h, min(50, len(closes_1h)))
                ema200 = _ema(closes_4h, min(20, len(closes_4h)))
                rsi14 = _rsi(closes_1h)
                atr14 = _atr(rows_1h)

                # 变化率:closes_1h 升序,最新在末尾
                change_1h = ((closes_1h[-1] - closes_1h[-2]) / closes_1h[-2] * 100) if len(closes_1h) > 1 else 0
                change_24h = ((closes_1h[-1] - closes_1h[-24]) / closes_1h[-24] * 100) if len(closes_1h) > 23 else 0
                change_4h = ((closes_4h[-1] - closes_4h[-4]) / closes_4h[-4] * 100) if len(closes_4h) > 3 else 0

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
            elif self.exchange == "aster":
                # Aster 通过 ml_trade_service._aster_fetch_account_summary 获取账户余额
                try:
                    summary = client._aster_fetch_account_summary()
                    if summary.get("ok"):
                        s = summary.get("summary", {}) or {}
                        total_eq = float(s.get("totalWalletBalance", 0) or 0)
                        if total_eq == 0:
                            usdt = summary.get("assets", {}).get("USDT", {}) or {}
                            total_eq = float(usdt.get("walletBalance", 0) or 0)
                except Exception as e:
                    logger.warning(f"Aster 获取账户余额失败: {e}")
                    total_eq = 0.0

            position_size = trade_order.get("position_size", 10)
            # risk_per_trade 已经是单笔风险金额(USDT),不应再乘 position_size
            risk_amount = trade_order.get("risk_per_trade", position_size * 0.02)
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
        """执行交易

        P0 黑天鹅防护:
          - 开仓(LONG/SHORT)成功后, 自动下交易所 TP/SL 条件单
          - 平仓(EXIT)前, 先取消所有 TP/SL 挂单
        即使程序崩溃/断网, 交易所条件单仍能触发, 防止黑天鹅事件.
        """
        if self.dry_run:
            sl = trade_order.get("stop_loss")
            tp = trade_order.get("take_profit")
            action = trade_order.get("action")
            has_tpsl = sl is not None and tp is not None and action in ("LONG", "SHORT")
            tpsl_set = bool(has_tpsl)
            tpsl_cancelled = (action == "EXIT")
            return {
                "dry_run": True,
                "action": action,
                "symbol": trade_order.get("coin"),
                "entry_price": trade_order.get("entry_price"),
                "position_size": trade_order.get("position_size"),
                "leverage": trade_order.get("leverage"),
                "stop_loss": sl,
                "take_profit": tp,
                "exchange": self.exchange,
                "tpsl_set": tpsl_set,
                "tpsl_cancelled": tpsl_cancelled,
            }

        client = self.get_exchange_client()
        if not client:
            return {"error": "无法连接交易所"}

        action = trade_order.get("action", "HOLD")
        coin = trade_order.get("coin", "BTC")
        position_size = trade_order.get("position_size", 10)
        leverage = int(trade_order.get("leverage", DEFAULT_LEVERAGE))
        leverage = max(MIN_LEVERAGE, min(MAX_LEVERAGE, leverage))
        stop_loss = trade_order.get("stop_loss")
        take_profit = trade_order.get("take_profit")

        if action == "HOLD":
            return {"result": "SKIP", "reason": "方向为HOLD"}

        try:
            if self.exchange == "hyperliquid":
                # P0: EXIT 前先取消所有 TP/SL 挂单
                if action == "EXIT":
                    try:
                        client.cancel_all_tpsl(coin)
                        logger.info(f"平仓前取消 TP/SL 挂单: {coin}")
                    except Exception as e:
                        logger.warning(f"取消 TP/SL 挂单失败({coin}): {e}")

                    result = client.close_position(
                        coin=coin,
                        tag="dreamos_auto",
                    )
                else:
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
                    else:
                        return {"error": f"未知动作: {action}"}

                if result.get("ok"):
                    self._last_trade_time[coin] = time.time()
                    # P0-3: 更新 4h 周期去重标记（持久化跨实例共享）
                    self._mark_4h_traded(coin)

                    # P0: 开仓成功后自动下 TP/SL 条件单（黑天鹅底线防护）
                    tpsl_result = None
                    if action in ("LONG", "SHORT") and stop_loss and take_profit:
                        try:
                            # 稍等 500ms 确保仓位已在交易所确认
                            time.sleep(0.5)
                            tpsl_result = client.set_tpsl_orders(
                                coin=coin,
                                stop_loss_price=float(stop_loss),
                                take_profit_price=float(take_profit),
                                is_market=True,
                            )
                            if tpsl_result.get("ok"):
                                logger.info(
                                    f"TP/SL 条件单已设置: {coin} | "
                                    f"SL={stop_loss} TP={take_profit} | "
                                    f"oids={tpsl_result.get('oids', [])}"
                                )
                            else:
                                logger.warning(
                                    f"TP/SL 条件单设置失败({coin}): {tpsl_result.get('error')}"
                                )
                        except Exception as e:
                            logger.warning(f"设置 TP/SL 条件单异常({coin}): {e}")
                            tpsl_result = {"ok": False, "error": str(e)}

                    return {
                        "result": "SUCCESS",
                        "action": action,
                        "symbol": coin,
                        "exchange": "hyperliquid",
                        "details": result,
                        "tpsl_result": tpsl_result,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                    }
                else:
                    return {"result": "FAILED", "error": result}

            elif self.exchange == "okx":
                inst_id = f"{coin}-USDT"
                if action == "LONG":
                    result = client.market_buy(inst_id, position_size, tag="auto_trader")
                elif action == "SHORT":
                    result = client.market_sell(inst_id, position_size / trade_order.get("price", 1), tag="auto_trader")
                elif action == "EXIT":
                    result = client.close_position(inst_id, tag="auto_trader") if hasattr(client, "close_position") else {"ok": False, "error": "not_supported"}
                else:
                    return {"error": f"未知动作: {action}"}

                if result.get("ok"):
                    self._last_trade_time[coin] = time.time()
                    # P0-3: 更新 4h 周期去重标记（持久化跨实例共享）
                    self._mark_4h_traded(coin)
                    return {
                        "result": "SUCCESS",
                        "action": action,
                        "symbol": coin,
                        "exchange": "okx",
                        "ord_id": result.get("ord_id"),
                        "position_size": position_size,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "tpsl_result": {"ok": False, "error": "okx_tpsl_not_implemented"},
                    }
                else:
                    return {"result": "FAILED", "error": result.get("raw", {})}

            elif self.exchange == "aster":
                # Aster v3 EVM 签名交易,调用 ml_trade_service 模块函数
                # P0-3 修复: EXIT 动作不需要设置杠杆,直接平仓
                if action == "EXIT":
                    # P0: 平仓前先取消所有 TP/SL 挂单
                    try:
                        positions, pos_err = client._aster_fetch_positions()
                        if pos_err or not positions:
                            return {"result": "SKIP", "reason": f"无持仓可平: {pos_err}"}
                        pos_qty = None
                        close_side = None
                        for p in positions:
                            if coin.upper() in str(p.get('symbol', '')).upper():
                                amt = float(p.get('position_amt') or p.get('positionAmt') or 0)
                                if abs(amt) > 0:
                                    pos_qty = abs(amt)
                                    close_side = 'sell' if amt > 0 else 'buy'
                                    break
                        if pos_qty is None:
                            return {"result": "SKIP", "reason": "无持仓可平"}
                        
                        # 获取持仓数量用于取消对应数量的条件单
                        qty_to_cancel = pos_qty
                        
                        # 取消 STOP_MARKET 和 TAKE_PROFIT_MARKET 订单
                        # Aster 没有批量取消 API，需要遍历订单取消
                        open_orders = client._aster_fetch_open_orders() if hasattr(client, '_aster_fetch_open_orders') else []
                        cancelled_count = 0
                        for o in open_orders:
                            if coin.upper() in str(o.get('symbol', '')).upper():
                                o_type = o.get('type', '')
                                if o_type in ('STOP_MARKET', 'TAKE_PROFIT_MARKET'):
                                    try:
                                        client._aster_order_cancel(o.get('symbol'), o.get('orderId'))
                                        cancelled_count += 1
                                    except Exception:
                                        pass
                        logger.info(f"平仓前取消 TP/SL 挂单: {coin}, 已取消{cancelled_count}个")
                        
                        r = client._aster_market_order_qty(coin, close_side, pos_qty, reduce_only=True)
                    except Exception as e:
                        logger.warning(f"Aster 平仓异常({coin}): {e}")
                        return {"result": "FAILED", "error": str(e)}
                else:
                    # LONG/SHORT: 下单前设置杠杆(动态 1-5 倍)
                    target_lev = int(trade_order.get("leverage", DEFAULT_LEVERAGE))
                    target_lev = max(MIN_LEVERAGE, min(MAX_LEVERAGE, target_lev))
                    lev_ok = False
                    try:
                        lev_resp = client._aster_update_leverage(coin, target_lev)
                        lev_used = lev_resp.get('leverage_used') or lev_resp.get('leverage') if isinstance(lev_resp, dict) else None
                        # 已持仓币种会返回 skipped=True(杠杆无法修改)
                        if isinstance(lev_resp, dict) and lev_resp.get('skipped'):
                            # P0-3 修复: 验证现有杠杆是否在安全范围内
                            try:
                                positions, _ = client._aster_fetch_positions()
                                current_lev = None
                                if positions:
                                    for p in positions:
                                        if coin.upper() in str(p.get('symbol', '')).upper():
                                            current_lev = int(p.get('leverage') or p.get('leverageSys') or 0)
                                            break
                                if current_lev and current_lev > MAX_LEVERAGE:
                                    logger.error(f"Aster 杠杆超限({coin}): 现有{current_lev}x > 最大{MAX_LEVERAGE}x, 拒绝下单")
                                    return {"result": "FAILED", "error": f"现有杠杆{current_lev}x超过安全上限{MAX_LEVERAGE}x,拒绝下单"}
                                logger.warning(f"Aster 杠杆无法修改({coin}, 已持仓,现有杠杆={current_lev or '未知'}x): {lev_resp.get('reason')}")
                                lev_ok = True
                            except Exception as verify_err:
                                logger.warning(f"Aster 杠杆验证失败({coin}): {verify_err}, 保守拒绝下单")
                                return {"result": "FAILED", "error": f"杠杆验证失败: {verify_err}"}
                        else:
                            # P0-3 修复: 验证杠杆确实设置成功
                            if lev_used and int(lev_used) > MAX_LEVERAGE:
                                logger.error(f"Aster 杠杆设置异常({coin}): 设置后{lev_used}x > 最大{MAX_LEVERAGE}x")
                                return {"result": "FAILED", "error": f"杠杆设置后{lev_used}x超过安全上限{MAX_LEVERAGE}x"}
                            logger.info(f"Aster 杠杆设置: {coin} → {lev_used or target_lev}x")
                            lev_ok = True
                    except Exception as e:
                        err_msg = str(e)
                        logger.error(f"Aster 设置杠杆失败({coin}, {target_lev}x): {err_msg}, 拒绝下单")
                        # P0-3: 杠杆设置失败时硬阻断,不下单
                        return {"result": "FAILED", "error": f"杠杆设置失败({err_msg}),为避免高杠杆风险不下单"}

                    if not lev_ok:
                        return {"result": "FAILED", "error": "杠杆设置未确认,不下单"}

                    if action == "LONG":
                        r = client._aster_market_order(coin, 'long', float(position_size),
                                                       reduce_only=False, allow_adjust=True)
                    elif action == "SHORT":
                        r = client._aster_market_order(coin, 'short', float(position_size),
                                                       reduce_only=False, allow_adjust=True)
                    else:
                        return {"error": f"未知动作: {action}"}

                # Aster 成功判断:resp 中 status == FILLED
                resp = r.get('resp', {})
                ok = False
                order_id = None
                if isinstance(resp, dict):
                    inner = resp.get('data', resp)
                    if isinstance(inner, dict):
                        if inner.get('status') in ('FILLED', 'NEW', 'PARTIALLY_FILLED'):
                            ok = True
                            order_id = inner.get('orderId')

                if ok:
                    self._last_trade_time[coin] = time.time()
                    # P0-3: 更新 4h 周期去重标记（持久化跨实例共享）
                    self._mark_4h_traded(coin)

                    # P0: 开仓成功后自动下 TP/SL 条件单（黑天鹅底线防护）
                    tpsl_result = None
                    if action in ("LONG", "SHORT") and stop_loss and take_profit:
                        try:
                            time.sleep(0.5)
                            positions, _ = client._aster_fetch_positions()
                            pos_qty = None
                            for p in positions:
                                if coin.upper() in str(p.get('symbol', '')).upper():
                                    amt = float(p.get('position_amt') or p.get('positionAmt') or 0)
                                    if abs(amt) > 0:
                                        pos_qty = abs(amt)
                                        break

                            if pos_qty is None:
                                pos_qty = position_size

                            if action == "LONG":
                                sl_side = "sell"
                                tp_side = "sell"
                            else:
                                sl_side = "buy"
                                tp_side = "buy"

                            sl_result = client._aster_stop_market_order_qty(
                                coin, sl_side, pos_qty, float(stop_loss), reduce_only=True
                            )
                            tp_result = client._aster_take_profit_market_order_qty(
                                coin, tp_side, pos_qty, float(take_profit), reduce_only=True
                            )

                            sl_ok = sl_result.get('resp', {}).get('status') in ('NEW', 'FILLED', 'PARTIALLY_FILLED') if isinstance(sl_result.get('resp'), dict) else False
                            tp_ok = tp_result.get('resp', {}).get('status') in ('NEW', 'FILLED', 'PARTIALLY_FILLED') if isinstance(tp_result.get('resp'), dict) else False

                            if sl_ok and tp_ok:
                                logger.info(
                                    f"Aster TP/SL 条件单已设置: {coin} | "
                                    f"SL={stop_loss} TP={take_profit} | "
                                    f"qty={pos_qty}"
                                )
                                tpsl_result = {"ok": True, "sl_result": sl_result, "tp_result": tp_result}
                            else:
                                logger.warning(
                                    f"Aster TP/SL 条件单设置失败({coin}): "
                                    f"SL={sl_result.get('resp', {}).get('msg', 'unknown')}, "
                                    f"TP={tp_result.get('resp', {}).get('msg', 'unknown')}"
                                )
                                tpsl_result = {"ok": False, "sl_result": sl_result, "tp_result": tp_result}
                        except Exception as e:
                            logger.warning(f"Aster 设置 TP/SL 条件单异常({coin}): {e}")
                            tpsl_result = {"ok": False, "error": str(e)}

                    return {
                        "result": "SUCCESS",
                        "action": action,
                        "symbol": coin,
                        "exchange": "aster",
                        "ord_id": order_id,
                        "details": r,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "tpsl_result": tpsl_result,
                    }
                else:
                    return {"result": "FAILED", "error": r}

            else:
                return {"error": f"不支持的交易所: {self.exchange}"}

        except Exception as e:
            return {"result": "ERROR", "error": str(e)}

    def check_exit(self, symbol: str, entry_price: float, direction: str) -> Dict[str, Any]:
        """检查离场条件 — 时间衰减 + 市场状态自适应止损

        持仓时间策略:
            0-20 根 K 线: 宽松止损，给仓位空间发展
            20-50 根: 线性收紧
            50+ 根: 紧凑止损 + 移动止盈

        市场状态叠加:
            震荡市 (ranging): regime_factor=1.5，避免被噪声扫出
            趋势市 (trend):   regime_factor=1.0，紧凑保护利润

        P1: 返回动态计算的 stop_loss / take_profit，供 modify_tpsl 更新交易所条件单
        """
        market_data = self._fetch_market_data(symbol)
        price = market_data.get("price", 0)
        if price == 0:
            return {"exit": False, "reason": "无法获取价格"}

        # 获取实时 ATR%
        atr_pct = market_data.get("atr_pct", 0.02)

        # 计算持仓 K 线数（基于开仓时间）
        bars_held = self._estimate_bars_held(symbol)

        # 时间衰减因子: 0-20 根 = 1.5, 20-50 根线性衰减到 1.0, 50+ 根 = 1.0
        if bars_held <= 20:
            time_factor = 1.5
        elif bars_held <= 50:
            time_factor = 1.5 - (bars_held - 20) * (0.5 / 30)  # 1.5 → 1.0
        else:
            time_factor = 1.0

        # 市场状态因子：震荡市更宽，趋势市更紧
        regime = self._detect_regime_from_market_data(market_data, atr_pct)
        regime_factor = 1.5 if regime == "ranging" else 1.0

        # 币种波动率因子：以 BTC 为基准，高波动币种额外放宽
        symbol_vol_factor = self._calc_symbol_vol_factor(symbol, atr_pct)

        # 最终止损因子 = 时间因子 × 市场状态因子 × 币种波动率因子
        sl_factor = time_factor * regime_factor * symbol_vol_factor

        # 止损/止盈比例
        sl_pct = atr_pct * 1.0 * sl_factor    # 基础 1.0x ATR × 复合因子
        tp_pct = atr_pct * 2.0                  # 止盈固定 2.0x ATR

        if direction == "LONG":
            stop_loss = entry_price * (1 - sl_pct)
            take_profit = entry_price * (1 + tp_pct)

            # 50+ 根 K 线后启用移动止盈
            if bars_held > 20:
                profit_pct = (price - entry_price) / entry_price if entry_price > 0 else 0
                if profit_pct > 0:
                    # 移动止损：保本后逐步上移
                    trail_stop = entry_price * (1 + profit_pct * 0.5)  # 保护 50% 利润
                    stop_loss = max(stop_loss, trail_stop)

            if price <= stop_loss:
                return {"exit": True, "reason": f"止损触发: {price:.4f} <= {stop_loss:.4f} (持仓{bars_held}根, factor={sl_factor:.2f}={time_factor:.2f}×{regime_factor:.1f}×{symbol_vol_factor:.1f})", "exit_price": stop_loss,
                        "stop_loss": stop_loss, "take_profit": take_profit, "current_price": price}
            if price >= take_profit:
                return {"exit": True, "reason": f"止盈触发: {price:.4f} >= {take_profit:.4f} (持仓{bars_held}根)", "exit_price": take_profit,
                        "stop_loss": stop_loss, "take_profit": take_profit, "current_price": price}
        else:
            stop_loss = entry_price * (1 + sl_pct)
            take_profit = entry_price * (1 - tp_pct)

            if bars_held > 20:
                profit_pct = (entry_price - price) / entry_price if entry_price > 0 else 0
                if profit_pct > 0:
                    trail_stop = entry_price * (1 - profit_pct * 0.5)
                    stop_loss = min(stop_loss, trail_stop)

            if price >= stop_loss:
                return {"exit": True, "reason": f"止损触发: {price:.4f} >= {stop_loss:.4f} (持仓{bars_held}根, factor={sl_factor:.2f}={time_factor:.2f}×{regime_factor:.1f}×{symbol_vol_factor:.1f})", "exit_price": stop_loss,
                        "stop_loss": stop_loss, "take_profit": take_profit, "current_price": price}
            if price <= take_profit:
                return {"exit": True, "reason": f"止盈触发: {price:.4f} <= {take_profit:.4f} (持仓{bars_held}根)", "exit_price": take_profit,
                        "stop_loss": stop_loss, "take_profit": take_profit, "current_price": price}

        return {
            "exit": False,
            "reason": f"继续持有 (持仓{bars_held}根, regime={regime}, SL factor={sl_factor:.2f}={time_factor:.2f}×{regime_factor:.1f}×{symbol_vol_factor:.1f}, atr={atr_pct:.4f})",
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "current_price": price,
            "bars_held": bars_held,
            "regime": regime,
            "sl_factor": round(sl_factor, 4),
        }

    def _estimate_bars_held(self, symbol: str) -> int:
        """估算持仓 K 线数

        基于 _last_trade_time 记录的开仓时间，按 1h 周期折算。
        如果没有记录，返回 0（按最宽松处理）。
        """
        entry_ts = self._last_trade_time.get(symbol, 0)
        if entry_ts == 0:
            return 0
        elapsed_hours = (time.time() - entry_ts) / 3600.0
        return max(1, int(elapsed_hours))

    def _detect_regime_from_market_data(self, market_data: Dict[str, Any], atr_pct: float) -> str:
        """从实时行情判断市场状态

        震荡市 (ranging): EMA 纠缠、价格在均线间反复
        趋势市 (trend):   EMA 多头/空头排列

        回退：用 ATR% 阈值判断
        """
        try:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            classifier = ScenarioClassifier()
            scenario = classifier.classify(market_data)
            if scenario.trend in ("BULL", "BEAR"):
                return "trend"
            return "ranging"
        except Exception:
            # 回退：ATR% 阈值
            if atr_pct > 0.03:
                return "trend"
            return "ranging"

    def _calc_symbol_vol_factor(self, symbol: str, atr_pct: float) -> float:
        """计算币种波动率因子（以 BTC 为基准）

        比较当前币种 ATR% 与 BTC ATR%，波动率越高的币种给越宽的止损缓冲。

        ratio = coin_atr / btc_atr
        ratio <= 1.0: 0.8  (比 BTC 还稳定，收紧)
        ratio 1.0-2.0: 1.0 (与 BTC 相当)
        ratio 2.0-3.0: 1.2 (中等高波动)
        ratio > 3.0:   1.4 (极端高波动)
        """
        symbol_upper = symbol.upper().strip()

        # BTC 自身是基准
        if symbol_upper in ("BTC", "BTCUSDT"):
            return 1.0

        # 获取 BTC 基准 ATR%
        btc_atr_pct = self._get_btc_atr_pct()
        if btc_atr_pct <= 0:
            # 无法获取 BTC 数据，用硬编码回退
            HIGH_VOL = {"SOL", "AVAX", "MATIC", "DOT", "LINK", "DOGE", "SHIB", "OP", "ARB"}
            if symbol_upper in HIGH_VOL:
                return 1.2
            return 1.0

        ratio = atr_pct / btc_atr_pct if btc_atr_pct > 0 else 1.0

        if ratio <= 1.0:
            return 0.8
        elif ratio <= 2.0:
            return 1.0
        elif ratio <= 3.0:
            return 1.2
        else:
            return 1.3

    _btc_atr_cache: Dict[str, Any] = {"ts": 0, "val": 0.0}

    def _get_btc_atr_pct(self) -> float:
        """获取 BTC 的 ATR%（带 5 分钟缓存）"""
        import time as _time
        now = _time.time()
        if self._btc_atr_cache["ts"] > 0 and (now - self._btc_atr_cache["ts"]) < 300:
            return self._btc_atr_cache["val"]

        try:
            btc_data = self._fetch_market_data("BTC")
            btc_atr = btc_data.get("atr_pct", 0.0)
            if btc_atr > 0:
                self._btc_atr_cache = {"ts": now, "val": btc_atr}
                return btc_atr
        except Exception:
            pass

        return 0.0

    def run_auto_trade(self, symbol: str) -> Dict[str, Any]:
        """运行完整自动化交易流程"""
        if not self.is_enabled():
            return {"result": "SKIP", "reason": "自动交易已禁用"}

        # P1-2: 检查该 symbol 是否因连续降级被暂停
        if symbol in self._suspended_symbols:
            logger.warning(f"Symbol {symbol} 因连续 {self.FALLBACK_SUSPEND_THRESHOLD} 次降级路径被暂停交易")
            return {"result": "SKIP", "reason": f"symbol {symbol} 已暂停(连续降级)"}

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

            # TradingAgent.run() 把最终决策放在顶层 action/confidence
            # 同时尝试从 outputs.A5.trade_order 获取详细的订单参数(可能为空)
            a5_output = analysis.get("outputs", {}).get("A5", {})
            trade_order = a5_output.get("trade_order", {})
            direction = trade_order.get("action") or analysis.get("action", "HOLD")

            # 置信度优先从顶层取(TradingAgent 最终决策),其次从 A5 取
            confidence = analysis.get("confidence") or a5_output.get("confidence", 0)

            # P1-2: 降级路径检测与告警
            is_fallback = not trade_order or not trade_order.get("entry_price")
            if is_fallback and direction != "HOLD":
                self._fallback_counts[symbol] = self._fallback_counts.get(symbol, 0) + 1
                count = self._fallback_counts[symbol]
                logger.warning(f"Symbol {symbol} 降级路径触发 (连续 {count}/{self.FALLBACK_SUSPEND_THRESHOLD})")
                if count >= self.FALLBACK_SUSPEND_THRESHOLD:
                    self._suspended_symbols.add(symbol)
                    logger.error(f"Symbol {symbol} 连续 {count} 次降级,已暂停交易")
                    result["steps"].append({"step": "decision", "status": "suspended", "reason": f"连续 {count} 次降级路径"})
                    result["final_result"] = "SUSPENDED_FALLBACK"
                    return result
            else:
                # 正常 trade_order,重置降级计数
                if self._fallback_counts.get(symbol, 0) > 0:
                    logger.info(f"Symbol {symbol} 降级计数重置 (A5 正常输出)")
                self._fallback_counts[symbol] = 0

            # 如果 A5 没有输出 trade_order 但顶层有方向,用缓存的 market_data 构造最小订单
            if not trade_order and direction != "HOLD":
                market_data = self._current_context.get("market_data", {})
                price = market_data.get("price", 0)
                # 价格为 0 说明行情数据获取失败(如 symbol 不存在),跳过下单
                if price <= 0:
                    result["steps"].append({"step": "decision", "status": "hold", "reason": f"行情数据无效(price={price})"})
                    result["final_result"] = "HOLD"
                    return result
                atr = market_data.get("atr14", 0) or price * 0.02
                atr_pct = (atr / price) if price > 0 else 0.02
                # 基于账户余额动态计算 position_size(不超过账户 20%,默认 10 USDT)
                position_size = 10.0
                try:
                    client = self.get_exchange_client()
                    if client and self.exchange == "aster":
                        summary = client._aster_fetch_account_summary()
                        if summary.get("ok"):
                            s = summary.get("summary", {}) or {}
                            eq = float(s.get("totalWalletBalance", 0) or 0)
                            if eq > 0:
                                # 用 18% 留余量,避免浮点精度触发 risk_check 的 20% 上限
                                position_size = round(min(10.0, eq * 0.18), 2)
                except Exception as e:
                    logger.warning(f"获取账户余额失败,用默认 position_size=10: {e}")
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
                    "position_size": position_size,
                    "leverage": calc_dynamic_leverage(confidence),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "risk_per_trade": position_size * atr_pct,
                }
                logger.info(f"构造最小 trade_order (A5 无输出): {direction} {symbol} @ {price}, size={position_size}, leverage={trade_order['leverage']}x, SL={stop_loss}, TP={take_profit}")

            if direction == "HOLD":
                result["steps"].append({"step": "decision", "status": "hold", "reason": "方向为HOLD"})
                result["final_result"] = "HOLD"
                return result

            # 对称门槛：多空同等置信度要求
            threshold = 0.62 if direction == "SHORT" else 0.62
            if confidence < threshold:
                result["steps"].append({"step": "decision", "status": "rejected", "reason": f"置信度不足({confidence:.2f} < {threshold}, 方向={direction})"})
                result["final_result"] = "CONFIDENCE_TOO_LOW"
                return result

            # 4h 周期去重：1h 调度但开仓基于 4h 指标，避免同一 4h 周期内重复开仓
            current_ts = int(time.time() * 1000)
            current_4h_ts = (current_ts // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
            last_4h_ts = self._last_trade_4h_ts.get(symbol, 0)
            if last_4h_ts == current_4h_ts:
                result["steps"].append({"step": "decision", "status": "rejected", "reason": f"4h 周期内已开仓(当前周期={current_4h_ts}, 上次={last_4h_ts})"})
                result["final_result"] = "DUPLICATE_4H"
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

            # P0-1 修复：离场时回填实际收益率到反馈收集器（更新开仓记录，而非追加新记录）
            exit_price = exit_result.get("exit_price", entry_price)
            if entry_price > 0:
                if direction == "LONG":
                    ret = (exit_price - entry_price) / entry_price
                else:
                    ret = (entry_price - exit_price) / entry_price
                ret -= 0.0008  # 扣手续费
            else:
                ret = 0.0
            # P0-1: 使用 update_exit_feedback 回填开仓记录，闭合反馈环
            self.update_exit_feedback(symbol, entry_price, exit_price, ret)
            self._try_trigger_evolution()

        return exit_result

    def run_exit_check_all(self) -> Dict[str, Any]:
        """检查所有持仓的离场条件并执行离场

        P0-2 修复：调度器定期调用此方法，检查所有未平仓持仓的
        止损/止盈条件，执行离场并回填实际收益率到反馈收集器。

        P1 动态调整：未触发离场时，根据时间衰减/移动止损动态更新交易所 TP/SL 条件单，
        确保即使程序离线，条件单也能反映最新风控状态。
        """
        client = self.get_exchange_client()
        if not client:
            return {"error": "无法连接交易所"}

        # 获取所有持仓
        positions = []
        try:
            if self.exchange == "aster":
                pos_list, err = client._aster_fetch_positions()
                if err:
                    return {"error": f"获取持仓失败: {err}"}
                positions = pos_list or []
            elif self.exchange == "hyperliquid":
                acct = client.get_account()
                for coin, pos in acct.get("positions", {}).items():
                    size = float(pos.get("size", 0))
                    if abs(size) > 0:
                        positions.append({
                            "symbol": coin,
                            "position_amt": size,
                            "entry_price": float(pos.get("entry_px", 0)),
                        })
            elif self.exchange == "okx":
                # OKX 通过 get_account_status 获取持仓
                status = self.get_account_status()
                if "error" in status:
                    return status
                # OKX spot 通常无持仓
                positions = []
        except Exception as e:
            logger.warning(f"获取持仓异常: {e}")
            return {"error": f"获取持仓异常: {e}"}

        if not positions:
            logger.info("离场检查: 无持仓")
            return {"result": "NO_POSITIONS", "checked": 0, "timestamp": datetime.now().isoformat()}

        results = []
        exit_count = 0
        tpsl_updated = 0

        for pos in positions:
            symbol = str(pos.get("symbol", "")).replace("-USDT", "").replace("-SWAP", "")
            entry_price = float(pos.get("entry_price") or pos.get("entryPx") or 0)
            amt = float(pos.get("position_amt") or pos.get("positionAmt") or 0)

            if entry_price <= 0 or abs(amt) <= 0:
                continue

            direction = "LONG" if amt > 0 else "SHORT"

            # 检查离场条件（同时返回动态 SL/TP）
            exit_result = self.check_exit(symbol, entry_price, direction)

            if exit_result.get("exit"):
                # 执行离场
                exec_result = self.execute_trade({
                    "action": "EXIT",
                    "coin": symbol,
                    "entry_price": entry_price,
                    "direction": direction,
                })

                # P0-1 修复：回填实际收益率（更新开仓记录，闭合反馈环）
                exit_price = exit_result.get("exit_price", entry_price)
                if entry_price > 0:
                    if direction == "LONG":
                        ret = (exit_price - entry_price) / entry_price
                    else:
                        ret = (entry_price - exit_price) / entry_price
                    ret -= 0.0008  # 手续费
                else:
                    ret = 0.0

                # P0-1: 使用 update_exit_feedback 回填开仓记录
                self.update_exit_feedback(symbol, entry_price, exit_price, ret)

                results.append({
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return": round(ret, 4),
                    "executed": True,
                    "reason": exit_result.get("reason", ""),
                    "exec_result": exec_result,
                })
                exit_count += 1
                logger.info(f"离场执行: {symbol} {direction} entry={entry_price} exit={exit_price} ret={ret:.4f} reason={exit_result.get('reason', '')}")
            else:
                # P1: 未离场时，动态更新交易所 TP/SL 条件单
                new_sl = exit_result.get("stop_loss")
                new_tp = exit_result.get("take_profit")
                tpsl_result = None

                if new_sl and new_tp and self.exchange == "hyperliquid" and hasattr(client, "modify_tpsl"):
                    try:
                        tpsl_result = client.modify_tpsl(
                            coin=symbol,
                            new_sl=float(new_sl),
                            new_tp=float(new_tp),
                            is_market=True,
                        )
                        if tpsl_result.get("ok"):
                            tpsl_updated += 1
                            logger.info(
                                f"TP/SL 已更新: {symbol} | "
                                f"SL={new_sl:.4f} TP={new_tp:.4f} | "
                                f"action={tpsl_result.get('action', 'modify')}"
                            )
                        else:
                            logger.debug(f"TP/SL 更新未变化或失败({symbol}): {tpsl_result.get('error')}")
                    except Exception as e:
                        logger.warning(f"TP/SL 动态更新异常({symbol}): {e}")
                        tpsl_result = {"ok": False, "error": str(e)}

                results.append({
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry_price,
                    "exit": False,
                    "reason": exit_result.get("reason", "继续持有"),
                    "stop_loss": new_sl,
                    "take_profit": new_tp,
                    "tpsl_result": tpsl_result,
                })

        # 如果有离场，触发进化
        if exit_count > 0:
            self._try_trigger_evolution()

        return {
            "result": "EXIT_CHECK_DONE",
            "checked": len(results),
            "exits": exit_count,
            "holds": len(results) - exit_count,
            "tpsl_updated": tpsl_updated,
            "details": results,
            "timestamp": datetime.now().isoformat(),
        }


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
