"""ExitModuleFacade — 离场模块统一接口

缺口B：暴露 decide(context) 供 BCRM/BDSM 子系统独立验证离场模块能力。
子系统无需迁移到 exit_engine，只需通过 Facade 调用 decide() 对比效果。

设计原则：
1. 子系统"独立验证"≠"迁移"。BCRM/BDSM 仍用自己的离场逻辑
2. Facade 是 exit_engine 的薄封装，不引入新决策逻辑
3. FAIL-OPEN：任何异常返回 hold ExitDecision，不阻塞调用方
4. 支持 load_gene(json_str) 加载进化后的参数基因

用法示例（子系统验证）：
    facade = ExitModuleFacade()
    decision = facade.decide(context)
    # 对比 decision 与子系统自己的离场决策

用法示例（进化后部署）：
    facade = ExitModuleFacade()
    facade.load_gene('{"trailing_arm_pct": 0.05, ...}')
    decision = facade.decide(context)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision
from dreambuddy_evolution.engines.exit_engine.exit_engine import EvolutionExitEngine
from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
    ExitStrategyParams,
)

logger = logging.getLogger(__name__)


class ExitModuleFacade:
    """离场模块统一接口

    封装 EvolutionExitEngine，提供：
    - decide(context): 离场决策（子系统验证入口）
    - get_params(): 获取当前参数基因
    - load_gene(json_str): 加载进化后的参数基因
    """

    def __init__(
        self,
        exit_engine: Optional[EvolutionExitEngine] = None,
        strategy_params: Optional[ExitStrategyParams] = None,
    ):
        """
        Args:
            exit_engine: 已构造的 EvolutionExitEngine（可选，缺省自动构造）
            strategy_params: 离场参数基因（可选，缺省用默认值）
        """
        self._strategy_params = strategy_params or ExitStrategyParams()
        if exit_engine is not None:
            self._engine = exit_engine
        else:
            # 自动构造 EvolutionExitEngine（不依赖 OKX/ESS/FTC）
            self._engine = EvolutionExitEngine(
                okx_client=None,
                ess_provider=None,
                ftc_bridge=None,
                shadow_rl_tracker=None,
                log_fn=lambda msg, level="INFO": None,
                strategy_params=self._strategy_params,
            )

    def decide(self, context: Dict[str, Any]) -> ExitDecision:
        """离场决策入口

        Args:
            context: 离场上下文，包含 symbol/pos_side/tier/upl_ratio/current_price 等

        Returns:
            ExitDecision: 离场决策（hold/adjust_sl_tp/trailing/partial_close/force_close）

        FAIL-OPEN：任何异常返回 hold ExitDecision
        """
        try:
            return self._engine.decide(context)
        except Exception as exc:
            logger.warning("[ExitModuleFacade] decide crash (FAIL-OPEN): %s", exc)
            return ExitDecision(
                action="hold",
                params={},
                reason=f"facade_fail_open: {exc}",
                sl_px=0.0,
                tp_px=0.0,
                confidence=0.0,
            )

    def get_params(self) -> ExitStrategyParams:
        """获取当前离场参数基因"""
        return self._strategy_params

    def load_gene(self, gene_json_str: str) -> None:
        """从基因 JSON 字符串加载参数

        Args:
            gene_json_str: JSON 字符串，如 '{"trailing_arm_pct": 0.05, ...}'
                         支持部分字段，缺省用默认值
        """
        try:
            d = json.loads(gene_json_str)
            self._strategy_params = ExitStrategyParams.from_dict(d)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("[ExitModuleFacade] load_gene crash (FAIL-OPEN): %s", exc)
            # 保持原有参数不变
