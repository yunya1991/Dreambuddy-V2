# REA 工程实践复现器演进 SPEC

> **版本**: v0.3 (2026-10-11) — 已通过同行评审，补充 NFR-1a inference 幻觉控制
> **状态**: 草案（待评审）
> **父工程**: [33-REA逆向解析工程](./SPEC.md)
> **关联**: 认知记忆系统 (4-MEMORY)、自进化系统 (23-)、DreamOS DSH

---

## 顶层定位：Proof of Engineering (PoE)

> **核心命题**：正如区块链用 POW/POS 建立去中心化信任，AI 编码时代需要 **Proof of Engineering**——AI 生成的代码必须附带"工程证明链"才能被工程系统接受。没有证明链的 AI 代码 = 没有挖矿的区块，不应被信任、不可维护、无法积累。

### 为什么需要 PoE

区块链解决的是"陌生人之间如何对账本达成共识"——通过工作量证明/权益证明，让不可信的参与者也能协作。AI 编码时代的核心问题是同构的：**人类和系统如何信任 AI 生成的代码？**

| 维度 | 区块链 | AI 编码 |
|---|---|---|
| 信任问题 | 陌生人对账本的共识 | 人/系统对 AI 代码的信任 |
| 无证明的代价 | 双花、伪造交易 | 幻觉、不可维护、认知债务 |
| 证明机制 | POW / POS | **PoE（工程证明链）** |
| 证明内容 | 哈希难题 / 抵押资产 | Evidence + 设计决策 + 演化叙事 + 方法论 |
| 验证方式 | 全节点校验 | REA 逆向审计 + 认知记忆 verify |
| 不可篡改 | 链式哈希 | Evidence provenance + git 历史 |

### PoE 的五层证明链

1. **Evidence（证据层）**：每条结论带 provenance + level + confidence + known_gaps（REA 已有）
2. **Design Decision（决策层）**：为什么这么设计——ADR 风格设计决策记录
3. **Evolution Narrative（叙事层）**：怎么演化而来——架构成长史 + 技术债路径
4. **Methodology（方法论层）**：能抽象出什么通用解法——跨项目模式蒸馏
5. **Audit（审计层）**：AI 产出的证据链完整度得分 + 认知债务清单

### 与认知系统的协同

PoE 不是孤立机制，而是认知系统在工程维度的延伸：

- **认知系统** = "记忆的证明链"：record（带证据写入）→ verify（贝叶斯置信度更新）→ recall（按证据检索）
- **REA/PoE** = "代码的证明链"：逆向还原（生成证据）→ 审计（校验完整度）→ 入库（沉淀方法论）
- **两者结合** = 完整的"AI 工作证明系统"：AI 的每一次产出（记忆/代码）都必须附带证明链，才能被系统接受和复用

这正是你说的"工程实践上的论证"——把数学证明的严谨性、区块链的信任机制、软件工程的可复现性，统一在一个框架里。

---

## Overview

- **Summary**: 将 33-REA 从"逆向解析工具"升级为"工程实践复现与蒸馏引擎"，实现 **Proof of Engineering**——让 AI 生成的代码附带可验证、可追溯、可积累的工程证明链。
- **Purpose**: 对冲 AI 编码时代的可复现性危机。AI 生成代码只给"结论"不给"证明链"（无方法论、无工具论、无可复现路径），REA 的 Evidence-First 架构天然适合反向重建这条证明链，把黑箱代码重新变成可验证、可追溯、可积累的工程知识。
- **Target Users**:
  - DreamOS 编排层 Agent（调用 REA 审计 AI 产出，执行 PoE 校验）
  - AI 编码流水线的质量门禁（PoE 作为代码合入门禁）
  - 工程知识沉淀者（将证明链蒸馏为可复用方法论）

---

## Goals

**G1 — 设计决策还原（Design Decision Recovery）**
从代码产物中还原"当初为什么这么设计"：识别架构模式、权衡痕迹、被放弃的替代方案，输出带证据的设计决策记录（ADR 风格）。

**G2 — 演化叙事生成（Evolutionary Narrative Generation）**
基于 git 历史 + 结构变化，合成"这个架构是怎么一步步长成这样的"故事线：关键转折点、重构动机、技术债累积路径。

