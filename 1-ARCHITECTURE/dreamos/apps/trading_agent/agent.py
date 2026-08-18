"""
Dreambuddy OS — Trading Agent 应用

将 S-A-C-G 四层内核串联为完整的交易 Agent：
    S (Sense)    → 意图识别：用户输入/市场数据 → 交易意图
    A (Arrange)  → 图编排：根据意图从注册表选节点、分配预算、构建执行图
    C (Compute)  → 执行：运行节点、反射决策、结果聚合
    G (GraphStore) → 存储：状态快照、历史记录、上下文压缩

用法:
    from dreamos.apps.trading_agent import TradingAgent

    agent = TradingAgent()
    result = agent.run(
        user_input="BTC 现在怎么看？",
        market_data={"price": 65000, "rsi14": 45, ...},
    )
    print(result["action"], result["confidence"])
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from dreamos.shared.state import State, new_state
from dreamos.shared.utils import gen_cycle_id

from dreamos.core.sense import IntentEngine, IntentResult
from dreamos.core.arrange import GraphPlanner, ExecutionPlan
from dreamos.core.compute import GraphExecutor, ExecutionReport
from dreamos.core.graph_store import GraphStore
from dreamos.budget import GlobalBudgetManager, CostTracker

from dreamos.registry import NodeRegistry, get_default_registry

from dreamos.core.capability import (
    CapabilityRegistry,
    CapabilityRouter,
    RoutingResult,
    get_default_capability_registry,
)
from dreamos.capabilities.trading import TradingCapability


class TradingAgent:
    """交易 Agent — S-A-C-G 全链路编排

    核心职责:
        1. 接收用户输入 + 市场数据
        2. S 层识别意图
        3. A 层编排执行图
        4. C 层执行
        5. G 层持久化
        6. 返回最终结果

    设计:
        - 节点可插拔：通过 Registry 管理，新增节点不影响 Agent
        - 预算全局管控：GlobalBudgetManager 统一分配
        - 状态可追溯：GraphStore 保存每个周期的完整快照
        - 自我进化：历史数据驱动 Evolution 持续优化
        - L0 工作记忆：WorkingMemoryManager 管理任务上下文
    """

    def __init__(self,
                 registry: Optional[NodeRegistry] = None,
                 capability_registry: Optional[CapabilityRegistry] = None,
                 budget_mode: str = "standard",
                 auto_register: bool = True,
                 default_capability: str = "trading",
                 enable_working_memory: bool = True):
        self.registry = registry or get_default_registry()
        self.capability_registry = capability_registry or get_default_capability_registry()
        self.capability_registry.attach_node_registry(self.registry)

        if auto_register:
            self._register_default_capability()
            self._import_skills()

        # 能力域路由器
        self.capability_router = CapabilityRouter(
            registry=self.capability_registry,
            default_capability_id=default_capability,
        )

        # 内核四层
        self.intent_engine = IntentEngine()
        self.graph_planner = GraphPlanner(registry=self.registry)
        self.graph_executor = GraphExecutor(registry=self.registry)
        # G 层默认启用文件持久化，确保跨会话检查点和历史不丢失
        default_storage_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "graph_store"
        )
        self.graph_store = GraphStore(storage_dir=default_storage_dir)

        # 横切关注点
        self.budget = GlobalBudgetManager(mode=budget_mode)
        self.cost_tracker = CostTracker()

        # L0 工作记忆（可选启用）
        self._enable_working_memory = enable_working_memory
        self.working_memory = None
        if enable_working_memory:
            try:
                import sys
                from pathlib import Path as _Path
                _root = _Path(__file__).resolve().parents[4]
                _wm_path = str(_root / "4-MEMORY" / "9-工具与接口")
                if _wm_path not in sys.path:
                    sys.path.insert(0, _wm_path)
                from working_memory_manager import WorkingMemoryManager
                self._wm_class = WorkingMemoryManager
            except ImportError:
                self._wm_class = None
                logger.info("WorkingMemoryManager 未安装，L0 工作记忆已禁用")

        # 统计
        self._cycle_count = 0

    def _inject_wm_to_llm_recognizer(self) -> None:
        """将工作记忆注入到 IntentEngine 的 LLMBasedRecognizer"""
        from dreamos.core.sense.recognizers import LLMBasedRecognizer
        
        for recognizer in self.intent_engine._recognizers:
            if isinstance(recognizer, LLMBasedRecognizer):
                recognizer.set_working_memory(self.working_memory)
                break

    # ── L0 工作记忆辅助方法 ────────────────────────

    def _init_working_memory(self, cycle_id: str, user_input: str,
                              market_data: Dict, context: Dict) -> None:
        """初始化 L0 工作记忆（在每次 run() 开始时调用）"""
        if not self._enable_working_memory or self._wm_class is None:
            return

        try:
            wm = self._wm_class(task_id=cycle_id)
            wm.set_task(
                title=f"交易分析: {user_input or market_data.get('symbol', 'N/A')}",
                goal=f"symbol={market_data.get('symbol', 'BTC')}, price={market_data.get('price', 0)}",
            )
            wm.set_context("user_input", user_input)
            wm.set_context("symbol", market_data.get("symbol", "BTC"))
            wm.set_context("price", str(market_data.get("price", 0)))
            self.working_memory = wm
            
            # 同步注入到 LLMBasedRecognizer（让 LLM 可以读取工作记忆）
            self._inject_wm_to_llm_recognizer()
        except Exception as e:
            logger.debug(f"工作记忆初始化失败: {e}")
            self.working_memory = None

    def _wm_set_context(self, key: str, value: Any) -> None:
        """写入上下文到工作记忆（静默失败）"""
        if self.working_memory is None:
            return
        try:
            self.working_memory.set_context(key, value)
        except Exception:
            pass

    def _wm_set_scratch(self, key: str, value: Any) -> None:
        """写入草稿到工作记忆（静默失败）"""
        if self.working_memory is None:
            return
        try:
            self.working_memory.set_scratch(key, value)
        except Exception:
            pass

    def _wm_checkpoint(self, name: str = "") -> None:
        """保存工作记忆检查点"""
        if self.working_memory is None:
            return
        try:
            self.working_memory.checkpoint(name)
        except Exception:
            pass

    def _distill_to_app_memory(self, result: Dict, market_data: Dict) -> None:
        """L0→L1 蒸馏：将本次周期经验上升到应用记忆"""
        if self.working_memory is None:
            return

        try:
            symbol = market_data.get("symbol", "BTC")
            action = result.get("action", "HOLD")
            confidence = result.get("confidence", 0)
            intent_type = result.get("intent", {}).get("type", "unknown")

            lesson = (
                f"交易分析 [{symbol}]: {intent_type} → {action} "
                f"(confidence={confidence:.2f}, "
                f"latency={result.get('latency_ms', 0):.0f}ms, "
                f"tokens={result.get('tokens_used', 0)})"
            )

            self.working_memory.update_status("completed")
            self.working_memory.distill_to_app_memory(
                target_memory_id="AM-TRD-001",
                lesson_content=lesson,
                confidence=min(confidence, 0.95),
                tags=[symbol, intent_type, action, "trading_agent"],
            )
        except Exception as e:
            logger.debug(f"工作记忆蒸馏失败: {e}")

    @property
    def working_memory_status(self) -> Dict[str, Any]:
        """获取工作记忆状态"""
        if self.working_memory is None:
            return {"enabled": False}
        return self.working_memory.get_stats()

    # ── 能力域与 SKILL 注册 ────────────────────────

    def _register_default_capability(self) -> None:
        """注册默认能力域（当前为交易能力域）"""
        if "trading" not in self.capability_registry:
            trading_cap = TradingCapability()
            self.capability_registry.register(trading_cap)

    def run(self,
            user_input: str = "",
            market_data: Optional[Dict[str, Any]] = None,
            context: Optional[Dict[str, Any]] = None,
            budget_mode: Optional[str] = None) -> Dict[str, Any]:
        """执行一次完整的交易分析周期

        Args:
            user_input: 用户自然语言输入
            market_data: 市场数据（价格/指标等）
            context: 额外上下文
            budget_mode: 临时覆盖预算模式

        Returns:
            交易决策结果字典:
            {
                "cycle_id": str,
                "intent": {...},
                "plan": {...},
                "execution": {...},
                "action": "LONG" | "SHORT" | "HOLD",
                "confidence": float,
                "rationale": [str],
                "tokens_used": int,
                "latency_ms": float,
            }
        """
        cycle_id = gen_cycle_id("trade")
        start_time = time.time()
        market_data = market_data or {}
        context = context or {}

        # ── 0. 预算开始 + 初始化 L0 工作记忆 ────────────────────────
        self.budget.begin_cycle(cycle_id)
        self._init_working_memory(cycle_id, user_input, market_data, context)

        # ── 1. S 层：意图识别 ─────────────────
        intent_result = self._sense(user_input, market_data, context)

        # ── 1.2 能力域路由 ───────────────────
        routing_result = self._route_capability(intent_result)
        if not routing_result.success:
            logger.warning(
                f"能力域路由失败: {routing_result.rationale}，回退到默认交易能力域"
            )

        # ── 1.3 写入 S 层结果到工作记忆 ─────────────────
        self._wm_set_context("intent_type", intent_result.intent_type)
        self._wm_set_context("intent_confidence", f"{intent_result.confidence:.2f}")
        self._wm_set_context("recommended_chain", intent_result.recommended_chain)
        self._wm_set_scratch("intent_result", {
            "type": intent_result.intent_type,
            "confidence": intent_result.confidence,
            "chain": intent_result.recommended_chain,
            "rationale": getattr(intent_result, "rationale", ""),
        })

        # ── 2. 构建 State ───────────────────
        state = new_state(cycle_id=cycle_id)
        state.inputs = {
            "user_input": user_input,
            "mkt": market_data,
            "context": context,
        }
        state.market_data = market_data  # type: ignore[attr-defined]

        # P0-4 修复: 确保 market_data 中有 "coin" 字段
        # A5/A3/F1 节点通过 mkt.get("coin", "BTC") 读取币种,
        # 但 market_data 只有 "symbol" 字段,导致所有币种开仓都下到 BTC
        if "coin" not in market_data and "symbol" in market_data:
            market_data["coin"] = market_data["symbol"]

        # ── 1.5 注入 Freqtrade 量化策略信号 ───────────────────
        freqtrade_signal = self._inject_freqtrade_signal(market_data)
        if freqtrade_signal:
            state.market_data["freqtrade_signal"] = freqtrade_signal

        # ── 1.6 注入基本面数据（F 链数据源）─────────────────────
        self._inject_fundamental_data(state.market_data)

        state.intent = {
            "intent_type": intent_result.intent_type,
            "confidence": intent_result.confidence,
            "recommended_chain": intent_result.recommended_chain,
            "base_chain": getattr(intent_result, "base_chain", []),
            "extend_nodes": getattr(intent_result, "extend_nodes", []),
            "rationale": getattr(intent_result, "rationale", ""),
            "recognizer": getattr(intent_result, "recognizer", ""),
            "scenario_id": context.get("scenario_id") or self._classify_scenario(market_data),
            "enable_subsystem": context.get("enable_subsystem", True),
            "capability_id": routing_result.capability_id,
            "capability_match_type": routing_result.match_type,
            "capability_config": routing_result.capability_config,
        }

        # P0-5 修复: 当 auto_trader 已查询编排记忆表时, 用记忆表的节点顺序覆盖 base_chain
        # 原问题: auto_trader 查询了记忆表得到 choice.nodes=["C1","C2","C3","A2","A4","A5","A9"],
        # 但只放到 context["recommended_orchestration"], agent.run 没有读取它,
        # 导致 GraphPlanner 收到 base_chain=["A1","A2",...] 的错误顺序,
        # A2 在 C1 之前执行, 读不到技术信号, 触发 REDO 超限
        recommended_orch = context.get("recommended_orchestration") or {}
        orch_nodes = recommended_orch.get("nodes") or []
        if orch_nodes:
            state.intent["base_chain"] = list(orch_nodes)
            state.intent["extend_nodes"] = []

        # ── 2.1 写入 State 上下文到工作记忆 ─────────────────
        self._wm_set_context("symbol", market_data.get("symbol", "BTC"))
        self._wm_set_context("price", str(market_data.get("price", 0)))
        scenario_id = state.intent.get("scenario_id", "")
        if scenario_id:
            self._wm_set_context("scenario_id", scenario_id)

        # ── 3. A 层：图编排 ──────────────────
        plan = self._arrange(intent_result, state)

        # ── 3.1 写入 A 层结果到工作记忆 ─────────────────
        self._wm_set_scratch("arrange_result", {
            "chain": getattr(plan, "planned_chain", ""),
            "node_count": len(plan.node_ids) if hasattr(plan, "node_ids") else 0,
            "node_ids": plan.node_ids if hasattr(plan, "node_ids") else [],
            "budget_allocated": getattr(plan.budget, "total", 0) if hasattr(plan, "budget") else 0,
        })

        # ── 4. C 层：执行 ────────────────────
        report = self._compute(state, plan)

        # ── 4.1 写入 C 层结果到工作记忆 ─────────────────
        self._wm_set_scratch("compute_result", {
            "executed_nodes": getattr(report, "executed_nodes", 0),
            "success_nodes": getattr(report, "success_nodes", 0),
            "skipped_nodes": getattr(report, "skipped_nodes", 0),
            "total_nodes": getattr(report, "total_nodes", 0),
            "total_tokens": getattr(report, "total_tokens", 0),
            "early_terminated": getattr(report, "early_terminated", False),
        })

        # ── 5. G 层：存储 ────────────────────
        self._store(state, report)

        # ── 5.1 工作记忆检查点 ─────────────────
        self._wm_checkpoint("post_store")

        # ── 6. 预算结算 ──────────────────────
        total_tokens = getattr(report, "total_tokens", 0)
        self.budget.end_cycle(tokens_total=total_tokens,
                              status="success" if state.final_action else "degraded")

        # ── 7. 组装结果 ──────────────────────
        latency_ms = (time.time() - start_time) * 1000

        final_action = getattr(report, "final_action", state.final_action or "HOLD")
        final_confidence = getattr(report, "final_confidence", state.final_confidence)

        # ── 7.1 写入最终结果到工作记忆 ─────────────────
        self._wm_set_context("final_action", final_action)
        self._wm_set_context("final_confidence", f"{final_confidence:.2f}")
        self._wm_set_context("latency_ms", f"{latency_ms:.0f}")
        self._wm_set_scratch("final_result", {
            "action": final_action,
            "confidence": final_confidence,
            "latency_ms": round(latency_ms, 1),
            "tokens_used": total_tokens,
        })

        # 收集所有节点输出
        outputs = self._collect_outputs(state)

        # 如果 A5 未产出 trade_order，从最终决策合成
        a5_out = outputs.get("A5", {})
        if not a5_out.get("trade_order"):
            synth_order = self._synthesize_trade_order(
                action=final_action,
                confidence=final_confidence,
                market_data=market_data,
                state=state,
            )
            if synth_order:
                a5_out["trade_order"] = synth_order
                a5_out["_synthesized"] = True
                a5_out.setdefault("rationale", ["[A5合成] 链路未包含A5，从最终决策合成交易指令"])
                outputs["A5"] = a5_out

        result = {
            "cycle_id": cycle_id,
            "intent": {
                "type": intent_result.intent_type,
                "confidence": intent_result.confidence,
                "recognizer": getattr(intent_result, "recognizer", ""),
            },
            "capability": {
                "capability_id": routing_result.capability_id,
                "match_type": routing_result.match_type,
                "match_score": routing_result.match_score,
                "rationale": routing_result.rationale,
            },
            "plan": {
                "chain": getattr(plan, "planned_chain", ""),
                "nodes": plan.node_ids if hasattr(plan, "node_ids") else [],
                "budget_allocated": getattr(plan.budget, "total", 0) if hasattr(plan, "budget") else 0,
            },
            "execution": {
                "nodes_planned": len(plan.node_ids) if hasattr(plan, "node_ids") else 0,
                "nodes_executed": getattr(report, "executed_nodes", 0),
                "success_count": getattr(report, "success_nodes", 0),
                "skipped_count": getattr(report, "skipped_nodes", 0),
                "total_nodes": getattr(report, "total_nodes", 0),
                "total_tokens": total_tokens,
                "early_terminated": getattr(report, "early_terminated", False),
                "termination_reason": getattr(report, "termination_reason", ""),
            },
            "action": final_action,
            "confidence": final_confidence,
            "rationale": self._collect_rationale(state),
            "tokens_used": total_tokens,
            "latency_ms": round(latency_ms, 1),
            "budget_status": self.budget.status(),
            "outputs": outputs,
        }

        self._cycle_count += 1

        # ── 8. L0→L1 蒸馏：将本次周期经验上升到应用记忆 ─────────────────
        self._distill_to_app_memory(result, market_data)

        return result

    # ── S 层 ────────────────────────────────

    def _classify_scenario(self, market_data: Dict) -> Optional[str]:
        """从 market_data 自动分类场景

        使用 ScenarioClassifier 对市场数据进行三维分类
        （趋势×波动率×动量），返回 scenario_id 供编排器使用。
        """
        if not market_data or "price" not in market_data:
            return None
        try:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            if not hasattr(self, "_scenario_classifier"):
                self._scenario_classifier = ScenarioClassifier()
            result = self._scenario_classifier.classify(market_data)
            return result.scenario_id
        except Exception as e:
            logger.debug(f"场景分类失败: {e}")
            return None

    def _sense(self, user_input: str, market_data: Dict,
               context: Dict) -> IntentResult:
        """S 层：意图识别"""
        return self.intent_engine.recognize(
            user_message=user_input,
            market=market_data,
            context=context,
        )

    def _route_capability(self, intent_result: IntentResult) -> RoutingResult:
        """能力域路由：根据意图选择最优能力域

        路由策略（文档 §7.1.1:
            1. exact: 意图类型精确匹配能力域 supported_intents
            2. fuzzy: 关键词与能力域 tags 匹配
            3. fallback: 回退到默认能力域（trading）
            4. none: 无匹配，返回失败

        Returns:
            RoutingResult: 路由决策结果
        """
        return self.capability_router.route(intent_result)

    def _inject_freqtrade_signal(self, market_data: Dict) -> Optional[Dict[str, Any]]:
        """注入 Freqtrade 量化策略信号

        从 10-经典指标系统的 Freqtrade 策略池获取综合信号，
        作为 Dream OS 的量化信号源之一。
        """
        if not os.environ.get("DREAMOS_FREQTRADE_SIGNAL", "1") == "1":
            return None

        symbol = market_data.get("symbol", "BTC")
        try:
            from dreamos.capabilities.trading.freqtrade_signal_adapter import FreqtradeSignalAdapter

            if not hasattr(self, "_freqtrade_adapter"):
                self._freqtrade_adapter = FreqtradeSignalAdapter()

            signal = self._freqtrade_adapter.get_signal(symbol)
            if signal.get("direction") != "HOLD" or signal.get("strategy_count", 0) > 0:
                logger.info(
                    f"Freqtrade信号: {symbol} | {signal['direction']} | "
                    f"conf={signal['confidence']:.1%} | "
                    f"策略数={signal.get('strategy_count', 0)} | "
                    f"多={signal.get('long_votes', 0)}/空={signal.get('short_votes', 0)}"
                )
                return signal
        except Exception as e:
            logger.warning(f"Freqtrade信号注入失败: {e}")

        return None

    def _inject_fundamental_data(self, market_data: Dict[str, Any]) -> None:
        """注入基本面数据到 market_data（F 链数据源）

        调用 FundamentalDataInjector 采集 30+ 基本面指标（ETF 流量、MVRV、链上数据等）
        并扁平化注入到 market_data，供 F2-F5 节点读取。

        环境变量:
            DREAMOS_FUNDAMENTAL_INJECTION=1 (默认启用)
        """
        if os.environ.get("DREAMOS_FUNDAMENTAL_INJECTION", "1") != "1":
            return

        symbol = market_data.get("symbol", "BTC")
        try:
            from dreamos.capabilities.trading.fundamental_injector import FundamentalDataInjector

            if not hasattr(self, "_fundamental_injector"):
                self._fundamental_injector = FundamentalDataInjector()

            injected = self._fundamental_injector.inject(market_data, symbol)
            if injected:
                logger.info(
                    f"基本面数据已注入: {symbol} | "
                    f"字段数={injected.get('_fundamental_field_count', 0)} | "
                    f"source={injected.get('_fundamental_source', 'unknown')}"
                )
            else:
                logger.warning(f"基本面数据注入返回空: {symbol}，F链将降级为HOLD")
                market_data["_f_chain_degraded"] = True
        except Exception as e:
            logger.warning(f"基本面数据注入失败: {e}，F链将降级为HOLD")
            market_data["_f_chain_degraded"] = True

    # ── A 层 ────────────────────────────────

    def _arrange(self, intent: IntentResult, state: State) -> ExecutionPlan:
        """A 层：图编排"""
        return self.graph_planner.plan(state)

    # ── C 层 ────────────────────────────────

    def _compute(self, state: State, plan: ExecutionPlan) -> ExecutionReport:
        """C 层：执行图（集成 G 层自动检查点）"""
        from dreamos.core.arrange.execution_graph import SequentialGraph

        graph = SequentialGraph()
        for meta in plan.selected_nodes:
            node = self.registry.get(meta.node_id)
            if node:
                graph.add_node(node)

        return self.graph_executor.execute(
            graph=graph,
            state=state,
            plan=plan,
            graph_store=self.graph_store,
        )

    # ── G 层 ────────────────────────────────

    def _store(self, state: State, report: ExecutionReport) -> None:
        """G 层：保存状态与历史"""
        # 保存检查点
        self.graph_store.checkpoint(state, node_id="__end__", metadata={"tag": "end_of_cycle"})

        # 记录历史
        self.graph_store.record(
            state=state,
            report={
                "total_tokens": getattr(report, "total_tokens", 0),
                "total_latency_ms": getattr(report, "total_latency_ms", 0),
                "success_rate": getattr(report, "success_rate", 0),
                "nodes_executed": getattr(report, "nodes_executed", 0),
            },
        )

    # ── 便捷方法 ────────────────────────────

    def _collect_outputs(self, state: State) -> Dict[str, Any]:
        """从 state.results 中收集所有节点输出"""
        outputs = {}
        results = state.results if state.results else {}
        for node_id, result in results.items():
            if hasattr(result, "outputs") and result.outputs:
                outputs[node_id] = result.outputs
        return outputs

    def _synthesize_trade_order(self, action: str, confidence: float,
                                market_data: Dict[str, Any],
                                state: State = None) -> Dict[str, Any]:
        """从最终决策合成交易订单（当 A5 未在链路中执行时）

        A5 节点仅在 A 链中存在。当使用 C/F/G 链路时，
        A5 不会被执行，此时从聚合器的最终决策合成交易指令。

        P3-1: 合成时也调用 A7 实践论门禁，确保所有链路（包括 C/F/G）
        都经过 65% 置信度门槛校验，避免低质量交易。
        """
        if action == "HOLD" or not market_data:
            return {}

        price = market_data.get("price", 0)
        if price <= 0:
            return {}

        # P3-1: A7 实践论门禁检查
        a7_gate = self._run_a7_gate(state, action, confidence, market_data)
        if not a7_gate.get("gate_passed", True):
            # 门禁未通过，不生成交易订单
            return {}

        # 门禁通过后，使用校准后的置信度
        calibrated_confidence = a7_gate.get("calibrated_confidence", confidence)

        from dreamos.capabilities.trading.nodes.a5_execution import (
            calc_dynamic_leverage,
            calc_dynamic_position_and_leverage,
        )
        atr_pct = market_data.get("atr_pct", 0.02)
        symbol = market_data.get("symbol", "BTC")

        # P0-6: Kelly 动态仓位 & 杠杆（置信度 × 波动率 × 账户权益）
        acc_eq = market_data.get("account_equity") or market_data.get("totalWalletBalance")
        if acc_eq is not None:
            try:
                acc_eq = float(acc_eq)
            except (TypeError, ValueError):
                acc_eq = None
        dyn = calc_dynamic_position_and_leverage(
            confidence=calibrated_confidence,
            atr_pct=atr_pct,
            account_equity=acc_eq,
            direction=action,
            symbol=symbol,
        )
        position_size = dyn["position_size"]
        leverage = int(dyn["leverage"])

        # 对称止损止盈（与A5节点保持一致）
        if action == "LONG":
            stop_loss = round(price * (1 - atr_pct * 1.0), 4)
            take_profit = round(price * (1 + atr_pct * 2.0), 4)
        else:
            stop_loss = round(price * (1 + atr_pct * 1.0), 4)
            take_profit = round(price * (1 - atr_pct * 2.0), 4)

        return {
            "action": action,
            "coin": symbol,
            "entry_price": price,
            "position_size": position_size,
            "leverage": leverage,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_per_trade": position_size * atr_pct,
            "rr_ratio": round(abs(take_profit - price) / max(abs(price - stop_loss), 0.0001), 2),
            "_a7_gate": a7_gate,
            "_synthesized": True,
            "_kelly": dyn,
        }

    def _run_a7_gate(self, state: State, direction: str, confidence: float,
                     market_data: Dict[str, Any]) -> Dict[str, Any]:
        """P3-1: 运行 A7 实践论门禁

        用于 C/F/G 链路（不含 A5）时补充门禁校验。
        """
        try:
            from dreamos.capabilities.trading.nodes.a7_practice_gate import A7PracticeGateNode
            a7_node = A7PracticeGateNode()

            if state is None:
                from dreamos.shared.state import new_state
                state = new_state(cycle_id="synth_a7")

            state.intent = {
                "direction": direction,
                "confidence": confidence,
            }
            state.market_data = market_data

            a7_result = a7_node.execute_core(state)
            return {
                "gate_passed": a7_result.outputs.get("gate_passed", False),
                "gate_result": a7_result.outputs.get("gate_result", "unknown"),
                "calibrated_confidence": a7_result.outputs.get("calibrated_confidence", confidence),
                "confidence_threshold": a7_result.outputs.get("confidence_threshold", 0.65),
                "direction": a7_result.direction,
            }
        except Exception as e:
            # A7 调用失败时保守处理：通过门禁（避免因门禁故障阻止所有交易）
            return {
                "gate_passed": True,
                "gate_result": "skipped_error",
                "calibrated_confidence": confidence,
                "direction": direction,
                "error": str(e),
            }

    def _collect_rationale(self, state: State) -> List[str]:
        """从各节点结果中收集 rationale"""
        rationale = []
        results = state.results if state.results else {}
        for node_id, result in results.items():
            if hasattr(result, "outputs") and result.outputs:
                node_rationale = result.outputs.get("rationale", [])
                if isinstance(node_rationale, list):
                    rationale.extend(node_rationale)
                elif isinstance(node_rationale, str):
                    rationale.append(node_rationale)
        return rationale

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """纯市场数据分析（无用户输入）"""
        return self.run(
            user_input="",
            market_data=market_data,
        )

    def chat(self, message: str, market_data: Optional[Dict] = None) -> Dict[str, Any]:
        """对话式交易分析"""
        return self.run(
            user_input=message,
            market_data=market_data or {},
        )

    @property
    def cycle_count(self) -> int:
        """已执行的周期数"""
        return self._cycle_count

    def history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取历史记录"""
        entries = self.graph_store.query_history()[:limit]
        return [e.to_dict() for e in entries]

    def status(self) -> Dict[str, Any]:
        """Agent 状态"""
        summary = self.graph_store.summary()
        return {
            "cycles_executed": self._cycle_count,
            "registered_nodes": len(self.registry),
            "registered_capabilities": len(self.capability_registry.list_ids()),
            "default_capability": self.capability_router.default_capability_id,
            "budget": self.budget.status(),
            "history_count": summary.get("history_entries", 0),
            "checkpoint_count": summary.get("checkpoints", 0),
        }

    def _import_skills(self):
        """自动导入 SKILL.md 文件到注册表（借鉴 Grok Build）

        在启动时扫描 skills 目录，解析 SKILL.md 文件，
        同时注册到 SkillEngine 和 NodeRegistry。
        """
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        skills_dir = root / "11-易经推理系统" / "skills"

        if not skills_dir.exists():
            return

        try:
            sys.path.insert(0, str(root / "16-调控系统"))
            from scripts.skill_importer import SkillImporter

            importer = SkillImporter(node_registry=self.registry)
            results = importer.scan_and_import(skills_dir)

            success_count = len(results["success"])
            if success_count > 0:
                print(f"[SKILL导入] 成功导入 {success_count} 个技能")
            if results["failed"]:
                print(f"[SKILL导入] 失败 {len(results['failed'])} 个")
                for f in results["failed"]:
                    print(f"  - {f['path']}: {f['error']}")
        except Exception as e:
            print(f"[SKILL导入] 跳过: {e}")

    def __repr__(self) -> str:
        wm_status = "on" if self.working_memory is not None else "off"
        return (f"<TradingAgent cycles={self._cycle_count} "
                f"nodes={len(self.registry)} "
                f"budget={self.budget.level()} "
                f"wm={wm_status}>")
