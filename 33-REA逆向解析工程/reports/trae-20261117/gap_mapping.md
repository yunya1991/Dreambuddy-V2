# Trae → 56 差距映射（R3）— v0.1

> 输入：`mechanism_cards.md` + `manifest.json` + `interaction_summary.json`。
> 原则：先映射现有 GAP，确认覆盖度；新候选用 `GAP-T*`，状态 `candidate`，不改 56 官方 GAP 表。

## §0 结论

- 共映射 5 个机制，产出 5 个候选缺口。
- **M3（命令信封）是唯一有硬证据的阻塞项**：1,006 条信封无 trace/session ID，导致 R2 的交叉证据门禁为 0%。
- M1/M2/M5 属于「契约已有、实现缺字段/缺版本/缺门控」，不应重复新建机制，应先核对 A1-2/A1-3/GAP-29 的现状。

## §1 机制 × 现有 GAP 映射

| 机制 | 名称 | 现有 GAP | 契约 | 判定 | 候选 |
|---|---|---|---|---|---|
| M1 | agent_type × model → skill bundle | GAP-02, GAP-13, GAP-19 | IF-1, IF-7 | 部分覆盖（缺模型维度与 bundle 标识） | GAP-T1 |
| M2 | session × mode → tool_set 快照 | GAP-19, GAP-23, GAP-25 | IF-7 | 部分覆盖（契约已有，版本/审计缺） | GAP-T2 |
| M3 | command → sandbox envelope | GAP-01, GAP-24, GAP-30 | IF-3, IF-7 | 契约覆盖，归因字段缺失（阻塞 R2 门禁） | GAP-T3 |
| M4 | session → checkpoint | GAP-20, GAP-24 | IF-4, ADR-10 | 未覆盖（缺 checkpoint 契约） | GAP-T4 |
| M5 | session → summary memory | GAP-15, GAP-29 | IF-5, ADR-06 | 部分覆盖（缺证据门控与训练接线） | GAP-T5 |

## §2 候选缺口

### GAP-T1 能力装配缺少「模型感知的 skill/tool bundle」标识

- 层级/优先级：L2 / **P1**（confidence=0.7）
- 机制：M1；现有 GAP：GAP-02, GAP-13, GAP-19
- 契约：IF-1 route_signal, IF-7 tool_set, ADR-09
- 事实：`{"agent_types": {"trae": 6, "code": 6, "design": 4, "work": 10}, "skill_range": {"trae": [1, 7], "code": [1, 6], "design": [1, 6], "work": [1, 14]}}`
- 判据：
  - route_signal 必须含 capability_bundle_id 与 model_profile
  - tool_set 快照必须引用 skill_bundle_id
  - 无 bundle 时不得静默降级，必须回 L1 或标 needs_review
- 推广前核对：先核对 GAP-02/GAP-13 的 l2_route 实现，避免与裁决层重复开缺口。

### GAP-T2 tool_set 只有单快照，无会话级版本/差异审计

- 层级/优先级：L2 / **P1**（confidence=0.7）
- 机制：M2；现有 GAP：GAP-19, GAP-23, GAP-25
- 契约：IF-7 tool_set.schema.json, G-L2-11
- 事实：`{"mcp_sessions": 25, "modes": {"Explore": 16, "Plan": 16, "browser_use": 32, "computer_use": 17, "general_purpose_task": 20, "search": 31, "solo_agent": 32, "solo_agent_lite": 37, "solo_design_lite": 20, "solo_work_lite": 37}}`
- 判据：
  - 每个 L2 会话产出 tool_set_hash
  - 工具面变更产出 diff 事件（added/removed/changed）
  - 审计可对比「LLM 可见工具」与「审批工具」是否同源
- 推广前核对：A1-2 已生成唯一快照；先确认是否已有 hash/版本字段，再决定是否新增。

### GAP-T3 执行信封缺 trace_id/session_id，命令与交互不可归因

- 层级/优先级：L2 / **P1**（confidence=0.9）
- 机制：M3；现有 GAP：GAP-01, GAP-24, GAP-30
- 契约：IF-3 L2Envelope.trace, IF-7 span.schema.json, G-L2-8
- 事实：`{"executions": 1006, "records": 627, "cross_evidence_rate": 0.0}`
- 判据：
  - 每条命令/工具执行 span 必含 trace_id、run_id、session_id
  - 交互记录与执行信封的 join_rate ≥95%
  - 无 ID 的信封不得作为回归/验收证据
- 推广前核对：这是 R2 门禁失败的直接原因；建议优先修，且只改我方执行链，不改 Trae。

### GAP-T4 无会话检查点契约（checkpoint → resume）

- 层级/优先级：L2 / **P2**（confidence=0.7）
- 机制：M4；现有 GAP：GAP-20, GAP-24
- 契约：IF-4 Ticket, ADR-10, G-L2-10
- 事实：`{"snapshots": 19, "repos": 19}`
- 判据：
  - paused ticket 必须引用 checkpoint_id + content hash
  - resume 必须从 checkpoint 恢复并复跑验证
  - 无 checkpoint 时不得声明 resumable=true
- 推广前核对：先验证 Ticket paused 是否已有等价物；若已有，改为补字段而非新建机制。

### GAP-T5 交互摘要未进入训练/台账，且缺证据门控

- 层级/优先级：L2 / **P1**（confidence=0.7）
- 机制：M5；现有 GAP：GAP-15, GAP-29
- 契约：IF-5 RepairLedger, ADR-06, G-L2-5, G-L2-7
- 事实：`{"records": 627, "sessions": 50, "gap_themes": {"数据/检索": 34, "部署/云端": 26, "前端/接口": 15, "路由/分层": 14, "门禁/验收": 13, "文档/规范": 11, "MCP/工具": 10, "trace/观测": 5}}`
- 判据：
  - 只有 ≥1 条 observation 级交叉证据的案例可入 training_cases
  - 纯 inference 案例标 inference，不用于优化结论
  - settled 台账必须引用 case_ref
- 推广前核对：与 GAP-29 的 L1 发现门禁联动；摘要缺口主题不能直接当 L1 finding。

## §3 推荐顺序

1. **GAP-T3**：补 trace_id/session_id，先让执行信封可归因（只改我方执行链）。
2. **GAP-T5**：给交互案例加证据门控，避免 inference 污染训练/台账。
3. **GAP-T1**：能力 bundle 标识，接 IF-1/IF-7。
4. **GAP-T2**：tool_set 会话级版本与 diff 审计。
5. **GAP-T4**：checkpoint→resume 契约（先确认 Ticket 是否已有等价物）。

## §4 局限

- 本映射基于 Trae 的声明与运行时产物，不证明我方现有实现缺失；每条候选推广前必须代码复核。
- R2 案例全部为摘要级 inference；GAP-T5 的「证据门控」是纪律建议，不是统计结论。
- `GAP-T*` 尚未合并进 56 官方 GAP-31+；需评审后登记。

## §5 复跑

```bash
PYTHONPATH=. python3 -m trae.gap_mapper --pilot reports/trae-20261117 --out reports/trae-20261117
```