**G3 — 方法论抽象层（Methodology Abstraction Layer）**
将针对具体项目的分析结果上升到"这类问题的通用解法"：跨项目对比、模式聚类、方法论模板生成，输出可复用的工程决策模式。

**G4 — AI 产出审计闭环（AI Output Audit Loop）**
为 AI 编码流水线提供自动审计能力：AI 提交后自动跑 REA，输出带证据的架构报告，把"认知债务"即时还清，并接入认知记忆系统形成可检索的工程知识库。

---

## Non-Goals

1. **不替代** 33-REA 现有的逆向解析能力（Python/TS 分析、调用链追踪、依赖图等），本 SPEC 是增量演进。
2. **不实现自动代码重写**：REA 只还原和审计，不修改目标代码（保持 Local-only + 只读原则）。
3. **不修改认知系统核心接口**：复用 `record` / `verify` / `recall` 现有契约，通过 `cognitive_integration.py` 扩展内容格式。
4. **不替代人工架构评审**：REA 输出是"带证据的分析报告"，最终设计决策仍需人工确认。
5. **不覆盖二进制逆向**：morluto/rea MCP 适配器保持可选，本 SPEC 聚焦源码级工程实践复现。

---

## Background & Context

### 问题本质：AI 编码的认识论缺陷

数学家抵制 OpenAI 的核心诉求是：**没有证明链的答案不配叫知识**。映射到软件工程：

| 数学语境 | 软件工程等价物 | AI 编码现状 |
|---|---|---|
| 公理 → 引理 → 定理 | 观察 → 推导 → 结论 | ❌ 直接跳到"能跑的代码" |
| 每步可证伪 | 每条结论带证据来源 | ❌ 无 provenance、无行号 |
| 证明可复现 | 他人可按同路径重现 | ❌ 换 prompt 结果就变 |
| 已知边界清晰 | 明确 known_gaps | ❌ 过度自信，不标局限 |
| 方法论可迁移 | 设计决策可复用 | ❌ 只给结果，不给"为什么" |

### REA 现有能力已构成"证明链"的基础

33-REA 已实现的能力天然对应数学证明链的各环节：

- **Evidence 数据结构** = 证明链原子单位（provenance / confidence / known_gaps / 4 层分级）
- **四阶段工作流**（Locate→Trace→Reduce→Annotate）= 完整证明流程
- **dependency_graph** = 依赖公理图（环检测 = 发现循环论证）
- **git_history** = 证明演化史
- **cognitive_integration** = 已验证证明链入库

### 现有缺口

| 缺口 | 说明 |
|---|---|
| 设计决策还原缺失 | 能还原"代码是什么"，但还原不出"为什么这么设计"（权衡、放弃的方案） |
| 演化叙事缺失 | `git_history` 有原始数据，但没合成架构成长故事线 |
| 方法论抽象缺失 | 分析结果针对具体项目，没有上升到"这类问题的通用解法" |
| AI 审计闭环缺失 | 没有为 AI 编码流水线提供自动审计的标准接口和门禁 |

---

## Functional Requirements

### 方向 A：设计决策还原（对应 G1）

**FR-A1**: 新增 `design_decision_recovery.py` 模块，提供 `recover_decisions(target)` 入口
- 输入：目标工程路径
- 输出：设计决策记录列表（ADR 风格），每条含 `decision`、`context`、`alternatives`、`consequences`、`evidence`
- 决策来源：架构模式识别 + 依赖关系分析 + 注释/文档提取 + 接口契约推断

**FR-A2**: 架构模式识别器
- 识别常见架构模式（MVC / 分层 / 事件驱动 / 管道过滤 / 插件化 等）
- 每条模式结论必须带 Evidence（observation 级：目录结构+依赖图；derivation 级：模式匹配）
- 无法确定时输出 `level=unknown` + known_gaps

**FR-A3**: 权衡痕迹检测
- 识别代码中的"设计权衡"信号：TODO/FIXME 注释、条件编译、兼容层、重复实现、废弃接口
- 输出"可能的权衡点"列表，标注置信度和已知局限

**FR-A4**: 替代方案推断
- 基于现有设计推断"被放弃的替代方案"（如：用了 ORM 但存在原生 SQL 片段 → 推断曾考虑过直接 SQL）
- 标注为 `inference` 级，必须带 known_gaps

