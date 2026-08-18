# 6-TRADING Sessions 目录

每次研究/执行均在此目录创建独立会话文件夹，便于归档、回溯和质量检查。

## 命名规则

```
{YYYYMMDD}-{SYMBOL}-{TRIGGER}/
```

| 字段 | 说明 | 示例 |
|------|------|------|
| YYYYMMDD | 日期 | 20260526 |
| SYMBOL | 交易标的（去除连字符） | BTC |
| TRIGGER | 触发类型 | SCREEN1 / SCREEN2 / TEAMB / REVIEW |

示例：`20260526-BTC-SCREEN1/`

## 目录结构

```
sessions/
  _template/                    ← 模板（参考用，不做实际交易）
  {session-id}/
    meta.json                   ← 会话元数据 + 状态机
    team-a/
      screen1/                  ← Screen 1 周线分析输出
        weekly-direction.md
        strategy-type.json
        raw/                    ← A1/A2/A3 原始输出
      screen2/                  ← Screen 2 日线预设输出
        daily-presets.json
        martingale-grid.json
        order-plan.md
        raw/
    team-b/                     ← Team B 实时执行记录
      a7-gate.json
      a4-validation.json
      execution-log.md
      position-state.json
      a6-events.jsonl           ← append-only 监控事件流
      a9-exit.json
    gate-c/
      pretrade-check.json       ← Gate C 门禁结果
    review/
      a8-reflection.md          ← Process D 复盘
    session-summary.md          ← 最终摘要
```

## 状态机（meta.json status 字段）

```
created → team_a_running → team_a_complete
        → team_b_running → gate_c_check → executing
        → monitoring → closed
```

## 质量检查要点

每次 Screen 2 完成后，人工 review `team-a/screen2/order-plan.md`：
- [ ] 方向与 Screen 1 一致？
- [ ] 马丁阶梯间隔合理（基于 20 日波动率）？
- [ ] 三大预设完整（入场/加仓/TP-SL）？
- [ ] 四等份资金原则满足？
