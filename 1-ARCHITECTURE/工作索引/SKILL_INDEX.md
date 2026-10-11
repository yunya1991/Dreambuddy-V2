# SKILL Index

> 自动生成于 2026-10-11 14:46
> 总数量: 247 SKILL

## 概览

| 分类 | 数量 |
|------|------|
| cognition | 14 |
| core | 2 |
| governance | 2 |
| knowledge | 2 |
| meta | 4 |
| orchestration | 77 |
| research | 51 |
| support | 1 |
| tooling | 43 |
| trading | 49 |
| trigger | 2 |

## 状态分布

| 状态 | 数量 |
|------|------|
| active | 207 |
| proposed | 28 |
| shadow | 12 |

## cognition

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| debate-adjudication-methodology | 1.0.0 | active | 裁判评审6维评分+RFD方法论。Invoke when 辩论裁判评审、6维评分、RFD裁决理由、InspireScore评分。 |
| debate-adjudication-methodology | 1.0.0 | active | 裁判评审6维评分+RFD方法论。Invoke when 辩论裁判评审、6维评分、RFD裁决理由、InspireScore评分。 |
| debate-con-side | 1.0.0 | active | 反方辩手辩论策略方法论。Invoke when 反方辩论策略、推翻举证、refutation、反方persona构建。 |
| debate-con-side | 1.0.0 | active | 反方辩手辩论策略方法论。Invoke when 反方辩论策略、推翻举证、refutation、反方persona构建。 |
| debate-pro-side | 1.0.0 | active | 正方辩手辩论策略方法论。Invoke when 正方辩论策略、prima facie举证、正方persona构建。 |
| debate-pro-side | 1.0.0 | active | 正方辩手辩论策略方法论。Invoke when 正方辩论策略、prima facie举证、正方persona构建。 |
| debate-reflection-methodology | 1.0.0 | active | 赛后反思5步循环方法论。Invoke when 辩论赛后反思、策略提取、gap分析、改进建议、Practice Loop。 |
| debate-reflection-methodology | 1.0.0 | active | 赛后反思5步循环方法论。Invoke when 辩论赛后反思、策略提取、gap分析、改进建议、Practice Loop。 |
| learning-episode-writer | 0.0.0 | active | 将每轮决策与结果固化为 episode（包含评分/门禁/执行/结果/证据引用），skip 也必须写入，作为学习闭环事实底座。 |
| learning-episode-writer | 0.0.0 | active | 将每轮决策与结果固化为 episode（包含评分/门禁/执行/结果/证据引用），skip 也必须写入，作为学习闭环事实底座。 |
| learning-lesson-distiller | 0.0.0 | active | 从 episodes 蒸馏 lessons（规则/禁令/偏好），引入频次与严重度阈值，防止“1 次失败=1 条死规则”的噪声过拟合。 |
| learning-proposal-generator | 0.0.0 | active | 将反思与蒸馏结果转为可治理的变更提案（proposal），只产出提案不自动应用，必须携带 rollback_plan_id 与 evidence_refs。 |
| memory-manager | 0.0.0 | active | Local memory management for agents. Compression detection, auto-snapshots, and semantic search. Use when agents need to detect compression risk before memory loss, save context snapshots, search historical memories, or track memory usage patterns. Never lose context again. |
| meta-reflection | 0.0.0 | active | Use when reviewing closed trading episodes, attributing outcomes to cognitive biases, detecting paper-tiger integration, or iterating executable lessons into the next decision cycle |

## core

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| artifact-alignment-manager | 1.0.0 | active | 产物投递管理 SKILL v7.3 |
| dream-governance-manager | 1.0.0 | active | Dream-MultiSkill 治理管理 SKILL v1.0 |

## governance

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| dream-hr-recruitment | 2.0.0 | active | Dream-MultiSkill HR/招聘部 - 负责技能市场搜索、候选人评估、技能安装与入职、试用期追踪、人才储备、蒸馏产物继承入职。当遇到以下情况时触发：需要某个技能但未安装、功能缺失需要新技能、现有技能不足需要升级、技能市场调研、能力缺口分析、蒸馏产物继承、大师能力包入职。 |
| dream-operation-director | 1.0.0 | active | Dream-MultiSkill 运营总监 (COO) - 负责协调各团队、流程优化、任务分配、跨部门沟通。当遇到以下情况时触发：协调多个部门、流程优化建议、任务分配不明确、跨部门问题升级、流程卡顿需要疏通。 |

## knowledge

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| knowledge-ingest | 1.0.0 | active | 知识沉淀 SKILL: SKILL 执行完成后将产出的知识/案例分类入库 + RAG 向量化 + 认知记录 + 索引更新。Invoke when research-type SKILLs complete, cognitive record tags contain 'knowledge-ingest', or explicit knowledge ingestion needed. |
| knowledge-ingest | 1.0.0 | active | 知识沉淀 SKILL: SKILL 执行完成后将产出的知识/案例分类入库 + RAG 向量化 + 认知记录 + 索引更新。Invoke when research-type SKILLs complete, cognitive record tags contain 'knowledge-ingest', or explicit knowledge ingestion needed. |

## meta

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| brainstorming | 0.0.0 | active | You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation. |
| debate-classic-methodology-—-oxford-式经典辩论赛制 | 0.0.0 | active |  |
| debate-classic-methodology-—-oxford-式经典辩论赛制 | 0.0.0 | active |  |
| executing-plans | 0.0.0 | active | Use when you have a written implementation plan to execute in a separate session with review checkpoints |

## orchestration

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| agent-collab-supervisor | 1.0 | active | 协作监督 SKILL。核验任务卡、评审记录、评论协议、测试证据与分支合规性。触发词：流程监督、监督检查、collab supervisor |
| architecture-sync-guard | 0.0.0 | active | 主干合并前的架构冲突与信息同步守卫流程。用于“检查架构一致性”“检查改一处是否需要同步其他文档/契约”“PR门禁冲突排查”等场景，确保 constraints/workflows/docs 的联动更新完整。 |
| boss-secretary | 0.0.0 | active |  |
| debate-topic-selector | 1.0.0 | active | 辩论话题选题引擎：WebSearch热点+交易SKILL信号+用户审校。Invoke when 用户提到选题、话题选题、选题辩论、辩论话题、topic selection时自动调用。 |
| debate-topic-selector | 1.0.0 | active | 辩论话题选题引擎：WebSearch热点+交易SKILL信号+用户审校。Invoke when 用户提到选题、话题选题、选题辩论、辩论话题、topic selection时自动调用。 |
| dispatching-parallel-agents | 0.0.0 | active | Use when facing 2+ independent tasks that can be worked on without shared state or sequential dependencies |
| dream-acceptance-verify | 1.0.0 | active | Bug修复/功能完成后的强制证据验收门禁：症状复测+日志证据+回归+影响面+边界五维验证，产出四文件验收包。AI宣称'完成/修复/通过'前必须调用，禁止靠感觉验收。 |
| dream-acceptance-verify | 1.0.0 | active | Bug修复/功能完成后的强制证据验收门禁：症状复测+日志证据+回归+影响面+边界五维验证，产出四文件验收包。AI宣称'完成/修复/通过'前必须调用，禁止靠感觉验收。 |
| dream-arch-collaboration-workflow | 0.0.0 | active | 三层架构能力协同调用规范+认知系统协作流程。Invoke for 主骨架调用链编排、跨子系统协同、LLM四阶段协作、认知recall命中架构记忆、或需调用DreamOS/DSH/子域能力时。 |
| dream-arch-collaboration-workflow | 0.0.0 | active | 三层架构能力协同调用规范+认知系统协作流程。Invoke for 主骨架调用链编排、跨子系统协同、LLM四阶段协作、认知recall命中架构记忆、或需调用DreamOS/DSH/子域能力时。 |
| dream-arch-gap-analysis-workflow | 1.0.0 | active | Orchestrates architecture gap analysis: recall → two-round audit → SPEC-A (gap list) → 3-dimension parallel Agent research (finance/AI multi-agent/GitHub) → integrate insights → SPEC-B (4-layer optimization + P0-P3 roadmap) → NotifyUser → hermes reflection. Invoke for 架构盘点/架构缺口/全局架构/SPEC-A/SPEC-B/架构现状/架构优化方案. |
| dream-arch-gap-analysis-workflow | 1.0.0 | active | Orchestrates architecture gap analysis: recall → two-round audit → SPEC-A (gap list) → 3-dimension parallel Agent research (finance/AI multi-agent/GitHub) → integrate insights → SPEC-B (4-layer optimization + P0-P3 roadmap) → NotifyUser → hermes reflection. Invoke for 架构盘点/架构缺口/全局架构/SPEC-A/SPEC-B/架构现状/架构优化方案. |
| dream-arch-research-orchestrator | 1.0.0 | active | 开工SKILL(默认名，方便记忆) — 架构调研编排元 SKILL: 自动编排「问题定义→调研→SPEC→评审→Plan」五阶段闭环，对应调研→SPEC→评审→PLAN流程。每步调度子 SKILL 输出结果，用户确认后推进。Invoke for architecture questions, spec formation, peer review planning, or structured research-to-plan workflows. 默认名: 开工SKILL/kickoff。 |
| dream-arch-research-orchestrator | 1.0.0 | active | 开工SKILL(默认名，方便记忆) — 架构调研编排元 SKILL: 自动编排「问题定义→调研→SPEC→评审→Plan」五阶段闭环，对应调研→SPEC→评审→PLAN流程。每步调度子 SKILL 输出结果，用户确认后推进。Invoke for architecture questions, spec formation, peer review planning, or structured research-to-plan workflows. 默认名: 开工SKILL/kickoff。 |
| dream-archive-center | 1.0.0 | active | Dream-MultiSkill 档案管理中心 — 外部历史经验库，与内部记忆互补。收集成功案例、失败教训、行业最佳实践，通过联网搜索获取外部档案。触发词：档案、案例、教训、历史经验、外部调研、类似事件 |
| dream-attention-radar | 1.0.0 | active | 📡 注意力雷达部 — 三源多头注意力标的筛选器
通过资金注意力、情绪注意力、周期注意力三大Query-Key-Value注意力头
做动态推理+协同注意力融合，输出做多/做空Top N具体标的排名。
触发词：注意力雷达、资金注意力、情绪注意力、周期注意力、
       三源注意力、标的筛选、多空排名、attention radar
 |
