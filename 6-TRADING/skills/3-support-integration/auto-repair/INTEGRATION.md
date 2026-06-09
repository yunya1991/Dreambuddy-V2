# auto-repair 集成规范 (Governance G3 — 提案落地 + 账户隔离)

> **原始 SKILL**: dream-multiskill-v2/skills/3-SUPPORT/auto-repair/SKILL.md v2.1.0
> **集成层级**: Governance（Process D 提案落地 + 系统健康守卫）
> **触发时机**: ① Process D Step 4.5 合规审查通过后 ② 每 72 小时独立健康检查

---

## 一、职责

1. **提案落地执行**：将 ai-trading-compliance 审查通过（R0/R1）的提案写回 SKILL 文件和 memory 文件
2. **账户隔离监控**：确保 6-TRADING 不混淆 OKX 实盘（`A5` profile）和模拟盘（`dreamdemo` profile）
3. **72 小时健康检查**：检查提案积压、账户状态、session 归档完整性

---

## 二、触发时机

| 触发 | 时机 | 触发方式 |
|------|------|---------|
| 提案落地 | Process D Step 4.5（合规审查完成后）| Process D 流程内调用 |
| 健康检查 | 每 72 小时独立运行 | 另设 CronCreate 任务（非四个主任务） |
| 手动触发 | 人工干预时 | 直接调用 |

---

## 三、提案落地规则（6-TRADING 版）

### 3.1 提案扫描路径

```
sessions/*/review/weekly-proposals.json
  → status=pending_review + compliance_receipt.decision=pass
  → 按 change_type 分类落地
```

### 3.2 落地决策矩阵

| 提案类型 | R 级 | 合规通过后 | 落地目标文件 |
|---------|------|----------|------------|
| `martingale_param_update` | R1 | ✅ 自动落地 | `TRIGGER_PROMPTS.md` 的 Screen 2 参数段（`<!-- MARTINGALE_PARAMS_START -->` 至 `<!-- MARTINGALE_PARAMS_END -->` 之间的文本）|
| `knowledge_base_update` | R0 | ✅ 自动落地 | `knowledge/` 对应文件 |
| `trigger_prompt_patch` | R2 | ⏸️ 等待人工 | 标注 `pending_human_review`，通知 dream-operation-director |
| `gate_threshold_update` | R2 | ⏸️ 等待人工 | 同上 |
| `skill_replacement` | R3 | ❌ 禁止自动 | 写入 `rejected_auto_land` 列表 |

### 3.3 落地动作清单

| 动作 | 说明 | 目标 |
|------|------|------|
| 更新触发提示词参数 | 仅限 R1 参数调整段（定位 `<!-- MARTINGALE_PARAMS_START -->` / `<!-- MARTINGALE_PARAMS_END -->` 标记，只替换标记内的数值，不修改标记外文本）| `6-TRADING/docs/TRIGGER_PROMPTS.md` |
| 更新知识库 | R0 历史数据 / 规律更新 | `6-TRADING/knowledge/` |
| 标注提案状态 | 所有提案执行后更新状态 | `weekly-proposals.json` status 字段 |
| 写落地报告 | 记录本次落地结果 | `sessions/{id}/governance/auto-repair-report.json` |

---

## 四、账户隔离监控（6-TRADING 版）

### 4.1 监控配置

```yaml
# 6-TRADING 账户隔离规则
monitored_accounts:
  live:
    profile: A5              # OKX 实盘
    status: disabled         # 默认禁用，仅人工确认后启用
    note: "Gate C PASS + 人工确认才可启用"
  demo:
    profile: dreamdemo       # OKX 模拟盘
    status: active           # 默认活跃
    note: "日常运行账户"
```

### 4.2 混淆风险检测

扫描以下文件中是否同时出现实盘/模拟盘标记：
- `sessions/*/team-b/execution-log.md`
- `sessions/*/team-b/episode.json` 的 `data_sources` 字段
- `memory/project_trading_session_state.md` 的 `current_account` 字段

发现混淆风险 → 立即暂停 Team B → 写入 `governance/account-isolation-alert.json`

---

## 五、72 小时健康检查项（6-TRADING 版）

| 检查项 | 优先级 | 通过标准 |
|-------|--------|---------|
| 账户隔离 | P0 | dreamdemo 为唯一活跃账户（实盘启用需人工） |
| 提案积压 | P0 | `weekly-proposals.json` 中无超过 14 天的未处理提案 |
| Session 归档完整性 | P1 | 每个 session 有 C4 归档标记 |
| Tavily 预算状态 | P1 | dream-cost-control 报告无 P1/P0 告警 |
| SKILL 注册表一致性 | P2 | SKILL_REGISTRY.md 版本与实际 INTEGRATION.md 数量一致 |

---

## 六、输出规范

写入 `sessions/{latest_session}/governance/auto-repair-report.json`:

```json
{
  "run_ts": "2026-05-27T06:00:00+08:00",
  "trigger": "process_d_step4.5 | health_check_72h",
  "account_isolation": {
    "status": "OK | WARNING | CRITICAL",
    "active_account": "dreamdemo",
    "mixed_reference_found": false
  },
  "proposals_landed": [
    {"proposal_id": "...", "type": "martingale_param_update", "status": "landed", "target_file": "TRIGGER_PROMPTS.md"}
  ],
  "proposals_pending_human": [
    {"proposal_id": "...", "type": "trigger_prompt_patch", "reason": "R2 requires human approval"}
  ],
  "proposals_rejected": [],
  "health_checks": {
    "session_archive_complete": true,
    "tavily_budget_ok": true,
    "skill_registry_consistent": true
  }
}
```

---

## 七、与其他 SKILL 的接口

| 接口 | 方向 | 说明 |
|------|------|------|
| ai-trading-compliance → auto-repair | 输入 | 合规回执决定落地权限 |
| auto-repair → TRIGGER_PROMPTS.md | 输出 | R1 提案自动更新参数段 |
| auto-repair → dream-operation-director | 通知 | R2 提案路由人工审批 |
| auto-repair → project_trading_session_state.md | 更新 | 落地完成后更新 pending_proposals 计数 |

---

*最后更新: 2026-05-27 v1.1 — GAP-TD2 fix: 新增 MARTINGALE_PARAMS_START/END 标记解析规范，确保 G3 精准落地*
