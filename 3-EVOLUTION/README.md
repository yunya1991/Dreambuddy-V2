# 3-EVOLUTION 进化引擎

> **版本**: v0.2 | **更新日期**: 2026-08-02
> **状态**: 🧪 实验状态，未集成到主线
> **语言**: TypeScript

---

## 1. 概述

进化引擎（Evolution Engine）是 DreamBuddy-V2 的自我进化能力实验模块，基于 TypeScript 实现。当前处于实验状态，未集成到主交易系统。

## 2. 设计概述

### 2.1 进化阶段流水线

进化记录（EvolutionRecord）按 9 阶段推进，由 `EvolutionOrchestrator` 编排：

```
discovery → learning → deep_analysis → capability_update
        → code_development → collaboration → approval → deployment → completed
```

阶段定义见 [types.ts](./types.ts) `EvolutionPhase`。

### 2.2 触发源

10 类触发源（`EvolutionTriggerSource`）：`execution_failure` / `low_confidence` / `chain_disagreement` / `user_feedback` / `governance_alert` / `scheduled_audit` / `lesson_distilled` / `a8_reflection` / `dream_oneirology` / `orchestration_optimization`。

### 2.3 三桥接架构

`EvolutionOrchestrator` 协调三个桥接器联动主交易系统：

| 桥接器 | 文件 | 职责 |
|--------|------|------|
| `DZEBridge` | [dze-bridge.ts](./dze-bridge.ts) | 触发 DZE 链（深度分析） |
| `DreamAgentBridge` | [dream-agent-bridge.ts](./dream-agent-bridge.ts) | 触发 Dream Agent 协作 |
| `ApprovalBridge` | [approval-bridge.ts](./approval-bridge.ts) | 创建审批工单（代码变更前门禁） |

### 2.4 更新层

进化产物可落到 6 个更新层（`UpdateLayer`）：`knowledge` / `memory` / `index` / `skill` / `code` / `architecture`。

## 3. 核心文件

| 文件 | 职责 |
|------|------|
| `evolution-orchestrator.ts` | 进化编排器，协调三桥接器与阶段流转 |
| `evolution-engine.ts` | 进化引擎核心，EvolutionRecord 生命周期管理 |
| `evolution-fullstack.test.ts` | 全栈测试 |
| `system-architecture-test.ts` | 系统架构测试 |
| `real-benchmark.ts` | 实际基准测试 |
| `types.ts` | 类型定义（10 触发源 × 9 阶段 × 6 状态 × 6 更新层） |
| `approval-bridge.ts` | 审批桥接（代码变更门禁） |
| `dream-agent-bridge.ts` | Dream Agent 桥接 |
| `dze-bridge.ts` | DZE 深度分析链桥接 |
| `health_dashboard.json` | 健康看板数据 |

## 4. 设计参考

进化引擎的设计理念参考 SSoT v3.0 §5.3（三大核心闭环）和 §6（认知系统 + 记忆进化）。实际节点编排能力以 SSoT v3.0 为准。

## 5. 后续计划

参见 [L3_MODULE_DOC_PLAN.md](../0-系统文档管理/3-文档治理/L3_MODULE_DOC_PLAN.md) — 待集成到主线后补建完整文档（ENGINEERING_INDEX + TECHNICAL_DESIGN）。

---

**文档版本**: v0.1
**最后更新**: 2026-07-31
