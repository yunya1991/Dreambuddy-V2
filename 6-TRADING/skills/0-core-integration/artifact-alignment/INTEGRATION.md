# artifact-alignment-manager 集成规范 (Team C — C4)

> **原始 SKILL**: dream-multiskill-v2/skills/0-CORE/artifact-alignment-manager/SKILL.md v7.3
> **集成团队**: Team C — 日内监控离场
> **触发时机**: Screen 1/2/3 各阶段完成后 + A9 离场后

---

## 一、职责

将 6-TRADING 的 session 文件（meta.json、daily-presets.json、a7-gate.json 等）转换为带标准 frontmatter 的产物，通过双渠道投递：
1. **主渠道**: `sessions/{session_id}/` 子目录（本仓库）
2. **产物中心**: `6-TRADING/artifacts/{category}/`（待建立，Phase 2）

---

## 二、A-series frontmatter 映射表（6-TRADING 版本）

| 产物文件 | chain_phase | type | dept | 投递时机 |
|---------|------------|------|------|---------|
| team-a/screen1/weekly-direction.md | A3 | strategy_directive | team-a | Screen 1 完成后 |
| team-a/screen1/strategy-type.json | A3 | strategy_directive | team-a | Screen 1 完成后 |
| team-a/screen2/daily-presets.json | A3 | daily_preset | team-a | Screen 2 完成后 |
| team-a/screen2/martingale-grid.json | A3 | daily_preset | team-a | Screen 2 完成后 |
| team-a/screen2/order-plan.md | A3 | order_plan | team-a | Screen 2 完成后 |
| team-b/a7-gate.json | A7 | gate_result | gate-c | Team B A7 检查后 |
| team-b/episode.json | A5 | execution_log | team-b | A5 执行后（B9 写入）|
| team-b/execution-log.md | A5 | execution_log | team-b | A5 执行后 |
| gate-c/pretrade-check.json | A5 | gate_result | gate-c | Gate C 裁决后 |
| review/a8-reflection.json | A8 | retrospective | process-d | A8 完成后 |
| review/weekly-lessons.json | A8 | lesson_delta | process-d | D2 完成后 |
| review/weekly-proposals.json | A8 | proposal | process-d | D3 完成后 |
| meta.json | A3 | session_meta | system | 每次状态变更后 |

---

## 三、frontmatter 模板

每个产物文件应在 JSON 中包含 `_artifact` 字段，或在 Markdown 文件头部添加：

```yaml
---
chain_phase: A3
type: strategy_directive
dept: team-a
session_id: 20260526-BTC-SCREEN1-v2
symbol: BTC-USDT-SWAP
created_at: 2026-05-26T20:00:00+08:00
version: "1"
---
```

---

## 四、时间戳标准

所有时间戳使用 **北京时间 UTC+8**，格式: `YYYY-MM-DDTHH:MM:SS+08:00`

---

## 五、当前实现状态

- Phase 1（当前）: session 文件直接写入 `sessions/` 子目录，frontmatter 作为 JSON 字段嵌入
- Phase 2（代码化）: 建立 `6-TRADING/artifacts/` 产物中心，运行 `sync_artifact.py`

---

*最后更新: 2026-05-26*
