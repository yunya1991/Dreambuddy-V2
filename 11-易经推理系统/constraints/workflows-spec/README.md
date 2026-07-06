# 工作流规范索引

- `memory.md`：记忆工作流规范
- `l4-memory/README.md`：L4 记忆规范目录（集中治理入口）
- `l4-memory/architecture-and-workflow-design.md`：L4 记忆工程架构规范（约束层基线）
- `l4-memory/acceptance-checklist.md`：L4 约束验收清单（`skeleton-ready` / `production-ready`）
- `trading.md`：交易决策工作流规范
- `governance.md`：治理工作流规范
- `knowledge.md`：知识库管理工作流规范
- `evolution.md`：系统进化工作流规范
- `evolution.md`（2026-05-11 更新）：纳入“记忆驱动进化闭环”工程部规范（最小闭环 + 验证门禁 + P0/P1/P2 路线）
- `evolution-p0-scope-freeze-2026-05-11.md`：P0 范围冻结（In Scope / Out of Scope）
- `evolution-p0-contracts-v0.1.md`：P0 三类契约定义（Candidate/ValidationReport/PromotionRecord）
- `evolution-p0-state-machine-errors.md`：P0 状态机与错误码字典
- `evolution-p0-acceptance-checklist.md`：P0 验收清单与 Go/No-Go 步骤
- `evolution-p0-acceptance-report-2026-05-11.md`：P0 Day1 手工验收报告（正/反样本 + Go/No-Go）
- `evolution-p0-acceptance-report-2026-05-12.md`：P0 Day2 自动化验收报告（Decision Gate + rollback pointer）
- `evolution-p0-decision-gate-spec-v0.1.md`：P0 Day2 Decision Gate 可执行规则与错误码映射
- `evolution-p0-rollback-pointer-spec-v0.1.md`：P0 Day2 rollback pointer 数据契约与恢复约定
- `evolution-p1-stage-policy-spec-v0.1.md`：P1 多门禁 `stage_policy` 独立判定策略规范
- `evolution-p1-acceptance-report-2026-05-12.md`：P1 多门禁聚合验收报告（stress/scenario/backtest + stage_policy）
- `evolution-p1-5-policy-template-versioning-spec-v0.1.md`：P1.5 `policy_version` 模板库与版本化规范
- `evolution-p1-5-regression-matrix-report-2026-05-12.md`：P1.5 回归矩阵执行报告
- `evolution-p2-approval-gate-spec-v0.1.md`：P2 审批票据门禁规范（Decision + Approval 双门禁）
- `evolution-p2-ops-automation-spec-v0.1.md`：P2 运营自动化规范（评分/看板/自动回滚/周期报表）
- `evolution.md`（2026-05-12 追加）：补齐推荐 workflow 拆分与默认 smoke 验收路径
- `communication-contract-v0.1.md`：三层通信调用与闭环升级契约
- `trading-communication-protocol-v2.md`：A0-A9 通信协议与定时驱动架构（v2.1，2026-05-12 更新：A0 集成化 + 治理环重构 + 定时调度；P1 追加：传输层对接 HTTP + Redis Streams）
- `memory.md`（2026-05-10 更新）：新增 L1~L4 显式入口映射与 `MemoryEngine` 调用对齐约定
- `trading.md`（2026-05-10 更新）：新增 A0-A9 显式入口映射与三批技能迁移清单
- `a0-a9-fullchain-checklist.md`：A0-A9 全链路迁移对照清单（源仓 vs 本地仓）
- `skill-inventory-checklist.md`：SKILL 全量迁移清单（分层明细 + 缺口）
- `skill-inventory-checklist.md`（2026-05-11 更新）：基线技能覆盖率审计（47/47）与重要级分层状态
- `a0-a9-tooling-audit-2026-05-11.md`：A0-A9 完整闭环相关工具核查（入口/技能/记忆/门禁）
- `a0-a9-system-level-implementation-checklist.md`：A0-A9 协议与三大闭环系统级实现清单（P0/P1/P2）

## 顶层到约束映射

- 顶层工程设计（主）：`docs/superpowers/plans/2026-05-12-l4-memory-architecture-upgrade.md`
- 补充规范：`docs/superpowers/specs/2026-05-12-l4-memory-architecture-and-workflow-design.md`
- 约束层规范（从）：`constraints/workflows-spec/l4-memory/architecture-and-workflow-design.md`
- 运行契约入口：`constraints/workflows-spec/memory.md`
