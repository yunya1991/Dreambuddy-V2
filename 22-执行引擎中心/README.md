# 22-执行引擎中心

> **更新日期**：2026-10-01（补建模块入口 README）
> **模块定位**：Dreambuddy 交易执行引擎中心（TEE — Trading Execution Engine）

## 概述

执行引擎中心负责将交易意图转化为实际订单执行，包含订单路由、滑点估计、算法执行、熔断（Kill Switch）、Fail-Open 容错、审计等核心能力。

## 目录结构

```
22-执行引擎中心/
├── tee_core/        # TEE 核心实现（adapters/algorithms/core/estimators/integrations）
├── scripts/         # 工具脚本（docs_consistency / shadow_compare / slip_compare_report）
├── tests/           # 测试套件（Task 1-12 TDD 测试）
└── audit/           # 影子运行审计日志（.jsonl，运行时数据）
```

## 核心能力

| 能力 | 说明 |
|------|------|
| 订单路由 | 多交易所智能路由 |
| 滑点估计 | 实时滑点建模与预估 |
| 算法执行 | TWAP/VWAP 等算法执行 |
| Kill Switch | 紧急熔断机制 |
| Fail-Open | 容错降级执行 |
| 审计 | 全链路执行审计 |

## 文档

文档索引见 [docs/README.md](./docs/README.md)。

> **注**：五文档标准（ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG）待按 TDD 开发节奏逐步补建。