**FR-A5**: 决策记录复用 Evidence 结构
- ADR 中的每条结论都引用至少一条 Evidence（provenance + level + confidence）
- 无证据的决策禁止输出（Evidence-First 硬约束）

### 方向 B：演化叙事生成（对应 G2）

**FR-B1**: 新增 `evolution_narrative.py` 模块，提供 `generate_narrative(target)` 入口
- 输入：目标工程路径（必须是 git 仓库）
- 输出：演化叙事文档，含时间线、关键转折点、重构动机、技术债累积

**FR-B2**: 架构转折点检测
- 基于 git log 分析：文件/目录大规模增删、依赖图剧变、核心模块重写
- 每个转折点带 Evidence（commit hash + 作者 + 时间 + 变更统计）

**FR-B3**: 重构动机推断
- 结合 commit message + 代码结构变化，推断重构动机（如："拆分 monolith 为微服务"、"引入依赖注入解耦"）
- 标注为 `inference` 级，带 known_gaps

**FR-B4**: 技术债累积路径
- 追踪 TODO/FIXME/XXX 注释的引入和消亡历史
- 输出"技术债时间线"：何时引入、是否偿还、当前存量

**FR-B5**: 叙事输出格式
- 结构化输出（JSON）+ 人类可读摘要（Markdown）
- 每条叙事结论带 Evidence 引用

### 方向 C：方法论抽象层（对应 G3）

**FR-C1**: 新增 `methodology_abstraction.py` 模块，提供 `abstract_methodology(investigations)` 入口
- 输入：多个项目的 REA 调查结果列表
- 输出：抽象方法论模板，含 `problem_pattern`、`solution_pattern`、`applicability`、`evidence`

**FR-C2**: 跨项目模式聚类
- 对多个项目的架构模式、设计决策、算法模式进行聚类
- 识别"同类问题的不同解法"和"跨项目复用的通用模式"
- 聚类结果带 Evidence（来自各项目的原始 Evidence 引用）

**FR-C3**: 方法论模板生成
- 将聚类结果抽象为可复用的方法论模板
- 模板含：问题描述、适用条件、解法步骤、已知局限、参考案例
- 模板质量标注为 `derivation` 级（基于多项目观察推导）

**FR-C4**: 方法论入库
- 方法论模板通过 `cognitive_integration.py` 写入认知记忆
- tags 标注 `methodology` + 问题域标签，便于后续 recall 检索

### 方向 D：AI 产出审计闭环（对应 G4）

**FR-D1**: 新增 `ai_audit.py` 模块，提供 `audit_ai_output(target, ai_context)` 入口
- 输入：目标工程路径 + AI 生成上下文（可选：prompt、模型、时间）
- 输出：审计报告，含架构健康度、证据链完整度、认知债务清单

**FR-D2**: 证据链完整度检查
- 检查 AI 生成代码是否有配套的设计文档、注释、测试
- 对缺失部分输出 `level=unknown` + known_gaps
- 计算"证据链完整度得分"（0.0-1.0）

**FR-D3**: 认知债务清单
- 识别 AI 生成代码中的"认知债务"：无注释的复杂逻辑、无测试的核心路径、魔法数字、硬编码
- 每条债务带 Evidence（文件+行号+问题描述）

**FR-D4**: 审计报告入库
- 审计结果通过 `cognitive_integration.py` 写入认知记忆
- 支持后续 recall 检索"某段 AI 生成代码的审计记录"

**FR-D5**: DSH 节点扩展
- 新增 DSH 节点 `S33_rea_audit` / `S33_rea_recover_decisions` / `S33_rea_narrative`
- 保持与现有 `S33_rea_analyze` / `S33_rea_trace` 一致的调用契约

---

## Non-Functional Requirements

**NFR-0（PoE 门禁硬约束）**: AI 生成的代码/变更在合入工程系统前，必须通过 PoE 校验——附带完整的工程证明链（至少含 Evidence 层和 Audit 层得分）。无证明链或证据链完整度低于阈值的 AI 产出，禁止合入。这是 PoE 作为"AI 时代开发证明算法"的核心落地。

**NFR-1（Evidence-First 硬约束）**: 所有输出的结论必须带 Evidence，无证据结论禁止输出。违反此条视为 P0 缺陷。

