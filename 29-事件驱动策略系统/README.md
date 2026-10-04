# 29-事件驱动策略系统

> **定位**：独立子交易系统（与 BCRM2.0、BDSM 平级）
> **版本**：v1.0 | **创建日期**：2026-10-04
> **状态**：✅ 已迁移独立运行

## 概述

事件驱动策略子交易系统，专注于**离散单点宏观事件的冲击响应**（脉冲，小时-天尺度），与趋势策略（连续价格序列的方向性判断，天-周尺度）形成互补。

**核心策略逻辑**：买预期，卖事实
- 预期阶段：市场提前消化利空 → 空头偏向
- 事件落地：利空出尽，资金反手买入 → 多头偏向
- 关键驱动：实际利率（名义利率 - 通胀预期）

## 核心能力

| 模块 | 职责 |
|------|------|
| `EventDrivenStrategy` | 5 维评分策略引擎（priced_in / real_rate / resilience / lower_shadow / cross_asset） |
| `EventDrivenTrader` | 独立子交易系统执行器（开仓/仓位/SL-TP/脉冲衰减离场） |
| `ConvictionScorer` | 6 因子置信度评分（hard/soft/none 三档过滤） |
| `EventDominanceController` | 宏观事件主导控制器（双层门控 + 降档安全机制） |
| `EventCaseLibrary` | FOMC 事件案例库（案例检索 + relief/reversal 统计 + 自学习） |

## 与其他子系统关系

- **初期**：独立运行，归因清晰（避免战略层式归因灾难）
- **成熟后**：通过 `SubSystemBridge.get_event_signal()` 开放接口供 BCRM2.0/自进化/战略层消费

## 目录结构

```
29-事件驱动策略系统/
├── event_driven/              # 核心包
│   ├── __init__.py
│   ├── event_driven_strategy.py   # EventDrivenStrategy + EventDrivenTrader + EventSignal
│   ├── conviction_scorer.py       # ConvictionScorer
│   ├── event_dominance_controller.py  # EventDominanceController
│   └── event_case_library.py      # EventCaseLibrary
├── tests/                     # 测试（114 个）
└── docs/                      # 五文档标准
```

## 快速开始

```python
from event_driven import EventDrivenStrategy, EventDrivenTrader, EventSignal

strategy = EventDrivenStrategy()
signal = strategy.evaluate(kline_data)  # 返回 EventSignal
print(signal.signal, signal.confidence)
```

## 关联文档

- [docs/README.md](./docs/README.md) — 五文档索引
- [SPEC-事件驱动策略独立化-共享事件层与弹性约束.md](../23-四层闭环自进化交易架构/SPEC-事件驱动策略独立化-共享事件层与弹性约束.md) — 架构设计 SPEC
