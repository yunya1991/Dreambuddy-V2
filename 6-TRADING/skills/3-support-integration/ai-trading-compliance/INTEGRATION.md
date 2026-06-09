# ai-trading-compliance 集成规范 (Governance G2 — 提案合规门禁)

> **原始 SKILL**: dream-multiskill-v2/skills/3-SUPPORT/ai-trading-compliance/SKILL.md v2.0.0
> **集成层级**: Governance（所有 Process D 提案的前置合规审查）
> **触发时机**: Process D D3 输出 `weekly-proposals.json` 后 → auto-repair 落地前

---

## 一、职责

对 Process D 每周产出的改进提案做 R0-R3 风险分级 + 9 项硬门禁审查，输出 `compliance_receipt.json`，决定提案能否由 auto-repair 自动落地，还是需要人工审核。

---

## 二、触发位置（两处）

| 触发场景 | 时机 | 说明 |
|---------|------|------|
| Process D Step 4.5 | D3 输出 `weekly-proposals.json` 后 | 必须触发，每条提案生成对应回执 |
| Team B 策略参数变更 | 任何直接修改 Gate C 阈值/马丁格参数的操作 | 防止 AI 自行扩大风险敞口 |

---

## 三、6-TRADING 提案类型 → R 级映射

| 提案类型 (D3 output) | R 级 | 含义 | 落地方式 |
|---------------------|------|------|---------|
| `trigger_prompt_patch` | R2 | 修改触发提示词逻辑 | ❌ 禁止自动落地，须人工审核后更新 `TRIGGER_PROMPTS.md` |
| `gate_threshold_update` | R2 | 修改 Gate C 通过阈值 | ❌ 禁止自动落地，须 risk_owner 审批 |
| `martingale_param_update` | R1 | 调整马丁格参数（TP/SL/间距）| ✅ 合规通过后 auto-repair 自动落地 |
| `knowledge_base_update` | R0 | 知识库新增/更新历史数据 | ✅ 自动落地（只读性写入）|
| `skill_replacement` | R3 | 替换某个 SKILL 版本 | ❌ 禁止自动落地，须人工走 PR 流程 |

---

## 四、6-TRADING 硬门禁映射（9 项）

| 门禁 ID | 原始含义 | 6-TRADING 对应 |
|--------|---------|--------------|
| H001 | SSoT 引用 | `doc_refs` 必须引用 `SKILL_REGISTRY.md` + 对应 `INTEGRATION.md` |
| H002 | 可复现性 | 提案必须包含 `evidence_refs[]`（指向 episode_id 或 session_id） |
| H003 | P3 门禁产物 | 提案必须包含 `data_source`（来自 DA 量化报告或 A8 反思）|
| H004 | 回滚可执行 | 必须包含 `rollback_plan_id`（D3 强制字段）|
| H005 | 密钥不出域 | 不涉及（6-TRADING 不做外联发布提案）|
| H006 | 环境隔离 | gate_threshold_update 必须先在 demo 环境验证 |
| H007 | 外联控制 | 不涉及 |
| H008 | 风险扩张 | R2/R3 提案有 `risk_expansion=true` 标记时须人工审批 |
| H009 | Rollback Plan ID | 同 H004，D3 已强制输出 |

**Fail-Closed**: H001/H002/H003/H004/H009 任一缺失 → `decision: fail` → 提案退回 D3 重生成。

---

## 五、输入规范（6-TRADING 版 change_bundle）

D3 输出的每条 proposal 需被包装为 `change_bundle.json`：

```json
{
  "intent": {
    "what": "从 proposal.title 提取",
    "why": "从 proposal.rationale 提取",
    "impact_scope": ["parameter" | "strategy" | "system"]
  },
  "change_type": "R0 | R1 | R2 | R3",
  "risk_level": "P0 | P1 | P3",
  "doc_refs": ["6-TRADING/docs/SKILL_REGISTRY.md", "对应 INTEGRATION.md"],
  "artifacts": {
    "data_snapshot_id": "sessions/{session_id}",
    "strategy_key": "提案影响的 SKILL ID"
  },
  "rollback_plan": {
    "rollback_plan_id": "来自 D3 强制字段",
    "rollback_points": ["恢复到上一版本 TRIGGER_PROMPTS.md"],
    "triggers": ["实际 PnL 比提案预期差 >20%"],
    "actions": ["revert TRIGGER_PROMPTS.md", "update memory"]
  },
  "evidence": ["来自 D3 的 evidence_refs[]"]
}
```

---

## 六、输出规范

写入 `sessions/{latest_session}/governance/compliance-receipt-{proposal_id}.json`:

```json
{
  "decision": "pass | warn | fail",
  "proposal_id": "来自 weekly-proposals.json",
  "change_classification": {
    "change_type": "R1",
    "risk_level": "P1",
    "auto_land_allowed": true
  },
  "blockers": [],
  "required_actions": [],
  "rollout_requirements": {
    "mode": "canary",
    "must_monitor": ["gate_pass_rate", "consecutive_skip_count"],
    "auto_rollback_triggers": ["gate_pass_rate < 0.4 within 5 sessions"]
  },
  "audit_fields": {
    "doc_refs": ["SKILL_REGISTRY.md"],
    "trace_id": "sessions/{session_id}",
    "approver_roles": ["risk_owner"]
  }
}
```

---

## 七、与 auto-repair 的接口

```
D3 weekly-proposals.json
  → [ai-trading-compliance] 逐条生成 compliance-receipt-{id}.json
  → decision=pass + R0/R1 → auto-repair 自动落地
  → decision=pass + R2/R3 → 写入 pending_human_review 列表，operation-director 路由人工审批
  → decision=fail  → 提案退回，写入 a8-reflection.json 的 rejected_proposals 字段
```

---

## 八、H009 宪法约束

> ⚠️ `trigger_prompt_patch` 和 `gate_threshold_update` 即使 `decision=pass`，也属于 R2，**禁止 auto-repair 自动落地**。必须人工审核后手动更新 `TRIGGER_PROMPTS.md`。

---

*最后更新: 2026-05-27 v1.0 | 集成 ai-trading-compliance v2.0 → Governance G2*
