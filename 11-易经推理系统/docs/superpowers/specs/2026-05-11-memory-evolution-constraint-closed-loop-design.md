# 记忆驱动进化闭环设计（最小可行版）

Date: 2026-05-11  
Status: Approved (Design)  
Scope: `memory -> evolution -> constraints` 自动化进化闭环（不改动现有交易主链结构）

## 1. 背景与目标

当前系统已具备：

- 记忆工作流入口（L1~L4）与 `MemoryEngine` 能力；
- 交易侧 A0-A9 主链协议与系统级门禁；
- 约束通信契约 `v0.1` 与主链可追溯审计能力。

本设计目标是补齐“最小严谨闭环”：

`记忆工作流（全局底座） -> 进化自动验证 -> 约束层升级/回滚`

并满足以下业务诉求：

- 理论-实践批判（A7/A8）可沉淀为可验证候选；
- 统计量变信号可驱动约束渐进演化；
- 做梦链路反馈可进入统一进化验证，而非直接影响主链；
- 整个链路具备审计、沙箱、压测、情景模拟、回测、回滚。

## 2. 设计原则

### 2.1 治理原则

- `constraints` 是唯一规则源（SSOT）。
- 约束升级唯一通道：`memory -> evolution -> constraints`。
- 任何验证失败必须 fail-closed，不允许“带病发布”。
- 自动化只做“可追溯决策”，不可产生黑箱升级。

### 2.2 金融风控原则（传统金融 + AI）

- 先控风险、再看收益：风险指标门禁优先级高于收益改进。
- 强制样本外验证：防止参数投机与过拟合。
- 尾部风险优先：极端场景劣化直接否决。
- 回滚先于升级：每次升级前必须存在可执行回滚指针。

### 2.3 工程原则（GitHub 成熟实践）

- Pipeline 分阶段、可重跑、可追踪、可审计 artifact。
- 每一步都结构化输出（JSON），并归档到 Actions Artifacts。
- 门禁结果通过 required checks 管控，不依赖人工口头确认。
- 变更通过 PR 合并，不允许直推主分支。

## 3. 闭环总体架构

## 3.1 数据与控制流

```text
memory (episode/case/distill/stats + theory/practice + dream feedback)
  -> evolution/feedback (candidate ingest)
  -> evolution/audit
  -> evolution/sandbox
  -> evolution/stress
  -> evolution/scenario
  -> evolution/backtest
  -> evolution/decision (approve/reject)
  -> constraints (promote) OR evolution/rollback
```

## 3.2 模块职责

- `memory`：提供候选素材，不直接改写约束。
- `evolution`：唯一验证与决策执行中台。
- `constraints`：仅接收通过全部门禁的升级 PR。
- `trading`：既是消费方，也是候选证据来源之一。

## 4. 最小闭环状态机

标准状态：

- `C0_COLLECTED`：候选收集完成
- `C1_AUDIT_PASSED`：审计通过
- `C2_SANDBOX_PASSED`：沙箱通过
- `C3_STRESS_PASSED`：压测通过
- `C4_SCENARIO_PASSED`：情景模拟通过
- `C5_BACKTEST_PASSED`：回测通过
- `C6_APPROVED`：进化决策通过
- `C7_PROMOTED`：约束发布成功
- `C8_ROLLED_BACK`：发布后触发回滚
- `C_FAIL`：任一步失败（附 `reason_code`）

状态转移规则：

- 任一阶段失败 -> `C_FAIL`，并冻结后续自动升级。
- 仅 `C6_APPROVED` 可进入 `C7_PROMOTED`。
- 发布后观察窗触发异常 -> `C8_ROLLED_BACK`。

## 5. 候选与报告契约

## 5.1 Candidate 契约（输入）

字段要求：

- `candidate_id`
- `trace_id`
- `constraint_version_base`
- `source_type` (`theory_practice` | `stats_evolution` | `dream_feedback` | `hybrid`)
- `source_refs[]`
- `hypothesis`
- `expected_effect`
- `risk_assessment`
- `evidence_refs[]`
- `schema_version`

## 5.2 ValidationReport 契约（阶段输出）

- `candidate_id`
- `stage` (`audit`/`sandbox`/`stress`/`scenario`/`backtest`)
- `pass` (bool)
- `metrics` (key-value)
- `violations[]`
- `timestamp`
- `artifacts[]`

## 5.3 PromotionRecord 契约（发布输出）

- `candidate_id`
- `from_version`
- `to_version`
- `decision`
- `rollback_pointer`
- `evidence_refs[]`
- `timestamp`

## 6. 自动验证门禁矩阵

## 6.1 Audit Gate

检查项：

- 字段完整性、schema 合法性
- 来源合法性（必须来自 memory 可追溯实体）
- 证据链完整性（`evidence_refs` 非空且可读）
- 冲突规则检测（与现有约束版本冲突）

拒绝条件：

- `EVIDENCE_INCOMPLETE`
- `CONTRACT_SCHEMA_INVALID`
- `CONSTRAINT_CONFLICT`

## 6.2 Sandbox Gate

检查项：

