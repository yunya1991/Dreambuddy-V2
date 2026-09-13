"""EvolutionExitEngine — 自进化系统独立离场决策引擎

职责（对应 Spec §X 独立离场策略）：
  1. decide(context) → ExitDecision：持仓中根据 R 向量/ESS/FTC/盈亏/时间/ATR 决策离场动作
  2. 动作集：hold / adjust_sl_tp / trailing / force_close
  3. 与 KlineEventHandler 对称：开仓由 KlineEventHandler，离场由 EvolutionExitEngine
  4. FAIL-OPEN：任何异常 → 返回 hold ExitDecision，不阻塞主链路

触发时机（用户决策 2026-09-07）：
  - K 线收盘事件（复用 _check_evolution_kline_signal 流）
  - 定时巡检（每轮 run_once）

硬约束：
  - 不修改 KlineEventHandler / ReflectionEngine 现有接口
  - 离场反思周期 ≥ 6h（G_close 稳定性保证）
  - ESS_delta ±0.02（回路增益 < 1 核心保证）
"""
from dreambuddy_evolution.engines.exit_engine.exit_engine import EvolutionExitEngine
from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision
from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
    ExitStrategyParams,
)

__all__ = ["EvolutionExitEngine", "ExitDecision", "ExitStrategyParams"]