**NFR-1a（Inference 幻觉控制硬约束）**: `inference` 级结论必须满足以下全部条件，否则降级为 `unknown`：
1. 必须带 `known_gaps` 且非空
2. 必须标注 `confidence ≤ 0.6`
3. 不计入 `evidence_chain_score` 的分子（不提升得分）
4. 同一条记录中 inference 级结论数量不得超过 observation + derivation 级结论数量的 50%

**NFR-2（向后兼容）**: 不破坏 33-REA 现有 API（`investigate()`、`PythonAnalyzer`、`Evidence` 等）。新增模块独立，通过组合复用现有能力。

**NFR-3（本地只读）**: 所有分析在本地运行，不上传目标代码，不执行目标程序，不修改目标仓库。

**NFR-4（性能）**: 单项目分析（< 1000 文件）在 60 秒内完成；超大型项目支持增量分析和结果缓存。

**NFR-5（可测试性）**: 每个新增模块有单元测试，覆盖率 ≥ 80%。Evidence-First 相关行为必须有测试覆盖。

**NFR-6（可观测性）**: 每个阶段输出结构化日志，含目标、阶段、耗时、Evidence 数量、known_gaps 数量。

**NFR-7（FAIL-OPEN）**: 任何阶段失败时，返回部分结果 + `level=unknown` 的 Evidence 说明失败原因，不抛未捕获异常。

---

## Constraints

- **技术约束**:
  - Python 原生实现，复用 33-REA 现有 AST 分析能力
  - Evidence 结构复用 `core/evidence.py` 的 `Evidence` / `EvidenceLevel`
  - 认知集成复用 `core/cognitive_integration.py` 的接口模式
  - git 操作只读（log / blame / show），不执行修改性操作

- **业务约束**:
  - 不输出可直接用于抄袭的代码片段，强调"理解原理→自己重写"
  - 设计决策还原是"推断"而非"事实"，必须标注 level 和 known_gaps

- **依赖约束**:
  - 依赖 33-REA 现有模块：`python_analyzer`、`ts_analyzer`、`dependency_graph`、`call_chain_tracer`、`git_history`、`algorithm_reducer`、`evidence`、`cognitive_integration`
  - 依赖认知记忆系统 MCP（`record` / `verify` / `recall`），但不直接调用，由 Agent 执行

---

## Assumptions

1. 目标工程是可读的本地目录或 git 仓库（远程仓库通过 GitHub API 适配器，已有 P2 实现）
2. 33-REA 现有模块（PythonAnalyzer、CallChainTracer 等）稳定可用
3. 认知记忆系统 MCP 接口稳定，`record` 支持任意文本内容 + tags
4. 设计决策还原的准确率不要求 100%（本身是 inference 级），但必须带证据和局限标注
5. 用户（Agent）会在审计报告输出后决定是否采纳建议

---

## Acceptance Criteria

### AC-1：设计决策还原输出 ADR 风格记录
- **Type**: `rule`
- **Given**: 一个含 MVC 架构的 Python 项目
- **When**: 调用 `recover_decisions(target)`
- **Then**: 返回至少 1 条设计决策记录，含 `decision`、`context`、`evidence` 字段，且 evidence 引用至少 1 条 `observation` 级 Evidence
- **Pass Condition**: 决策记录结构完整 + 有 Evidence 支撑 + 无证据字段为空
- **Evidence**: 单元测试 `test_design_decision_recovery.py` 对固定 fixture 项目的输出断言

### AC-2：架构模式识别带证据
- **Type**: `rule`
- **Given**: 一个分层架构项目
- **When**: 架构模式识别器运行
- **Then**: 识别出的架构模式结论必须带 `provenance`（文件+行号）和 `level` 标注
- **Pass Condition**: 每条模式结论的 provenance 非空 + level ∈ {observation, derivation, inference, unknown}
- **Evidence**: 单元测试断言每条模式结论的 provenance 和 level 字段

### AC-3：演化叙事检测转折点
- **Type**: `rule`
- **Given**: 一个有明确架构重构历史的 git 仓库
- **When**: 调用 `generate_narrative(target)`
- **Then**: 输出至少 1 个架构转折点，含 commit hash、时间、变更统计
- **Pass Condition**: 转折点的 commit hash 存在于 git log + 变更统计非零
- **Evidence**: 单元测试用构造的 git 历史 fixture 验证转折点检测

