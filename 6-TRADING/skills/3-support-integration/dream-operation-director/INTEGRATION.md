# dream-operation-director 集成规范 (Governance G4 — 跨团队升级路由)

> **原始 SKILL**: dream-multiskill-v2/skills/3-SUPPORT/dream-operation-director/SKILL.md v1.0.0
> **集成层级**: Governance（按需触发，不在常规执行链中）
> **触发时机**: 出现跨团队阻塞、Gate C 硬失败、提案需要人工审批时

---

## 一、职责

当 6-TRADING pipeline 出现无法自动解决的阻塞时，提供结构化的升级路径和跨团队协调，确保问题进入明确的人工处理流程，而不是在自动化中循环失败。

**定位**：纯升级路由，不参与正常执行流程。

---

## 二、6-TRADING 触发场景

| 触发条件 | 来源 | 升级路径 |
|---------|------|---------|
| Screen 1 `SCREEN1_BLOCKED`（Tavily 连续失败）| Team A Phase-0 | SOP-2 → 人工确认是否降级或延迟 |
| Team B `PARALLEL_INPUT_INCOMPLETE`（B3/B4/B5 任一失败）| Team B | SOP-2 → 人工确认哪个 SKILL 故障 |
| Gate C `BLOCK`（H001-H009 硬失败，原因不明）| B6 | SOP-2 → risk_owner 审查 |
| auto-repair 标注 `pending_human_review` 的 R2 提案 | Governance | SOP-2 → strategy_owner 审批 |
| `sleepwalk_alert=true` 且 Process D 未解决 | B9 / Project D | SOP-3 → 流程优化提案 |
| 账户隔离 `CRITICAL`（实盘/模拟盘混淆）| auto-repair | SOP-2 → 立即人工介入 |

---

## 三、6-TRADING 部门目录

| 部门 | 对应 SKILL | 职责 |
|------|-----------|------|
| Team A 研究 | dream-screen1-first / screen2 / A1-A7 / AC / IA / MS | 周线/日线研究预设 |
| Team B 执行 | dream-screen3-third / B2-B9 | 入场决策链 |
| Team C 监控 | C1 (A6) / C2 (A7) / C3 (A9) / C4 (artifact) | 持仓监控离场 |
| Process D 复盘 | D1 / D2 / D3 / DA / OE / CC / PR / RE | 每周复盘三级闭环 |
| Governance | dream-constitution / ai-trading-compliance / auto-repair / operation-director | 治理层 |
| Knowledge Base | dream-knowledge / master_profiles | 策略知识 |

---

## 四、SOP 映射（6-TRADING 版）

### SOP-2: 跨团队问题升级

当任何 SKILL 输出 `BLOCKED` / `FAIL` / `PARALLEL_INCOMPLETE` 时：

```
Step 1: 问题定性
  → 记录: 哪个 SKILL / 哪个 Session / 错误码 / 上下文
  → 判断影响范围: 仅当前 session? 还是系统性问题?

Step 2: 确定升级路径
  → Tavily 失败 → 检查 dream-cost-control 预算状态，等待次日重置
  → B3/B4/B5 并行失败 → 检查 SKILL 本身日志，人工排查
  → Gate C H001-H009 失败 → 读取 compliance-receipt.json 的 blockers 字段
  → R2 提案待批 → 通知 risk_owner / strategy_owner（写入 governance/pending-approvals.md）
  → 账户混淆 → 立即暂停所有 Team B 操作

Step 3: 写升级记录
  → 写入 sessions/{id}/governance/escalation-log.json
  → 格式: { "ts", "trigger", "skill_id", "issue", "tried", "escalated_to", "expected_resolution" }

Step 4: 跟进
  → 问题解决后更新 escalation-log.json 的 resolution 字段
  → 若是系统性问题 → 触发 Process D SOP-3 流程优化
```

### SOP-3: 流程优化建议（仅限梦游或系统性问题）

```
触发条件:
  → sleepwalk_alert=true 且 Process D 评估后未解决
  → 连续 2 周出现相同类型的升级事件

输出:
  → governance/operation-improvement.md（流程优化建议）
  → 传递给 D3 作为 trigger_prompt_patch 提案依据
```

---

## 五、R2 提案人工审批路由

当 ai-trading-compliance 输出 `decision=pass + change_type=R2` 时，operation-director 负责路由审批：

| 提案类型 | 审批角色 | 审批方式 |
|---------|---------|---------|
| `trigger_prompt_patch` | strategy_owner（用户）| 人工修改 TRIGGER_PROMPTS.md |
| `gate_threshold_update` | risk_owner（用户）| 人工修改 Gate C 阈值配置 |

路由记录写入 `sessions/{latest}/governance/pending-approvals.md`:

```markdown
## 待审批提案

### [R2] gate_threshold_update — 2026-05-27

- **提案内容**: Gate C 通过阈值从 70 降回 65（red_team_flag 场景）
- **合规回执**: compliance-receipt-xxx.json — decision: pass
- **审批角色**: risk_owner
- **依据**: DA 量化报告显示连续 SKIP 率 72%，超过历史基准 50%
- **状态**: ⏳ 待审批
```

---

## 六、与其他 SKILL 的接口

| 接口 | 方向 | 说明 |
|------|------|------|
| auto-repair → operation-director | 触发 | R2 提案路由审批 |
| 任意 SKIP/BLOCK → operation-director | 触发 | 无法自动解决的阻塞升级 |
| operation-director → D3 | 输出 | SOP-3 优化建议转为正式提案 |
| operation-director → governance/escalation-log | 写入 | 升级记录存档 |

---

*最后更新: 2026-05-27 v1.0 | 集成 dream-operation-director v1.0 → Governance G4*
