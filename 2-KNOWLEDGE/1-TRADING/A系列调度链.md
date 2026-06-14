# A 系列调度链 — Cron 任务概览

> A1–A9 任务链：深度调研 → 战略解析 → 战略制定 → 战术验证 → 执行 → 监控 → 离场 + 治理。
> 源：a-series-intraday-architecture, Cron-调度

## 调度概览

| 环节 | 阶段 | Cron 排程 | 模型 | Skill 绑定 |
|:---:|:---|:---|:---|:---|
| A1 | 深度调研 | 01:00 daily | deepseek-v4-pro | dream-strategy-research |
| A2 | 战略解析 | 02:00 daily | deepseek-v4-pro | dream-strategy-parser |
| A3 | 战略制定 | 03:00 daily | deepseek-v4-pro | dream-strategy-designer |
| A4 | 战术验证 | 每240m | deepseek-v4-flash | dream-tactical-validator |
| A5 | 战术执行 | 每480m | deepseek-v4-flash | dream-tactical-executor |
| A6 | 情报监控 | 每4h | (default) | dream-intelligence-monitor |
| A8 | 治理审查 | 14:00 daily | deepseek-v4-pro | A8-theory-practice-verification |
| A9 | 离场决策 | 每4h（A6动态启停） | deepseek-v4-pro | dream-exit-skill-v2 |

## 状态机流转

```
A1 → A2 → A3 → A4 → A5 → A6(持仓监控) → A9(离场)
                   ↓ (失败回退)
              A3(STRATEGIZING)
```

## 注意

- **A7 无独立 cron** — A7-practice-theory 内嵌在 A4/A5 执行前的门禁检查中
- A6 产出 control_decision 供 scheduler 路由（含 A9 启停）
- 所有 A 系列 cron 均有 execution_loop 元数据管理
- A8 为 no_agent 脚本 + LLM 混合模式，调用 A8-theory-practice-verification + dream-contradiction-theory

_最后更新：2026-06-13 | 来源：知识库完善_
