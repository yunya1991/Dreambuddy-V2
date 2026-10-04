---
name: dream-arch-gap-analysis-workflow
description: "Orchestrates architecture gap analysis: recall → two-round audit → SPEC-A (gap list) → 3-dimension parallel Agent research (finance/AI multi-agent/GitHub) → integrate insights → SPEC-B (4-layer optimization + P0-P3 roadmap) → NotifyUser → hermes reflection. Invoke for 架构盘点/架构缺口/全局架构/SPEC-A/SPEC-B/架构现状/架构优化方案."
version: 1.0.0
created: 2026-09-28
updated: 2026-09-28
license: Internal
status: active
category: orchestration
triggers: [架构盘点, 架构缺口, 全局架构, SPEC-A, SPEC-B, 架构现状, 架构优化方案, 架构缺口分析]
depends_on: [dream-research-workflow, recall, record, verify, Agent, WebSearch, Glob, Grep, Read, skill-creator]
provides: [arch-gap-analysis-orchestration]
cognitive_links: [VM-1790608324891-417ef57c]
---

# Dream Arch Gap Analysis Workflow — 架构盘点与优化方案 SPEC 工作流 SKILL

> 把"recall（硬约束）→ 两轮盘点 → SPEC-A（缺口清单）→ 3 维度并行 Agent 调研 → 整合启示 → SPEC-B（4 层优化方案 + P0-P3 路线图）→ NotifyUser → hermes 反思"的 8 步架构盘点流程固化为可复用编排，元 SKILL 为 `dream-research-workflow`，结尾执行 hermes 反思决定是否再衍生新 SKILL。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-arch-gap-analysis-workflow/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/dream-arch-gap-analysis-workflow/SKILL.md`（项目级索引发现，本文件）

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **架构盘点**：用户需要对系统当前架构做全局盘点，输出"现状 vs 文档/规划"的差距清单
   - 触发词：「架构盘点」「架构缺口」「全局架构」「架构现状」
2. **行业对标调研**：用户希望基于现状缺口，对比行业最新（2025-2026）趋势做架构优化方案
   - 触发词：「架构优化方案」「行业对标」「SPEC-A」「SPEC-B」
3. **跨层架构梳理**：用户希望梳理多个层（前端/OS 内核/驱动层/中台）之间的协同关系与缺失项
   - 触发词：「跨层架构」「SACG」「DSH Subagent」「前端3.1」「中台」
4. **hermes 反思**：架构盘点结束后，用户希望反思是否形成/衍生新 SKILL
   - 触发词：「形成 SKILL」「反思」「hermes」「可复用经验」

**与 `dream-research-workflow` 的边界**：本 SKILL 聚焦"架构盘点+缺口清单+优化方案 SPEC"闭环；若需更深度的单维度专题调研（如 4 维多源/论文检索），转 `dream-research-workflow` 步骤 2。

---

## 二、8 步标准流程

### 步骤 1：recall 检索（硬约束，不可跳过）

**输入**：用户架构盘点任务描述

**处理**：
```
recall(context="架构盘点 <关键词> SPEC 优化方案", top_k=5, min_quality="C")
```

即使认为没有相关经验也必须调用一次——记忆库可能有相关记录（如本仓库 `VM-1790608324891-417ef57c` 即架构盘点 SPEC 经验）。

**输出**：相关历史经验列表（用于避免重复踩坑 + 复用已有方案）

### 步骤 2：两轮深度盘点

**输入**：用户架构盘点范围 + recall 经验

**处理**：用 `Agent(subagent_type=Explore)` 并行盘点多个层（每层一个 Agent）：

| 盘点维度 | 调研要点 | 输出 |
|---------|---------|------|
| 前端层 | 路由/组件/Store/API Client/分层是否与文档一致 | 现状 vs 文档差距表 |
| OS 内核层 (SACG) | S/A/C/G 四层 + 横切组件实际运行状态 | 各层状态表 |
| 驱动层 (DSH) | Subagent 列表 + 输出契约 + 图表能力 + C-Drive 循环 | Subagent 矩阵 |
| 中台 | 各组件（产物/网关/百炼等）实施进度 | 进度表 |

**已知坑**：
- 必须 Grep/Read 真实代码，不能凭记忆（曾因凭记忆漏掉已实现能力）
- README.md 与实现常存在矛盾（文档规划 40 子页面但实际 4 个），需标注矛盾
- 关键术语需澄清避免混淆（如 "C 系列" 在前端/SACG/C 链是不同抽象层）

**输出**：4 份分维盘点笔记（markdown 片段，含文件路径/行号）

### 步骤 3：形成 SPEC-A（缺口清单）

**输入**：4 份分维盘点笔记 + recall 经验

**SPEC-A 报告模板**（必须含以下小节）：

```markdown
# 全局架构现状与 N 缺口 SPEC (SPEC-A)

> 版本 / 日期 / 状态 / 定位 / 调研方法 / 与既有文档关系表

## 一、N 层 OS 架构总览
（ASCII 架构图 + 职责分层表 + 数据驱动避幻觉硬约束）

