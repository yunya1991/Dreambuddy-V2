# 6-TRADING 飞书群组 Chat ID 清单

> 最后验证: 2026-06-03

## 群组列表

| 群名 | Chat ID | 用途 |
|------|---------|------|
| Trading-Research | `oc_36c575b6f39a8df3dd75057a96685a21` | Screen1 周线多角色研究 |
| Trading-Desk | `oc_36c8543cea823b7546fcaad55d111f9f` | Screen2/Screen3 入场执行 |
| Trading-Management | `oc_9cf9f141613b4e6a0f34651843cf8b9b` | 总调度 / home_channel |
| Trading-Review | `oc_8868a5c84f3d8427afa9ed1a9ad7fb76` | Process D 复盘 |
| Trading-RiskControl | `oc_20fcedf0c35035568ea8fa947380f75d` | Gate-C / A9 风控 |

## DM

| 名称 | Chat ID |
|------|---------|
| DM-云涯Hermes | `oc_0b8badf8770b13c9359145a939a3eb8c` |

## 快速恢复

当 `channel_directory.json` 被 Gateway 重建后丢失群组时，复制以下 JSON 写入 `platforms.feishu` 数组：

```json
{"id": "oc_36c575b6f39a8df3dd75057a96685a21", "name": "Trading-Research", "type": "group", "thread_id": null},
{"id": "oc_36c8543cea823b7546fcaad55d111f9f", "name": "Trading-Desk", "type": "group", "thread_id": null},
{"id": "oc_9cf9f141613b4e6a0f34651843cf8b9b", "name": "Trading-Management", "type": "group", "thread_id": null},
{"id": "oc_8868a5c84f3d8427afa9ed1a9ad7fb76", "name": "Trading-Review", "type": "group", "thread_id": null},
{"id": "oc_20fcedf0c35035568ea8fa947380f75d", "name": "Trading-RiskControl", "type": "group", "thread_id": null}
```

同时检查 `config.yaml` 中 `group_rules` 是否包含以上 5 个 chat_id（Phase 3.5 一致性检查）。
