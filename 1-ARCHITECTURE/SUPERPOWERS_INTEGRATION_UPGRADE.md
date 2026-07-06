# Dreambuddy OS × Superpowers 方法论集成升级技术文档

> **版本**: v1.0
> **日期**: 2026-07-04
> **状态**: 设计审议中
> **作者**: 架构组
> **核心理念**: 借鉴 Superpowers 方法论上层建筑，巩固 Dreambuddy OS 内核创新
> **变更范围**: S 层增强 + A 层生态兼容 + C 层方法论约束

---

## 一、背景与动机

### 1.1 问题陈述

当前 Dreambuddy OS 已建立完整的 S/A/C/G 四层架构（感知 / 编排 / 执行 / 存储），在交易领域形成了动态图编排的核心创新。但在实际运行中暴露出以下不足：

1. **意图识别不够"多问后做"**：模糊请求直接进入执行，导致结果偏离用户期望
2. **节点执行缺乏方法论约束**：C 层节点执行依赖反射决策，但缺少"先验证再前进"的强制门禁
3. **技能生态封闭**：SkillsRegistry 仅支持内部 A/C/F 链技能，无法复用社区方法论
4. **进化机制不够系统**：补充节点虽有记忆存储，但缺少"写技能→验证→提升"的完整闭环

### 1.2 Superpowers 方法论价值