## 二、前端层现状
（实现盘点表 + 已实现核心能力 + README 与实现矛盾清单）

## 三、OS 内核 SACG 现状
（S/A/C/G 各层状态 + 横切组件表 + 关键证据含文件路径行号）

## 四、DSH Subagent 现状
（Subagent 清单 + 现状审计 + 输出契约 + 关键设计待实施项）

## 五、中台现状
（各组件实施进度）

## 六、缺口清单（按 P0/P1/P2 优先级组织）
（每缺口含 #/缺口/现状/目标/影响范围/优先级）

## 七、关键术语澄清（避免概念混淆）

## 八、与既有文档关系
```

**输出**：SPEC-A 路径（建议 `1-ARCHITECTURE/specs/<TOPIC>_GLOBAL_ARCH_SPEC.md`）

### 步骤 4：3 维度并行 Agent 调研

**输入**：SPEC-A 缺口清单

**处理**：用 `Agent(subagent_type=general-purpose)` 并行调研 3 维度（独立工具调用可在同一批次发出）：

| 维度 | 调研对象 | 调研要点 |
|------|---------|---------|
| 金融产品 | Bloomberg / FactSet / TradingAgents / AI-Hedge-Fund / 专业 risk/portfolio 子系统 | 编排模式/Subagent 隔离/输出契约/Checkpoint/图表能力/风险组合独立性/Cost 控制 |
| AI multi-agent | Anthropic multi-agent / Claude Code Task / OpenAI agents-as-tools / Cognition Devin / Cursor Background / LangGraph / AutoGen | 同上 |
| GitHub 开源 | TradingAgents / LangGraph / AutoGen / CrewAI / AI-Hedge-Fund / OpenAI Swarm / SWE-agent | 同上 + 学术背书（Matryoshka Agent 论文等） |

**已知坑**：
- 必须用 WebSearch/WebFetch 拉取 2025-2026 最新信息（不能凭训练数据，AutoGen 2025-10 进维护模式这种重大转向必须查实）
- 每 Agent 返回时记录项目 stars/最新版本号/重大转向时间点
- 学术论文（如 arxiv 2607.25090 Matryoshka Agent）作为学术背书单独列出
- 用户提到的特定产品（如 Meta Muse）单独 WebSearch 调研并形成子节

**输出**：3 份分维调研笔记 + 横向对比表（19+ 产品/项目）+ 学术背书清单

### 步骤 5：整合启示与去重

**输入**：3 份分维调研笔记 + 横向对比表

**处理**：
1. 提取每维度的"启示"（5 条/维，共 15 条）
2. 跨维度去重整合为 12 条左右
3. 标注"行业共识"（多产品收敛的结论）vs"创新点"（少数产品首创）

**输出**：12 条整合启示 + 行业共识表

### 步骤 6：形成 SPEC-B（优化方案）

**输入**：SPEC-A 缺口清单 + 12 条整合启示

**SPEC-B 报告模板**（必须含以下小节）：

```markdown
# 行业对标调研结论与架构优化方案 SPEC (SPEC-B)

> 版本 / 日期 / 状态 / 定位 / 调研方法 / 与既有文档关系表

## 一、调研方法与范围
（3 维度并行调研表 + 调研新发现）

## 二、3 维度调研结果
（金融产品 + AI multi-agent + GitHub 开源 各维度产品对标表 + 学术背书）

## 三、行业共识（已收敛）
（Orchestrator+Subagent 模式 / Checkpoint+Resume+Cost 仪表 / Subagent 输出契约标准化）

## 四、横向对比表
（N 产品/项目 × 7 维度对比表）

## 五、启示清单（12 条）
（每启示含来源 + 应用要点）

## 六、架构优化方案（按 4 层组织）
### 6.1 OS 内核层优化方案
### 6.2 驱动层优化方案
### 6.3 前端层优化方案
### 6.4 中台优化方案

## 七、优先级实施路线图（P0-P3）
（P0 架构闭环 / P1 决策质量 / P2 补齐 / P3 升级）

## 八、与 SPEC-A N 缺口的对应关系
（每缺口对应哪些优化项 + 优先级）

