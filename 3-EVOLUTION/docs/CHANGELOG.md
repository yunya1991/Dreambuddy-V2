# 变更记录 — 3-EVOLUTION 进化引擎

> **版本**: v1.0 | **更新日期**: 2026-09-30

---

## 版本变更记录

| 版本 | 日期 | 变更内容 | 影响范围 |
|------|------|----------|----------|
| v1.0 | 2026-09-30 | 补建完整文档体系：新建 `docs/ENGINEERING_INDEX.md`、`docs/TECHNICAL_DESIGN.md`、`docs/API_SPEC.md`、`docs/CHANGELOG.md`，对齐 DOC_STANDARD L3 模块文档建设规范 | 文档 |
| v0.2 | 2026-08-02 | README 版本更新至 v0.2，状态标记为实验状态未集成主线 | 文档 |
| v0.1 | 2026-07-31 | 初始版本：进化引擎核心实现（`EvolutionEngine`、`EvolutionOrchestrator`、`DZEBridge`、`DreamAgentBridge`、`ApprovalBridge`），9 阶段流水线、10 触发源、6 更新层、三桥接架构；配套全栈测试与系统架构测试 | 核心代码 + 测试 |

---

## 详细变更

### v1.0 — 2026-09-30

**文档建设**
- 新建 `docs/ENGINEERING_INDEX.md`：模块定位、目录地图、文件清单、核心流程、配置参数、测试体系、技术债务、快速导航
- 新建 `docs/TECHNICAL_DESIGN.md`：概述、分层架构、核心算法（代码变更判定/变更类型分派/DZE 阶段推进/Gate 门禁/奖励分账/超时自动批准）、数据流、接口设计、状态管理、配置管理、错误处理、扩展性设计
- 新建 `docs/API_SPEC.md`：5 个核心类（EvolutionEngine / EvolutionOrchestrator / DZEBridge / DreamAgentBridge / ApprovalBridge）全部公开方法签名、参数表、示例、错误码
- 新建 `docs/CHANGELOG.md`：本文件

### v0.2 — 2026-08-02

**文档更新**
- README 版本升至 v0.2，明确"实验状态，未集成到主线"

### v0.1 — 2026-07-31

**核心功能**
- `types.ts`：定义 10 触发源（`EvolutionTriggerSource`）、9 阶段（`EvolutionPhase`）、6 状态（`EvolutionStatus`）、6 更新层（`UpdateLayer`）及 Finding/Lesson/Proposal/Record/DZEChain/DreamAgentTask/ApprovalRequest 接口
- `evolution-engine.ts`：`EvolutionEngine` 实现进化记录生命周期、Finding/Lesson/Proposal 管理、阶段流转、代码变更判定（严重度 + 受影响区域关键字）
- `evolution-orchestrator.ts`：`EvolutionOrchestrator` 实现 9 阶段流水线编排，协调三桥接器，知识路径与代码路径分流
- `dze-bridge.ts`：`DZEBridge` 实现 DZE 链 d1→e3 状态机、Gate1(d4)/Gate2(z4) 门禁、产物登记
- `dream-agent-bridge.ts`：`DreamAgentBridge` 实现任务注册/领取/提交/校验/入账流程、DREAM 奖励三方分账（developer 60% / validator 20% / governance 20%）、账本与区块高度
- `approval-bridge.ts`：`ApprovalBridge` 实现 5 类审批（design/kickoff/risk/merge/deployment）、超时自动批准规则（默认 5 条）

**测试**
- `evolution-fullstack.test.ts`：全链路集成测试
- `system-architecture-test.ts`：系统架构测试
- `real-benchmark.ts`：零Token规划器 vs 传统 LLM 性能基准评测

---

**文档版本**: v1.0
**最后更新**: 2026-09-30
