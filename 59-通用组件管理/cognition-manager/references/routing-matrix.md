# 路由矩阵

## 判定树

```
新信息进入
├─ D1 可复用性：是否包含可重复执行的流程？
│   ├─ 是 且 历史同指纹 executions ≥ 2 ──▶ primary=skill
│   ├─ 是 且 次数不足 / 未接入执行记录 ──▶ 候选 skill，requires_user_confirm=true
│   └─ 否 → 继续
├─ D2 稳定性：是否描述工作区的稳定事实？
│   ├─ 是 ──▶ primary=doc
│   └─ 否 → 继续
├─ D3 经验性：是否是取舍 / 坑 / 结论？
│   ├─ 是 ──▶ primary=memory（须过准入四问）
│   │        └─ 准入结果 unknown → state=pending，不写入检索
│   └─ 否 → 继续
└─ 默认 ──▶ primary=session（TTL：Dev 7 天 / Office 14 天）
```

重叠处理：按「可复用性 > 稳定性 > 经验性」定 `primary`，其余命中写入 `attachments[]` 并保留理由；不允许因选定主载体而丢弃其他归属。

## 两个易混概念

- `attachments`：**同时成立**的归属（清单既是技能又是文档）
- `alternatives`：**互相竞争**的候选（0.82 判技能、0.61 判文档，二选一未定）

## 关系与物化

| 字段 | 枚举 |
|---|---|
| `edge` | `references / implements / documented_by / derived_from / supersedes` |
| `materialize` | `none`（只登记）/ `stub`（标题+指针）/ `full`（生成正文） |

默认：Dev `stub`，Office `none`；条数上限 Dev 3 条、Office 0 条。

## confidence

```
confidence = 0.35·evidence + 0.30·consistency + 0.20·history + 0.15·(1 − conflict)
```

| 分量 | 规则 |
|---|---|
| `evidence` | 有文件 / 执行记录 = 1.0；仅用户确认 = 0.6；无证据 = 0.3 |
| `consistency` | 单一命中 = 1.0；多命中但主载体明确 = 0.8；多命中未定 = 0.5；仅默认 = 0.2 |
| `history` | `min(executions / 5, 1.0)` |
| `conflict` | 仅候选互斥未决 = 0.5；attachments 不扣分；否则 0 |

阈值：两版 `high = 0.80`；`low` Dev 0.50 / Office 0.55。

- `confidence ≥ high` 且无需确认且准入通过 → `plan` 输出 patch，`apply` 才落盘
- 中间区间或需确认 → `next_action = ask_user`
- 低于 `low` → 不写入，仅返回 `alternatives`
- 准入含 `unknown` → 写 `pending`，不进入检索

## M2 现状

`cm route` 已实现判定树、attachments / alternatives、confidence、patch 与 plan/apply 决策；默认 `plan`，`apply` 需 `cm config apply=on` 且单次调用 `--apply`。写入前快照到 `.cm/backup/<run_id>/`，`cm rollback` 逆序恢复。
