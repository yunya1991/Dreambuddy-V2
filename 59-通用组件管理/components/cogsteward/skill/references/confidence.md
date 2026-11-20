# confidence 计算规范

> **状态**: 已实现（M2 `cm route`），契约 v0.5
> **对应 SPEC**: §5.5.1 / §5.5.2 / V13
> **可调来源**: 工作区 `.cm/config.yaml` 的 `weight_*` 键；默认值来自 `scripts/modes/*.yaml`

## 1. 公式

```
confidence = 0.35·evidence + 0.30·consistency + 0.20·history + 0.15·(1 − conflict)
```

权重仅为默认值，必须写入模式配置；任何路由记录都必须落盘 `confidence_parts`，缺失即视为不可审计，不得进入 `apply`。

## 2. 分量取值

| 分量 | 取值规则 |
|---|---|
| `evidence` | 有文件 / 执行记录 = 1.0；仅用户确认 = 0.6；无证据 = 0.3 |
| `consistency` | 判定树单一命中 = 1.0；多命中但主载体明确（有 attachments 支撑）= 0.8；多命中且主载体未定 = 0.5；无命中仅默认 = 0.2 |
| `history` | `min(executions / 5, 1.0)`，`executions` 只统计近 90 天同指纹、且 `source ∈ {record, mark_done}` |
| `conflict` | **仅**表示候选互斥且未决（`alternatives` 非空且接近）= 0.5；attachments 本身不扣分；否则 0 |

## 3. 阈值

| 模式 | high | low |
|---|---|---|
| Dev | 0.80 | 0.50 |
| Office | 0.80 | 0.55 |

分档动作：

| 区间 | 动作 |
|---|---|
| `confidence ≥ high` 且无需确认且准入通过 | `plan` 输出 patch；`apply` 才落盘（先备份） |
| `low ≤ confidence < high`，或 `requires_user_confirm=true` | 输出建议，`next_action=ask_user` |
| `confidence < low` | 不写入，仅返回 `alternatives` |
| 准入含 `unknown` | 写 `pending`，不进入检索 |

## 4. 公式 → 阈值联调表

`high = 0.80`、执行次数指同指纹 `executions`：

| 场景 | evidence | consistency | conflict | 第 2 次 | 第 3 次 | 第 5 次 | 何时达 high |
|---|---|---|---|---|---|---|---|
| 单一命中 | 1.0 | 1.0 | 0 | 0.88 | 0.92 | 1.00 | 第 2 次 |
| 多归属、主载体明确 | 1.0 | 0.8 | 0 | 0.82 | 0.86 | 0.94 | 第 2 次 |
| 多归属、主载体未定 | 1.0 | 0.5 | 0 | 0.67 | 0.71 | 0.79 | 不自动达 high（转确认） |
| 候选互斥未决 | 1.0 | 0.5 | 0.5 | 0.595 | 0.635 | 0.715 | 不自动达 high（转确认） |

结论：合法的 D1 场景（单命中 / 多归属明确）在第 2 次执行即可达 `high`；未定场景永远不自动执行。

## 5. 复算要求

- 每条路由必须同时输出 `confidence` 与 `confidence_parts`，四个分量缺一不可
- 复算脚本必须能从 `evidence` / `executions` / `conflict` 重放出同一数值（允许 ±0.001 浮点误差）
- 修改权重后必须重跑 V13 校准，不得只改公式不重算
- 禁止在 `reasons` 中出现无数据支撑的「已重复 N 次」

## 6. 校准验收（V13）

按 `< low / low–high / ≥ high` 三档统计实际精确率，要求：

1. 单调递增；且
2. 高分组精确率 ≥ 0.90；或整体 ECE ≤ 0.15

未通过时只能保持 `plan`，不得对任何工作区开启 `apply`。

## 7. 示例

一次多归属、主载体明确的路由，近 90 天同指纹执行 3 次：

```
evidence   = 1.0   （有文件证据）
consistency= 0.8   （技能命中 + 文档从属）
history    = 0.6   （3 / 5）
conflict   = 0     （无互斥候选）

confidence = 0.35×1.0 + 0.30×0.8 + 0.20×0.6 + 0.15×1.0
           = 0.35 + 0.24 + 0.12 + 0.15 = 0.86
```

0.86 ≥ 0.80，且 `requires_user_confirm=false`、准入通过 → `plan` 输出 patch 摘要。
