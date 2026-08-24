# -*- coding: utf-8 -*-
"""ExitManager — 持仓与离场管理层策略链.

Spec: docs/superpowers/specs/2026-08-20-exit-manager-design.md

核心设计:
  - 核心层（卦象主离场 + Classic 兜底 + 保护期 + 静态 SLTP）不动
  - 扩展层 6 个 ExitStrategy 子类按优先级链式调用
  - ExitManager.evaluate() 返回首个非 pass 的 ExitDecision
  - BCRM2 spec 的 S2/S3/S4 开关作为 ExitStrategy.enabled 属性融入
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ================================================================
# 数据结构
# ================================================================

@dataclass
class ExitContext:
    """传入各 ExitStrategy 的上下文快照。"""

    coin: str
    inference: Dict[str, Any]
    pos_info: Dict[str, Any]
    tracker_pos: Any
    in_protection: bool
    age_hours: float
    ev: Optional[float] = None
    multi_horizon: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    # 跨币种推理结果（TimeoutProfitSwitch/RankedTp 需要）
    all_inferences: Optional[Dict[str, Any]] = None
    # 当前已持仓币种集合（用于候选过滤）
    held_coins: Optional[Any] = None  # set or list
    # 信号反转策略的 per-call 基础阈值（由 polling_trader 传入）
    effective_threshold: Optional[float] = None


@dataclass
class ExitDecision:
    """ExitStrategy 返回的离场决策。"""

    action: str  # "force_close" | "adjust_sl_tp" | "ranked_tp" | "hold" | "pass"
    reason: str
    params: Optional[Dict[str, Any]] = None
    strategy_name: str = ""

    @staticmethod
    def pass_() -> "ExitDecision":
        """不触发，交由下一策略。"""
        return ExitDecision(action="pass", reason="", strategy_name="")


# ================================================================
# 抽象基类
# ================================================================

class ExitStrategy(ABC):
    """离场策略抽象基类。"""

    name: str = ""
    priority: int = 0
    enabled: bool = True

    @abstractmethod
    def evaluate(self, context: ExitContext) -> ExitDecision:
        """评估离场决策。返回 action='pass' 表示不触发。"""

    def record_outcome(self, decision: ExitDecision, pnl: float, win: bool):
        """记录该次决策的实际盈亏结果，用于贡献值统计。"""
        # 默认空实现，子类可覆盖


# ================================================================
# ExitManager
# ================================================================

class ExitManager:
    """离场策略链管理器（v1.4.1 路径B改造：支持portfolio_mode切换+多组合子链）。

    按优先级链调用各 ExitStrategy.evaluate()，返回首个非 pass 的决策。
    全部 pass 时返回 ExitDecision.pass_()，由 polling_trader 进入核心层
    （卦象主离场 + Classic 兜底）。

    路径B新增：
      - portfolio_mode 属性（setter切链，默认"default"字节等价改造前行为）
      - _chains 字典（mode→List[ExitStrategy]，默认从PORTFOLIO_MODE_CHAINS注入）
      - evaluate() 时：若当前模式有链 → 使用chain；否则回退到default/legacy _strategies
    """

    def __init__(self, strategies: List[ExitStrategy] = None):
        # Legacy 单链（改造前等价行为，portfolio_mode=default时作为fallback）
        self._strategies: List[ExitStrategy] = sorted(
            strategies or [], key=lambda s: s.priority
        )
        self._log_buffer: List[Dict[str, Any]] = []
        self._storage: Any = None  # EvolutionStorageSQLite 适配器
        # ── 路径B：组合模式子链字典 ──
        self.portfolio_mode: str = "default"
        self._chains: Dict[str, List[ExitStrategy]] = {}
        try:
            # 防御：允许策略层未被打包的情况（独立import不崩）
            from ..strategy_algo_layer import PORTFOLIO_MODE_CHAINS as _PMC  # noqa: E402
            for m, chain in (_PMC or {}).items():
                self._chains[str(m)] = sorted(list(chain), key=lambda s: getattr(s, "priority", 9999))
        except Exception:  # noqa: BLE001 fail-open：无chain时仍通过legacy _strategies正常工作
            self._chains = {}

    def set_storage(self, storage: Any) -> None:
        """注入 storage 适配器（EvolutionStorageSQLite），用于贡献值统计。"""
        self._storage = storage

    # =================================================================
    # 路径 B：组合模式切换（模式名非法→fail-open回退"default"）
    # =================================================================
    def register_chain(self, mode: str, strategies: List[ExitStrategy]) -> None:
        """注册/覆盖某个组合模式的策略链（外部可动态注入，如polling_trader初始化时）。"""
        mode_key = str(mode or "").strip() or "default"
        self._chains[mode_key] = sorted(list(strategies or []), key=lambda s: getattr(s, "priority", 9999))

    def get_current_chain(self) -> List[ExitStrategy]:
        """获取当前portfolio_mode对应的链：
        1) _chains[self.portfolio_mode] 存在 → 用它；
        2) 否则 _chains["default"] 存在 → 用 default 链（fail-open安全回退）；
        3) 否则 legacy _strategies（改造前行为，字节等价）。
        """
        mode = str(getattr(self, "portfolio_mode", "default") or "").strip() or "default"
        if mode in self._chains and self._chains[mode]:
            return self._chains[mode]
        if "default" in self._chains and self._chains["default"]:
            return self._chains["default"]
        return self._strategies

    def evaluate(
        self,
        coin: str,
        inference: Dict[str, Any],
        pos_info: Dict[str, Any],
        tracker_pos: Any,
        in_protection: bool,
        age_hours: float,
        **kwargs: Any,
    ) -> ExitDecision:
        """按优先级链调用各策略，返回首个非 pass 的决策。"""
        ctx = ExitContext(
            coin=coin,
            inference=inference,
            pos_info=pos_info,
            tracker_pos=tracker_pos,
            in_protection=in_protection,
            age_hours=age_hours,
            ev=kwargs.get("ev"),
            multi_horizon=kwargs.get("multi_horizon"),
            confidence=kwargs.get("confidence", 0.0),
            all_inferences=kwargs.get("all_inferences"),
            held_coins=kwargs.get("held_coins"),
            effective_threshold=kwargs.get("effective_threshold"),
        )
        # 路径B：按portfolio_mode切链；未知模式回退legacy链（fail-open安全字节等价）
        for strategy in self.get_current_chain():
            if not getattr(strategy, "enabled", True):
                continue
            decision = strategy.evaluate(ctx)
            if decision.action != "pass":
                decision.strategy_name = getattr(strategy, "name", "") or getattr(decision, "strategy_name", "")
                return decision
        return ExitDecision.pass_()

    def get_strategy_contribution(self, days: int = 30) -> Dict[str, Any]:
        """返回各策略近 N 天的贡献统计（触发次数/胜率/平均盈亏）。

        委托给注入的 storage 适配器（EvolutionStorageSQLite.get_exit_strategy_contribution）。
        无 storage 时返回空 dict。
        """
        if self._storage is None:
            return {}
        try:
            return self._storage.get_exit_strategy_contribution(days=days)
        except Exception:
            return {}
