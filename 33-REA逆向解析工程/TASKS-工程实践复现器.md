# REA 工程实践复现器演进 - Implementation Plan

> **关联 SPEC**: [spec.md](./spec.md)
> **父工程**: 33-REA逆向解析工程

---

## Task 1: 架构模式识别器

- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 新增 `core/architecture_pattern_detector.py`
  - 识别常见架构模式：MVC、分层、事件驱动、管道过滤、插件化、微内核
  - 识别依据：目录结构 + 依赖图 + import 关系 + 命名约定
  - 每条模式结论输出 Evidence（provenance + level + confidence + known_gaps）
  - 复用 `dependency_graph.DependencyGraph` 和 `python_analyzer.PythonAnalyzer`
- **Acceptance Criteria Addressed**: AC-2, AC-6
- **Test Requirements**:
  - `rule` TR-1.1: 对一个含 MVC 目录结构的 fixture 项目，识别器输出含 "MVC" 模式结论，且该结论的 provenance 非空、level ∈ {observation, derivation}
  - `rule` TR-1.2: 对一个无明确模式的简单脚本项目，识别器输出 `level=unknown` 且 known_gaps 非空
  - `rule` TR-1.3: 所有模式结论均引用至少 1 条 Evidence，不存在裸结论
- **Notes**: 模式识别是方向 A 的基础组件，被设计决策还原模块调用

---

## Task 2: 设计决策还原模块

- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 新增 `core/design_decision_recovery.py`，提供 `recover_decisions(target)`
  - 组合架构模式识别（Task 1）+ 权衡痕迹检测（TODO/FIXME/兼容层/重复实现）+ 替代方案推断
  - 输出 ADR 风格决策记录：`{decision, context, alternatives, consequences, evidence}`
  - 替代方案推断标注为 `inference` 级，必须带 known_gaps
  - 无证据的决策禁止输出
- **Acceptance Criteria Addressed**: AC-1, AC-6, AC-9
- **Test Requirements**:
  - `rule` TR-2.1: 对 MVC fixture 项目，`recover_decisions` 返回 ≥ 1 条决策记录，含 decision/context/evidence 字段
  - `rule` TR-2.2: 每条决策记录的 evidence 引用 ≥ 1 条 `observation` 或 `derivation` 级 Evidence
  - `rule` TR-2.3: 替代方案推断字段（alternatives）存在时，其 level 必须为 `inference` 且 known_gaps 非空
  - `rubric` TR-2.4: 设计决策还原质量；scale 1-5；anchors 1=严重误报/3=识别主要模式但权衡弱/5=ADR 可作架构草稿；threshold >= 3；evidence: 对 freqtrade/vectorbt/dreambuddy 模块人工评估
- **Notes**: 本任务完成方向 A 的核心能力

---

## Task 3: 演化叙事生成模块

- **Status**: `pending`
- **Priority**: medium
- **Depends On**: None（独立依赖 git_history）
- **Description**:
  - 新增 `core/evolution_narrative.py`，提供 `generate_narrative(target)`
  - 复用 `git_history` 模块获取 commit log / blame / 文件变更统计
  - 架构转折点检测：文件/目录大规模增删、依赖图剧变、核心模块重写
  - 重构动机推断：commit message + 结构变化 → 动机标签
  - 技术债累积路径：TODO/FIXME 注释的引入与消亡历史
  - 输出：结构化 JSON + Markdown 叙事摘要
- **Acceptance Criteria Addressed**: AC-3, AC-10
- **Test Requirements**:
  - `rule` TR-3.1: 对构造的含重构历史的 git fixture 仓库，`generate_narrative` 输出 ≥ 1 个转折点，含 commit hash（存在于 git log）+ 变更统计（非零）
  - `rule` TR-3.2: 非 git 仓库调用时，输出 `level=unknown` 的 Evidence 说明降级原因，不抛异常（FAIL-OPEN）
  - `rule` TR-3.3: 技术债时间线中的每条 TODO 记录带 commit hash 和文件路径
  - `rubric` TR-3.4: 演化叙事可读性；scale 1-5；anchors 1=commit堆砌/3=有时间线但动机粗糙/5=完整架构成长故事；threshold >= 3；evidence: 对 dreambuddy 仓库人工评估
- **Notes**: 本任务完成方向 B

---

## Task 4: 跨项目模式聚类与方法论抽象

- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 2（复用决策记录输出格式）
- **Description**:
  - 新增 `core/methodology_abstraction.py`，提供 `abstract_methodology(investigations)`
  - 输入：多个项目的 REA 调查结果（含架构模式、设计决策）
  - 跨项目模式聚类：识别同类问题的不同解法、跨项目复用的通用模式
  - 方法论模板生成：`{problem_pattern, solution_pattern, applicability, evidence, known_gaps}`
  - 聚类结果的 evidence 引用来自各项目原始 Evidence
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-4.1: 对 3 个都使用 MVC 的 mock 调查结果，`abstract_methodology` 输出 ≥ 1 条方法论模板，problem_pattern 含 "MVC"，evidence 引用来自 ≥ 2 个项目
  - `rule` TR-4.2: 方法论模板的 level 标注为 `derivation`（基于多项目观察推导）
  - `rule` TR-4.3: 输入为空列表时返回空模板列表 + `level=unknown` Evidence，不抛异常
