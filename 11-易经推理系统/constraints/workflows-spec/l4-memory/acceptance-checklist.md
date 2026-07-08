# L4约束验收清单

Date: 2026-05-12
Status: Active
Scope: L4 记忆工作流规范验收（文档与工程对齐）

## 使用说明

- `skeleton-ready`：用于判断"骨架已就位，可继续迭代实现"。
- `production-ready`：用于判断"可进入稳定运行与治理闭环"。
- 任一 `MUST` 项不满足，则该级别验收不通过。

## A. Skeleton-Ready 门禁

### A1. 架构与映射

- [ ] `MUST` 顶层工程设计文档已存在且可访问：`docs/superpowers/plans/2026-05-12-l4-memory-architecture-upgrade.md`
- [ ] `MUST` 约束层 L4 架构规范已落地到 `constraints/workflows-spec/l4-memory/`。
- [ ] `MUST` `README.md` 已建立"顶层 -> 约束 -> 运行契约"索引映射。
- [ ] `MUST` `memory.md` 已声明 L4 规范引用与执行原则。

### A2. 对象契约

- [ ] `MUST` TradeCase.vNext 字段已定义：`thinking_chain[]`、`evidence_chain[]`、`decision_outcome`、`l4_status`。
- [ ] `MUST` ReviewRecord 双向复盘字段已定义：`mistakes[]`、`successes[]`、`theory_practice_gap`。
- [ ] `MUST` DistillRecord 三层结构已定义：`what_is_it/why_it_works/how_to_apply`。
- [ ] `MUST` Distill 向后兼容映射已定义：`claim/actionable_rules`。
- [ ] `MUST` StatsSnapshot 的 `regime/category/severity` 过滤维度已定义。

### A3. 流程与门禁

- [ ] `MUST` L4 状态机已定义：`M0~M4/M_FAIL`。
- [ ] `MUST` 失败语义最小集已定义并可追溯 `reason_code/evidence_refs`。
- [ ] `MUST` 主链约束已定义：`memory -> evolution -> constraints`。
- [ ] `MUST` 明确"入口薄封装、复杂能力下沉"的分层约束。

## B. Production-Ready 门禁

### B1. 产物质量

- [ ] `MUST` L4 产物可追溯：`trace_id/stage_id/evidence_refs/constraint_version` 完整。
- [ ] `MUST` 候选输出具备拒绝/回滚语义，不允许无证据升级。
- [ ] `MUST` 文档中的状态机、错误码、字段定义不存在冲突。
- [ ] `MUST` 文档与约束层索引无失效路径。

### B2. 实现对齐（与分支协同）

- [ ] `MUST` 分支实现已标注能力状态：`skeleton-ready` 或 `production-ready`。
- [ ] `MUST` `review_engine/a7a8_bridge/thinking_chain_index_extension` 与规范字段对齐。
- [ ] `MUST` A0-A9 到 L4 的最小数据通道具备可审计输入输出。
- [ ] `MUST` 蒸馏三问链路具备可执行校验（非纯占位）。

### B3. 运行治理

- [ ] `MUST` 任一门禁失败默认 fail-closed，并输出结构化审计。
- [ ] `MUST` 进化链路验证报告可回放（至少包含 audit/sandbox 级别）。
- [ ] `SHOULD` 提供周/月治理汇总（成功率、拒绝率、回滚率、主要 reason_code）。
- [ ] `SHOULD` 四象限统计支持按 `regime/category/severity` 检索。

## C. 验收结论模板

- 验收级别：`skeleton-ready` / `production-ready`
- 结论：`PASS` / `FAIL`
- 未通过项：
  - `ID`:
  - `Reason`:
  - `Owner`:
  - `ETA`:
