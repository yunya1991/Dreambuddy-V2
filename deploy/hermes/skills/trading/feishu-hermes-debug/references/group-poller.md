# Group Poller v2 架构

## 链路

```
群聊 @云涯Hermes
    │
    ▼ (REST API 轮询, 12s 间隔)
group_poller.py
    │ 检测 @mention → 写入 pending_group_mentions.jsonl
    │ 发送 👀 ack 到群
    ▼
GroupMentionProcessor-60s (cron, 每分钟)
    │ 读 pending file → Agent 处理
    │ send_message 回复到群 (REST API 兜底)
    ▼
群内收到 Agent 回复
```

## 关键文件

| 文件 | 路径 | 作用 |
|------|------|------|
| Poller 脚本 | `C:\tmp\group_poller.py` | 主轮询进程 |
| State | `~/.hermes/feishu_poller_state.json` | seen_ids (防重复) |
| Pending | `~/.hermes/pending_group_mentions.jsonl` | 待处理 @mention |
| Inbox (旧) | `~/.hermes/feishu_inbox.jsonl` | v1 旧格式，不再写入 |

## Pending 文件格式

```json
{"ts": "2026-06-03T15:37:16", "group_name": "Trading-RiskControl", "chat_id": "oc_20fced...", "sender": "ou_a7862...", "text": "@_user_1 查询今天比特币价格", "msg_id": "om_x100b...", "status": "pending"}
```

状态流转: `pending` → `processed`（由 MentionProcessor cron 标记）

## 依赖

- `~/.hermes/.env` — FEISHU_APP_ID/SECRET
- 飞书 REST API: `im/v1/messages` (读), `auth/v3/tenant_access_token` (token)
- 需要 scope: `im:message:readonly`, `im:message:send_as_bot`

## 去重

seen_ids 最多保留 500 条，滚动淘汰。只基于 message_id 去重，不区分群组。
