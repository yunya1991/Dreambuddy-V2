# 会话与待定分拣

> 目标：把「过期会话」和「反复复核仍无结论的待定项」收干净，避免索引与体检被噪声拖累。
> 实现：`scripts/core/triage.py`；CLI `cm triage [--expire-sessions] [--drop-pending]`。

## 1. 默认行为（演练）

- 不修改任何状态，`dry_run=true`；
- 列出 `sessions.triaged_at IS NULL AND expires_at < now` 的过期会话（最多 20 条）；
- 列出 `pending.state='open'` 的待定项（最多 20 条），附 `review_count` 与等待小时数。

## 2. 状态迁移

| 开关 | 对象 | 动作 |
|---|---|---|
| `--expire-sessions` | 过期且未分拣的会话 | `triaged_at = now`（标记为已回收，不再重复统计） |
| `--drop-pending` | `review_count >= 3` 的待定项 | `state = 'dropped'` |
| `--drop-pending` | 其余 open 待定项 | `review_count += 1` |

- 两个开关都未给时不执行任何 `UPDATE`；
- 重复执行不会重复丢弃：已 `dropped` 的条目不再进入 `state='open'` 查询；
- 不启动后台守护进程，所有迁移都是前台一次性执行。

## 3. 判定口径

- 「过期」只以 `expires_at < now` 为准，不按创建时间推算；
- `review_count` 达到 3 表示已人工看过 3 次仍无结论，第 4 次分拣时丢弃；
- `sessions` 表不新增状态列：`triaged_at` 非空即代表「已处理（含过期回收）」，取舍见 TECHNICAL_DESIGN §10 D11。

## 4. 输出契约

```json
{
  "command": "triage",
  "dry_run": false,
  "session_ttl_days": 7,
  "sessions": {"expired": 3, "marked_expired": 3, "items": []},
  "pending": {
    "open": 5, "drop_threshold": 3, "dropped": 1, "incremented": 4,
    "dropped_refs": ["sha256:..."], "items": []
  },
  "notes": ["已回收 3 条过期会话", "丢弃 1 条、复核 4 条待定项"]
}
```

## 5. 边界

- 只处理本地 `.cm/index.db` 中的会话与待定项，不触碰工作区业务文件；
- 不做语义判断：是否仍为 `unknown` 由人类或后续版本决定，见 TECHNICAL_DESIGN §10 D12；
- 丢弃 = 移出待办队列，不物理删除记录。
