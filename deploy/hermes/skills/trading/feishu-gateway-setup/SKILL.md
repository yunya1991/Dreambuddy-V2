---
name: feishu-gateway-setup
description: Feishu Bot 与 Hermes Gateway 的双向通信配置与排错。涵盖 App 创建、权限配置、事件订阅、发布流程、Gateway config.yaml、频道目录持久化、以及群聊/单聊消息收发调试。
category: trading
triggers:
  - "飞书通信"
  - "feishu bot"
  - "hermes gateway feishu"
  - "群聊不回复"
  - "收不到消息"
  - "事件订阅"
  - "channel directory"
  - "send_message"
---

# Feishu × Hermes Gateway 双向通信配置

## 概述

Hermes Agent 通过 Gateway 的 Feishu 平台适配器实现双向通信：
- **出站**：`send_message(target="feishu:群名", ...)` 或 REST API
- **入站**：WebSocket 长连接接收 `im.message.receive_v1` 事件

---

## 一、飞书 App 配置清单

### 1.1 必需权限（Developer Console → 权限管理）

| 权限 scope | 用途 | 
|-----------|------|
| `im:message:send_as_bot` | Bot 发送消息 |
| `im:message.p2p_msg:readonly` | 接收单聊消息 |
| `im:message.group_at_msg:readonly` | 接收群聊 @消息 |
| `im:message.group_at_msg.include_bot:readonly` | 接收其他 Bot 的 @消息 |
| `im:message:readonly` | 读取消息内容 |
| `im:chat:read` | 读取群信息 |
| `im:chat.members:bot_access` | 订阅 Bot 进出群事件 |

### 1.2 事件订阅（Developer Console → 事件与回调）

1. 订阅方式选 **「使用长连接接收事件」（WebSocket）**
2. 添加事件 → 以应用身份订阅 → 消息分类 → 勾选：
   - **接收消息 v2.0**（`im.message.receive_v1`）
   - 展开后确保勾选：单聊消息 + 群聊@消息 + 群聊全部消息（按需）

### 1.3 发布（关键！每次改权限/事件后必须重做）

```
https://open.feishu.cn/app/{app_id}/version
```
1. 创建版本 → 填版本号 → 保存 → **提交发布**
2. 管理员审批通过后生效
3. 不发布 = 事件订阅不工作（即使权限已添加）

---

## 二、Hermes config.yaml 配置

```yaml
platforms:
  feishu:
    enabled: true
    connection_mode: websocket
    domain: feishu
    home_channel:
      platform: feishu
      chat_id: "oc_xxx"       # 主频道
      name: "Trading-Desk"    # ⚠️ name 字段必须存在，否则 Gateway 解析崩溃
    group_rules:
      "oc_chat_id_1":
        policy: open
        require_mention: false
      # ... 所有需要 Bot 响应的群
```

### ⚠️ 常见配置坑

- **`home_channel.name` 缺失** → Gateway 启动时 `TypeError: string indices must be integers`，平台不注册
- **group_rules 不完整** → Bot 在某些群不会响应
- **require_mention 默认 true** → 未在 group_rules 中配置的群需要 @ 才能触发

---

## 三、频道目录持久化

### 问题
Gateway 每次重启从 `sessions.json` 重建频道目录。没有群聊消息记录 → 频道目录只有 DM → `send_message(action='list')` 找不到群。

### 解决方案
参考 `references/channel-guard.py` —— 守护脚本每 30s 检查 `channel_directory.json`，自动补全已知交易群。

部署方式：
```bash
python ~/.hermes/scripts/channel_guard.py &
```

### 手动修复
```python
import json
channel_dir = "~/.hermes/channel_directory.json"
# 写入已知群组到 data["platforms"]["feishu"]
```

---

## 四、调试方法论

### 优先级排查顺序

1. **REST API 发消息测试出站**：`POST /im/v1/messages` → `code=0` 说明出站正常
2. **REST API 读消息确认入站内容**：`GET /im/v1/messages?container_id_type=chat&container_id=oc_xxx` → 确认用户 @ 了正确的 Bot
3. **Gateway 日志查事件**：`grep "Received raw message" gateway.log` → 零事件 = 订阅未生效
4. **App 发布状态**：`GET /application/v6/applications/{app_id}` → `status=1` = 未发布
5. **事件是否添加**：Developer Console → 事件与回调 → 已添加事件列表

### 单聊通 / 群聊不通

经典症状 = **事件订阅中添加了"接收消息"但未展开勾选群聊子项**，或**添加后未重新发布**。

---

## 五、Gateway 重启后的标准操作

**⚠️ 重要**：Hermes 的 bash 终端无法可靠启动 Windows 版 Gateway（用户名含 `.` 时路径解析失败；bash 环境缺少 Windows .env 凭证）。必须通过 **execute_code + Python subprocess** 重启，详见 `feishu-hermes-debug` Phase 5。

```python
# 在 execute_code 中执行（不是 terminal/bash）:
import subprocess, os
hermes = r"C:\Users\<user>\AppData\Local\Programs\Python\Python312\Scripts\hermes.exe"
env = os.environ.copy(); env["HOME"] = os.path.expanduser("~")
subprocess.Popen([hermes, "gateway", "run", "--replace"], env=env)
```