## 九、调研 Sources（关键文献）
## 十、下一步行动
## 十一、本 SPEC 不覆盖项（明确边界）
```

**输出**：SPEC-B 路径（建议 `1-ARCHITECTURE/specs/<TOPIC>_OPTIMIZATION_INDUSTRY_BENCHMARK_SPEC.md`）

### 步骤 7：NotifyUser 提交 review

**输入**：SPEC-A + SPEC-B 两份文档路径

**处理**：
```
NotifyUser(
  explanation="架构盘点完成，提交 SPEC-A（缺口清单）+ SPEC-B（优化方案）供 review",
  file_paths=[SPEC-A 绝对路径, SPEC-B 绝对路径]
)
```

**输出**：用户 review 决议（批准/调整/需要 brainstorming）

### 步骤 8：hermes 反思

**输入**：用户 review 决议 + 全流程笔记

**处理**：
1. 用户确认后，调用认知系统 `record` 记录经验
2. **hermes 反思**：评估本次流程是否值得形成/衍生新 SKILL（决策树见第五节）
3. 若需要深化某维度，转 `dream-research-workflow` 步骤 2

**record 模板**：

```
record(
  content="[架构盘点] <TOPIC> | 盘点 N 层 | 缺口 N 个(P0×N/P1×N/P2×N) | 行业对标 N 产品 | 启示 N 条 | 优化方案 N 项 | SPEC-A: <路径> | SPEC-B: <路径>",
  quality_level="B",
  tags="架构盘点,协作流程,行业对标,优化方案,hermes反思,可复用,<域标签>"
)
```

---

## 三、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | 用户架构盘点任务 | recall 经验列表 |
| 步骤 2 | recall + 任务范围 | 4 份分维盘点笔记 |
| 步骤 3 | 4 份笔记 | SPEC-A（路径） |
| 步骤 4 | SPEC-A 缺口清单 | 3 份调研笔记 + 横向对比表 |
| 步骤 5 | 3 份笔记 + 对比表 | 12 条整合启示 |
| 步骤 6 | SPEC-A + 12 启示 | SPEC-B（路径） |
| 步骤 7 | SPEC-A + SPEC-B | 用户 review 决议 |
| 步骤 8 | review 决议 + 笔记 | 认知 record + 可选新 SKILL |

---

## 四、相关 SKILL 与文档

| 类型 | 名称 | 用途 |
|------|------|------|
| 元 | `dream-research-workflow` | 本 SKILL 的元编排，hermes 反思决策树来源 |
| 工具 | `Agent(subagent_type=Explore)` | 两轮盘点（4 层并行 Agent） |
| 工具 | `Agent(subagent_type=general-purpose)` | 3 维度并行调研（金融/AI/GitHub） |
| 工具 | `WebSearch`/`WebFetch` | 行业最新趋势拉取（2025-2026） |
| 工具 | `Glob`/`Grep`/`Read` | 本仓库代码状态核实 |
| 工具 | `NotifyUser` | 提交 SPEC 供用户 review |
| 下游 | `dream-tdd-dev-workflow` | SPEC-B P0 优化项落地为 TDD 开发 |
| 下游 | `dream-eng-mgmt-workflow` | SPEC-B P0-P3 路线图转化为工程排期 |
| 元 | `skill-creator` | hermes 反思后创建新 SKILL |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 五、hermes 反思决策树

> 引用元 SKILL `dream-research-workflow` 第五节决策树（来源记忆 `VM-1790001702811-24bffe86`，B 级硬约束）。

```
本次架构盘点流程是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步，本 SKILL 8 步 ✅）
│   ├── 涉及多 Agent 并行调用（≥ 2 个 Agent，本 SKILL 步骤 2 + 步骤 4 共 7 个 Agent ✅）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思」
│
└── 否（满足以下全部）：
    ├── 一次性盘点
    ├── 单一层架构
    └── 无复用价值
    → 仅 record 经验
    → tags 不含「SKILL」
```

---

## 六、认知闭环（recall + record + verify）

**任务开始前**（硬约束，不可跳过）：

```
recall(context="架构盘点 <TOPIC 关键词> SPEC 优化方案", top_k=5, min_quality="C")
```

**任务完成后**：

```
record(content="<本次盘点摘要> | 缺口 <N> | 优化方案 <N> | SPEC-A: <路径> | SPEC-B: <路径>",
       quality_level="B",
       tags="架构盘点,协作流程,行业对标,优化方案,hermes反思,可复用,<域标签>")

# 如已验证某条已有记忆
verify(memory_id="VM-xxx", success=true)
```

**已沉淀的认知记忆**（可 recall 复用）：

| Memory ID | 等级 | 内容摘要 |
|-----------|------|---------|
| `VM-1790608324891-417ef57c` | B | 架构盘点+行业对标+优化方案 SPEC 流程（本 SKILL 创建依据） |
| `VM-1790607800376-993061bf` | B | 金融产品对标（Bloomberg/FactSet/TradingAgents/AI-Hedge-Fund 等） |
| `VM-1790607836656-587dad72` | B | AI multi-agent 对标（Anthropic/ClaudeCode/OpenAI/Devin/Cursor/LangGraph/AutoGen） |
| 本 SKILL 创建后新增 | B | 架构盘点落地经验，tags 含「SKILL,架构盘点,hermes反思」 |

---

## 七、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-28 | 初始版本，8 步流程 + 4 层并行盘点 + 3 维度并行调研 + 4 层优化方案 + P0-P3 路线图 + hermes 反思决策树 |

---

## 八、本 SKILL 不覆盖项（明确边界）

| 不覆盖项 | 责任 SKILL/文档 |
|---------|---------------|
| 单维度深度专题调研（4 维多源 + 论文检索） | `dream-research-workflow` |
| SPEC-B P0 优化项的 TDD 落地 | `dream-tdd-dev-workflow` |
| SPEC-B P0-P3 路线图转化为工程排期 | `dream-eng-mgmt-workflow` |
| 单个 Subagent 的 TDD 开发 | `dream-subagent-tdd-workflow` |
| 文档同步与索引更新 | `dream-doc-sync-workflow` |