- **Notes**: 本任务完成方向 C 的核心；方法论入库在 Task 5

---

## Task 5: AI 产出审计模块

- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 2
- **Description**:
  - 新增 `core/ai_audit.py`，提供 `audit_ai_output(target, ai_context=None)`
  - 证据链完整度检查：注释覆盖、测试覆盖、文档存在性 → 计算 `evidence_chain_score`（0.0-1.0）
  - 认知债务清单：无注释复杂逻辑、无测试核心路径、魔法数字、硬编码
  - 组合架构模式识别（Task 1）和设计决策还原（Task 2）评估 AI 产出的架构健康度
  - 每条债务带 Evidence（文件+行号+问题描述）
- **Acceptance Criteria Addressed**: AC-5, AC-6
- **Test Requirements**:
  - `rule` TR-5.1: 对无注释无测试的 AI 代码 fixture，`audit_ai_output` 输出 `evidence_chain_score` ∈ [0,1] 且 < 0.5，认知债务清单非空
  - `rule` TR-5.2: 对有完整注释和测试的 fixture，`evidence_chain_score` >= 0.7
  - `rule` TR-5.3: 每条认知债务带 provenance（文件+行号）和 level 标注
- **Notes**: 本任务完成方向 D 的核心审计能力

---

## Task 6: 认知集成扩展

- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 2, Task 4, Task 5
- **Description**:
  - 扩展 `core/cognitive_integration.py`
  - 新增 `prepare_decision_record_params(decisions)` → 设计决策入库参数（tags 含 `rea-decision`）
  - 新增 `prepare_methodology_record_params(methodology)` → 方法论入库参数（tags 含 `rea-methodology`）
  - 新增 `prepare_audit_record_params(audit_result)` → 审计报告入库参数（tags 含 `rea-audit`）
  - 复用现有 `prepare_memory_content` 模式，输出 `{content, quality_level, tags}`
- **Acceptance Criteria Addressed**: AC-8
- **Test Requirements**:
  - `rule` TR-6.1: `prepare_audit_record_params` 输出 tags 含 `rea-audit`，content 包含证据链得分和债务摘要
  - `rule` TR-6.2: `prepare_methodology_record_params` 输出 tags 含 `rea-methodology`，content 包含 problem_pattern 和 solution_pattern
  - `rule` TR-6.3: 输出参数可直接传给认知系统 `record` 工具（结构合法）
- **Notes**: 不直接调用 MCP，由 Agent 执行 record

---

## Task 7: DSH 新节点接入

- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 2, Task 3, Task 5
- **Description**:
  - 扩展 `dsh_nodes.py`，新增 3 个节点：
    - `S33_rea_recover_decisions(target)` → 设计决策还原
    - `S33_rea_narrative(target)` → 演化叙事
    - `S33_rea_audit(target, ai_context=None)` → AI 审计
  - 保持与现有 `S33_rea_analyze` 一致的调用契约（NDJSON stdin/stdout）
  - 每个节点返回结构化 JSON，含 target、evidence、known_gaps
- **Acceptance Criteria Addressed**: AC-7
- **Test Requirements**:
  - `rule` TR-7.1: 通过 IPC 调用 `S33_rea_audit` 返回合法 JSON，含 target/evidence/known_gaps 字段
  - `rule` TR-7.2: 3 个新节点均注册到 DSH 节点注册表，可被发现
  - `rule` TR-7.3: 节点失败时返回含 `level=unknown` Evidence 的部分结果，不中断 DSH 进程
- **Notes**: 参照现有 `S33_rea_analyze` 实现模式

---

## Task 8: 集成测试与回归验证

- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 2, Task 3, Task 4, Task 5, Task 6, Task 7
- **Description**:
  - 新增 `tests/test_integration_reproduction.py`
  - 端到端测试：对 dreambuddy 自身某模块运行完整复现流程（决策还原 → 审计）
  - 回归测试：确保现有 33-REA 测试（109/109）零失败
  - Evidence-First 全量扫描：确认所有新增输出无裸结论
- **Acceptance Criteria Addressed**: AC-6, AC-9, AC-10
- **Test Requirements**:
  - `rule` TR-8.1: 现有 33-REA 全量测试通过（exit code 0）
  - `rule` TR-8.2: 端到端复现流程产出决策记录 + 审计报告，且全程无裸结论
  - `rubric` TR-8.3: 设计决策还原质量（与 AC-9 一致）；threshold >= 3
  - `rubric` TR-8.4: 演化叙事可读性（与 AC-10 一致）；threshold >= 3
- **Notes**: 本任务是验收门禁，需所有前置任务完成

---

## AC 覆盖矩阵

| AC | 覆盖任务 |
|---|---|
| AC-1 设计决策还原输出 ADR | Task 2 |
| AC-2 架构模式识别带证据 | Task 1 |
| AC-3 演化叙事检测转折点 | Task 3 |
| AC-4 方法论抽象跨项目聚类 | Task 4 |
| AC-5 AI 审计输出证据链得分 | Task 5 |
| AC-6 Evidence-First 硬约束 | Task 1, 2, 5, 8 |
| AC-7 DSH 新节点可调用 | Task 7 |
| AC-8 审计结果可写入认知记忆 | Task 6 |
| AC-9 设计决策还原质量 | Task 2, Task 8 |
| AC-10 演化叙事可读性 | Task 3, Task 8 |
