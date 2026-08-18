# 主题索引 — TOPIC_MAP

> **版本**: v2.0 | **更新日期**: 2026-07-31
> **定位**: 按主题组织的跨系统文档索引（对齐 SSoT v3.0）
> **关联**: [SYSTEM_MAP.md](./SYSTEM_MAP.md) · [ARCHITECTURE_MAP.md](./ARCHITECTURE_MAP.md)

---

## 交易策略

| 主题 | 关键文档 | 代码入口 |
|------|---------|----------|
| V4 减半周期逃顶 | [12-三屏趋势系统/docs/TECHNICAL_DESIGN.md](../../12-三屏趋势系统/docs/TECHNICAL_DESIGN.md) | `ml/halving_top_exit_strategy.py` |
| 波浪互斥融合 | [12-三屏趋势系统/docs/STRATEGY_LINES.md](../../12-三屏趋势系统/docs/STRATEGY_LINES.md) | `ml/ewave_strategy_adapter.py` |
| V15 马丁格尔 | [14-V15经典马丁策略/docs/TECHNICAL_DESIGN.md](../../14-V15经典马丁策略/docs/TECHNICAL_DESIGN.md) | `core/v15_signal.py` |
| 经典指标 16 层信号 | [10-经典指标系统/docs/TECHNICAL_DESIGN.md](../../10-经典指标系统/docs/TECHNICAL_DESIGN.md) | `ml_trade_service.py` |
| 套利交易 | [10-经典指标系统/docs/API_SPEC.md](../../10-经典指标系统/docs/API_SPEC.md) | `carry_service.py` |

---

## 离场决策

| 主题 | 关键文档 | 代码入口 |
|------|---------|----------|
| ClassicExitSystem 四层优先级 | [10-经典指标系统/docs/API_SPEC.md](../../10-经典指标系统/docs/API_SPEC.md) | `classic_exit_system.py` → `ClassicExitSystem` |
| A9 四态离场决策 | [16-调控系统/docs/API_SPEC.md](../../16-调控系统/docs/API_SPEC.md) | `core/a9_exit_decision.py` → `a9_exit_decision_handler` |
| 易经离场系统 | [11-易经推理系统/docs/TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) | `scripts/memory_l4/yijing_exit_system.py` |
| 技术离场适配器 | [16-调控系统/docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) | `core/technical_exit_adapter.py` |
| 策略离场哲学 | [16-调控系统/docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) | `core/strategy_exit_adapter.py` |

---

## 风控体系

| 主题 | 关键文档 | 代码入口 |
|------|---------|----------|
| 三层风控架构 | [13-通用风控模块/docs/TECHNICAL_DESIGN.md](../../13-通用风控模块/docs/TECHNICAL_DESIGN.md) | `core/engine.py` → `RiskEngine` |
| L1 价值-风险评估 | [13-通用风控模块/docs/API_SPEC.md](../../13-通用风控模块/docs/API_SPEC.md) §3.4 | `core/l1_assessor.py` |
| ML 风控模型 | [13-通用风控模块/docs/API_SPEC.md](../../13-通用风控模块/docs/API_SPEC.md) §3.5 | `core/ml_model.py` |
| 飞书告警 | [13-通用风控模块/docs/API_SPEC.md](../../13-通用风控模块/docs/API_SPEC.md) §3.6 | `core/alert.py` |
| 17 条默认规则 | [13-通用风控模块/docs/API_SPEC.md](../../13-通用风控模块/docs/API_SPEC.md) §3.7 | `rules/` |
| 风控知识 | [2-KNOWLEDGE/1-TRADING/风控体系.md](../../2-KNOWLEDGE/1-TRADING/风控体系.md) | - |

---

## BCRM 与易经推理

| 主题 | 关键文档 | 代码入口 |
|------|---------|----------|
| BCRM 2.0 完整设计 | [11-易经推理系统/docs/TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) v2.9 | `scripts/memory_l4/bcrm2_adapter.py` |
| BCRM 1.0 矛盾力学 | [11-易经推理系统/docs/TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) | `scripts/memory_l4/bcrm/engine.py` |
| 辩证 ML 引擎 | [11-易经推理系统/docs/API_SPEC.md](../../11-易经推理系统/docs/API_SPEC.md) | `scripts/memory_l4/bcrm2/dialectical_ml_engine.py` |
| QMM 量化记忆 | [11-易经推理系统/docs/API_SPEC.md](../../11-易经推理系统/docs/API_SPEC.md) | `scripts/memory_l4/qmm/engine.py` |
| 五角校验 | [11-易经推理系统/docs/TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) | BCRM2×力学引擎×A0×Ising×TDA |
| A0 矛盾分析 | [11-易经推理系统/docs/TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) | `scripts/memory_l4/bcrm2/a0_contradiction.py` |