### AC-4：方法论抽象跨项目聚类
- **Type**: `rule`
- **Given**: 3 个都使用 MVC 模式的项目调查结果
- **When**: 调用 `abstract_methodology(investigations)`
- **Then**: 输出至少 1 条方法论模板，problem_pattern 含 "MVC" 关键词，evidence 引用来自至少 2 个项目
- **Pass Condition**: 方法论模板存在 + evidence 跨项目引用
- **Evidence**: 单元测试用 3 个 mock 调查结果验证聚类和模板生成

### AC-5：AI 审计输出证据链完整度得分
- **Type**: `rule`
- **Given**: 一个无注释、无测试的 AI 生成代码目录
- **When**: 调用 `audit_ai_output(target)`
- **Then**: 输出审计报告含 `evidence_chain_score`（0.0-1.0）且 < 0.5，含认知债务清单
- **Pass Condition**: score 字段存在且在 [0,1] + 债务清单非空
- **Evidence**: 单元测试用构造的 AI 生成代码 fixture 验证

### AC-6：Evidence-First 硬约束
- **Type**: `rule`
- **Given**: 任意 REA 新增模块的输出
- **When**: 检查所有结论性字段
- **Then**: 不存在无 Evidence 支撑的结论（每条结论引用 ≥ 1 条 Evidence 或明确标注 level=unknown）
- **Pass Condition**: 全量扫描输出无"裸结论"
- **Evidence**: 单元测试 + 代码审查 checklist

### AC-7：DSH 新节点可调用
- **Type**: `rule`
- **Given**: DSH 运行环境
- **When**: 通过 IPC 调用 `S33_rea_audit`
- **Then**: 返回结构化 JSON 结果，含 target、evidence、known_gaps 字段
- **Pass Condition**: IPC 调用成功 + 返回结构符合契约
- **Evidence**: 集成测试通过 IPC 调用验证

### AC-8：审计结果可写入认知记忆
- **Type**: `rule`
- **Given**: 一份审计报告
- **When**: 通过 `cognitive_integration.prepare_record_params(audit_result)` 格式化
- **Then**: 输出可直接传给 `record` 的参数（content + quality_level + tags），tags 含 `rea-audit`
- **Pass Condition**: 输出参数结构合法 + tags 含预期标签
- **Evidence**: 单元测试验证格式化输出

### AC-9：设计决策还原质量
- **Type**: `rubric`
- **Dimension**: 设计决策还原的准确性与有用性
- **Scale**: 1-5
- **Anchors**: 1 = 输出与实际设计严重不符或大量误报；3 = 能识别主要架构模式但权衡/替代方案推断较弱；5 = 准确识别架构模式、权衡痕迹、替代方案，ADR 记录可直接作为架构文档草稿
- **Pass Threshold**: >= 3
- **Evidence**: 对 3 个真实开源项目（freqtrade、vectorbt、dreambuddy 自身模块）运行，人工评估 ADR 记录质量

### AC-10：演化叙事可读性
- **Type**: `rubric`
- **Dimension**: 演化叙事的可读性与信息量
- **Scale**: 1-5
- **Anchors**: 1 = 只是 commit log 的堆砌，无叙事结构；3 = 有时间线和转折点，但重构动机推断粗糙；5 = 完整的架构成长故事，转折点清晰、动机合理、技术债路径可追溯
- **Pass Threshold**: >= 3
- **Evidence**: 对 dreambuddy 自身仓库运行叙事生成，人工评估叙事质量

---

## Open Questions

- [ ] **Q1**: 设计决策还原的准确率如何量化评估？是否需要构建标注数据集？
- [ ] **Q2**: 方法论抽象的输入来自哪里？是 REA 历史调查结果的累积，还是需要主动分析一批标杆项目？
- [ ] **Q3**: AI 审计是否需要接入 git hook / CI 实现自动化？还是先提供手动调用接口？
- [ ] **Q4**: 演化叙事对非 git 项目如何降级？是否需要支持纯目录分析？
- [x] **Q5**: 设计决策还原中的"替代方案推断"容易产生幻觉，如何控制 inference 级结论的输出比例？
  - **已解决**：通过 NFR-1a 四条硬约束控制——必须带 known_gaps、confidence≤0.6、不计入 evidence_chain_score 分子、inference 数量不超过 observation+derivation 的 50%。不满足则降级为 unknown。
