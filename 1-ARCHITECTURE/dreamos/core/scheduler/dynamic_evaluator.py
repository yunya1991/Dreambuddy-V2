"""
Dream OS 动态评估调度器 (DynamicEvaluationScheduler)

**核心职责**:
    1. 定期评估调度 - 按时间间隔自动触发评估回测
    2. 事件触发评估 - 响应亏损事件、市场事件、阈值事件等
    3. 评估任务管理 - 队列化、优先级调度、结果收集
    4. 编排策略更新 - 基于评估结果自动更新最优编排

**设计理念**:
    Dream OS 的核心是"评估回测调用编排"的闭环。动态评估调度器实现了：
    - 定期评估：确保系统持续学习和优化
    - 按需评估：在关键事件发生时立即触发评估
    - 自适应调度：根据系统状态动态调整评估频率

**事件类型**:
    - LOSS_EVENT: 亏损事件（单次亏损超过阈值或连续亏损）
    - DRAWDOWN_EVENT: 回撤事件（账户净值回撤超过阈值）
    - MARKET_EVENT: 市场事件（大幅波动、趋势反转、波动率突变）
    - THRESHOLD_EVENT: 阈值事件（模块能力评分变化、置信度变化）
    - MANUAL_EVENT: 手动触发事件
    - SCHEDULED_EVENT: 定期调度事件

**调度策略**:
    - 高优先级：亏损事件、回撤事件（立即执行）
    - 中优先级：市场事件、阈值事件（30秒内执行）
    - 低优先级：定期调度事件（按计划执行）
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)


class EventType(Enum):
    """事件类型"""
    LOSS_EVENT = "loss"
    DRAWDOWN_EVENT = "drawdown"
    MARKET_EVENT = "market"
    THRESHOLD_EVENT = "threshold"
    MANUAL_EVENT = "manual"
    SCHEDULED_EVENT = "scheduled"


class Priority(Enum):
    """任务优先级"""
    HIGH = 1
    MEDIUM = 2
    LOW = 3


@dataclass
class EvaluationEvent:
    """评估事件"""
    event_type: EventType
    priority: Priority
    timestamp: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "priority": self.priority.value,
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass
class EvaluationTask:
    """评估任务"""
    task_id: str
    event: EvaluationEvent
    status: str = "pending"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EventTrigger:
    """事件触发器基类"""

    def __init__(self, scheduler: "DynamicEvaluationScheduler", config: Dict[str, Any]):
        self.scheduler = scheduler
        self.config = config

    def check(self, *args, **kwargs) -> Optional[EvaluationEvent]:
        """检查是否触发事件"""
        return None


class LossEventTrigger(EventTrigger):
    """亏损事件触发器"""

    def __init__(self, scheduler: "DynamicEvaluationScheduler", config: Dict[str, Any]):
        super().__init__(scheduler, config)
        self.max_single_loss = config.get("max_single_loss", 5.0)
        self.max_consecutive_losses = config.get("max_consecutive_losses", 3)
        self.consecutive_loss_count = 0
        self.recent_trades: deque = deque(maxlen=10)

    def on_trade_result(self, pnl_percent: float) -> Optional[EvaluationEvent]:
        """收到交易结果时检查"""
        self.recent_trades.append(pnl_percent)

        if pnl_percent < -self.max_single_loss:
            self.consecutive_loss_count = 0
            return EvaluationEvent(
                event_type=EventType.LOSS_EVENT,
                priority=Priority.HIGH,
                timestamp=datetime.now().isoformat(),
                details={
                    "reason": "single_loss_exceeded",
                    "loss_amount": abs(pnl_percent),
                    "threshold": self.max_single_loss,
                    "recent_trades": list(self.recent_trades),
                },
            )

        if pnl_percent < 0:
            self.consecutive_loss_count += 1
            if self.consecutive_loss_count >= self.max_consecutive_losses:
                event = EvaluationEvent(
                    event_type=EventType.LOSS_EVENT,
                    priority=Priority.HIGH,
                    timestamp=datetime.now().isoformat(),
                    details={
                        "reason": "consecutive_losses",
                        "consecutive_count": self.consecutive_loss_count,
                        "threshold": self.max_consecutive_losses,
                        "recent_trades": list(self.recent_trades),
                    },
                )
                self.consecutive_loss_count = 0
                return event
        else:
            self.consecutive_loss_count = 0

        return None


class DrawdownEventTrigger(EventTrigger):
    """回撤事件触发器"""

    def __init__(self, scheduler: "DynamicEvaluationScheduler", config: Dict[str, Any]):
        super().__init__(scheduler, config)
        self.max_drawdown = config.get("max_drawdown", 10.0)
        self.peak_value = 100.0
        self.current_value = 100.0

    def on_portfolio_update(self, value: float) -> Optional[EvaluationEvent]:
        """收到组合净值更新时检查"""
        self.current_value = value
        if value > self.peak_value:
            self.peak_value = value

        drawdown = (self.peak_value - value) / self.peak_value * 100

        if drawdown > self.max_drawdown:
            event = EvaluationEvent(
                event_type=EventType.DRAWDOWN_EVENT,
                priority=Priority.HIGH,
                timestamp=datetime.now().isoformat(),
                details={
                    "reason": "drawdown_exceeded",
                    "drawdown": drawdown,
                    "threshold": self.max_drawdown,
                    "peak_value": self.peak_value,
                    "current_value": self.current_value,
                },
            )
            self.peak_value = value
            return event

        return None


class MarketEventTrigger(EventTrigger):
    """市场事件触发器"""

    def __init__(self, scheduler: "DynamicEvaluationScheduler", config: Dict[str, Any]):
        super().__init__(scheduler, config)
        self.volatility_threshold = config.get("volatility_threshold", 0.15)
        self.price_move_threshold = config.get("price_move_threshold", 5.0)
        self.last_price = {}
        self.last_volatility = {}

    def on_market_update(self, symbol: str, price: float, volatility: float = 0) -> Optional[EvaluationEvent]:
        """收到市场更新时检查"""
        if symbol in self.last_price:
            price_change = abs(price - self.last_price[symbol]) / self.last_price[symbol] * 100
            if price_change > self.price_move_threshold:
                return EvaluationEvent(
                    event_type=EventType.MARKET_EVENT,
                    priority=Priority.MEDIUM,
                    timestamp=datetime.now().isoformat(),
                    details={
                        "reason": "price_spike",
                        "symbol": symbol,
                        "price_change": price_change,
                        "threshold": self.price_move_threshold,
                        "current_price": price,
                        "previous_price": self.last_price[symbol],
                    },
                )

        if symbol in self.last_volatility and volatility > 0:
            vol_change = abs(volatility - self.last_volatility[symbol]) / self.last_volatility[symbol]
            if vol_change > self.volatility_threshold:
                return EvaluationEvent(
                    event_type=EventType.MARKET_EVENT,
                    priority=Priority.MEDIUM,
                    timestamp=datetime.now().isoformat(),
                    details={
                        "reason": "volatility_surge",
                        "symbol": symbol,
                        "volatility_change": vol_change,
                        "threshold": self.volatility_threshold,
                        "current_volatility": volatility,
                    },
                )

        self.last_price[symbol] = price
        self.last_volatility[symbol] = volatility
        return None


class ThresholdEventTrigger(EventTrigger):
    """阈值事件触发器"""

    def __init__(self, scheduler: "DynamicEvaluationScheduler", config: Dict[str, Any]):
        super().__init__(scheduler, config)
        self.confidence_threshold = config.get("confidence_threshold", 0.3)
        self.capability_drop_threshold = config.get("capability_drop_threshold", 0.1)
        self.last_module_capabilities: Dict[str, float] = {}

    def on_capability_update(self, module_id: str, score: float) -> Optional[EvaluationEvent]:
        """收到模块能力更新时检查"""
        if module_id in self.last_module_capabilities:
            drop = self.last_module_capabilities[module_id] - score
            if drop > self.capability_drop_threshold:
                return EvaluationEvent(
                    event_type=EventType.THRESHOLD_EVENT,
                    priority=Priority.MEDIUM,
                    timestamp=datetime.now().isoformat(),
                    details={
                        "reason": "capability_drop",
                        "module_id": module_id,
                        "score_drop": drop,
                        "threshold": self.capability_drop_threshold,
                        "previous_score": self.last_module_capabilities[module_id],
                        "current_score": score,
                    },
                )

        self.last_module_capabilities[module_id] = score
        return None


class DynamicEvaluationScheduler:
    """动态评估调度器

    **核心能力**:
        1. 定期评估：按时间间隔自动触发评估回测
        2. 事件触发：响应亏损、回撤、市场、阈值等事件
        3. 任务队列：支持优先级调度和并发控制
        4. 结果收集：统一管理评估结果并更新编排策略

    **用法**:
        scheduler = DynamicEvaluationScheduler()

        # 启动调度器
        scheduler.start()

        # 订阅事件
        scheduler.subscribe(EventType.LOSS_EVENT, my_callback)

        # 触发手动评估
        scheduler.trigger_manual_evaluation(reason="策略调整后")

        # 停止调度器
        scheduler.stop()
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

        self.schedule_interval = self.config.get("schedule_interval", 3600)
        self.max_concurrent_tasks = self.config.get("max_concurrent_tasks", 1)
        self.task_timeout = self.config.get("task_timeout", 300)

        self._running = False
        self._thread = None
        self._task_queue: deque = deque()
        self._active_tasks: Dict[str, EvaluationTask] = {}
        self._task_counter = 0
        self._lock = threading.Lock()

        self._callbacks: Dict[EventType, List[Callable]] = {}
        self._event_triggers: Dict[str, EventTrigger] = {}

        self._init_triggers()

        self._evolution_engine = None
        self._trading_evaluator = None
        self._evaluation_memory = None

    def _init_triggers(self):
        """初始化事件触发器"""
        trigger_config = self.config.get("triggers", {})

        self._event_triggers["loss"] = LossEventTrigger(
            self, trigger_config.get("loss", {})
        )
        self._event_triggers["drawdown"] = DrawdownEventTrigger(
            self, trigger_config.get("drawdown", {})
        )
        self._event_triggers["market"] = MarketEventTrigger(
            self, trigger_config.get("market", {})
        )
        self._event_triggers["threshold"] = ThresholdEventTrigger(
            self, trigger_config.get("threshold", {})
        )

    def _get_evolution_engine(self):
        """获取进化引擎（延迟初始化）"""
        if self._evolution_engine is None:
            from dreamos.evolution.engine import EvolutionEngine
            self._evolution_engine = EvolutionEngine()
        return self._evolution_engine

    def _get_trading_evaluator(self):
        """获取交易评估器（延迟初始化）"""
        if self._trading_evaluator is None:
            from dreamos.capabilities.trading.evaluator import TradingAnalysisEvaluator
            self._trading_evaluator = TradingAnalysisEvaluator()

            from dreamos.core.memory.orchestration_memory import OrchestrationMemory
            memory = OrchestrationMemory()
            memory.load()
            self._trading_evaluator.set_orchestration_memory(memory._data)

        return self._trading_evaluator

    def _get_evaluation_memory(self):
        """获取评估记忆系统（延迟初始化）"""
        if self._evaluation_memory is None:
            from dreamos.core.memory.evaluation_memory import EvaluationMemory
            self._evaluation_memory = EvaluationMemory()
            self._evaluation_memory.load()
        return self._evaluation_memory

    # ── 调度控制 ──────────────────────────────────────────────

    def start(self):
        """启动调度器"""
        if self._running:
            logger.warning("调度器已在运行")
            return

        self._running = True
        logger.info("启动动态评估调度器")

        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止调度器"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("动态评估调度器已停止")

    def _scheduler_loop(self):
        """调度器主循环"""
        last_scheduled_time = datetime.now()

        while self._running:
            try:
                self._process_tasks()

                now = datetime.now()
                if (now - last_scheduled_time).total_seconds() >= self.schedule_interval:
                    self._schedule_periodic_evaluation()
                    last_scheduled_time = now

                time.sleep(1)
            except Exception as e:
                logger.error(f"调度器循环异常: {e}")
                time.sleep(10)

    # ── 定期评估 ──────────────────────────────────────────────

    def _schedule_periodic_evaluation(self):
        """调度定期评估任务"""
        logger.info(f"触发定期评估 (间隔: {self.schedule_interval}秒)")
        self._enqueue_task(
            EvaluationEvent(
                event_type=EventType.SCHEDULED_EVENT,
                priority=Priority.LOW,
                timestamp=datetime.now().isoformat(),
                details={
                    "reason": "periodic_schedule",
                    "interval": self.schedule_interval,
                },
            )
        )

    def set_schedule_interval(self, seconds: int):
        """设置定期评估间隔"""
        self.schedule_interval = seconds
        logger.info(f"定期评估间隔已更新为 {seconds} 秒")

    # ── 事件触发 ──────────────────────────────────────────────

    def trigger_manual_evaluation(self, reason: str = "manual"):
        """手动触发评估"""
        logger.info(f"手动触发评估: {reason}")
        self._enqueue_task(
            EvaluationEvent(
                event_type=EventType.MANUAL_EVENT,
                priority=Priority.HIGH,
                timestamp=datetime.now().isoformat(),
                details={"reason": reason},
            )
        )

    def on_trade_result(self, pnl_percent: float):
        """处理交易结果，触发亏损事件检查"""
        # 记录到短期记忆
        try:
            eval_memory = self._get_evaluation_memory()
            eval_memory.record_trade({
                "pnl_percent": pnl_percent,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.debug(f"记录交易到短期记忆失败: {e}")

        trigger = self._event_triggers.get("loss")
        if trigger:
            event = trigger.on_trade_result(pnl_percent)
            if event:
                logger.info(f"检测到亏损事件: {event.details.get('reason')}")
                self._enqueue_task(event)

    def on_portfolio_update(self, value: float):
        """处理组合净值更新，触发回撤事件检查"""
        trigger = self._event_triggers.get("drawdown")
        if trigger:
            event = trigger.on_portfolio_update(value)
            if event:
                logger.info(f"检测到回撤事件: {event.details.get('reason')}")
                self._enqueue_task(event)

    def on_market_update(self, symbol: str, price: float, volatility: float = 0):
        """处理市场更新，触发市场事件检查"""
        trigger = self._event_triggers.get("market")
        if trigger:
            event = trigger.on_market_update(symbol, price, volatility)
            if event:
                logger.info(f"检测到市场事件: {event.details.get('reason')}")
                self._enqueue_task(event)

    def on_capability_update(self, module_id: str, score: float):
        """处理模块能力更新，触发阈值事件检查"""
        trigger = self._event_triggers.get("threshold")
        if trigger:
            event = trigger.on_capability_update(module_id, score)
            if event:
                logger.info(f"检测到阈值事件: {event.details.get('reason')}")
                self._enqueue_task(event)

    # ── 任务管理 ──────────────────────────────────────────────

    def _enqueue_task(self, event: EvaluationEvent):
        """入队评估任务"""
        with self._lock:
            self._task_counter += 1
            task = EvaluationTask(
                task_id=f"eval_{self._task_counter:06d}",
                event=event,
            )
            self._task_queue.append((event.priority, task))

            self._task_queue = deque(
                sorted(self._task_queue, key=lambda x: x[0].value)
            )

            logger.debug(f"任务入队: {task.task_id} ({event.event_type.value})")

    def _process_tasks(self):
        """处理任务队列"""
        with self._lock:
            while self._task_queue and len(self._active_tasks) < self.max_concurrent_tasks:
                priority, task = self._task_queue.popleft()
                task.status = "running"
                task.started_at = datetime.now().isoformat()
                self._active_tasks[task.task_id] = task

                threading.Thread(
                    target=self._execute_task,
                    args=(task,),
                    daemon=True,
                ).start()

    def _execute_task(self, task: EvaluationTask):
        """执行评估任务"""
        try:
            logger.info(f"开始执行评估任务: {task.task_id}")

            result = self._run_evaluation(task.event)

            with self._lock:
                task.status = "completed"
                task.completed_at = datetime.now().isoformat()
                task.result = result
                self._active_tasks.pop(task.task_id, None)

            self._notify_callbacks(task.event.event_type, result)
            self._update_orchestration(result)

            # 更新评估记忆（越用越聪明）
            eval_memory = self._get_evaluation_memory()
            learning_summary = eval_memory.learn_from_evaluation(result)
            eval_memory.save()
            logger.info(f"评估记忆学习: {learning_summary}")

            logger.info(f"评估任务完成: {task.task_id}")

        except Exception as e:
            logger.error(f"评估任务失败: {task.task_id}, 错误: {e}")
            with self._lock:
                task.status = "failed"
                task.completed_at = datetime.now().isoformat()
                task.result = {"error": str(e)}
                self._active_tasks.pop(task.task_id, None)

    def _run_evaluation(self, event: EvaluationEvent) -> Dict[str, Any]:
        """运行评估"""
        evaluator = self._get_trading_evaluator()

        from dreamos.core.memory.execution_feedback import ExecutionFeedbackCollector
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory

        memory = OrchestrationMemory()
        memory.load()

        collector = ExecutionFeedbackCollector(memory)
        feedback = collector._records

        trades = []
        trade_id = 0
        for scenario, scenario_trades in feedback.items():
            scenario_info = memory.get_scenario(scenario) or {}
            nodes = scenario_info.get("nodes", [])

            for trade in scenario_trades:
                trade_id += 1
                entry_price = trade.get("entry_price", 0)
                exit_price = trade.get("exit_price", 0)

                if exit_price > 0 and entry_price > 0:
                    if trade.get("direction", "") == "LONG":
                        pnl_percent = (exit_price - entry_price) / entry_price * 100
                    else:
                        pnl_percent = (entry_price - exit_price) / entry_price * 100
                else:
                    pnl_percent = trade.get("result", 0) * 100

                trades.append({
                    "trade_id": f"trade_{trade_id:06d}",
                    "symbol": trade.get("symbol", ""),
                    "direction": trade.get("direction", ""),
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_percent": pnl_percent,
                    "holding_period": 1,
                    "scenario": scenario,
                    "chain_used": trade.get("pattern", ""),
                    "nodes_used": nodes,
                    "entry_confidence": 0.65 if trade.get("direction") else 0,
                    "exit_reason": "normal" if exit_price > 0 else "open",
                    "stop_loss_hit": pnl_percent < -3,
                    "take_profit_hit": 0 < pnl_percent < 2,
                    "signal_strength": 0.6,
                    "scenario_mismatch": False,
                    "actual_volatility": 0.02,
                    "estimated_volatility": 0.02,
                    "momentum_confidence": 0.5,
                    "correlation_conflict": False,
                    "expected_direction": trade.get("expected_direction", ""),
                    "timestamp": trade.get("timestamp", ""),
                })

        scenarios = list(memory._data.get("scenarios", {}).keys())
        report = evaluator.generate_report(trades, scenarios=scenarios)

        report_dict = report.to_dict()
        report_dict["trigger_event"] = event.to_dict()

        report_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "capabilities", "trading", "reports"
        )
        os.makedirs(report_dir, exist_ok=True)

        report_path = os.path.join(report_dir, f"evaluation_{report.report_id}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, ensure_ascii=False, indent=2)

        return report_dict

    def _update_orchestration(self, result: Dict[str, Any]):
        """根据评估结果更新编排策略"""
        recommendations = result.get("orchestration_recommendations", {})

        from dreamos.core.memory.orchestration_memory import OrchestrationMemory
        memory = OrchestrationMemory()
        memory.load()

        updated_count = 0
        for scenario, rec in recommendations.items():
            if rec.get("confidence", 0) > 0.7:
                evidence = {
                    "metrics": {
                        "win_rate": rec.get("confidence", 0),
                        "return": rec.get("expected_improvement", 0),
                        "sharpe": 0,
                    },
                    "sample_count": 10,
                    "confidence": "high",
                }
                memory.update_from_evolution(
                    scenario_id=scenario,
                    new_pattern=rec.get("recommended_chain", ""),
                    nodes=rec.get("recommended_nodes", []),
                    score=rec.get("confidence", 0),
                    evidence=evidence,
                )
                updated_count += 1

        if updated_count > 0:
            memory.save()
            logger.info(f"更新了 {updated_count} 个场景的编排策略")

    # ── 回调机制 ──────────────────────────────────────────────

    def subscribe(self, event_type: EventType, callback: Callable):
        """订阅事件回调"""
        if event_type not in self._callbacks:
            self._callbacks[event_type] = []
        self._callbacks[event_type].append(callback)
        logger.debug(f"订阅事件: {event_type.value}")

    def unsubscribe(self, event_type: EventType, callback: Callable):
        """取消订阅事件回调"""
        if event_type in self._callbacks:
            self._callbacks[event_type].remove(callback)

    def _notify_callbacks(self, event_type: EventType, result: Dict[str, Any]):
        """通知所有订阅者"""
        callbacks = self._callbacks.get(event_type, [])
        for callback in callbacks:
            try:
                callback(event_type, result)
            except Exception as e:
                logger.error(f"回调执行失败: {e}")

    # ── 状态查询 ──────────────────────────────────────────────

    def get_task_status(self, task_id: str) -> Optional[EvaluationTask]:
        """获取任务状态"""
        with self._lock:
            return self._active_tasks.get(task_id)

    def get_pending_tasks(self) -> List[EvaluationTask]:
        """获取待处理任务列表"""
        with self._lock:
            return [task for _, task in self._task_queue]

    def get_active_task_count(self) -> int:
        """获取活跃任务数"""
        with self._lock:
            return len(self._active_tasks)

    def get_stats(self) -> Dict[str, Any]:
        """获取调度器统计信息"""
        with self._lock:
            return {
                "running": self._running,
                "pending_tasks": len(self._task_queue),
                "active_tasks": len(self._active_tasks),
                "total_tasks_processed": self._task_counter,
                "schedule_interval": self.schedule_interval,
            }

    def __repr__(self) -> str:
        return f"<DynamicEvaluationScheduler running={self._running} pending={len(self._task_queue)} active={len(self._active_tasks)}>"


import os