| dream-backtest-verify | 1.0.0 | active | Orchestrates 5-step post-hoc backtest verification: load trades → fetch klines → run detector gate → rebound attribution → value report. Invoke for backtest verification of trading subsystems (BDSM/BCRM/strategy/evolution/washout). |
| dream-backtest-verify | 1.0.0 | active | Orchestrates 5-step post-hoc backtest verification: load trades → fetch klines → run detector gate → rebound attribution → value report. Invoke for backtest verification of trading subsystems (BDSM/BCRM/strategy/evolution/washout). |
| dream-bayesian-opt | 0.0.0 | active |  |
| dream-bugfix-workflow | 1.0.0 | active | Orchestrates bugfix: symptom collect → reproduce → root cause (5why) → fix proposal → TDD verify → hermes reflection. Invoke for bug fix, root cause analysis. |
| dream-bugfix-workflow | 1.0.0 | active | Orchestrates bugfix: symptom collect → reproduce → root cause (5why) → fix proposal → TDD verify → hermes reflection. Invoke for bug fix, root cause analysis. |
| dream-classic-pipeline-tdd-migration | 0.0.0 | active | Orchestrates Classic Pipeline C0-C8 nine-node TDD migration: RED test (assert real business logic) → GREEN impl (simplified extraction from ml_trade_service.py) → REFACTOR (full suite no regression) → E2E serial validation → frontend agent-browser acceptance. Invoke for classic pipeline node migration, C0-C8 TDD, node RED-GREEN-REFACTOR cycle, or frontend pipeline acceptance testing. |
| dream-classic-pipeline-tdd-migration | 0.0.0 | active | Orchestrates Classic Pipeline C0-C8 nine-node TDD migration: RED test (assert real business logic) → GREEN impl (simplified extraction from ml_trade_service.py) → REFACTOR (full suite no regression) → E2E serial validation → frontend agent-browser acceptance. Invoke for classic pipeline node migration, C0-C8 TDD, node RED-GREEN-REFACTOR cycle, or frontend pipeline acceptance testing. |
| dream-code-commit-sync-workflow | 1.0.0 | active | Orchestrates code-change auto-commit: change parse → precise stage → validate (tsc/tests) → conventional commit message → commit → orphan-scan → cognitive record. Invoke when code changes are complete and need committing, or when user says 'commit/sync code'. |
| dream-code-commit-sync-workflow | 1.0.0 | active | Orchestrates code-change auto-commit: change parse → precise stage → validate (tsc/tests) → conventional commit message → commit → orphan-scan → cognitive record. Invoke when code changes are complete and need committing, or when user says 'commit/sync code'. |
| dream-code-deploy-pipeline | 1.0.0 | active | Orchestrates full code delivery pipeline: local commit → GitHub CI (Actions) → server deploy (webhook/update.sh) → healthcheck → rollback. Invoke when user wants to sync code to cloud, deploy to server, set up CI/CD, or roll back a bad deployment. |
| dream-code-deploy-pipeline | 1.0.0 | active | Orchestrates full code delivery pipeline: local commit → GitHub CI (Actions) → server deploy (webhook/update.sh) → healthcheck → rollback. Invoke when user wants to sync code to cloud, deploy to server, set up CI/CD, or roll back a bad deployment. |
| dream-code-sync-orphan-scan-workflow | 1.0.0 | active | Orchestrates 6-step post-commit orphan-component scan + integration + commit lock for frontend src/. Invoke when git commit/push completes, to detect untracked/modified files and orphan .tsx components that should have been wired up but weren't. Catches 'claimed done but not committed' regressions. |
| dream-code-sync-orphan-scan-workflow | 1.0.0 | active | Orchestrates 6-step post-commit orphan-component scan + integration + commit lock for frontend src/. Invoke when git commit/push completes, to detect untracked/modified files and orphan .tsx components that should have been wired up but weren't. Catches 'claimed done but not committed' regressions. |
| dream-completion-evolution-workflow | 1.0.0 | active | 收尾SKILL(默认名，方便记忆) — SPEC任务完成后的自动收尾编排器: 验收门禁→代码提交→文档同步→SKILL治理→认知闭环→最终报告。智能路由按变更类型决定执行哪些步骤，验收是硬门禁其余FAIL-OPEN。与开工SKILL对称：开工负责启动闭环(调研→SPEC→评审→PLAN)，收尾负责完成闭环(验收→commit→文档→治理→认知→报告)。Invoke when a SPEC task/feature/bugfix is dev-complete and needs wrap-up, or when user says '收尾/wrap up/finish up/complete'. 默认名: 收尾SKILL/wrapup。 |
| dream-completion-evolution-workflow | 1.0.0 | active | 收尾SKILL(默认名，方便记忆) — SPEC任务完成后的自动收尾编排器: 验收门禁→代码提交→文档同步→SKILL治理→认知闭环→最终报告。智能路由按变更类型决定执行哪些步骤，验收是硬门禁其余FAIL-OPEN。与开工SKILL对称：开工负责启动闭环(调研→SPEC→评审→PLAN)，收尾负责完成闭环(验收→commit→文档→治理→认知→报告)。Invoke when a SPEC task/feature/bugfix is dev-complete and needs wrap-up, or when user says '收尾/wrap up/finish up/complete'. 默认名: 收尾SKILL/wrapup。 |
| dream-cost-control | 0.0.0 | active | Dream-MultiSkill 成本控制部 (CFO) - 交易成本分析、算力预算控制、收益归因、ROI评估。超预算时告警。触发：成本、预算、ROI、收益、手续费、滑点、API费用 |
| dream-data-analysis | 1.0.0 | active | 将每轮多维输出沉淀为可统计时间序列并产出趋势/阻力/归因图与校准建议。Invoke when 需要把长期记忆与数学统计用于趋势惯性与阻力最小原则落地。触发词：数据分析、趋势图、阻力分析、校准建议、雷达图、图表展示、可视化、Dashboard、MA/EMA、趋势强度、阻力分解、长期记忆统计、episode分析 |
| dream-data-analysis | 1.0.0 | active | 将每轮多维输出沉淀为可统计时间序列并产出趋势/阻力/归因图与校准建议。Invoke when 需要把长期记忆与数学统计用于趋势惯性与阻力最小原则落地。触发词：数据分析、趋势图、阻力分析、校准建议、雷达图、图表展示、可视化、Dashboard、MA/EMA、趋势强度、阻力分解、长期记忆统计、episode分析 |
| dream-doc-sync-gate | 1.0 | active |  |
| dream-doc-sync-workflow | 1.0.0 | active | Orchestrates 7-step doc index sync: change parse → 0-系统文档管理/INDEX update → 2-KNOWLEDGE index update → doc_lint+link_checker validate → doc_coverage → feishu base sync → cognitive record. Invoke when docs are added/deleted/modified, or cognitive record tags contain 'doc-sync'. |
| dream-doc-sync-workflow | 1.0.0 | active | Orchestrates 7-step doc index sync: change parse → 0-系统文档管理/INDEX update → 2-KNOWLEDGE index update → doc_lint+link_checker validate → doc_coverage → feishu base sync → cognitive record. Invoke when docs are added/deleted/modified, or cognitive record tags contain 'doc-sync'. |
| dream-eng-mgmt-workflow | 1.0.0 | active | Orchestrates eng mgmt: requirement breakdown → milestone planning → dependency graph → scheduling → risk plan → hermes reflection. Invoke for eng mgmt, scheduling, milestone. |
| dream-eng-mgmt-workflow | 1.0.0 | active | Orchestrates eng mgmt: requirement breakdown → milestone planning → dependency graph → scheduling → risk plan → hermes reflection. Invoke for eng mgmt, scheduling, milestone. |
| dream-execution-cost-model | 0.0.0 | active | 在下单前评估手续费、滑点与最坏成交假设，给出是否允许市价单/是否需要降级执行的建议，供 dream-multiSkill 做执行前门禁。 |
| dream-feature-landing-workflow | 1.0.0 | active | Orchestrates DreamOS feature landing: backend contract/hook changes → 3.1-FRONTEND API+component+store adaptation → FAIL-OPEN validation (tsc+tests+HTTP200). Invoke when implementing SPEC tasks (D/F/O/M series) or landing new DreamOS features. |
| dream-feature-landing-workflow | 1.0.0 | active | Orchestrates DreamOS feature landing: backend contract/hook changes → 3.1-FRONTEND API+component+store adaptation → FAIL-OPEN validation (tsc+tests+HTTP200). Invoke when implementing SPEC tasks (D/F/O/M series) or landing new DreamOS features. |
| dream-genome-factor-workflow | 1.0.0 | active | Orchestrates genome factor development: recall → RED (3 test files) → GREEN (3 impl files) → wire-up → backtest → regression → cognitive closure. Invoke for genome factor, washout reversal, pump-dump reversal, factor TDD. |
| dream-genome-factor-workflow | 1.0.0 | active | Orchestrates genome factor development: recall → RED (3 test files) → GREEN (3 impl files) → wire-up → backtest → regression → cognitive closure. Invoke for genome factor, washout reversal, pump-dump reversal, factor TDD. |
| dream-intelligence-analysis | 1.0.0 | active | 📡 情报分析核心理论与工具箱 — 蒸馏自《情报分析心理学》+ 《结构化分析技术》
提供认知偏见检查、结构化分析工具、情报验证流程，提升 A6 情报分析的专业性和严谨性。

