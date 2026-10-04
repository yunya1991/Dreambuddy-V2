# 工程索引 — 3-EVOLUTION 进化引擎

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 模块级工程索引（L4 自进化层），对齐 DOC_STANDARD §3.1 / §4

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 3 |
| 模块名称 | 3-EVOLUTION 进化引擎 |
| 模块层级 | **L4 自进化层**（实验状态，未集成到主线交易系统） |
| 核心职责 | 接收 10 类触发源，按 9 阶段流水线编排进化记录，协调 DZE 开发链 / Dream Agent 协作网络 / 审批门禁三桥接器，将进化产物落到 6 个更新层 |
| 主入口 | `EvolutionOrchestrator`（编排入口）/ `EvolutionEngine`（生命周期管理） |
| 依赖关系 | 上游：被监控子系统触发（execution_failure / low_confidence 等）；下游：DZE 链、Dream Agent 协作网络、飞书审批 |
| 外部依赖 | 无运行时外部依赖（纯 TypeScript 内存态实现） |
| 语言 | TypeScript |
| 运行状态 | 🧪 实验中（未集成主线） |
| 文档状态 | 📝 完整（README + ENGINEERING_INDEX + TECHNICAL_DESIGN + API_SPEC + CHANGELOG） |

**核心维度矩阵**：

| 维度 | 数量 | 取值 |
|------|------|------|
| 触发源 `EvolutionTriggerSource` | 10 | execution_failure / low_confidence / chain_disagreement / user_feedback / governance_alert / scheduled_audit / lesson_distilled / a8_reflection / dream_oneirology / orchestration_optimization |
| 进化阶段 `EvolutionPhase` | 9 | discovery → learning → deep_analysis → capability_update → code_development → collaboration → approval → deployment → completed |
| 进化状态 `EvolutionStatus` | 6 | pending / in_progress / blocked / completed / failed / skipped |
| 更新层 `UpdateLayer` | 6 | knowledge / memory / index / skill / code / architecture |

---

## 2. 目录地图

```
3-EVOLUTION/
├── docs/                             # 文档目录
│   ├── ENGINEERING_INDEX.md          # 本文件 — 工程索引
│   ├── TECHNICAL_DESIGN.md           # 技术设计
│   ├── API_SPEC.md                   # 接口规范
│   └── CHANGELOG.md                  # 变更记录
├── proposals/                        # 进化提案记录
│   ├── PROP-20260809-BATCH1-架构治理cron.md
│   ├── PROP-20260814-DREAMOS-四层闭环诊断与完善优化.md
│   ├── PROP-20260815-DREAMOS-四层闭环P1接线-认知反馈闭环补全.md
│   ├── PROP-20260816-DREAMOS-双腿对冲策略与币池动态排名.md
│   ├── PROP-20260816-DREAMOS-最小名义真单闭环冒烟测试-执行报告.md
│   ├── PROP-20260816-DREAMOS-闭环数据链路补全-B层指标注入与平仓对账.md
│   └── PROP-COG-20260810-NOISE-记忆库噪声治理与等级一致性.md
├── README.md                         # 用户文档
├── types.ts                          # 类型定义（触发源×阶段×状态×更新层）
├── evolution-engine.ts               # 进化引擎核心 — EvolutionRecord 生命周期
├── evolution-orchestrator.ts         # 进化编排器 — 协调三桥接器与阶段流转
├── dze-bridge.ts                     # DZE 深度分析链桥接
├── dream-agent-bridge.ts             # Dream Agent 协作网络桥接
├── approval-bridge.ts                # 审批桥接（代码变更门禁）
├── real-benchmark.ts                 # 零Token规划器 vs 传统LLM 性能基准评测
├── evolution-fullstack.test.ts       # 全链路集成测试
├── system-architecture-test.ts       # 系统架构测试
└── health_dashboard.json             # 健康看板数据
```

---

## 3. 文件清单与职责

### 3.1 核心层

| 文件 | 职责 | 关键导出 |
|------|------|----------|
| `types.ts` | 类型定义（10 触发源 × 9 阶段 × 6 状态 × 6 更新层，以及 Finding/Lesson/Proposal/Record/DZEChain/DreamAgentTask/ApprovalRequest 接口） | `EvolutionTriggerSource`, `EvolutionPhase`, `EvolutionStatus`, `UpdateLayer`, `EvolutionFinding`, `EvolutionLesson`, `EvolutionProposal`, `EvolutionRecord`, `DZEChainTrigger`, `DreamAgentTask`, `ApprovalRequest`, `EvolutionEngineConfig` |
| `evolution-engine.ts` | 进化引擎核心：`EvolutionRecord` 生命周期管理、Finding/Lesson/Proposal 增删、阶段流转、代码变更判定 | `EvolutionEngine` |
| `evolution-orchestrator.ts` | 进化编排器：协调 DZE/DreamAgent/Approval 三桥接器，驱动 9 阶段流水线 | `EvolutionOrchestrator`, `OrchestratorResult` |

