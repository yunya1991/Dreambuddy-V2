"""classic_pipeline.strategy_factory — 策略工厂模块。

策略生产链路的模块化封装：
  pipeline   : 流水线编排（trigger→regime→candidate→baseline→paramopt→changeset→approval）
  changeset  : 变更包 + config_patch 验证
  approval   : 审批对接（核心，不含 LLM 分析师）
  registry   : 策略库查询（load/pick/get_entry）
  execution  : Freqtrade 执行（IStrategy 三钩子动态加载）
  gate       : Gate 检查（回测指标校验）
  audit      : 审计辅助（统一 trace_id/stage/action/actor/ts/result）
  blueprint  : Flask Blueprint，注册策略工厂路由

边界：只纳入"策略生产链路"的编排和对接，不吞并通用审批/策略管理/治理能力。
"""
from __future__ import annotations

__version__ = "0.1.0"