触发词：情报分析、认知偏见、结构化分析、红队分析、情景分析、关键假设检查、ACH、竞争性假设分析、情报验证、不确定性分析
 |
| dream-intelligence-monitor | 4.9.0 | active | 📡 情报监控 — 永不间断的市场雷达
每小时运行，持续监控市场状态变化、异常信号、战略环境变更，
当检测到重大变化时，触发相应的响应流程。
⚠️ v4.8新增: **Level 1.5 A2增量更新脚本** (2026-04-29修复)
⚠️ v4.9新增: **A6→做梦部自动复制脚本** (2026-04-29修复)
⚠️ v4.9新增: **Level 1.5 A2增量更新脚本** (2026-04-29修复)
触发词：情报监控、市场监控、实时监控、异常告警、战略变更、P0告警、重大变化、A4上报、A4触发A6、宏观资产、共振信号、风险库检测、Exit Skill联动
 |
| dream-intelligence-monitor | 4.9.0 | active | 📡 情报监控 — 永不间断的市场雷达
每小时运行，持续监控市场状态变化、异常信号、战略环境变更，
当检测到重大变化时，触发相应的响应流程。
⚠️ v4.8新增: **Level 1.5 A2增量更新脚本** (2026-04-29修复)
⚠️ v4.9新增: **A6→做梦部自动复制脚本** (2026-04-29修复)
⚠️ v4.9新增: **Level 1.5 A2增量更新脚本** (2026-04-29修复)
触发词：情报监控、市场监控、实时监控、异常告警、战略变更、P0告警、重大变化、A4上报、A4触发A6、宏观资产、共振信号、风险库检测、Exit Skill联动
 |
| dream-module-post-dev-verify-workflow | 1.0.0 | active | Orchestrates 7-step post-dev module verification: boundary identify → public API list → integration point grep → test run → artifact log check → doc alignment → cognitive closure. Invoke when a module is 'dev complete' to catch 'coded but not wired' regressions before commit. |
| dream-module-post-dev-verify-workflow | 1.0.0 | active | Orchestrates 7-step post-dev module verification: boundary identify → public API list → integration point grep → test run → artifact log check → doc alignment → cognitive closure. Invoke when a module is 'dev complete' to catch 'coded but not wired' regressions before commit. |
| dream-performance-review | 0.0.0 | active | Dream-MultiSkill 绩效考核部 (HRBP) - 定期评估各部门/技能表现、顾问团考核、对不合格者启动PIP改进计划，改进无效时触发招聘流程。监控GitHub/技能市场热门项目。触发：绩效、考核、KPI、评分、评级、GitHub监控、市场情报、能力盘点、顾问考核、顾问绩效 |
| dream-product-hub-maintenance | 1.0.0 | active | 产物中心前端(localhost:3456)维护指南。覆盖内容扫描、文件格式、分类映射、常见踩坑及修复。触发词：产物中心、Product Hub、feed修复、内容不显示、excerpt、article显示 |
| dream-qwen-eval-collab | 1.0.0 | active | Orchestrates 5-step Qwen collab: user need → trae analysis → bsk calls Qwen research → trae evaluates & generates spec → user review. Invoke for Qwen/second-round eval, or complex 4-dim research (finance+github+modular+code). |
| dream-qwen-eval-collab | 1.0.0 | active | Orchestrates 5-step Qwen collab: user need → trae analysis → bsk calls Qwen research → trae evaluates & generates spec → user review. Invoke for Qwen/second-round eval, or complex 4-dim research (finance+github+modular+code). |
| dream-research-workflow | 1.0.0 | active | Orchestrates 5-step research: need analysis → multi-source research (finance+github+modular+code) → cross-validation → report → hermes reflection. Invoke for deep research, market research, or tech research. |
| dream-research-workflow | 1.0.0 | active | Orchestrates 5-step research: need analysis → multi-source research (finance+github+modular+code) → cross-validation → report → hermes reflection. Invoke for deep research, market research, or tech research. |
| dream-scattered-file-cleanup | 0.0.0 | active | 散落文件治理工作流（金融级+盆景式）：双维度分类→状态机判断→索引登记→三态决策→认知闭环5步流程。Invoke when 处理散落文件、隐藏目录排查、标号目录根层文件清理、或需统一文档管理时。 |
| dream-scattered-file-cleanup | 0.0.0 | active | 散落文件治理工作流（金融级+盆景式）：双维度分类→状态机判断→索引登记→三态决策→认知闭环5步流程。Invoke when 处理散落文件、隐藏目录排查、标号目录根层文件清理、或需统一文档管理时。 |
| dream-science-orchestrator | 1.0.0 | shadow | 科研引擎统一入口。根据任务类型路由到具体科研 SKILL，复用 dream-research-workflow 的 5 维交叉验证和 hermes 反思，输出可执行开发任务打通调研→开发衔接。触发词：科研编排、研究引擎、调研开发、科研任务 |
| dream-science-orchestrator | 1.0.0 | shadow | 科研引擎统一入口。根据任务类型路由到具体科研 SKILL，复用 dream-research-workflow 的 5 维交叉验证和 hermes 反思，输出可执行开发任务打通调研→开发衔接。触发词：科研编排、研究引擎、调研开发、科研任务 |
| dream-science-orchestrator | 1.0.0 | shadow | 科研引擎统一入口。根据任务类型路由到具体科研 SKILL，复用 dream-research-workflow 的 5 维交叉验证和 hermes 反思，输出可执行开发任务打通调研→开发衔接。触发词：科研编排、研究引擎、调研开发、科研任务 |
| dream-science-orchestrator | 1.0.0 | shadow | 科研引擎统一入口。根据任务类型路由到具体科研 SKILL，复用 dream-research-workflow 的 5 维交叉验证和 hermes 反思，输出可执行开发任务打通调研→开发衔接。触发词：科研编排、研究引擎、调研开发、科研任务 |
| dream-self-iteration-workflow | 0.0.0 | active | Orchestrates L4 self-iteration: hermes reflection (trace analysis → skill-creator) + param optimization (Bayesian + walk-forward) + case ingest gate (4-dim value assessment) + doc sync (checksum → dream-doc-sync). Invoke for L4 self-iteration, hermes auto-reflection, parameter auto-optimization, case library ingest, or document auto-sync. |
| dream-self-iteration-workflow | 0.0.0 | active | Orchestrates L4 self-iteration: hermes reflection (trace analysis → skill-creator) + param optimization (Bayesian + walk-forward) + case ingest gate (4-dim value assessment) + doc sync (checksum → dream-doc-sync). Invoke for L4 self-iteration, hermes auto-reflection, parameter auto-optimization, case library ingest, or document auto-sync. |
| dream-skill-index-governance | 1.0.0 | active | Meta-SKILL: governs SKILL index/version/dependency/lifecycle/conflict/drift. Invoke for SKILL registry build, lifecycle transition, conflict detection, or drift monitoring. |
| dream-skill-index-governance | 1.0.0 | active | Meta-SKILL: governs SKILL index/version/dependency/lifecycle/conflict/drift. Invoke for SKILL registry build, lifecycle transition, conflict detection, or drift monitoring. |
| dream-subagent-tdd-workflow | 1.0.0 | active | Orchestrates DSH subagent TDD: RED test (ModuleNotFoundError) → GREEN impl (subagent_types.py shared contract) → IPC handler registration → cognitive closure. Invoke for subagent dev, macro/flow/onchain/valuation/risk/portfolio agent. |
| dream-subagent-tdd-workflow | 1.0.0 | active | Orchestrates DSH subagent TDD: RED test (ModuleNotFoundError) → GREEN impl (subagent_types.py shared contract) → IPC handler registration → cognitive closure. Invoke for subagent dev, macro/flow/onchain/valuation/risk/portfolio agent. |
| dream-tdd-dev-workflow | 1.0.0 | active | Orchestrates TDD cycle: need analysis → RED (failing test) → GREEN (minimal impl) → REFACTOR → hermes reflection. Invoke for TDD dev, red-green-refactor. |
| dream-tdd-dev-workflow | 1.0.0 | active | Orchestrates TDD cycle: need analysis → RED (failing test) → GREEN (minimal impl) → REFACTOR → hermes reflection. Invoke for TDD dev, red-green-refactor. |
| dreambuddy-os | 1.1.0 | active | Dreambuddy V2 AI 驱动操作系统 — 系统级 SKILL 内核