---

## 宏观分析与 SKILL

| 主题 | 关键文档 | 代码入口 |
|------|---------|----------|
| A1 调研适配器 | [16-调控系统/docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) | `core/a1_research_adapter.py` |
| A2 第一性原理 | [16-调控系统/docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) | `core/a2_first_principles_adapter.py` |
| A3 策略设计 | [16-调控系统/docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) | `core/a3_strategy_adapter.py` |
| SKILL 执行引擎 | [16-调控系统/docs/API_SPEC.md](../../16-调控系统/docs/API_SPEC.md) | `core/skill_engine.py` → `SkillEngine` |
| A 系列调度链 | [2-KNOWLEDGE/1-TRADING/A系列调度链.md](../../2-KNOWLEDGE/1-TRADING/A系列调度链.md) | - |

---

## 执行与交易

| 主题 | 关键文档 | 代码入口 |
|------|---------|----------|
| Aster 执行器 | [12-三屏趋势系统/docs/API_SPEC.md](../../12-三屏趋势系统/docs/API_SPEC.md) §7 | `live/aster_executor.py` |
| V4 波浪实盘 | [12-三屏趋势系统/docs/API_SPEC.md](../../12-三屏趋势系统/docs/API_SPEC.md) §7 | `live/v4_wave_trader.py` |
| OKX 模拟盘 | [11-易经推理系统/docs/API_SPEC.md](../../11-易经推理系统/docs/API_SPEC.md) | `scripts/memory_l4/okx_simulated.py` |
| ml_trade_service | [10-经典指标系统/docs/API_SPEC.md](../../10-经典指标系统/docs/API_SPEC.md) | `ml_trade_service.py`（端口 8092） |

---

## 进化与学习

| 主题 | 关键文档 | 代码入口 |
|------|---------|----------|
| 增强进化闭环 | [16-调控系统/docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) | `core/enhanced_evolution.py` |
| 基础进化闭环 | [16-调控系统/docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) | `core/evolution_loop.py` |
| 回测验证框架 | [16-调控系统/docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) | `core/backtest_framework.py` |
| L4 记忆管道 | [11-易经推理系统/docs/API_SPEC.md](../../11-易经推理系统/docs/API_SPEC.md) | `scripts/memory_l4/pipeline.py` |
| 自进化引擎 | [11-易经推理系统/docs/API_SPEC.md](../../11-易经推理系统/docs/API_SPEC.md) | `scripts/memory_l4/self_evolution_engine.py` |

---

## 监控与告警

| 主题 | 关键文档 | 代码入口 |
|------|---------|----------|
| 监控告警系统 | [15-监控告警系统/README.md](../../15-监控告警系统/README.md) | `monitor_core.py` |
| 飞书告警 | [13-通用风控模块/docs/API_SPEC.md](../../13-通用风控模块/docs/API_SPEC.md) §3.6 | `core/alert.py` |
| 实时行情流 | [16-调控系统/docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) | `core/realtime_market_stream.py` |

---

## 数据与基础设施

| 主题 | 关键文档 | 代码入口 |
|------|---------|----------|
| 统一持仓查询 | [16-调控系统/docs/API_SPEC.md](../../16-调控系统/docs/API_SPEC.md) | `core/unified_position_query.py` |
| 市场数据获取 | [16-调控系统/docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) | `core/market_data_fetcher.py` |
| K 线数据 | [12-三屏趋势系统/docs/API_SPEC.md](../../12-三屏趋势系统/docs/API_SPEC.md) | `data/market_data.py` |
| 产物中台 | [7-产物中台/docs/ENGINEERING_INDEX.md](../../7-产物中台/docs/ENGINEERING_INDEX.md) | - |
| 数据源降级 | [2-KNOWLEDGE/2-TECHNICAL/数据源降级管道标准.md](../../2-KNOWLEDGE/2-TECHNICAL/数据源降级管道标准.md) | - |

---

**文档版本**: v2.0
**最后更新**: 2026-07-31