### 3.2 桥接层

| 文件 | 职责 | 关键导出 |
|------|------|----------|
| `dze-bridge.ts` | DZE 开发链桥接：创建 d1→d4→z1→z4→e1→e3 链状态，Gate1/Gate2 门禁，产物登记 | `DZEBridge`, `DZEPhase`, `DZEChainState` |
| `dream-agent-bridge.ts` | Dream Agent 协作网络桥接：注册任务、开发者领取/提交、校验、治理入账、奖励分账 | `DreamAgentBridge`, `AgentRole`, `LedgerEntry`, `DreamAgentNetworkState` |
| `approval-bridge.ts` | 审批桥接：Gate1(方案)/Gate2(开工)/Merge/Deployment/Risk 五类审批，超时自动批准规则 | `ApprovalBridge`, `ApprovalGate`, `AutoApprovalRule` |

### 3.3 测试与基准层

| 文件 | 职责 |
|------|------|
| `evolution-fullstack.test.ts` | 全链路集成测试：进化闭环、DZE 链打通、审批门禁、Dream Agent 协作 |
| `system-architecture-test.ts` | 系统架构测试：模块协同、状态一致性、性能基准（依赖 `24-图结构上下文压缩/planner`） |
| `real-benchmark.ts` | 零Token规划器 vs 智谱GLM-4 / DeepSeek 真实性能对比评测（依赖 `24-图结构上下文压缩/planner`） |

### 3.4 配置与数据层

| 文件 | 职责 |
|------|------|
| `health_dashboard.json` | 健康看板数据 |
| `proposals/` | 进化提案记录（7 份 PROP-* 文档） |

---

## 4. 核心流程索引

### 4.1 进化主流程（9 阶段流水线）

```
触发源 (10 类)
    │
    ▼
EvolutionOrchestrator.startEvolution(triggerSource, findings)
    ├─→ EvolutionEngine.createEvolution()        → discovery
    ├─→ transitionPhase('learning')
    ├─→ extractLessons(findings) → addLessons()  → learning
    ├─→ generateProposals()                      → deep_analysis
    └─→ processProposals()
         ├─ requires_code=true  → triggerCodePath()
         │     ├─ DZEBridge.createChainFromEvolution()  → d1
         │     ├─ EvolutionEngine.triggerCodeDevelopment() → code_development
         │     └─ ApprovalBridge.createApprovalForGate1()  → 审批门禁
         └─ requires_code=false → triggerKnowledgePath()
               ├─ EvolutionEngine.applyKnowledgeUpdate()   → capability_update
               └─ allProposalsImplemented → completed
```

### 4.2 代码变更路径（DZE 链 + 双门禁 + Dream Agent）

```
code_development
    │
    ▼
DZE d1→d2→d3→d4 (需求→设计→评审→方案)
    │
    ▼ Gate1 (design 审批)  ← ApprovalBridge.createApprovalForGate1()
    │   passGate1() → z1
    │
    ▼
DZE z1→z2→z3→z4 (拆解→计划→排期→实施计划)
    │
    ▼ Gate2 (kickoff 审批)  ← ApprovalBridge.createApprovalForGate2()
    │   passGate2() → e1
    │
    ▼
DreamAgentBridge.registerTaskFromDZE()  → collaboration
    ├─ assignDeveloper()   → claimed
    ├─ submitForValidation() → in_progress
    ├─ validateTask()      → validated  (奖励: developer 60% + validator 20%)
    └─ finalizeTask()      → ledgered   (治理奖励 20%, block_height++)
    │
    ▼
DZE e1→e2→e3 (编码→测试→部署)
    │   completeChain(deployment_ref)
    ▼
deployment → completed
```

### 4.3 审批超时自动批准流程

```
ApprovalBridge.checkTimeouts()  /  Orchestrator.processApprovalTimeout()
    │
    ▼
autoApproveIfEligible(approvalId)
    ├─ 非 pending → 跳过
    ├─ 无 auto_approve 规则 → 跳过
    ├─ 未达 timeout_minutes → 跳过
    └─ 超时 → status='timeout_auto_approved', decided_by='auto-approval-bot'
         ├─ design 类型 → passGate1(approved=true)
         └─ kickoff 类型 → passGate2(approved=true)
```