定位： Dreambuddy OS 的核心调度层，通过调用已有 SKILL 和 API 实现完整协作，
本身是纯编排层，不重复建设任何能力。

核心能力：
1. 意图识别 — 零 Token 本地计算，6 种意图类型
2. 架构规划（SACG 四层）— 基于 A1 Feed + 知识库 + 记忆构建蓝图/执行图/时间线/图存储
3. 节点注册表 NodeRegistry — 35个模块配置 + 11个本地实现
4. 统一节点执行器 UnifiedNodeExecutor — 整合注册表+适配器+重试+降级
5. 动态执行 — 三大思维链主链 + 节点动态组合 + 反思决策
6. 错误码体系 — 6大类错误码，标准化错误处理
7. 压力测试框架 — 6种压测场景，性能验证
8. 自我进化 — A7/A8 实践论 + gap_score 路由 + 做梦部
9. D-Z-E 开发链 — 自进化引擎驱动，向外学习创建新能力
10. 预算管理 — Token 三档 + 仓位风控 + 成本核算

验证实验： Agent B（系统架构验证组）通过执行本 SKILL 来验证整个系统设计的可行性。

调用原则：
- 调用的不重复建设
- 能力清单在总架构中已存在
- 架构检查模块可定期验证执行效果
 |
| dreambuddy-os | 1.1.0 | active | Dreambuddy V2 AI 驱动操作系统 — 系统级 SKILL 内核

定位： Dreambuddy OS 的核心调度层，通过调用已有 SKILL 和 API 实现完整协作，
本身是纯编排层，不重复建设任何能力。

核心能力：
1. 意图识别 — 零 Token 本地计算，6 种意图类型
2. 架构规划（SACG 四层）— 基于 A1 Feed + 知识库 + 记忆构建蓝图/执行图/时间线/图存储
3. 节点注册表 NodeRegistry — 35个模块配置 + 11个本地实现
4. 统一节点执行器 UnifiedNodeExecutor — 整合注册表+适配器+重试+降级
5. 动态执行 — 三大思维链主链 + 节点动态组合 + 反思决策
6. 错误码体系 — 6大类错误码，标准化错误处理
7. 压力测试框架 — 6种压测场景，性能验证
8. 自我进化 — A7/A8 实践论 + gap_score 路由 + 做梦部
9. D-Z-E 开发链 — 自进化引擎驱动，向外学习创建新能力
10. 预算管理 — Token 三档 + 仓位风控 + 成本核算

验证实验： Agent B（系统架构验证组）通过执行本 SKILL 来验证整个系统设计的可行性。

调用原则：
- 调用的不重复建设
- 能力清单在总架构中已存在
- 架构检查模块可定期验证执行效果
 |
| dual-agent-conflict-gate | 1.0 | active | 双代理协作冲突前置门禁。每次 agent 开始任务前调用，读取 git status / 分支状态，检查文件边界、共享文件占用、契约冻结级别与并行条件，输出 SAFE / WARNING / BLOCK + reason_codes。触发词：冲突检查、协作门禁、任务前检查、conflict gate、开始任务 |
| evolution-system-sync | 0.0.0 | active | Dream-Agent 协作网络 / DZE 开发链定时同步与审计（3-EVOLUTION 进化系统）。触发词：Dream-Agent 每小时同步、DZE 每日审计、dream-agent-bridge、dze-bridge、账本、区块高度、DREAM 奖励、Validator 队列、进化系统状态、DreamAgent-Sync-Hourly、DZEChain-Audit-Daily。 |
| intelligence-radar | 0.0.0 | active | Use when monitoring market intelligence, detecting signal regime shifts across the three-screen MA system, or tiering response triggers (P0/P1, Level 1-3) across the trading decision chain |
| master-seminar | 1.0.0 | active | 🎓 大师研讨SKILL - 让已蒸馏的交易大师基于A系列报告分阵营辩论
核心职能: 大师分阵营辩论 / 挑刺 / 追问 / 进化
触发词: 大师研讨、召唤大师辩论、让大师讨论、大师评议
差异化: 基于每日A系资料训练，驱动大师动态进化
 |
| master-seminar | 1.0.0 | active | 🎓 大师研讨SKILL - 让已蒸馏的交易大师基于A系列报告分阵营辩论
核心职能: 大师分阵营辩论 / 挑刺 / 追问 / 进化
触发词: 大师研讨、召唤大师辩论、让大师讨论、大师评议
差异化: 基于每日A系资料训练，驱动大师动态进化
 |
| system-maintenance | 1.0.0 | active | 🔧 系统维护 SKILL - 基于架构文档的系统健康检查与修复

核心能力：
1. 架构健康检查：对照架构文档检查各模块实现状态
2. 问题追踪：识别实现与规划的偏差
3. 维护报告：生成定期维护报告
4. 修复流程：按架构规划执行修复或触发开发任务

触发词：
- 系统维护、架构检查、健康检查、周维护、月度维护
- 检查架构、查看进度、更新状态、架构同步
- 发现问题、修复计划、迭代规划
 |

## research

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| A8-theory-practice-verification | 1.6 (纯粹理性内部批评自循环) | active | 🔍 理论与实践结合验证SKILL - 纯粹的理性内部批评自循环。检查A0-A7的理论与实践结合情况，做到'知行合一'，通过自我批评敦促系统进化。触发词：A8、理论与实践结合、知行合一、自我批评、系统检验、批判性思维、辩证思维、系统进化、内部批评、自循环 |
| A8-theory-practice-verification | 1.6 (纯粹理性内部批评自循环) | active | 🔍 理论与实践结合验证SKILL - 纯粹的理性内部批评自循环。检查A0-A7的理论与实践结合情况，做到'知行合一'，通过自我批评敦促系统进化。触发词：A8、理论与实践结合、知行合一、自我批评、系统检验、批判性思维、辩证思维、系统进化、内部批评、自循环 |
| dream-bailian-integration | v1.0 | active | Dream-MultiSkill 百炼集成中心 - 统一管理百炼API调用、知识库构建、 工作流编排、Function Calling、产物传递(AAM)。触发词：百炼、知识库构建、 RAG配置、API调用、百炼工作流、模型蒸馏、Function Calling配置。
 |
| dream-bailian-integration | v1.0 | active | Dream-MultiSkill 百炼集成中心 - 统一管理百炼API调用、知识库构建、 工作流编排、Function Calling、产物传递(AAM)。触发词：百炼、知识库构建、 RAG配置、API调用、百炼工作流、模型蒸馏、Function Calling配置。
 |
| dream-constitution | 1.0.0 | active | Dream-MultiSkill 系统最高指导宪法 (唯物主义版)。所有决策必须调取此文件作为第一性原理依据。触发词：宪法、最高指导、第一性原理、唯物主义、决策前必须 |
| dream-contradiction-theory | 1.1.0 | active | ⚖️ A0 矛盾分析理论 — A1/A2/A3的统一矛盾操作系统
蒸馏毛泽东《矛盾论》+《孙子兵法》+克劳塞维茨《战争论》的核心方法论，
为A1(发现矛盾)、A2(抓住矛盾)、A3(利用矛盾)提供统一的矛盾分析框架。
禁止"信号不足=等待"，矛盾永远存在，关键是识别主要矛盾并利用它。
触发词：矛盾分析、主要矛盾、矛盾论、矛盾发现、矛盾利用、抓主要矛盾、矛盾转化
 |
| dream-contradiction-theory | 1.1.0 | active | ⚖️ A0 矛盾分析理论 — A1/A2/A3的统一矛盾操作系统
蒸馏毛泽东《矛盾论》+《孙子兵法》+克劳塞维茨《战争论》的核心方法论，
为A1(发现矛盾)、A2(抓住矛盾)、A3(利用矛盾)提供统一的矛盾分析框架。
禁止"信号不足=等待"，矛盾永远存在，关键是识别主要矛盾并利用它。
触发词：矛盾分析、主要矛盾、矛盾论、矛盾发现、矛盾利用、抓主要矛盾、矛盾转化
 |
| dream-first-principles | 2.6.1 | active | 🧠 第一性原理分析 — 战略制定的哲学根基
基于"市场总是沿着阻力最小方向运行"和"趋势具有延续性"两大原理，
深度分析当前市场状态，推演阻力来源与趋势动力。
触发词：第一性原理、阻力最小、趋势分析、动力分析、市场本质、分析完成请顾问评审、宏观资产、黄金、原油、铜
 |
| dream-first-principles | 2.6.1 | active | 🧠 第一性原理分析 — 战略制定的哲学根基
基于"市场总是沿着阻力最小方向运行"和"趋势具有延续性"两大原理，
深度分析当前市场状态，推演阻力来源与趋势动力。
触发词：第一性原理、阻力最小、趋势分析、动力分析、市场本质、分析完成请顾问评审、宏观资产、黄金、原油、铜
 |
| dream-knowledge | 1.0.0 | active | 📚 知识库SKILL - 核心交易策略和工具的动态知识库

核心能力：
1. 知识沉淀：联网搜索/实践复盘 → 评分 → 入库
2. 知识检索：按评分排序，高评分优先
3. 知识进化：实践反馈驱动评分调整
4. 定期维护：72h自动评估和清理

触发词：
- 知识沉淀、知识入库、新策略入库
- 知识检索、查找策略、找工具
- 知识进化、评分更新、策略复盘
- 知识库维护、知识评估
 |