- 对同一 replay 集对比 `base constraint` 与 `candidate constraint`
- 不允许风险项恶化超阈值

拒绝条件：

- `SANDBOX_REGRESSION`

## 6.3 Stress Gate

检查项：

- 峰值压力下延迟、错误率、重试率
- 关键路径可用性与降级策略有效性

拒绝条件：

- `STRESS_SLO_VIOLATION`

## 6.4 Scenario Gate

检查项：

- 牛/熊/震荡/极端事件情景仿真
- 风险暴露、回撤边界、仓位稳定性

拒绝条件：

- `SCENARIO_RISK_BREACH`

## 6.5 Backtest Gate

检查项（最小集合）：

- `MaxDD` 不得恶化超过阈值
- `Sharpe` 不低于基线容忍区间
- 交易成本敏感性不过度劣化

拒绝条件：

- `BACKTEST_PERF_REGRESSION`
- `TAIL_RISK_OVER_LIMIT`

## 7. GitHub 自动化流程设计

## 7.1 Workflow 拆分

建议新增 5 个工作流（均仅设计，不立即改代码）：

- `memory-candidate-ingest.yml`
  - 定时收集候选，写入 `artifacts/evolution/feedback/`
- `evolution-validation-gate.yml`
  - 串行执行 audit/sandbox/stress/scenario/backtest
- `constraint-promotion.yml`
  - 仅当 gate 全绿，自动创建约束升级 PR
- `post-promotion-watch.yml`
  - 发布后观察窗监控（异常触发 rollback）
- `constraint-rollback.yml`
  - 执行回滚并生成回滚审计报告

## 7.2 Required Checks 建议

在主 PR Gate 中新增或串联：

- `Evolution Audit Gate`
- `Evolution Sandbox Gate`
- `Evolution Stress Gate`
- `Evolution Scenario Gate`
- `Evolution Backtest Gate`

## 7.3 Artifact 规范建议

- `artifacts/evolution/feedback/*.json`
- `artifacts/evolution/audit/*.json`
- `artifacts/evolution/sandbox/*.json`
- `artifacts/evolution/stress/*.json`
- `artifacts/evolution/scenario/*.json`
- `artifacts/evolution/backtest/*.json`
- `artifacts/evolution/promotion/*.json`
- `artifacts/evolution/rollback/*.json`

## 8. 失败语义与处置策略

统一错误码：

- `CANDIDATE_INVALID`
- `AUDIT_FAILED`
- `SANDBOX_REGRESSION`
- `STRESS_SLO_VIOLATION`
- `SCENARIO_RISK_BREACH`
- `BACKTEST_PERF_REGRESSION`
- `PROMOTION_BLOCKED`
- `ROLLBACK_REQUIRED`

处置策略：

- 阶段失败立即停止自动推进；
- 自动创建审计 issue；
- 写入可追溯报告并通知治理环；
- 仅允许人工二次确认后重试。

## 9. 最小闭环 DoD（Definition of Done）

以下全部满足才视为闭环完成：

- 候选可由记忆层自动收集并结构化入队；
- 自动验证五关可连续运行并产出审计报告；
- 仅全绿候选可触发约束升级 PR；
- 发布后监控可自动触发回滚流程；
- 任一失败可定位到 `stage + reason_code + evidence_refs`。

## 10. 分阶段实施路线图（P0/P1/P2）

## P0（最小骨架，1~2 周）

目标：把“可跑通的闭环骨架”搭起来。

范围：

- 候选契约与验证报告契约固化；
- `ingest -> audit -> sandbox -> decision` 最小链路；
- 回滚指针机制（不必全自动回滚，只需可执行）；
- GitHub workflow 雏形 + artifact 归档。

验收：

- 至少 1 条候选可完整跑到 decision；
- 审计与沙箱失败可阻断发布；
- 产物全量可追溯。

## P1（风控强化，2~4 周）

目标：补齐金融风控验证闭环。

范围：

- 接入 stress/scenario/backtest 三类验证；
- 明确风险阈值配置（基线可版本化）；
- 升级 required checks；
- 发布后观察窗与自动告警。

验收：

- 五关门禁全部可执行；
- 任一风控越界可自动拒绝发布；
- 观察窗异常能触发 rollback 提案。

## P2（生产级运营，4~8 周）

目标：形成可持续进化运营体系。

范围：

- 候选优先级排序（收益/风险/覆盖度评分）；
- 版本对比看板（可后续补 UI，先 JSON 指标）；
- 自动回滚执行器与 RTO 指标；
- 月度审计报表与治理 KPI。

验收：

- 闭环运行具备稳定 SLO；
- 回滚成功率与恢复时间可量化；
- 形成周/月审计节律，支持治理复盘。

## 11. 执行建议（不改代码阶段）

立即可执行的三件事：

- 先在约束层补齐闭环契约字段与错误码字典（文档层）。
- 先定义 P0 风险阈值最小集合（只设硬门槛）。
- 先跑一轮“手工模拟流程”验证状态机与审计字段完整性。

后续进入代码实施时，再按 P0 -> P1 -> P2 逐步落地，避免一次性改造风险。
