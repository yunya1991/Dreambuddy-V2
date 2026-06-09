# learning-proposal-generator 集成规范 (Process D — D3)

> **原始 SKILL**: dream-multiskill-v2/skills/0-CORE/learning-proposal-generator/SKILL.md
> **集成团队**: Process D — 交易复盘（三级学习闭环第 3 步；下游 G2 合规审查为强制步骤）
> **触发时机**: learning-lesson-distiller (D2) 完成后，Process D Step 4；输出后强制触发 Step 4.5 (ai-trading-compliance G2)

---

## 一、职责

将 D2 输出的 `lessons_delta` 转化为可治理的系统改进提案。每个提案必须包含 `rollback_plan_id`（如何撤销）和 `evidence_refs`（指向具体 episode）。提案本身不自动执行，需人工审核。

---

## 二、提案类型（6-TRADING 版）

| type | R级别 | 修改目标 | 示例 |
|------|-------|---------|------|
| `trigger_prompt_patch` | R2 | Screen 1/2/3 CronCreate 触发提示词 | 新增 Phase-0 步骤 |
| `martingale_param_update` | R1 | Screen 2 马丁格参数（间距/仓位比例/止损距离） | 将 L0 仓位从 30% 降至 20%（资金费率风险）|
| `gate_threshold_update` | R2 | A7/Gate C 评分阈值 | 资金费率 < -5% 时 composite_confidence 折扣系数 0.8 |
| `knowledge_base_update` | R1 | 知识库策略评分参数 | 更新 futures_martingale SHORT 的历史胜率 |
| `skill_improvement_plan` | R1 | 低评分 SKILL 改进计划（由 PR D级触发） | B3 评分逻辑改进 |
| `skill_replacement` | R3 | SKILL 替换（由 PR 连续 D 级 3 周触发）| 替换 dream-signal-scoring-spec | 须最高人工审核，禁止 G3 自动落地 |

---

## 三、Proposal Schema

```json
{
  "proposal_id": "PROP-20260526-001",
  "type": "trigger_prompt_patch",
  "title": "Screen 2 Phase-0 新增资金费率风险折扣逻辑",
  "target_file": "6-TRADING/docs/TRIGGER_PROMPTS.md",
  "patch_content": "在 Screen 2 Phase-0 P0.3 后新增: 若资金费率 < -5%，自动在 data_context 中注入 squeeze_risk_high=true，Screen 2 A1/A2/A3 须明确评估 Short Squeeze 概率",
  "reason": "F_SHORT_SQUEEZE_UNDERWEIGHTED: 3 次因资金费率极值导致空头亏损",
  "reason_codes": ["F_SHORT_SQUEEZE_UNDERWEIGHTED"],
  "rollback_plan_id": "ROLLBACK-20260526-001",
  "rollback_plan": "删除 squeeze_risk_high 注入步骤，恢复原 Phase-0 流程",
  "evidence_refs": ["20260526-BTC-SCREEN2-v2-episode-001"],
  "require_shadow_verification": true,
  "shadow_period_days": 7,
  "status": "pending_compliance_check",
  "created_at": "2026-05-26T06:30:00+08:00",
  "approved_by": null,
  "applied_at": null
}
```

---

## 四、提案生命周期（v1.3 Governance 链）

```
D3 生成 proposal → status: pending_compliance_check
  → Step 4.5: [ai-trading-compliance G2] 逐条合规审查
      R0/R1 + pass → auto_land_allowed=true → G3 自动落地
      R2 + pass    → pending_human_review=true → G4 路由人工审批
      fail         → rejected → 写入 a8-reflection.json 的 rejected_proposals
  → Step 4.6: [auto-repair G3]
      auto_land_allowed=true (R0/R1):
        martingale_param_update → 自动更新 TRIGGER_PROMPTS.md 参数段
        knowledge_base_update   → 自动更新 knowledge/ 对应文件
        skill_improvement_plan  → 自动更新 INTEGRATION.md PIP 段
      pending_human_review (R2):
        → 写入 governance/pending-approvals.md
        → [dream-operation-director G4] 通知 risk_owner / strategy_owner
      R3 (skill_replacement):
        → 直接路由 G4 人工审批，G3 不接触
```

**R级别说明**:
| R级 | 类型 | 自动落地 | 人工审核 |
|-----|------|---------|---------|
| R0 | knowledge_base_update（评分参数） | ✅ G3 自动 | — |
| R1 | martingale_param_update / skill_improvement_plan | ✅ G3 自动 | — |
| R2 | trigger_prompt_patch / gate_threshold_update | ❌ | ✅ 必须 |
| R3 | skill_replacement | ❌ | ✅ 最高优先级 |

**宪法 H009 约束**: trigger_prompt_patch 和 gate_threshold_update (R2) 即使 G2 合规通过，禁止 G3 自动落地，须人工审核后手动修改 TRIGGER_PROMPTS.md。

---

## 五、输出文件

写入 `sessions/{latest_session}/review/weekly-proposals.json`:

```json
{
  "generated_at": "2026-05-26T06:30:00+08:00",
  "source_lessons": "review/weekly-lessons.json",
  "proposals": [ ... ]
}
```

---

*最后更新: 2026-05-27 v1.3 — GAP-D2 fix: 新增 R级别分类、skill_replacement/skill_improvement_plan 类型、pending_compliance_check 状态、G2/G3/G4 完整提案生命周期*