| dream-knowledge | 1.0.0 | active | 📚 知识库SKILL - 核心交易策略和工具的动态知识库

核心能力：
1. 知识沉淀：联网搜索/实践复盘 → 评分 → 入库
2. 知识检索：按评分排序，高评分优先
3. 知识进化：实践反馈驱动评分调整
4. 定期维护：72h自动评估和清理

触发词：
- 知识沉淀、知识入库、新策略入库
- 知识检索、查找策略、找工具
- 知识进化、评分更新、策略复盘
- 知识库维护、知识评估
 |
| dream-knowledge | 1.0.0 | active | 📚 知识库SKILL - 核心交易策略和工具的动态知识库

核心能力：
1. 知识沉淀：联网搜索/实践复盘 → 评分 → 入库
2. 知识检索：按评分排序，高评分优先
3. 知识进化：实践反馈驱动评分调整
4. 定期维护：72h自动评估和清理

触发词：
- 知识沉淀、知识入库、新策略入库
- 知识检索、查找策略、找工具
- 知识进化、评分更新、策略复盘
- 知识库维护、知识评估
 |
| dream-oneirology | 2.0.0 | active | 🌙 做梦部 — 基于弗洛伊德《梦的解析》的潜意识分析部门。
每日17:00运行，分析交易系统的"梦境"——被压制的判断、强迫性重复、矛盾图谱、反事实推演。
输出大胆观点，不受门禁约束，提供"第三只眼"视角。

触发词：做梦、梦境、潜意识、反直觉、大胆观点、被压制的判断、噩梦、反事实、梦的解析、
做梦部、弗洛伊德、凝缩、移置、象征、强迫性重复、创伤、矛盾图谱、
夜间分析、反顾问、魔鬼代言人、被压制的维度
 |
| dream-oneirology | 2.0.0 | active | 🌙 做梦部 — 基于弗洛伊德《梦的解析》的潜意识分析部门。
每日17:00运行，分析交易系统的"梦境"——被压制的判断、强迫性重复、矛盾图谱、反事实推演。
输出大胆观点，不受门禁约束，提供"第三只眼"视角。

触发词：做梦、梦境、潜意识、反直觉、大胆观点、被压制的判断、噩梦、反事实、梦的解析、
做梦部、弗洛伊德、凝缩、移置、象征、强迫性重复、创伤、矛盾图谱、
夜间分析、反顾问、魔鬼代言人、被压制的维度
 |
| dream-science-cross-disciplinary | 1.0.0 | proposed | 跨学科调研SKILL，建立金融交易与复杂系统/统计物理/信息论/博弈论/网络科学的映射关系 |
| dream-science-cross-disciplinary | 1.0.0 | proposed | 跨学科调研SKILL，建立金融交易与复杂系统/统计物理/信息论/博弈论/网络科学的映射关系 |
| dream-science-cross-disciplinary | 1.0.0 | proposed | 跨学科调研SKILL，建立金融交易与复杂系统/统计物理/信息论/博弈论/网络科学的映射关系 |
| dream-science-cross-disciplinary | 1.0.0 | proposed | 跨学科调研SKILL，建立金融交易与复杂系统/统计物理/信息论/博弈论/网络科学的映射关系 |
| dream-science-experiment-design | 1.0.0 | proposed | 科研实验设计。设计回测/对照实验的具体方案，确保实验可复现、可验证。触发词：实验设计、回测设计、对照实验、experiment design |
| dream-science-experiment-design | 1.0.0 | proposed | 科研实验设计。设计回测/对照实验的具体方案，确保实验可复现、可验证。触发词：实验设计、回测设计、对照实验、experiment design |
| dream-science-experiment-design | 1.0.0 | proposed | 科研实验设计。设计回测/对照实验的具体方案，确保实验可复现、可验证。触发词：实验设计、回测设计、对照实验、experiment design |
| dream-science-experiment-design | 1.0.0 | proposed | 科研实验设计。设计回测/对照实验的具体方案，确保实验可复现、可验证。触发词：实验设计、回测设计、对照实验、experiment design |
| dream-science-framework-research | 1.0.0 | proposed | 整体框架研究SKILL，多Agent辩论模式研究交易系统顶层架构 |
| dream-science-framework-research | 1.0.0 | proposed | 整体框架研究SKILL，多Agent辩论模式研究交易系统顶层架构 |
| dream-science-framework-research | 1.0.0 | proposed | 整体框架研究SKILL，多Agent辩论模式研究交易系统顶层架构 |
| dream-science-framework-research | 1.0.0 | proposed | 整体框架研究SKILL，多Agent辩论模式研究交易系统顶层架构 |
| dream-science-hypothesis-verification | 1.0.0 | shadow | 交易假设科研级验证SKILL，含可证伪性检验、对照实验、统计显著性、消融实验 |
| dream-science-hypothesis-verification | 1.0.0 | shadow | 交易假设科研级验证SKILL，含可证伪性检验、对照实验、统计显著性、消融实验 |
| dream-science-hypothesis-verification | 1.0.0 | shadow | 交易假设科研级验证SKILL，含可证伪性检验、对照实验、统计显著性、消融实验 |
| dream-science-hypothesis-verification | 1.0.0 | shadow | 交易假设科研级验证SKILL，含可证伪性检验、对照实验、统计显著性、消融实验 |
| dream-science-literature-review | 1.0.0 | shadow | 专业领域文献综述SKILL，PRISMA系统综述+Socratic引导，聚焦金融/量化/交易文献 |
| dream-science-literature-review | 1.0.0 | shadow | 专业领域文献综述SKILL，PRISMA系统综述+Socratic引导，聚焦金融/量化/交易文献 |
| dream-science-literature-review | 1.0.0 | shadow | 专业领域文献综述SKILL，PRISMA系统综述+Socratic引导，聚焦金融/量化/交易文献 |
| dream-science-literature-review | 1.0.0 | shadow | 专业领域文献综述SKILL，PRISMA系统综述+Socratic引导，聚焦金融/量化/交易文献 |
| dream-science-paper-writing | 1.0.0 | proposed | 科研论文写作。将策略研究成果撰写为结构化研究报告，借鉴 Style Calibration 方法平衡学术严谨性与工程可落地性。触发词：论文写作、研究报告、科研写作、paper writing |
| dream-science-paper-writing | 1.0.0 | proposed | 科研论文写作。将策略研究成果撰写为结构化研究报告，借鉴 Style Calibration 方法平衡学术严谨性与工程可落地性。触发词：论文写作、研究报告、科研写作、paper writing |
| dream-science-paper-writing | 1.0.0 | proposed | 科研论文写作。将策略研究成果撰写为结构化研究报告，借鉴 Style Calibration 方法平衡学术严谨性与工程可落地性。触发词：论文写作、研究报告、科研写作、paper writing |
| dream-science-paper-writing | 1.0.0 | proposed | 科研论文写作。将策略研究成果撰写为结构化研究报告，借鉴 Style Calibration 方法平衡学术严谨性与工程可落地性。触发词：论文写作、研究报告、科研写作、paper writing |
| dream-science-peer-review | 1.0.0 | proposed | 同行评审SKILL，Devil's Advocate让步阈值协议+7模式阻断清单，多视角评审策略逻辑 |
| dream-science-peer-review | 1.0.0 | proposed | 同行评审SKILL，Devil's Advocate让步阈值协议+7模式阻断清单，多视角评审策略逻辑 |
| dream-science-peer-review | 1.0.0 | proposed | 同行评审SKILL，Devil's Advocate让步阈值协议+7模式阻断清单，多视角评审策略逻辑 |
| dream-science-peer-review | 1.0.0 | proposed | 同行评审SKILL，Devil's Advocate让步阈值协议+7模式阻断清单，多视角评审策略逻辑 |
| dream-science-statistics-check | 1.0.0 | proposed | 回测统计审查SKILL，检查p值/效应量/置信区间/多重比较/数值一致性 |
| dream-science-statistics-check | 1.0.0 | proposed | 回测统计审查SKILL，检查p值/效应量/置信区间/多重比较/数值一致性 |
| dream-science-statistics-check | 1.0.0 | proposed | 回测统计审查SKILL，检查p值/效应量/置信区间/多重比较/数值一致性 |
| dream-science-statistics-check | 1.0.0 | proposed | 回测统计审查SKILL，检查p值/效应量/置信区间/多重比较/数值一致性 |
| dream-science-uncertainty-reasoning | 1.0.0 | proposed | 不确定性推理SKILL，量化策略不确定性：市场状态/参数敏感性/过拟合风险 |
| dream-science-uncertainty-reasoning | 1.0.0 | proposed | 不确定性推理SKILL，量化策略不确定性：市场状态/参数敏感性/过拟合风险 |
| dream-science-uncertainty-reasoning | 1.0.0 | proposed | 不确定性推理SKILL，量化策略不确定性：市场状态/参数敏感性/过拟合风险 |
| dream-science-uncertainty-reasoning | 1.0.0 | proposed | 不确定性推理SKILL，量化策略不确定性：市场状态/参数敏感性/过拟合风险 |
| ontology | 0.0.0 | active | Typed knowledge graph for structured agent memory and composable skills. Use when creating/querying entities (Person, Project, Task, Event, Document), linking related objects, enforcing constraints, planning multi-step actions as graph transformations, or when skills need to share state. Trigger on "remember", "what do I know about", "link X to Y", "show dependencies", entity CRUD, or cross-skill data access. |

