---
name: dream-arch-research-orchestrator
description: "开工SKILL(默认名，方便记忆) — 架构调研编排元 SKILL: 自动编排「问题定义→调研→SPEC→评审→Plan」五阶段闭环，对应调研→SPEC→评审→PLAN流程。每步调度子 SKILL 输出结果，用户确认后推进。Invoke for architecture questions, spec formation, peer review planning, or structured research-to-plan workflows. 默认名: 开工SKILL/kickoff。"
version: 1.0.0
created: 2026-10-08
updated: 2026-10-09
license: Internal
status: active
category: orchestration
triggers: [开工, 开工SKILL, kickoff, 项目启动, 架构调研编排, 研究编排, 调研到计划, 架构闭环, research orchestrator]
depends_on: [dream-contradiction-theory, dream-research-workflow, dream-qwen-eval-collab, dream-science-peer-review, dream-eng-mgmt-workflow]
provides: [research-orchestration, spec-workflow, arch-closed-loop]
cognitive_links: [VM-1791451681907-97a41b26]
---

## Autonomy Boundary

可自主执行：
- 阶段间状态机流转调度
- 子 SKILL 选择（简单/复杂问题分流）
- 认知 record/verify 调用
- 用户确认门守卫

需用户确认：
- 每阶段完成后确认是否进入下一阶段（强制确认门）
- 评审不通过时选择回退还是继续
- 阶段间跳过（需显式要求）

禁止：
- 自动执行任何阶段（必须用户确认）
- 跳过评审阶段直接进入 Plan
- 评审不通过后强行推进

---

# Dream Arch Research Orchestrator — 架构调研编排元 SKILL

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-arch-research-orchestrator/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/dream-arch-research-orchestrator/SKILL.md`（项目级索引发现，本文件）

> **默认名：开工SKILL**（方便记忆，对应"调研→SPEC→评审→PLAN"流程）。与"收尾SKILL"（dream-completion-evolution-workflow）对称：开工负责项目启动闭环，收尾负责项目完成闭环。

> 架构问题的标准闭环调度器。当用户提出问题或发现架构问题时，自动编排"调研 → SPEC → 评审 → Plan"五阶段流程，每阶段结束调用对应子 SKILL 输出结果，用户确认后明确推荐下一步。

> **本质是元 SKILL（SKILL 调度器）**，自身不做具体调研/设计/评审/计划，而是调度子 SKILL。

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **架构设计问题**：用户提出架构设计需求
   - 触发词：「开工」「开工SKILL」「架构调研编排」「研究编排」「调研到计划」「架构闭环」
2. **架构缺陷修复**：发现现有架构缺陷需要系统化修复
3. **新功能落地前**：新功能落地前的调研+设计
4. **标准闭环场景**：任何需要"调研→SPEC→评审→Plan"标准闭环的场景

---

## 二、五阶段闭环 + 子 SKILL 调度

| 阶段 | 子 SKILL | 输入 | 输出 | 用户确认门 |
|------|---------|------|------|-----------|
| **1. 问题定义** | `dream-contradiction-theory`（矛盾论拆解） | 用户原始问题 | 问题定义包（问题陈述 + 主要矛盾 + 约束 + 调研域） | ✅ 确认问题定义 |
| **2. 调研** | `dream-research-workflow`（多源调研）或 `dream-qwen-eval-collab`（千问二轮） | 问题定义包 | 调研报告（含4维交叉验证） | ✅ 确认调研结论 |
| **3. SPEC 形成** | `dream-qwen-eval-collab` 步骤4（spec合成） | 调研报告 | SPEC 文档（含接口/数据/验收） | ✅ 确认 SPEC |
| **4. 评审** | `dream-science-peer-review`（同行评审）或 `dream-qwen-eval-collab` 评估 | SPEC 文档 | 评审报告（含通过/修改建议/P0-P2） | ✅ 确认评审结论 |
| **5. Plan** | `dream-eng-mgmt-workflow`（工程管理） | 评审通过的 SPEC | 执行计划（里程碑/依赖/调度/风险） | ✅ 确认 Plan，进入执行 |

---

## 三、状态机

```
[INIT] → start(problem)
    ↓
[PROBLEM] → dream-contradiction-theory → confirm → [RESEARCH]
    ↓ rollback                               ↓
    ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←← [SPEC]
    ↓                                         ↓
[RESEARCH] → dream-research-workflow → confirm → [SPEC]
    ↓ rollback                                     ↓
    ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←← [REVIEW]
    ↓                                               ↓
[SPEC] → dream-qwen-eval-collab → confirm → [REVIEW]
    ↓                                      ↓
    ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←← [PLAN]
    ↓                                        ↓
[REVIEW] → dream-science-peer-review → confirm → [PLAN]
    ↓ rollback                                  ↓
[PLAN] → dream-eng-mgmt-workflow → confirm → [DONE]
```

**状态定义**:
- `INIT`: 初始状态，等待 start()
- `PROBLEM`: 问题定义阶段
- `RESEARCH`: 调研阶段
- `SPEC`: SPEC 形成阶段
- `REVIEW`: 评审阶段
- `PLAN`: Plan 阶段
- `DONE`: 完成

**转移条件**:
- `confirm()`: 当前阶段完成 → 下一阶段
- `rollback(targetStage)`: 回退到指定阶段（仅支持回退，不可跳过）
- `skip()`: 跳过当前阶段（需显式调用，仅适用于非关键阶段）

---

## 四、关键设计

1. **每步强制用户确认门**：阶段间不可跳过，必须用户显式确认
2. **可回退**：评审阶段若发现问题，可回退到 SPEC 阶段修订
3. **子 SKILL 选择策略**：
   - 调研：简单问题用 `dream-research-workflow`（本地，快）；复杂问题用 `dream-qwen-eval-collab`（千问，深）
   - 评审：严谨架构用 `dream-science-peer-review`（Devil's Advocate）；快速评估用 `dream-qwen-eval-collab` 步骤3
4. **认知闭环**：每个阶段结束后调用 `record` 记录经验，整个流程结束后调用 `verify` 验证
5. **每步输出 `recommended_next` + `recommended_skill`**：明确推荐下一步操作

---

## 五、接口

```typescript
class ResearchOrchestrator {
  start(problem: string): StageResult        // 启动阶段1
  confirm(): StageResult                      // 确认当前阶段，推进下一阶段
  rollback(targetStage: string): StageResult  // 回退到指定阶段
  getCurrentStage(): string                   // 获取当前阶段
  getStatus(): OrchestratorStatus             // 获取完整状态
}

interface StageResult {
  stage: string;
  skill_called: string;
  output: any;
  recommended_next: string;
  recommended_skill: string;
  needs_confirmation: boolean;
}
```