重启后验证（同样用 execute_code）：
```python
# 1. 等待 Feishu 连接确认（检查 gateway.log）
# 2. 确认 "✓ feishu connected" 和 "Gateway running with 1 platform(s)"
# 3. 确认 Channel directory built: N target(s) — N 应包含所有群

重启后还需：(4) 重启 group_poller.py（独立进程随 Gateway 被杀），(5) 检查 cron jobs deliver（可能重置为 local）。完整清单见 feishu-hermes-debug Phase 6。
```

### 5.1 重启后完整恢复清单（必做）

Gateway 重启后有三个组件静默丢失。完整检查+修复脚本见 `feishu-hermes-debug` Phase 6：

| 序号 | 检查项 | 症状 | 修复 |
|------|--------|------|------|
| 1 | 频道目录群组 | `channel_directory.json` 只剩 DM | 手动写回 5 个群组 |
| 2 | `group_poller.py` | `feishu_poller_state.json` 不再更新 | subprocess 重启 poller |
| 3 | Cron deliver | 所有 job deliver=`local` | 批量更新为 origin+5群 |
| 4 | GroupMentionProcessor | 群聊 @mention 无 Agent 回复 | 确认 cron 存在且 enabled |

### 5.2 群聊消息双通道架构

```
主通道：WebSocket 事件推送（App 已发布后）
兜底通道：group_poller.py v2 (REST API 12s) → pending file → Cron(60s) → Agent 回复
```

- Poller: `C:\tmp\group_poller.py` (v2, 写入 `pending_group_mentions.jsonl`)
- Cron: `GroupMentionProcessor-60s` (每分钟 Agent 处理并回复群)
- 架构文档: `feishu-hermes-debug` → `references/group-poller.md`

---

## 六、飞书平台内置服务（不需要手动"集成"）

以下飞书功能由平台自动提供——调用 API 后飞书系统 Bot 自动推送通知，**不需要手动配置、加群或添加 scope**：

| 服务 | 触发方式 | 自动推送 |
|------|---------|---------|
| 审批 | `lark-cli approval instances` 创建实例 | "有新审批待处理"通知 |
| 任务 | `lark-cli task +create` 创建任务 | 任务创建通知 / 到期提醒 |
| OKR | `lark-cli okr +progress-create` 更新进度 | KR 进度变更 / 周期结束提醒 |
| 多维表格自动化 | Console 配置 Workflow 规则 | 记录变更→自动发消息 |

**⚠️ 常见误判**：以为这些需要像 `im:message` scope 一样去"集成"——实际上和 `send_message` 一样是飞书平台 API，调了就生效。做系统评估时不要把它们标记为"未集成"。

### 6.1 任务管理：lark-cli task 替代手写 REST

`feishu_notify.py` 的 `task_create`/`task_complete` 已迁移为 lark-cli：

```bash
lark-cli task +create --summary "标题" --due "+7d"
lark-cli task +complete --task-id "<guid>"
```

收益：不依赖 `get_token()`、日期用自然语义、错误处理统一。

---

## 参考文件

- `references/feishu-debug-transcript.md` — 本次会话的完整排错过程
- `scripts/channel_guard.py` — 频道目录守护脚本
- `references/cloud-deploy.md` — 腾讯云 Lighthouse 部署方案（systemd 服务 + deploy 脚本）

## 六、Hermes Dashboard Web UI

Dashboard 是独立服务，不属于 Gateway。端口 9119。

```bash
# 诊断
hermes dashboard --status

# 启动（首次需 npm build 30-60s）
hermes dashboard --port 9119 --no-open

# 已 build 过可用 --skip-build 秒起
hermes dashboard --port 9119 --no-open --skip-build
```

Windows 上 bash terminal 无法启动 hermes.exe，需用 execute_code + subprocess。
云上部署用 systemd service，Dashboard 默认只绑 127.0.0.1。

## 七、平台内置机器人（无需手动集成）

以下飞书功能是**平台内置**的，API 调用后自动推送通知，不需要额外配置：

| 机器人 | 触发方式 | 说明 |
|--------|---------|------|
| 审批机器人 | 创建审批实例 | 自动推送"有新审批待处理" |
| 任务机器人 | task_create | 自动在消息里推送任务提醒 |
| OKR 机器人 | 更新 KR 进度 | 自动推送进度变更通知 |

**不需要**把机器人拉进群、不需要配置 webhook——飞书系统自动处理。
- `deploy/` — 腾讯云一键部署 (GitHub: `yunya1991/Dreambuddy-V2/deploy/`)

## 七、腾讯云部署

GitHub `deploy/` 目录包含完整部署方案：

```bash
git clone https://github.com/yunya1991/Dreambuddy-V2.git /home/luke/tmp
# scp .env to /home/luke/.hermes/.env
cd /home/luke/tmp/deploy && sudo bash deploy.sh
```

systemd 守护：`hermes-gateway` + `group-poller` + `hermes-dashboard`，crash 10-15s 自动重启。channel_directory 预写入 5 个交易群。