## support

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| resource-efficiency-analyst | 1.0.0 | active | 资源效率分析师 (resource-efficiency-analyst) |

## tooling

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| auto-repair | 2.1.0 | active | Dream-MultiSkill 系统健康自动修复与提案落地工具 v2.1。

**核心功能**：
- 账户隔离监控：确保系统不混淆实盘和模拟盘
- 三邮箱状态检查：秘书/调研部/待修复邮箱（顾问已内嵌SKILL，物理邮箱已废弃）
- ⭐ 提案落地执行：检查完邮箱后负责落地提案
- 72小时定时健康检查：自动检测并修复系统问题
- ⭐ 合规检查：检测各SKILL合规性，违规记录与处罚

**触发词**：
- "auto-repair"、"系统健康"、"健康检查"、"自动修复"
- "账户隔离"、"账户监控"、"检查实盘"、"检查模拟盘"
- "邮箱检查"、"三邮箱"、"秘书邮箱"
- "提案归档"、"提案落地"、"提案执行"、"待处理提案"
- "72小时"、"定时检查"、"健康报告"
- "落地提案"、"执行提案"、"处理全部提案"
- "运营健康检查"、"治理检查"、"合规检查"、"检测违规" |
| branch-lifecycle-automation | 0.0.0 | active | 分支与 PR 生命周期自动治理技能。用于“清理分支堆积”“自动标记状态”“定时收敛 PR/分支”场景；默认低风险自动处置，高风险升级人工处理。 |
| code-review-merge-assistant | 0.0.0 | active | 本地一键代码审核与合并助手。用于“代码审核合并”“一键合并到main”“检查通过后自动合并”等场景，自动执行分支检查、PR检查等待、门禁通过后 squash 合并与主干同步。 |
| data-troubleshoot | 0.0.0 | active | 排查基本面数据链路问题：前端显示异常值（0.000、错误标签、量级不对、字段缺失）时，系统化追踪 18-DB→backfill→19-DAL→快照→API→前端 全链路，含字段契约验证、数据质量检查、云端一致性核对。Invoke when frontend shows suspicious values (0.000, wrong labels, missing fields, magnitude errors) or user reports incorrect fundamental data. |
| data-troubleshoot | 0.0.0 | active | 排查基本面数据链路问题：前端显示异常值（0.000、错误标签、量级不对、字段缺失）时，系统化追踪 18-DB→backfill→19-DAL→快照→API→前端 全链路，含字段契约验证、数据质量检查、云端一致性核对。Invoke when frontend shows suspicious values (0.000, wrong labels, missing fields, magnitude errors) or user reports incorrect fundamental data. |
| drawio | 1.0.0 | active | Generate draw.io diagrams (architecture, flow, data flow) as editable .drawio files with optional PNG/SVG/PDF export |
| drawio | 1.0.0 | active | Generate draw.io diagrams (architecture, flow, data flow) as editable .drawio files with optional PNG/SVG/PDF export |
| drawio | 1.0.0 | active | Generate draw.io diagrams (architecture, flow, data flow) as editable .drawio files with optional PNG/SVG/PDF export |
| drawio | 1.0.0 | active | Generate draw.io diagrams (architecture, flow, data flow) as editable .drawio files with optional PNG/SVG/PDF export |
| find-skills | 0.0.0 | active | Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for X", "is there a skill that can...", or express interest in extending capabilities. This skill should be used when the user is looking for functionality that might exist as an installable skill. |
| finishing-a-development-branch | 0.0.0 | active | Use when implementation is complete, all tests pass, and you need to decide how to integrate the work |
| github | 0.0.0 | active | Interact with GitHub using the `gh` CLI. Use `gh issue`, `gh pr`, `gh run`, and `gh api` for issues, PRs, CI runs, and advanced queries. |
| graph-context-compressor | 1.0.0 | active | 🗜️ 图结构上下文压缩 SKILL - 对话过程中自动构建三层图（B 层蓝图 / A 层架构 / C 层执行），
自动评估节点价值，压缩低价值节点，生成可可视化的压缩摘要。

核心能力：
1. 上下文图谱构建：对话消息 → B/A/C 三层图结构
2. 语义感知压缩：Token/耗时/关键词多维度评分，自动保留高价值节点
3. 意图路由：根据对话主题自动匹配对应 Blueprint 模板
4. 可视化输出：生成前后对比数据，可直接用于前端组件渲染

触发场景：
- 用户请求压缩上下文、总结对话
- 对话超过 10 条消息，需要保留关键信息
- 对话包含明确的执行步骤/决策过程（如策略研究、交易执行链）
- 需要展示决策路径时
- 对话转向新主题前，需要总结旧主题

输入格式：
- 对话消息列表（role + content + timestamp）
- 可选：已知的架构步骤、关键决策点
- 可选：目标压缩率（默认 0.5）

输出格式：
- 压缩结果摘要（压缩率、保留节点数）
- 保留节点列表（高价值内容）
- 压缩节点列表（摘要引用）
- 前端可用的可视化数据（VisualizationData）
 |
| hermes-feishu-bot-debug | 0.0.0 | active | 诊断和修复 Hermes Bot 飞书双向通信问题。涵盖 Gateway 配置、WebSocket 事件订阅、Channel Directory 管理、App 发布流程。 |
| markdown-new | 0.0.0 | active | Convert public web pages into clean Markdown with markdown.new for AI workflows. Use when tasks require URL-to-Markdown conversion for summarization, RAG ingestion, extraction, archiving, or token reduction, including selecting conversion method (auto/ai/browser), enabling image retention, and handling rate limits or conversion failures. |
| nature-figure | 1.0.0 | active | Nature/高影响力期刊投稿级科研图工作流，含多面板证据架构、子图对齐门、PDF碰撞审计 |
| nature-figure | 1.0.0 | active | Nature/高影响力期刊投稿级科研图工作流，含多面板证据架构、子图对齐门、PDF碰撞审计 |
| nature-figure | 1.0.0 | active | Nature/高影响力期刊投稿级科研图工作流，含多面板证据架构、子图对齐门、PDF碰撞审计 |
| nature-figure | 1.0.0 | active | Nature/高影响力期刊投稿级科研图工作流，含多面板证据架构、子图对齐门、PDF碰撞审计 |
| nature-shared | 1.0.0 | active | nature-skills 共享内容目录，提供通用样式模板和工具函数 |
| nature-shared | 1.0.0 | active | nature-skills 共享内容目录，提供通用样式模板和工具函数 |
| polling-trader-reload | 0.0.0 | active | Reload polling_trader after code changes: kill old → wait flock release → start new with same config → verify pidfile + main loop. Invoke when polling_trader.py modified or user says '重启/reload polling_trader'. |
| polling-trader-reload | 0.0.0 | active | Reload polling_trader after code changes: kill old → wait flock release → start new with same config → verify pidfile + main loop. Invoke when polling_trader.py modified or user says '重启/reload polling_trader'. |
| receiving-code-review | 0.0.0 | active | Use when receiving code review feedback, before implementing suggestions, especially if feedback seems unclear or technically questionable - requires technical rigor and verification, not performative agreement or blind implementation |
| requesting-code-review | 0.0.0 | active | Use when completing tasks, implementing major features, or before merging to verify work meets requirements |
| safe-main-merge | 0.0.0 | active | 面向新手和团队成员的主干安全合并标准流程。用于“准备合并到main/主干”“发布前检查”“PR合并与回滚”场景，执行稳定的分支、校验、合并、验证、回滚步骤，避免直接推main导致风险。 |
| safe-service-restart | 0.0.0 | active | 服务重启硬门禁流程：commit → 验证工作区干净 → 重启 → 验证前后代码一致。Invoke whenever a backend/frontend service needs to be restarted after code changes, to prevent regression from uncommitted changes. |
| safe-service-restart | 0.0.0 | active | 服务重启硬门禁流程：commit → 验证工作区干净 → 重启 → 验证前后代码一致。Invoke whenever a backend/frontend service needs to be restarted after code changes, to prevent regression from uncommitted changes. |
| skill-creator | 2.0.0 | active | Guide for creating effective skills with mandatory multi-domain research. Use when users want to create a new skill or update an existing skill that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations. Enforces 5-domain research (AI/finance/product/engineering/GitHub) before skill formation per project hard constraint VM-1790765308904. |
| skill-creator | 2.0.0 | active | Guide for creating effective skills with mandatory multi-domain research. Use when users want to create a new skill or update an existing skill that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations. Enforces 5-domain research (AI/finance/product/engineering/GitHub) before skill formation per project hard constraint VM-1790765308904. |
| skill-creator | 0.0.0 | active | Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations. |
| skill-creator | 0.0.0 | active | Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends agent capabilities with specialized knowledge, workflows, or tool integrations. |
| subagent-driven-development | 0.0.0 | active | Use when executing implementation plans with independent tasks in the current session |
| systematic-debugging | 0.0.0 | active | Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes |
| tavily | 0.0.0 | active | AI-optimized web search using Tavily Search API. Use when you need comprehensive web research, current events lookup, domain-specific search, or AI-generated answer summaries. Tavily is optimized for LLM consumption with clean structured results, answer generation, and raw content extraction. Best for research tasks, news queries, fact-checking, and gathering authoritative sources. |
| tee-red-green-progress | 1.0.0 | active | Standard TDD workflow for TEE Tasks N→N+1 in dreambuddy-v2: (1) recall before any coding (hard constraint), (2) write RED spec tests asserting ModuleNotFoundError for new module, (3) run to confirm red count, (4) implement production code to reach GREEN, (5) run full TEE suite (22-执行引擎中心/tests/) to validate 0 regression, (6) append TR evidence blocks to tasks.md. Invoke on every new TEE task (Task 1–N) or when the user asks to continue the next TEE stage. |
| tee-red-green-progress | 1.0.0 | active | Standard TDD workflow for TEE Tasks N→N+1 in dreambuddy-v2: (1) recall before any coding (hard constraint), (2) write RED spec tests asserting ModuleNotFoundError for new module, (3) run to confirm red count, (4) implement production code to reach GREEN, (5) run full TEE suite (22-执行引擎中心/tests/) to validate 0 regression, (6) append TR evidence blocks to tasks.md. Invoke on every new TEE task (Task 1–N) or when the user asks to continue the next TEE stage. |
| test-driven-development | 0.0.0 | active | Use when implementing any feature or bugfix, before writing implementation code |
| using-git-worktrees | 0.0.0 | active | Use when starting feature work that needs isolation from current workspace or before executing implementation plans - ensures an isolated workspace exists via native tools or git worktree fallback |
| using-superpowers | 0.0.0 | active | Use when starting any conversation - establishes how to find and use skills, requiring skill invocation before ANY response including clarifying questions |
| verification-before-completion | 0.0.0 | active | Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always |
| writing-plans | 0.0.0 | active | Use when you have a spec or requirements for a multi-step task, before touching code |
| writing-skills | 0.0.0 | active | Use when creating new skills, editing existing skills, or verifying skills work before deployment |

