# Group Poller v2 架构

## 问题背景

飞书 App 未发布时群聊 WebSocket 事件不推送，需要 REST API 轮询兜底。
即使 App 已发布，群聊消息投递也可能不稳定，poller 作为双通道冗余。

## v2 链路

```
用户 @云涯Hermes 在群里
       │
       ▼ (12s 间隔 REST API 轮询)
group_poller.py
       │ 写入 pending_group_mentions.jsonl
       │ 发送 👀 ack 到群
       ▼
GroupMentionProcessor-60s cron (每分钟)
       │ 读 pending → Agent 处理
       │ send_message / REST API 回复到群
       ▼
群内收到 Agent 回复
```

## Poller 脚本

路径: `C:\tmp\group_poller.py`（Windows）/ `/home/luke/tmp/group_poller.py`（Linux）

功能:
- 每 12 秒轮询 5 个交易群的最新消息
- 检测 @mention（BOT_OPEN_ID: `ou_bcf92b6057e502054ca32bcd8ebf6570`）
- 写入 `pending_group_mentions.jsonl`（不直接处理）
- 发送 ack 告知用户已收到

## Cron Job 配置

```json
{
  "name": "GroupMentionProcessor-60s",
  "schedule": "* * * * *",
  "deliver": "local",
  "workdir": "C:\\tmp"
}
```

Prompt 中需包含 REST API 回退逻辑（CLI 模式下 `send_message` 工具可能不可用）。

## Pending 文件格式

```json
{"ts": "2026-06-03T15:43:03", "group_name": "Trading-RiskControl", "chat_id": "oc_20fced...", "sender": "ou_a7862e...", "text": "@_user_1 查下比特币今天价格", "msg_id": "om_x100b6e...", "status": "pending"}
```

status: `pending` → Agent 处理后 → `processed`

## 启动方式

Windows:
```python
import subprocess, os
python_path = r"C:\Users\luke.zhang\AppData\Local\Programs\Python\Python312\python.exe"
proc = subprocess.Popen([python_path, r"C:\tmp\group_poller.py"], env={"HOME": os.path.expanduser("~")}, creationflags=subprocess.CREATE_NO_WINDOW)
```

Linux (systemd):
```
[Service]
ExecStart=/usr/bin/python3 /home/luke/tmp/group_poller.py
Restart=always
```

## 去重

Poller 使用 `seen_ids` 集合（持久化到 `feishu_poller_state.json`）防止重复处理。
超过 500 条自动截断。
