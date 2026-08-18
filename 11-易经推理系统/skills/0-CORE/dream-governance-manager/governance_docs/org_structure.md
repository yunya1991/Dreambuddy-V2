# 公司组织与架构 · 结构说明

> **本文档描述 Dream-MultiSkill 系统的组织架构、部门职责与协作关系**
> 
> **维护规则**: 新增/撤销部门、变更职责后必须同步更新本文档

---

## 文档信息

| 项目 | 内容 |
|------|------|
| 文件位置 | `~/.workbuddy/skills/dream-governance-manager/governance_docs/org_structure.md` |
| 版本 | v1.0 |
| 创建日期 | 2026-05-01 |
| 最后更新 | 2026-05-01 |
| 维护者 | 治理管理部（COO） |

---

## 一、组织架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                      最高决策层                                  │
│                      (老板 / User)                               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
│  治理层       │   │  交易链路层    │   │  支持层           │
│  (Governance) │   │  (A1-A5)     │   │  (Support)       │
└──────────────┘   └──────────────┘   └──────────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
│ 宪法委员会    │   │ A6 情报监控   │   │ 秘书部            │
│ 治理管理部    │   │ A7 实践论     │   │ 自动修复部        │
│ HR/招聘部    │   │ A8 理论实践   │   │ 运营总监          │
│ 绩效考核部    │   │               │   │ CFO 成本控制      │
│ CFO 成本控制 │   │               │   │ 任务创建器        │
└──────────────┘   └──────────────┘   └──────────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
│ 知识层       │   │ 记忆层        │   │ 基础设施层        │
│ (Knowledge)  │   │ (Memory)      │   │ (Infra)          │
└──────────────┘   └──────────────┘   └──────────────────┘
```

---

## 二、部门职责一览

### 2.1 治理层（Governance）

| 部门 | SKILL 路径 | 核心职责 | 维护文件 |
|------|------------|----------|----------|
| 宪法委员会 | `dream-constitution` | 最高指导文件、唯物主义原理 | `SKILL.md` |
| 治理管理部 | `dream-governance-manager` | 72h 健康检查、违规检测、处罚执行 | `governance_docs/*` |
| HR/招聘部 | `dream-hr-recruitment` | 技能市场搜索、候选人评估、入职 | `SKILL.md` |
| 绩效考核部 | `dream-performance-review` | 定期评估、顾问考核、PIP | `SKILL.md` |
| CFO 成本控制部 | `dream-cost-control` | 交易成本分析、算力预算、ROI | `SKILL.md` |

---

### 2.2 交易链路层（A1-A5 + A6-A8）

| 编号 | 部门 | SKILL 路径 | 核心职责 |
|------|------|------------|----------|
| A1 | 深度调研部 | `dream-strategy-research` | 市场情报、档案数据、宏观环境 |
| A2 | 第一性原理分析部 | `dream-first-principles` | 阻力最小方向、趋势动力分析 |
| A3 | 战略制定部 | `dream-strategy-designer` | 完整战略指令、多币种/工具 |
| A4 | 战术验证部 | `dream-tactical-validator` | 多情景验证方案、三层索引、高级委托 |
| A5 | 战术执行部 | `dream-tactical-executor` | A4 验证报告 + A6 情报 → 综合判断执行 |
| A6 | 情报监控部 | `dream-intelligence-monitor` | 永不间断市场雷达、P0 告警触发 A1-A5 |
| A7 | 实践论部 | `A7-practice-theory` | 基于《实践论》的交易实践指导 |
| A8 | 理论实践验证部 | `A8-theory-practice-verification` | 理论与实践结合验证、自我批评 |

---

### 2.3 支持层（Support）

| 部门 | SKILL 路径 | 核心职责 |
|------|------------|----------|
| 秘书部 | `boss-secretary` | 信息收集、分级路由、汇总报告、邮件投递 |
| 自动修复部 | `auto-repair` | 系统健康自动修复、提案落地、72h 定时检查 |
| 运营总监 | `dream-operation-director` | 跨部门协调、流程优化、任务分配 |
| 做梦部 | `dream-oneirology` | 潜意识分析、反直觉观点、大胆洞察 |
| 任务创建器 | `dream-task-creator` | 自动化任务创建、定时任务管理 |

---

### 2.4 知识层（Knowledge & Learning）

| 部门 | SKILL 路径 | 核心职责 |
|------|------------|----------|
| 知识库 | `dream-knowledge` | 策略动态知识库、评分入库、知识进化 |
| 档案中心 | `dream-archive-center` | 外部历史经验库、联网搜索档案 |
| 数据分析部 | `dream-data-analysis` | 趋势/阻力/归因图、E[R] 映射、校准建议 |
| Episode 写入器 | `learning-episode-writer` | 决策与结果固化、skip 也写入 |
| 经验蒸馏器 | `learning-lesson-distiller` | episodes → lessons（规则/禁令/偏好） |
| 提案生成器 | `learning-proposal-generator` | lessons → 可治理变更提案 |
| 经验召回包 | `learning-recall-pack` | 从 lessons 召回本轮相关经验 |

---

### 2.5 记忆层（Memory）

| 部门 | SKILL 路径 | 核心职责 |
|------|------------|----------|
| 记忆管理器 | `memory-manager` | 压缩检测、自动快照、语义搜索 |
| 记忆蒸馏器 | `memory-distiller` | 定期审查 MEMORY.md、防止膨胀 |
| 会话索引 | `memory-session-index` | episodes/dream_* 可检索索引 |
| 记忆预算策略 | `memory-budget-policy` | 多层记忆配额、晋升/降级规则 |
| 上下文围栏 | `memory-context-fencing` | 外部信息围栏注入、防污染 |

---

### 2.6 基础设施层（Infrastructure）

| 模块 | SKILL 路径 | 核心职责 |
|------|------------|----------|
| OKX 交易引擎 | `dream-exit-skill-v2` | 退出策略、风险管理、自动化检查 |
| API 网关 | `api-gateway` | 100+ API 托管 OAuth |
| Tavily 搜索 | `tavily` | AI 优化网页搜索 |
| Agent Reach | `agent-reach` | 16 平台内容搜索 |
| 多搜索引擎 | `multi-search-engine` | 16 引擎（7 CN + 9 Global） |
| 技能创建器 | `skill-creator` | 创建/更新 SKILL 指南 |

---

## 三、信息流与协作关系

### 3.1 三邮箱体系（宪法§12.2）

```
各部门报告
    │
    ▼
┌───────────────────────────────────────────────┐
│  ① 秘书邮箱 (boss-secretary/reports/)         │
│     收集各部门工作总结（唯一输入源）           │
│     消费: Secretary-Processor (每 2h)         │
└───────────────────┬───────────────────────────┘
                    │ 分级路由
        ┌───────────┴───────────┐
        ▼                       ▼
    P0 交易                P1/P2/P3
        │                       │
        ▼                       ▼
    A1-A5 专属通道      ② 调研部邮箱
    (30min 超时自主)      (boss-secretary/reports/research/)
                           消费: Research-Processor (每 8h)
                               │
                               ▼
                          ③ 待修复邮箱
                          (boss-secretary/pending_tasks/inbox/)
                              消费: Auto-Repair-Processor (每 8h)
```

### 3.2 双轨决策链路（宪法第二章·补充）

| 链路 | 触发条件 | 处理流程 | 超时处理 |
|------|----------|----------|----------|
| P0/P1 交易 | 止损触发、趋势反转、杠杆超标 | A1→A2→A3→A4→A5 | 30min 无回复 → 自主执行 |
| P2/常规 | 系统优化、流程改进、新增功能 | 调研→顾问会诊→提案→执行 | 按顾问链路 |

---

## 四、部门编号与缩写对照

| 编号 | 部门名称 | 缩写 | SKILL 关键词 |
|------|----------|------|--------------|
| - | 宪法委员会 | CONST | `dream-constitution` |
| G01 | 治理管理部 | GOV | `dream-governance-manager` |
| G02 | HR/招聘部 | HR | `dream-hr-recruitment` |
| G03 | 绩效考核部 | PR | `dream-performance-review` |
| G04 | CFO 成本控制部 | CFO | `dream-cost-control` |
| A1 | 深度调研部 | RES | `dream-strategy-research` |
| A2 | 第一性原理分析部 | FP | `dream-first-principles` |
| A3 | 战略制定部 | SD | `dream-strategy-designer` |
| A4 | 战术验证部 | TV | `dream-tactical-validator` |
| A5 | 战术执行部 | TE | `dream-tactical-executor` |
| A6 | 情报监控部 | IM | `dream-intelligence-monitor` |
| A7 | 实践论部 | PT | `A7-practice-theory` |
| A8 | 理论实践验证部 | TPV | `A8-theory-practice-verification` |
| S01 | 秘书部 | SEC | `boss-secretary` |
| S02 | 自动修复部 | AR | `auto-repair` |
| S03 | 运营总监 | COO | `dream-operation-director` |
| S04 | 做梦部 | ONE | `dream-oneirology` |
| K01 | 知识库 | KNO | `dream-knowledge` |
| K02 | 档案中心 | ARC | `dream-archive-center` |
| K03 | 数据分析部 | DA | `dream-data-analysis` |
| M01 | 记忆管理器 | MEM | `memory-manager` |

---

## 五、动态更新机制

### 5.1 更新触发条件

| 触发条件 | 更新内容 | 执行者 |
|----------|----------|--------|
| 新增部门 | 在第二章添加部门条目、更新组织架构图 | 治理管理部 |
| 撤销部门 | 在第二章标记`[已撤销]`，移至历史章节 | 治理管理部 |
| 职责变更 | 更新对应部门的核心职责描述 | 治理管理部 |
| 编号调整 | 更新第四章编号与缩写对照表 | 治理管理部 |
| 信息流变更 | 更新第三章信息流与协作关系 | 治理管理部 |

### 5.2 更新检查清单

```
组织架构更新后检查清单：
□ 组织架构图（第一章）已更新？
□ 部门职责一览表（第二章）已更新？
□ 信息流与协作关系（第三章）已更新？
□ 部门编号与缩写对照表（第四章）已更新？
□ 治理文档索引（constitution.md）已同步更新？
```

### 5.3 更新记录

| 版本 | 日期 | 更新内容 | 更新人 |
|------|------|----------|--------|
| v1.0 | 2026-05-01 | 初始创建，7 层架构、5 类部门、完整职责 | 治理管理部 |

---

## 六、历史部门变更记录

| 日期 | 变更类型 | 部门名称 | 说明 |
|------|----------|----------|------|
| 2026-05-01 | 初始创建 | 全部 | 首次建立组织架构文档 |

---

> **最后更新**: 2026-05-01
> **维护者**: 治理管理部（COO）
> **宪法依据**: 宪法§0.1 核心文件定位 — 公司章程定义部门职责
> **下次审查**: 2026-05-08（每周审查）