## trading

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| 6-trading-screen1-framework | 0.0.0 | active | Screen1 七维牛熊检测框架。以 MA200 三日确认为方向锚，七维度加权评分（技术指标检测器 40分 + 减半周期/矿工经济/链上估值/宏观金融/跨市场），输出 BULL/BEAR/NEUTRAL。 |
| A7-practice-theory | 1.0.0 | active | 📘 A7 实践论SKILL v2.1 - 交易实践指导框架 (正式上线版) |
| A7-practice-theory | 1.0.0 | active | 📘 A7 实践论SKILL v2.1 - 交易实践指导框架 (正式上线版) |
| a6-monitor-trigger | 1.0.0 | active | SKILL: a6-monitor-trigger |
| agent-a-trading | 0.0.0 | active |  |
| agent-collab-gatec | 1.0.0 | active | SKILL: agent-collab-gatec |
| agent-collab-screen1 | 1.0.0 | active | SKILL: agent-collab-screen1 |
| ai-trading-compliance | 2.0.0 | active | AI 驱动的交易创新合规与治理门禁审查 v2.0 - 可执行版本。对 AI 建议/自动化/策略创新做合规审查并输出 pass/warn/fail。涉及变更包、门禁、灰度发布、回滚、审计时调用。 |
| approval-timeout-check | 0.0.0 | active | 审批超时守卫 — 检查 PENDING 审批单，超时后触发 AI 兜底决策。每 10 分钟 cron 触发。 |
| asset-research | 1.0.0 | active | Skill: 资产标的调研 |
| dream-backtest | 0.0.0 | active |  |
| dream-exit-skill-v2 | v2.2 | active | A9 离场决策 v2.2 - 四层离场决策链 + 风险库(21事件) + A6联动 + OKX TP/SL联动 + MEMORY日志 + 自动推送 + 参数优化。 触发词：离场决策、A9、风险检查、强制离场、参数优化、停止损失、 移动止损、分批离场、风险事件、A6联动、MEMORY日志
 |
| dream-exit-skill-v2 | v2.2 | active | A9 离场决策 v2.2 - 四层离场决策链 + 风险库(21事件) + A6联动 + OKX TP/SL联动 + MEMORY日志 + 自动推送 + 参数优化。 触发词：离场决策、A9、风险检查、强制离场、参数优化、停止损失、 移动止损、分批离场、风险事件、A6联动、MEMORY日志
 |
| dream-pretrade-gatekeeper | 0.0.0 | active | 统一执行"交易前门禁"：数据完整性、评分冲突、账户回撤熔断、执行成本/滑点阈值、事件风险与 Dream Mode 降级，输出 PASS/SKIP 与理由码。 |
| dream-pretrade-gatekeeper | 0.0.0 | active | 统一执行"交易前门禁"：数据完整性、评分冲突、账户回撤熔断、执行成本/滑点阈值、事件风险与 Dream Mode 降级，输出 PASS/SKIP 与理由码。 |
| dream-regime-detector | 1.0.0 | active | Dream-Regime-Detector |
| dream-regime-detector | 1.0.0 | active | Dream-Regime-Detector |
| dream-risk-position-sizing | 0.0.0 | active | 基于风险预算与波动率缩放，将评分结果映射为仓位名义、杠杆、止损金额与账户级风险占用，并输出可审计的仓位建议。 |
| dream-risk-position-sizing | 0.0.0 | active | 基于风险预算与波动率缩放，将评分结果映射为仓位名义、杠杆、止损金额与账户级风险占用，并输出可审计的仓位建议。 |
| dream-screen1-first | 0.0.0 | active |  |
| dream-screen2-second | 0.0.0 | active |  |
| dream-screen3-third | 1.0 | active |  |
| dream-signal-scoring-spec | 0.0.0 | active | 将多源输入（技术/宏观/记忆/团队评审）标准化为可复现的三维评分与冲突判定，输出结构化评分与理由码，供 dream-multiSkill 调度。 |
| dream-signal-scoring-spec | 0.0.0 | active | 将多源输入（技术/宏观/记忆/团队评审）标准化为可复现的三维评分与冲突判定，输出结构化评分与理由码，供 dream-multiSkill 调度。 |
| dream-strategy-designer | 1.0.0 | active | 🎯 Dream-Strategy-Designer: 战略制定部 (v2.6) |
| dream-strategy-designer | 1.0.0 | active | 🎯 Dream-Strategy-Designer: 战略制定部 (v2.6) |
| dream-strategy-parser | 2.0.0 | active | 战略解析器v2.0 - 读取strategy_library.yaml v3.0，按7种Regime匹配策略+工具组合，输出战略指令到评分系统。触发词：战略解析、strategy parse、战略匹配、战略指令、strategy directive、Step0路由、Regime匹配、策略选择。 |
| dream-strategy-parser | 2.0.0 | active | 战略解析器v2.0 - 读取strategy_library.yaml v3.0，按7种Regime匹配策略+工具组合，输出战略指令到评分系统。触发词：战略解析、strategy parse、战略匹配、战略指令、strategy directive、Step0路由、Regime匹配、策略选择。 |
| dream-strategy-research | 1.7.0 | active | 🌐 深度调研 — 战略制定前的侦察兵
在制定战略前，系统性地收集市场情报、档案数据、链上信号、宏观环境、宏观资产背景。
触发词：深度调研、市场调研、情报收集、档案研究、宏观分析、链上数据、调研完成请顾问评审、宏观背景、宏观资产、黄金、原油、铜
 |
| dream-strategy-research | 1.7.0 | active | 🌐 深度调研 — 战略制定前的侦察兵
在制定战略前，系统性地收集市场情报、档案数据、链上信号、宏观环境、宏观资产背景。
触发词：深度调研、市场调研、情报收集、档案研究、宏观分析、链上数据、调研完成请顾问评审、宏观背景、宏观资产、黄金、原油、铜
 |
| dream-systematic-trading | 0.0.0 | active |  |
| dream-tactical-executor | 3.8.0 | active | ⚡ 战术执行 — **综合判断决策执行**

**【v3.5定位】**

A5 = 根据A4验证报告 + A6情报，综合判断并执行

**【v3.5核心链路】**

A4验证报告 → A6情报 → 综合判断 → 决策执行 → 仓位同步

**【自动化闭环】**

- A4确定性高 (SI≥±30+Edge同向≥20) → 内置A5自动执行
- A4确定性不高 → 等待A5综合判断（A4+A6）

**【约束条件】**

- 完整链路: A1→A2→A3→A4 必须就位
- A7实践论门禁检查
- RM顾问评审否决权

触发词：战术执行、生成信号、执行信号、入场点位、止损止盈、大仓入场、下单前检查、交易检查、执行前请顾问确认、A5自主执行、实践论、实践指导、真理标准、实践验证、A4联动、确定性联动、A4触发A5
 |
| dream-tactical-executor | 3.8.0 | active | ⚡ 战术执行 — **综合判断决策执行**

**【v3.5定位】**

A5 = 根据A4验证报告 + A6情报，综合判断并执行

**【v3.5核心链路】**

A4验证报告 → A6情报 → 综合判断 → 决策执行 → 仓位同步

**【自动化闭环】**

- A4确定性高 (SI≥±30+Edge同向≥20) → 内置A5自动执行
- A4确定性不高 → 等待A5综合判断（A4+A6）

**【约束条件】**

- 完整链路: A1→A2→A3→A4 必须就位
- A7实践论门禁检查
- RM顾问评审否决权

触发词：战术执行、生成信号、执行信号、入场点位、止损止盈、大仓入场、下单前检查、交易检查、执行前请顾问确认、A5自主执行、实践论、实践指导、真理标准、实践验证、A4联动、确定性联动、A4触发A5
 |
| dream-tactical-validator | 7.2.0 | active | 🔬 战术验证 — **A3推演验证方案设计师** + **矛盾论验证者**

**【v7.0核心定位】**

A4 = A3多情景验证方案设计 + **三层索引体系** + 高级委托落地 + 验证报告输出

**【v7.0核心升级】** ⭐NEW
1. **三层索引体系**: 策略索引(大师→联网→实践) → 工具索引 → 跨资产设计
2. **按序索引**: 大师策略(最高) → 联网搜索(次) → 实践经验(兜底)
3. **交易工具索引**: Regime→工具匹配矩阵
4. **跨资产设计**: 宏观资产池(XAUT/COIN/CL/XCU) + 币种相关性

**【v6.1核心改进】**
- 之前问题: A4直接认可A3结论，错了只知道A3不对，但不知道什么是对的
- 现在改进: A4为A3每个情景设计验证方案，通过知识库索引获得合适策略，落地验证
- 如果验证与A3有出入 → 补充验证（原文件不改，只增不减）

**多策略原则**: 基于A3推演的多情景，为每个情景匹配知识库策略

**矛盾论闭环**:
- A1: 调查发现矛盾
- A2: 第一性原理分析矛盾
- A3: 利用矛盾进行沙盘推演（输出情景A/B/C+概率）
- A4: 用实践进行场景验证（三层索引 → 高级委托落地）
- A5: 综合判断决策执行

**三层索引体系** (v7.0核心):
```
第一层: 策略索引(必须按序)
  ①大师策略(最高) → ②联网搜索(次) → ③实践经验(兜底)
第二层: 工具索引
  Regime→工具匹配 + OKX命令模板
第三层: 跨资产设计(可选)
  宏观资产池 + 币种相关性 + 组合方案
输出: 最佳策略方案 → 高级委托落地
```

**自动化闭环**:
- A4确定性高 → 内置A5自动执行
- A4确定性不高 → 等待A5综合判断

**强约束【v7.0必须遵守】**:
【V1】仅操作DEMO模拟盘账户，禁止操作实盘账户
【V2】必须接收A3推演结论，根据A3情景设计验证方案
【V3】每次执行必须为A3每个情景设计验证委托方案
【V4】通过高级委托(预挂单/OCO/移动止盈)落地验证
【V5】输出验证报告，包含：情景验证状态、市场反馈、置信度调整
【V6】A4验证结果传递给A5，A5根据验证结果选择方向执行
【V7】遇到任何bug/故障/报错 → 必须先查FAQ (宪法§11)
【V8】A4执行前必须通过A7实践论门禁检查
【V9】验证方案必须包含多维度(不同价格区间/不同触发条件)
【V10】如果验证与A3有出入 → 补充验证（原文件不改，只增不减）
【V11】三层索引必须按顺序执行，大师→联网→实践

触发词：验证方案、A3验证、情景验证、矛盾验证、验证报告、多情景验证、预挂单验证、委托验证方案、三层索引、策略索引、工具索引、跨资产设计
 |
| dream-tactical-validator | 7.2.0 | active | 🔬 战术验证 — **A3推演验证方案设计师** + **矛盾论验证者**

**【v7.0核心定位】**

A4 = A3多情景验证方案设计 + **三层索引体系** + 高级委托落地 + 验证报告输出

**【v7.0核心升级】** ⭐NEW
1. **三层索引体系**: 策略索引(大师→联网→实践) → 工具索引 → 跨资产设计
2. **按序索引**: 大师策略(最高) → 联网搜索(次) → 实践经验(兜底)
3. **交易工具索引**: Regime→工具匹配矩阵
4. **跨资产设计**: 宏观资产池(XAUT/COIN/CL/XCU) + 币种相关性

**【v6.1核心改进】**
- 之前问题: A4直接认可A3结论，错了只知道A3不对，但不知道什么是对的
- 现在改进: A4为A3每个情景设计验证方案，通过知识库索引获得合适策略，落地验证
- 如果验证与A3有出入 → 补充验证（原文件不改，只增不减）

**多策略原则**: 基于A3推演的多情景，为每个情景匹配知识库策略

**矛盾论闭环**:
- A1: 调查发现矛盾
- A2: 第一性原理分析矛盾
- A3: 利用矛盾进行沙盘推演（输出情景A/B/C+概率）
- A4: 用实践进行场景验证（三层索引 → 高级委托落地）
- A5: 综合判断决策执行

**三层索引体系** (v7.0核心):
```
第一层: 策略索引(必须按序)
  ①大师策略(最高) → ②联网搜索(次) → ③实践经验(兜底)
第二层: 工具索引
  Regime→工具匹配 + OKX命令模板
第三层: 跨资产设计(可选)
  宏观资产池 + 币种相关性 + 组合方案
输出: 最佳策略方案 → 高级委托落地
```

**自动化闭环**:
- A4确定性高 → 内置A5自动执行
- A4确定性不高 → 等待A5综合判断

**强约束【v7.0必须遵守】**:
【V1】仅操作DEMO模拟盘账户，禁止操作实盘账户
【V2】必须接收A3推演结论，根据A3情景设计验证方案
【V3】每次执行必须为A3每个情景设计验证委托方案
【V4】通过高级委托(预挂单/OCO/移动止盈)落地验证
【V5】输出验证报告，包含：情景验证状态、市场反馈、置信度调整
【V6】A4验证结果传递给A5，A5根据验证结果选择方向执行
【V7】遇到任何bug/故障/报错 → 必须先查FAQ (宪法§11)
【V8】A4执行前必须通过A7实践论门禁检查
【V9】验证方案必须包含多维度(不同价格区间/不同触发条件)
【V10】如果验证与A3有出入 → 补充验证（原文件不改，只增不减）
【V11】三层索引必须按顺序执行，大师→联网→实践

触发词：验证方案、A3验证、情景验证、矛盾验证、验证报告、多情景验证、预挂单验证、委托验证方案、三层索引、策略索引、工具索引、跨资产设计
 |
| evolution-case-ingest | 0.0.0 | active | 为自进化系统案例库（washout/washout_reversal/pump_dump_reversal）新增闭环训练案例。Invoke when 用户要求为自进化系统增加训练案例、入库市场行情样本、或补充 CBR/KNN 案例库。 |
| evolution-case-ingest | 0.0.0 | active | 为自进化系统案例库（washout/washout_reversal/pump_dump_reversal）新增闭环训练案例。Invoke when 用户要求为自进化系统增加训练案例、入库市场行情样本、或补充 CBR/KNN 案例库。 |
| feishu-gateway-setup | 0.0.0 | active | Feishu Bot 与 Hermes Gateway 的双向通信配置与排错。涵盖 App 创建、权限配置、事件订阅、发布流程、Gateway config.yaml、频道目录持久化、以及群聊/单聊消息收发调试。 |
| feishu-hermes-debug | 0.0.0 | active | Diagnose and fix Hermes Agent ↔ Feishu Bot communication issues. Covers WebSocket connectivity, send_message tool, channel directory, inbound message events, app publishing, scope management, and gateway restart procedures. |
| process-d-trigger | 1.0.0 | active | SKILL: process-d-trigger |
| screen-martin-trading | 0.0.0 | active |  |
| screen1-trigger | 1.0.0 | active | SKILL: screen1-trigger |
| screen2-trigger | 0.0.0 | active | 每日 Screen2 日线预设触发调度。优先委托 dream-screen2-second SKILL，缺失时降级到 web_search + 内联 A1/A2/A3 分析。 |
| screen3-trigger | 1.0.0 | active | SKILL: screen3-trigger |
| t0-market-cognition | 0.0.0 | active | Multi-dimensional market cognition: information collection, conflict analysis, path-of-least-resistance, regime classification, and direction determination. |
| t1-strategy-synthesis | 0.0.0 | active | Synthesize strategic directive, three-scenario Bayesian deduction, and contingency plan from T0 market cognition output. |
| t2-trade-execution | 0.0.0 | active | Tactical validation, position execution and four-layer exit decision flow for live trading. Merges A4 (tactical validation) + A5 (execution) + A9 (exit decision) into one three-stage skill: validate → execute → exit. |
| t3-risk-gatekeeper | 0.0.0 | active | Pre-trade gatekeeping, in-trade circuit breaker and post-trade attribution. The hard gate itself — all checks are non-negotiable constraints derived from A7 (practice gate) + A4 constraint system. |
| trading-strategy-optimization | 0.0.0 | active | End-to-end workflow for optimizing 6-TRADING backtest strategies. Covers code archaeology, root-cause diagnosis, proposal design within V9 constraints, implementation, and backtest execution. Used when user asks to improve strategy metrics (Sharpe, MaxDD, returns) for specific coins or market regimes. |

## trigger

| 名称 | 版本 | 状态 | 描述 |
|------|------|------|------|
| wiki-ingest-trigger | 1.0.0 | active | Cognitive event → Wiki ingest trigger. When cognitive record tags contain 'wiki-compile', TAG_HOOKS emits triggered_skills: [wiki-ingest-trigger]. Agent reads this signal and calls wiki_ingest(content, source) via DSH IPC or python-server directly. |
| wiki-ingest-trigger | 1.0.0 | active | Cognitive event → Wiki ingest trigger. When cognitive record tags contain 'wiki-compile', TAG_HOOKS emits triggered_skills: [wiki-ingest-trigger]. Agent reads this signal and calls wiki_ingest(content, source) via DSH IPC or python-server directly. |