---

## 5. 配置参数索引

### 5.1 `EvolutionEngineConfig`（`types.ts` / `evolution-engine.ts`）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `data_dir` | `./evolution_data` | 进化数据目录 |
| `auto_trigger_dze` | `true` | 自动触发 DZE 链 |
| `auto_trigger_dream_agent` | `true` | 自动触发 Dream Agent 协作 |
| `auto_create_approvals` | `true` | 自动创建审批工单 |
| `approval_timeout_minutes` | `30` | 审批超时（分钟） |
| `min_severity_for_code_change` | `medium` | 触发代码变更的最低严重度（low/medium/high） |

### 5.2 `AutoApprovalRule` 默认规则（`approval-bridge.ts` `initDefaultRules()`）

| approval_type | max_severity | max_complexity | auto_approve | timeout_minutes | required_checks |
|---------------|--------------|----------------|--------------|-----------------|-----------------|
| design | low | small | true | 30 | syntax_check, impact_analysis |
| kickoff | low | small | true | 30 | plan_review, risk_assessment |
| merge | medium | medium | true | 60 | validator_approved, test_passed |
| deployment | low | small | false | 120 | staging_test, rollback_plan |
| risk | low | small | false | 60 | risk_mitigation |

### 5.3 代码内置常量

| 文件 | 常量 | 值 | 说明 |
|------|------|----|------|
| `dze-bridge.ts` | 阶段顺序 | d1,d2,d3,d4,z1,z2,z3,z4,e1,e2,e3 | DZE 11 阶段 |
| `dream-agent-bridge.ts` | 基础奖励 | small=100, medium=500, large=2000 | DREAM 奖励基数 |
| `dream-agent-bridge.ts` | 奖励分账 | developer=60%, validator=20%, governance=20% | 三方分账比例 |
| `evolution-engine.ts` | 代码区域关键字 | code, skill, engine, module, component, api | `requiresCodeChange` 判定 |
| `evolution-engine.ts` | 严重度等级 | low=0, medium=1, high=2, critical=3 | 严重度排序 |

---

## 6. 测试体系

| 文件 | 测试内容 | 运行方式 |
|------|----------|----------|
| `evolution-fullstack.test.ts` | 进化端到端闭环、DZE 链打通、审批门禁、Dream Agent 协作 | `npx tsx evolution-fullstack.test.ts` |
| `system-architecture-test.ts` | 架构机制运转、模块协同、状态一致性、性能基准 | `npx tsx system-architecture-test.ts` |
| `real-benchmark.ts` | 零Token规划器 vs GLM-4 / DeepSeek 真实性能对比（需 `ZHIPU_API_KEY` / `DEEPSEEK_API_KEY`） | `npx tsx real-benchmark.ts` |

> 测试依赖 `../24-图结构上下文压缩/planner/` 模块（`ChainPlanner` / `planner-types`）。

---

## 7. 技术债务

| 债务项 | 严重程度 | 说明 |
|--------|----------|------|
| 纯内存态无持久化 | 高 | `EvolutionEngine.records` / `DZEBridge.chainStates` / `DreamAgentBridge.state` / `ApprovalBridge.approvals` 均为内存 `Map`，进程重启丢失全部进化记录 |
| 未集成主线交易系统 | 高 | 当前为实验模块，未接入实际交易触发源与飞书审批 OpenAPI |
| 审批未对接飞书 | 中 | `ApprovalRequest` 含 `feishu_approval_code` / `feishu_instance_code` 字段但未实际调用飞书审批 API |
| DZE 链无真实执行 | 中 | `DZEBridge` 仅维护状态机，未驱动真实 D1-D4 / Z1-Z4 / E1-E3 执行 |
| 无配置加载机制 | 低 | `EvolutionEngineConfig` 通过构造函数传入，未从配置文件读取 |

---

## 8. 快速导航

| 目标 | 路径 |
|------|------|
| 用户文档 | [../README.md](../README.md) |
| 技术设计 | [./TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) |
| 接口规范 | [./API_SPEC.md](./API_SPEC.md) |
| 变更记录 | [./CHANGELOG.md](./CHANGELOG.md) |
| 类型定义 | [../types.ts](../types.ts) |
| 编排器 | [../evolution-orchestrator.ts](../evolution-orchestrator.ts) |
| 引擎核心 | [../evolution-engine.ts](../evolution-engine.ts) |

---

**文档版本**: v1.0
**最后更新**: 2026-09-30