[obra/superpowers](https://github.com/obra/superpowers)（MIT 协议，194k+ Star）是 Claude Code 生态的方法论插件，提供 7 阶段软件开发工作流：

| 阶段 | Skill | 核心价值 |
|------|-------|---------|
| 1 | `brainstorming` | Socratic 提问澄清需求，HARD-GATE 阻断式确认 |
| 2 | `using-git-worktrees` | 工作区隔离，不污染主分支 |
| 3 | `writing-plans` | 拆解为 2-5 分钟微任务，自审查覆盖度 |
| 4 | `subagent-driven-development` | 子代理独立执行 + 两阶段审查 |
| 5 | `test-driven-development` | 强制红-绿-重构循环 |
| 6 | `requesting-code-review` | Spec 合规 + 代码质量双审查 |
| 7 | `finishing-a-development-branch` | 验证测试 + 分支收尾决策 |

**核心方法论原则**：
- 系统化优于即兴（Systematic over ad-hoc）
- 复杂度消减（Complexity reduction）
- 证据优于声明（Evidence over claims）
- 先验证后完成（Verification before completion）

### 1.3 集成边界原则

**必须坚守的核心创新（不动）**：
- ✅ S/A/C/G 四层 OS 内核架构
- ✅ 动态图编排（节点 + 边 + 状态），非固定线性流水线
- ✅ 置信度驱动的反射决策机制（CONTINUE/REDO/JUMP/EARLY_TERMINATE）
- ✅ G 层原生状态管理（检查点、压缩、回放）
- ✅ A/C/F 三大领域 50+ 专业交易技能

**可以借鉴的方法论上层建筑（动）**：
- 🔄 S 层：HARD-GATE 澄清机制
- 🔄 A 层：SkillsRegistry 格式兼容
- 🔄 C 层：节点级方法论约束（TDD / 两阶段审查 / 子代理派发）

---

## 二、架构现状与对标分析

### 2.1 Dreambuddy OS 四层架构

```
┌─────────────────────────────────────────┐
│  S 层 Sense 感知层                       │
│  IntentEngine + Recognizers              │
│  职责：理解意图，产出 IntentResult        │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  A 层 Arrange 编排层                     │
│  GraphPlanner + NodeSelector             │
│  职责：动态构建执行图（非固定流水线）      │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  C 层 Compute 执行层                     │
│  GraphExecutor + Reflector + Aggregator  │
│  职责：图遍历执行 + 反射决策 + 结果聚合   │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  G 层 Graph 存储层                       │
│  GraphStore + Checkpointer + Compressor  │
│  职责：状态检查点 + 上下文压缩 + 历史回放 │
└─────────────────────────────────────────┘
```

### 2.2 Superpowers 架构定位

```
┌─────────────────────────────────────────┐
│  方法论层（Superpowers 7 阶段）           │
│  运行在 AI 编程工具之上（Claude Code 等） │
│  本质：Prompt 工程方法论，非 OS 架构      │
└─────────────────────────────────────────┘
```

**关键差异**：Superpowers 是单层方法论，依赖宿主工具；Dreambuddy OS 是完整 OS 内核，自带状态管理和图存储。

### 2.3 三层对标矩阵

| 维度 | Dreambuddy OS | Superpowers | 关系 |
|------|--------------|-------------|------|
| **架构层级** | OS 内核（4层） | 方法论插件（1层） | 我们低一层，包含它 |
| **执行模型** | 动态图编排 | 线性 7 阶段流水线 | 图是更通用表达 |
| **节点来源** | A/C/F 链 50+ 交易技能 | 14 个通用编程 Skill | 领域不同，可互补 |
| **状态管理** | G 层原生存储 | git worktree + spec 文档 | 我们更体系化 |
| **记忆进化** | 进化系统（验证→提升） | writing-skills（创建新技能） | 思路相似 |
| **澄清机制** | S 层 IntentEngine | brainstorming HARD-GATE | 可借鉴 |
| **执行约束** | Reflector 反射决策 | TDD + 两阶段审查 | 可借鉴 |
| **子代理** | 无 | subagent-driven-development | 可借鉴 |

---

## 三、S 层升级：HARD-GATE 澄清机制

### 3.1 现状分析

S 层当前通过 [intent-clarification-engine.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/intent-clarification-engine.ts) 实现：

- `assessAmbiguity()` - 6 维度模糊度评估
- `generateClarificationQuestion()` - LLM 驱动生成澄清问题
- 模糊度 ≥ 50 时触发澄清
- 支持多轮收敛（最多 3 轮）

**不足**：
- 缺少 HARD-GATE 硬阻断（用户确认前可能进入执行）
- 缺少 Socratic 提问法（一次一个问题）
- 缺少 spec 文档产出（澄清后无结构化确认文档）

### 3.2 借鉴 Superpowers brainstorming

**借鉴点 1：HARD-GATE 硬阻断**

```typescript
// 增强后的 HARD-GATE 约束
<HARD-GATE>
在用户明确确认澄清结果前，禁止进入 A 层编排和 C 层执行。
这适用于所有模糊度 ≥ 50 的请求，无论看起来多简单。
</HARD-GATE>
```

**借鉴点 2：Socratic 提问法**

- 一次只问一个问题（One question at a time）
- 优先多选题（Multiple choice preferred）
- 聚焦目的 / 范围 / 深度 / 约束 / 成功标准 5 个维度

**借鉴点 3：Spec 文档产出**

澄清完成后，生成结构化的意图确认文档：

```
docs/intent-specs/YYYY-MM-DD-<topic>-intent.md
  - 用户原始请求
  - 澄清问答记录
  - 最终确认的意图
  - 范围边界
  - 成功标准
```

### 3.3 升级方案

| 项目 | 现状 | 升级后 | 改动文件 |
|------|------|--------|---------|
| HARD-GATE | 软触发（模糊度≥50） | 硬阻断（未确认不执行） | task-manager.ts |
| 提问方式 | 可一次多问 | 严格一次一问 | intent-clarification-engine.ts |
| Spec 文档 | 无 | 澄清后生成确认文档 | 新增 intent-spec-writer.ts |
| 多轮收敛 | 最多 3 轮 | 最多 3 轮（不变） | 不变 |

### 3.4 不变的核心

- ✅ S 层定位不变（感知层，产出 IntentResult）
- ✅ 意图识别引擎不变（规则 + LLM + 动态识别器）
- ✅ 意图路由机制不变

---

## 四、A 层升级：生态兼容（格式导入）

### 4.1 现状分析

A 层 [SkillsRegistry](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/skills-registry.ts) 当前：

- 支持内部 SkillCapability 注册
- 提供 `recommend()` 和 `getAll()` 等查询接口
- 节点补充通过 [node-gap-supplementer.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/node-gap-supplementer.ts) + [supplement-memory-store.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/supplement-memory-store.ts) 实现
- 进化路径：draft → validated → promoted

**不足**：
- 不支持导入外部 Skill 格式
- 无法复用 Superpowers 社区生态
- 无法导出我们的技能为通用格式

### 4.2 借鉴 Superpowers SKILL.md 格式

**Superpowers Skill 格式**：

```
skills/
  brainstorming/
    SKILL.md          ← frontmatter + Markdown 指令
    visual-companion.md
  test-driven-development/
    SKILL.md
    testing-anti-patterns.md
```

**SKILL.md 结构**：

```yaml
---
name: brainstorming
description: "You MUST use this before any creative work..."
---
# 标题
<HARD-GATE>硬约束</HARD-GATE>
## Checklist 检查清单
## Process Flow 流程图
## Key Principles 原则
```

### 4.3 升级方案：三层生态兼容

#### L1 格式兼容（优先实施）

在 SkillsRegistry 增加 `importFromSuperpowers()` 和 `exportToSuperpowers()` 方法：

```
Superpowers SKILL.md
      ↓ 解析 frontmatter + markdown
  转换为 SkillCapability
      ↓ 注册到
  SkillsRegistry
      ↓ 可导出为
  Superpowers SKILL.md
```

**价值**：
- 可直接复用社区通用 Skill（如 `systematic-debugging`、`writing-skills`）
- 我们的交易技能可导出为通用格式反哺社区
- 不改变图架构核心

#### L2 方法论借鉴（已完成大部分）

- S 层澄清对齐 brainstorming HARD-GATE（见第三章）
- C 层方法论约束（见第五章）
- writing-skills 对接进化系统

#### L3 生态互通（中期）

- 社区技能可直接导入 SkillsRegistry
- 我们的进化系统产出的技能可发布为 Superpowers 格式
- 长期价值：对接 Claude Code 作为执行后端时 Skill 层无缝衔接

### 4.4 不变的核心

- ✅ A 层动态图编排不变（非固定流水线）
- ✅ DynamicNodePlanner 不变（意图驱动节点选择）
- ✅ ChainPlanner 四维规划不变（Token 预算 / 知识库 / 历史 / 标的）
- ✅ 置信度驱动的动态追加/跳过不变

---

## 五、C 层升级：方法论约束层

### 5.1 现状分析

C 层当前通过 [graph-executor.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/graph-executor.ts) 实现：

```
while (还有节点) {
  取下一批可执行节点 → 执行节点 → 反射决策 → 决定下一步
}
```

**反射决策类型**（来自 [reflector.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/compute/reflector.py)）：
- `CONTINUE` - 正常继续
- `REDO` - 重新执行（置信度低但可挽救）
- `INSERT_BEFORE` - 插入补充节点
- `JUMP_TO` - 跳转到其他节点
- `EARLY_TERMINATE` - 提前终止
- `SKIP` - 跳过当前节点

**不足**：
- 节点执行无方法论约束（拿到任务直接干）
- 缺少"先验证再前进"的强制门禁
- 缺少子代理派发机制（复杂节点无法并行）
- 缺少两阶段审查（Spec 合规 + 质量）

### 5.2 借鉴 Superpowers 7 阶段

**适配分析**：

| Superpowers 阶段 | C 层对应 | 适配度 | 是否借鉴 |
|-----------------|---------|--------|---------|
| brainstorming（全套） | S 层已做 | 低 | ❌ 不重复 |
| using-git-worktrees | executionId 隔离 | 低 | ❌ 不适用 |
| writing-plans（全套） | A 层已做 | 低 | ❌ 不重复 |
| **subagent-driven-development** | 无 | **高** | ✅ 借鉴 |
| **test-driven-development** | 无 | **高** | ✅ 借鉴 |
| **requesting-code-review** | Reflector | **高** | ✅ 借鉴 |
| finishing-a-development-branch | Aggregator | 中 | 🔄 部分 |

### 5.3 升级方案：MethodologyExecutor 方法论包装器

#### 5.3.1 架构定位

```
┌─────────────────────────────────────────┐
│  C 层 - 图执行 + 方法论约束（增强）       │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │  MethodologyExecutor (新增)     │    │
│  │  Superpowers 方法论适配层        │    │
│  └────────────┬────────────────────┘    │
│               ▼                         │
│  ┌─────────────────────────────────┐    │
│  │  GraphExecutor (已有，不变)      │    │
│  │  图遍历 + 节点调度               │    │
│  └────────────┬────────────────────┘    │
│               ▼                         │
│  ┌─────────────────────────────────┐    │
│  │  Reflector (已有，增强)          │    │
│  │  反射决策 + 两阶段审查           │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

**核心原则**：MethodologyExecutor 是"包装器"不是"替换器"，可随时回退到原有 C 层执行。

#### 5.3.2 三个关键适配点

##### 适配点 1：节点级 TDD（test-driven-development）

**适用场景**：策略代码节点（S5 / developer 意图）

```
节点执行前：
  1. 先写测试用例（红）
  2. 跑测试确认失败
  3. 写最小实现（绿）
  4. 重构
  5. 提交
```

**实现位置**：[dev-chain.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dev-chain.ts) 的 `executeS5` 增加 TDD 约束。

**门禁规则**：
- 如果 Claude 先写代码再补测试，删除代码重来
- 测试未通过前不提交
- 测试通过后必须提交（红-绿-提交循环）

##### 适配点 2：两阶段审查（requesting-code-review）

**适用场景**：所有节点执行后

```
节点执行后：
  阶段1 - Spec 合规审查：
    - 是否符合 A 层计划要求
    - 产出是否完整
    - 有无偏离方向
    → Critical 问题阻断进度
  
  阶段2 - 质量审查：
    - 置信度是否达标
    - 有无边界遗漏
    - 有无风险点
    → Warning 记录但继续
```

**实现位置**：增强 Reflector，在 `CONTINUE` 决策前增加两阶段审查。

**问题分级**：
- **Critical**：偏离计划方向、破坏已有功能 → 阻塞
- **Warning**：代码风格、缺少边界测试 → 记录继续
- **Info**：命名建议、注释优化 → 记录继续

##### 适配点 3：子代理派发（subagent-driven-development）

**适用场景**：复杂节点（深度分析、多维度研究）

```
复杂节点执行时：
  1. 拆分为 N 个子任务
  2. 每个子任务派发独立子代理（隔离上下文）
  3. 子代理执行 + 自审查
  4. 主代理汇总结果
```

**实现位置**：GraphExecutor 增加 `dispatchSubagent()` 方法。

**价值**：
- 上下文隔离（每个子任务干净上下文）
- 审查客观性（子代理 A 写的，主代理审查）
- 并行执行（多个子任务并发）

#### 5.3.3 不借鉴的部分

| Superpowers 阶段 | 不借鉴原因 |
|-----------------|-----------|
| brainstorming（全套） | S 层已做意图澄清，C 层不重复 |
| using-git-worktrees | 交易系统不是代码仓库，执行隔离用 executionId |
| writing-plans（全套） | A 层已做图编排，C 层不重复规划 |
| finishing-a-development-branch | 用 Aggregator 聚合，不需要 git 流程 |

### 5.4 不变的核心

- ✅ 图架构（动态编排，非固定流水线）
- ✅ S/A/C/G 四层分层
- ✅ 反射决策机制（CONTINUE/REDO/JUMP 等）
- ✅ 置信度驱动

---

## 六、实施路径

### 6.1 分阶段推进

| Phase | 内容 | 改动范围 | 风险 | 优先级 |
|-------|------|---------|------|--------|
| **P0** | S 层 HARD-GATE 增强 | task-manager.ts + intent-clarification-engine.ts | 低 | 高 |
| **P1** | S 层 Spec 文档产出 | 新增 intent-spec-writer.ts | 低 | 高 |
| **P2** | A 层 SkillsRegistry 格式兼容 | skills-registry.ts | 中 | 高 |
| **P3** | C 层 MethodologyExecutor 骨架 | 新增 methodology-executor.ts | 低 | 中 |
| **P4** | C 层节点级 TDD | dev-chain.ts | 中 | 中 |
| **P5** | C 层两阶段审查 | reflector 增强 | 中 | 中 |
| **P6** | C 层子代理派发 | graph-executor.ts | 高 | 低 |

### 6.2 关键原则

1. **可回退**：每个 Phase 保持可回退，方法论层出问题可绕过回到原有执行
2. **不破坏核心**：任何改动不能破坏图架构、四层分层、反射决策
3. **渐进式**：先骨架后填充，先验证后推广
4. **可验证**：每个 Phase 完成后有明确的验收标准

### 6.3 验收标准

| Phase | 验收标准 |
|-------|---------|
| P0 | 模糊度≥50 的请求必须用户确认后才进入 A 层 |
| P1 | 澄清完成后生成 intent-spec 文档并持久化 |
| P2 | 可导入 Superpowers SKILL.md 并注册为 SkillCapability |
| P3 | MethodologyExecutor 可包装 GraphExecutor，可开关 |
| P4 | S5 策略代码节点强制 TDD，测试不过不提交 |
| P5 | 节点执行后有 Spec 合规 + 质量两阶段审查报告 |
| P6 | 复杂节点可派发子代理并行执行 |

---

## 七、风险评估与缓解

### 7.1 架构风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 方法论层过度干预简单任务 | 中 | 中 | 复杂度自动路由（micro/light/full） |
| HARD-GATE 导致交互繁琐 | 中 | 中 | 模糊度<50 不触发，简单意图直接执行 |
| 子代理派发成本过高 | 高 | 高 | 仅复杂节点启用，有明确触发条件 |
| 格式兼容引入安全风险 | 低 | 中 | 导入 Skill 沙箱执行，限制权限 |

### 7.2 性能风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| TDD 增加执行时间 | 高 | 中 | 仅策略代码节点启用，分析类不启用 |
| 两阶段审查增加延迟 | 中 | 中 | 审查并行化，非阻塞 |
| Spec 文档写入 IO | 低 | 低 | 异步写入，不阻塞主流程 |

### 7.3 用户体验风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 澄清问题过多导致用户流失 | 中 | 高 | 最多 3 轮，每轮一个多选题 |
| 方法论约束让响应变慢 | 中 | 中 | 复杂度路由，简单任务快速通道 |

---

## 八、核心创新保护声明

本升级方案**明确以下核心创新不可妥协**：

1. **S/A/C/G 四层 OS 内核架构** - 不退化为单层方法论
2. **动态图编排** - 不退化为固定线性流水线
3. **置信度驱动的反射决策** - 不被方法论约束取代
4. **G 层原生状态管理** - 不依赖外部存储
5. **A/C/F 三大领域交易技能** - 不被通用编程技能替代

**Superpowers 是上层建筑，不是地基。我们站在它的肩膀上，而不是建在它之上。**

---

## 九、参考资料

### 9.1 内部资料

- [WORKBUDDY_OS_MODULAR_ARCHITECTURE.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/WORKBUDDY_OS_MODULAR_ARCHITECTURE.md) - 模块化架构技术文档
- [SYSTEM_ARCHITECTURE_OVERVIEW.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) - 系统总体架构
- [intent-recognition-engine-design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/intent-recognition-engine-design.md) - 意图识别引擎设计

### 9.2 实现文件

- [intent-clarification-engine.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/intent-clarification-engine.ts) - 意图澄清引擎（S 层）
- [node-gap-supplementer.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/node-gap-supplementer.ts) - 节点缺失补充器（A 层）
- [supplement-memory-store.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/supplement-memory-store.ts) - 记忆存储进化（A 层）
- [dynamic-node-planner.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/dynamic-node-planner.ts) - 动态节点规划器（A 层）
- [graph-executor.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/graph-executor.ts) - 图执行引擎（C 层）
- [reflector.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/compute/reflector.py) - 反射决策器（C 层）

### 9.3 外部资料

- [obra/superpowers](https://github.com/obra/superpowers) - Superpowers 官方仓库（MIT 协议）
- [Superpowers SKILL.md 格式](https://github.com/obra/superpowers/tree/main/skills) - Skill 格式参考
- [Claude Code Plugins](https://claude.com/plugins/superpowers) - 官方插件市场

---

## 十、变更记录

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|---------|------|
| 2026-07-04 | v1.0 | 初版发布，包含 S/A/C 三层升级方案 | 架构组 |

---

## 附录 A：Superpowers 7 阶段详细对照

### A.1 brainstorming（头脑风暴）

- **触发时机**：用户提出创意性需求
- **核心机制**：Socratic 提问 + HARD-GATE 硬阻断
- **Dreambuddy 适配**：S 层 IntentClarificationEngine（已完成）
- **不借鉴部分**：完整 spec 文档流程（我们用 IntentResult 替代）

### A.2 using-git-worktrees（工作区隔离）

- **触发时机**：设计确认后
- **核心机制**：git worktree 隔离 + 项目 setup
- **Dreambuddy 适配**：不适用（交易系统非代码仓库）
- **替代方案**：executionId + G 层检查点

### A.3 writing-plans（计划编写）

- **触发时机**：工作区就绪后
- **核心机制**：拆解为 2-5 分钟微任务
- **Dreambuddy 适配**：A 层 GraphPlanner（已完成）
- **不借鉴部分**：微任务粒度（我们的节点粒度更粗）

### A.4 subagent-driven-development（子代理开发）

- **触发时机**：计划确认后
- **核心机制**：每任务独立子代理 + 两阶段审查
- **Dreambuddy 适配**：C 层 MethodologyExecutor（计划中）
- **借鉴价值**：上下文隔离 + 审查客观性

### A.5 test-driven-development（TDD）

- **触发时机**：每个实现任务内部
- **核心机制**：红-绿-重构循环
- **Dreambuddy 适配**：C 层 S5 策略代码节点（计划中）
- **借鉴价值**：先验证后提交，避免"先写后补"

### A.6 requesting-code-review（代码审查）

- **触发时机**：每个任务完成后
- **核心机制**：Spec 合规 + 代码质量双审查
- **Dreambuddy 适配**：C 层 Reflector 增强（计划中）
- **借鉴价值**：问题分级（Critical/Warning/Info）

### A.7 finishing-a-development-branch（分支收尾）

- **触发时机**：所有任务完成后
- **核心机制**：验证测试 + 合并/PR/保留/丢弃决策
- **Dreambuddy 适配**：C 层 Aggregator（已有）
- **借鉴价值**：收尾决策选项化

---

## 附录 B：进化系统对接 Superpowers writing-skills

### B.1 Superpowers writing-skills 机制

```
用户提出新需求 → Claude 创建新 SKILL.md → 测试 → 提交
```

### B.2 Dreambuddy 进化系统

```
用户提出新需求 → LLM 生成补充节点 → draft 状态
     ↓
  多次验证成功 → validated 状态
     ↓
  成熟后提升 → 注册为正式 SkillCapability
     ↓
  可导出为 Superpowers SKILL.md 格式
```

### B.3 对接价值

- 我们的进化系统有了更清晰的方法论参照
- 社区技能可直接导入我们的 SkillsRegistry
- 我们的交易技能可导出反哺社区

---

**文档结束**
