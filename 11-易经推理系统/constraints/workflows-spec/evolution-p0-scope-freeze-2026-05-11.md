# Evolution P0 Scope Freeze (2026-05-11)

## In Scope

- candidate ingest
- audit gate
- sandbox gate
- decision gate
- rollback pointer
- artifacts traceability

## Out of Scope

- stress gate
- scenario gate
- backtest gate
- auto rollback executor
- UI dashboard

## Entry Criteria

- `memory -> evolution -> constraints` 主链契约已存在并可引用
- `trace_id/evidence_refs/schema_version` 字段在主契约中定义
- 进化工作流规范已纳入工程部规范主文档

## Exit Criteria

- 候选可入队并产出结构化 Candidate
- 审计与沙箱失败可 fail-closed 阻断发布
- Decision 仅允许全绿候选进入 Promote
- 每次 Decision 都包含 rollback pointer
