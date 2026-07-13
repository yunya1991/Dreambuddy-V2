"""
通用风控引擎 - 统一入口
========================
RiskEngine 是所有风控功能的统一入口，整合三层风控体系。

三层架构：
    L1 - 事前门禁层 (PreTradeGate)  - 交易前检查，决定是否允许开仓
    L2 - 仓位管理层 (PositionSizer)  - 仓位计算，决定开多大仓位
    L3 - 事后离场层 (ExitEngine)     - 持仓监控，决定何时离场

使用方式：
    from risk_engine import RiskEngine

    engine = RiskEngine(config)
    engine.register_default_rules()

    # 事前风控
    result = engine.pre_trade_check(signal, context)

    # 仓位计算
    size = engine.calculate_position(signal, context)

    # 离场决策
    action = engine.check_exit(position, market, context)
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass

from .context import (
    Signal,
    PositionState,
    MarketSnapshot,
    RiskContext,
    RiskCheckResult,
    PositionSizeResult,
    ExitResult,
    ExitAction,
    Direction,
    ReasonCode,
)
from .registry import RuleRegistry, RuleCategory
from .pre_trade_gate import PreTradeGate
from .position_sizer import PositionSizer
from .exit_engine import ExitEngine
from .l1_assessor import L1ValueRiskAssessor, ExitFeatureSet, L1Mode, L2HysteresisState
from .ml_model import MLModelRegistry, ModelPrediction
from .alert import RiskAlertNotifier, AlertEvent, AlertLevel, AlertCategory

try:
    from ..rules.gate_rules import register_default_gate_rules
    from ..rules.position_rules import register_default_position_rules
    from ..rules.exit_rules import register_default_exit_rules
except ImportError:
    from rules.gate_rules import register_default_gate_rules
    from rules.position_rules import register_default_position_rules
    from rules.exit_rules import register_default_exit_rules


class RiskEngine:
    """通用风控引擎 - 统一入口

    整合事前门禁、仓位管理、事后离场三层风控体系，
    提供统一、易用的风控接口。

    核心特性：
        - 三层风控体系，层层递进
        - 可插拔规则，灵活扩展
        - 理由码体系，审计可追踪
        - Fail-Closed 原则，安全第一
        - SDK式集成，低侵入性

    示例:
        engine = RiskEngine({
            "max_daily_drawdown_pct": 0.10,
            "risk_per_trade_pct": 0.02,
            "max_concurrent_positions": 5,
        })
        engine.register_default_rules()

        # 事前检查
        result = engine.pre_trade_check(signal, context)
        if result.passed:
            # 计算仓位
            size = engine.calculate_position(signal, context, result.position_modifier)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

        self.registry = RuleRegistry()

        self.pre_trade_gate = PreTradeGate(
            registry=self.registry,
            config=self.config.get("gate", {}),
        )

        self.position_sizer = PositionSizer(
            registry=self.registry,
            config=self.config.get("position", {}),
        )

        self.exit_engine = ExitEngine(
            registry=self.registry,
            config=self.config.get("exit", {}),
        )

        self.l1_assessor = L1ValueRiskAssessor(self.config.get("l1", {}))
        self.ml_registry = MLModelRegistry()
        self.alert_notifier = RiskAlertNotifier(self.config.get("alert", {}))

        self._l2_states: Dict[str, L2HysteresisState] = {}
        self._dd_snapshots: Dict[str, list] = {}

        self._default_rules_registered = False

    def register_default_rules(self):
        """注册所有默认风控规则"""
        if self._default_rules_registered:
            return

        register_default_gate_rules(self.registry, self.config)
        register_default_position_rules(self.registry, self.config)
        register_default_exit_rules(self.registry, self.config)

        self._default_rules_registered = True

    def pre_trade_check(
        self,
        signal: Signal,
        context: RiskContext,
        extra: Optional[Dict[str, Any]] = None,
    ) -> RiskCheckResult:
        """事前风控检查

        执行所有事前门禁规则，检查是否允许开仓。

        Args:
            signal: 交易信号
            context: 风控上下文
            extra: 额外参数

        Returns:
            RiskCheckResult 检查结果
        """
        if not self._default_rules_registered:
            self.register_default_rules()

        return self.pre_trade_gate.check(signal, context, extra)

    def calculate_position(
        self,
        signal: Signal,
        context: RiskContext,
        position_modifier: float = 1.0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> PositionSizeResult:
        """计算仓位大小

        根据风险预算、置信度、波动率等计算合适的仓位。

        Args:
            signal: 交易信号
            context: 风控上下文
            position_modifier: 仓位调整系数
            extra: 额外参数

        Returns:
            PositionSizeResult 仓位计算结果
        """
        if not self._default_rules_registered:
            self.register_default_rules()

        return self.position_sizer.calculate(signal, context, position_modifier, extra)

    def check_exit(
        self,
        position: PositionState,
        market: Optional[MarketSnapshot] = None,
        context: Optional[RiskContext] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> ExitResult:
        """离场决策检查

        对持仓进行离场决策，返回最高优先级的离场动作。

        Args:
            position: 持仓状态
            market: 市场快照
            context: 风控上下文
            extra: 额外参数

        Returns:
            ExitResult 离场决策结果
        """
        if not self._default_rules_registered:
            self.register_default_rules()

        return self.exit_engine.check(position, market, context, extra)

    def full_pre_trade(
        self,
        signal: Signal,
        context: RiskContext,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """完整的事前风控流程（门禁 + 仓位）

        一次性执行事前门禁检查和仓位计算。

        Args:
            signal: 交易信号
            context: 风控上下文
            extra: 额外参数

        Returns:
            {
                "check": RiskCheckResult,
                "position": PositionSizeResult (仅当check.passed时),
            }
        """
        check_result = self.pre_trade_check(signal, context, extra)

        result = {"check": check_result}

        if check_result.passed:
            position_result = self.calculate_position(
                signal,
                context,
                check_result.position_modifier,
                extra,
            )
            result["position"] = position_result

        return result

    def register_rule(
        self,
        name: str,
        category: str,
        handler: Callable,
        priority: int = 100,
        description: str = "",
    ):
        """注册自定义规则

        Args:
            name: 规则名称
            category: 规则类别 ('gate' | 'position' | 'exit')
            handler: 规则处理函数
            priority: 优先级
            description: 规则描述
        """
        cat_map = {
            "gate": RuleCategory.GATE,
            "position": RuleCategory.POSITION,
            "exit": RuleCategory.EXIT,
        }
        category_enum = cat_map.get(category.lower())
        if not category_enum:
            raise ValueError(f"无效的规则类别: {category}")

        self.registry.register(
            name=name,
            category=category_enum,
            handler=handler,
            priority=priority,
            description=description,
        )

    def enable_rule(self, name: str) -> bool:
        """启用规则"""
        return self.registry.enable(name)

    def disable_rule(self, name: str) -> bool:
        """禁用规则"""
        return self.registry.disable(name)

    def list_rules(self) -> Dict[str, List[Dict[str, Any]]]:
        """列出所有规则"""
        return self.registry.list_all()

    def get_status(self, context: RiskContext) -> Dict[str, Any]:
        """获取风控状态概览"""
        return {
            "total_equity": context.total_equity,
            "daily_pnl": context.daily_pnl,
            "daily_drawdown_pct": context.daily_drawdown_pct,
            "consecutive_losses": context.consecutive_losses,
            "active_positions": context.active_positions_count,
            "win_rate": context.win_rate,
            "total_trades": context.total_trades,
            "rules_count": len(self.registry),
            "gate_rules": len(self.registry.get_enabled_rules(RuleCategory.GATE)),
            "position_rules": len(self.registry.get_enabled_rules(RuleCategory.POSITION)),
            "exit_rules": len(self.registry.get_enabled_rules(RuleCategory.EXIT)),
            "ml_models": self.ml_registry.list_models(),
            "alert_count": len(self.alert_notifier.get_history(9999)),
        }

    # ── L1 价值-风险评估 ──────────────────────────────────

    def assess_value_risk(
        self,
        position: PositionState,
        features: ExitFeatureSet,
        l1_mode: L1Mode = L1Mode.HEURISTIC,
    ) -> Any:
        """L1 价值-风险评估

        对持仓进行 hold_risk / hold_value 评估，输出离场动作建议。

        Args:
            position: 持仓状态
            features: 离场特征集
            l1_mode: 评估模式 (HEURISTIC / MRD / ML)

        Returns:
            L1AssessmentResult 评估结果
        """
        coin = position.coin or "default"
        l2_state = self._l2_states.setdefault(coin, L2HysteresisState())
        snapshots = self._dd_snapshots.get(coin, [])

        result = self.l1_assessor.assess(
            position=position,
            features=features,
            l2_state=l2_state,
            l1_mode=l1_mode,
            snapshot_history=snapshots,
        )

        snapshots.append({"ts": l2_state.last_update_ts, "dd": features.dd})
        max_len = max(3, int(self.config.get("l1", {}).get("risk_budget_len", 12)))
        self._dd_snapshots[coin] = snapshots[-max_len:]

        if result.action in ("close", "reduce"):
            self.alert_notifier.alert_exit_trigger(
                coin=coin,
                action=result.action,
                reason=f"hold_risk={result.hold_risk:.3f} value={result.hold_value:.3f}",
                priority="p1",
                details={
                    "hold_risk": f"{result.hold_risk:.3f}",
                    "hold_value": f"{result.hold_value:.3f}",
                    "mrd_score": f"{result.mrd_score:.3f}",
                    "reduce_frac": f"{result.reduce_frac:.2f}",
                },
            )

        return result

    # ── ML 模型管理 ──────────────────────────────────────

    def load_ml_model(self, name: str, meta_path: str) -> bool:
        """加载 ML 模型"""
        return self.ml_registry.load_model(name, meta_path)

    def load_ml_committee(self, name: str, members: list) -> bool:
        """加载 Committee 模型"""
        return self.ml_registry.load_committee(name, members)

    def ml_predict(self, model_name: str, features: Dict[str, float]) -> ModelPrediction:
        """ML 模型预测"""
        return self.ml_registry.predict(model_name, features)

    def list_ml_models(self) -> Dict[str, Any]:
        """列出所有 ML 模型"""
        return self.ml_registry.list_models()

    # ── 告警通知 ──────────────────────────────────────────

    def alert(self, event: AlertEvent) -> bool:
        """发送告警"""
        return self.alert_notifier.alert(event)

    def get_alert_history(self, limit: int = 50) -> list:
        """获取告警历史"""
        return self.alert_notifier.get_history(limit)
