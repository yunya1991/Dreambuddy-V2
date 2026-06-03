---
name: hermes-feishu-bot-debug
description: 诊断和修复 Hermes Bot 飞书双向通信问题。涵盖 Gateway 配置、WebSocket 事件订阅、Channel Directory 管理、App 发布流程。
triggers:
  - "飞书通信"
  - "bot 收不到消息"
  - "send_message 无目标"
  - "群聊不回复"
  - "单聊可以群聊不行"
  - "事件订阅"
  - "im.message.receive_v1"
  - "WebSocket 事件"
---

# Hermes Bot 飞书双向通信调试指南

## 诊断优先级（严格按此顺序）

### 第一层：Gateway 连通性

```bash
# 检查 Gateway 日志中的 Feishu 连接状态
grep -i "feishu" ~/.hermes/logs/gateway.log | tail -20
```

**正常输出应有**：
```
✓ feishu connected
Gateway running with 1 platform(s)
```

**常见故障**：
| 症状 | 原因 | 修复 |
|------|------|------|
| `No messaging platforms enabled` | config.yaml 解析崩溃 | 检查 `platforms.feishu.home_channel` 格式，确保是 dict 不是 string |
| Gateway 启动后无 Feishu 连接日志 | 进程启动失败 | `hermes gateway stop && hermes gateway restart` |

### 第二层：Channel Directory（send_message 目标列表）

`send_message(action='list')` 返回空时：

```bash
# 直接检查 channel_directory.json
cat ~/.hermes/channel_directory.json | python -m json.tool
```

如果 `platforms.feishu` 为空数组 `[]`，手动填充已知群：
```json
{
  "platforms": {
    "feishu": [
      {"id": "oc_xxx", "name": "群名称", "type": "group"}
    ]
  }
}
```

> 注意：Gateway 重启会清空 channel_directory.json，需要重新填充。

**备选方案**：即使 `send_message(action='list')` 为空，`send_message(action='send')` 使用显式 chat_id 仍然可用。

### 第三层：出站消息验证

```python
import requests, json
# 使用 Hermes Bot 的 app_id/app_secret
token = requests.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    json={"app_id": APP_ID, "app_secret": APP_SECRET}).json()["tenant_access_token"]

requests.post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
    headers={"Authorization": f"Bearer {token}"},
    json={"receive_id": "oc_xxx", "msg_type": "text",
          "content": json.dumps({"text": "test"})})
```

### 第四层：入站消息（最关键）

Gateway 日志中搜索入站消息：
```bash
grep "Received raw message" ~/.hermes/logs/gateway.log
grep "Inbound dm message\|Inbound group message" ~/.hermes/logs/gateway.log
```

**诊断矩阵**：

| 单聊收得到 | 群聊收得到 | 根因 | 修复 |
|:---:|:---:|---|---|
| ✅ | ❌ | 事件只订阅了单聊，没勾群聊 | 飞书后台「事件与回调」→ 展开「接收消息」→ 勾选群聊选项 |
| ❌ | ❌ | App 未发布或事件未添加 | 见下方「事件订阅完整流程」 |
| ✅ | ✅ | 正常 | — |

### 第五层：权限检查

```python
# 查看 App 当前所有权限
requests.get(f"https://open.feishu.cn/open-apis/application/v6/applications/{app_id}?lang=zh_cn",
    headers={"Authorization": f"Bearer {token}"})
```

群聊消息需要的权限（缺一不可）：
- `im:message.group_at_msg:readonly` — @机器人消息
- `im:message.group_msg` — 群内全部消息（敏感权限）
- `im:message.p2p_msg:readonly` — 单聊消息

## 事件订阅完整流程

### 第一步：飞书后台添加事件
```
https://open.feishu.cn/app/{APP_ID}/event
```
1. 确认订阅方式为「使用长连接接收事件」
2. 点击「添加事件」→ 消息分类 → **「接收消息」**
3. **展开事件**，确保三种消息类型全部勾选：
   - 单聊消息
   - 群聊@机器人消息
   - 群聊全部消息

### 第二步：创建版本并发布
```
https://open.feishu.cn/app/{APP_ID}/version
```
1. 创建版本 → 填写版本号 → 可用范围选「全体成员」
2. 保存 → 提交发布

**飞书官方文档原文**：
> "即使相关权限已开通，仍需发布应用才能使配置生效"

### 第三步：重启 Gateway
```bash
hermes gateway stop && sleep 3 && hermes gateway restart
```

## 调试技巧

### 查看群聊中的消息（验证 @mention 是否正确）
```python
r = requests.get(
    f"https://open.feishu.cn/open-apis/im/v1/messages?container_id_type=chat&container_id={chat_id}&page_size=5&sort_type=ByCreateTimeDesc",
    headers=headers)
# 检查返回的 mentions 字段，确认 @mention 的 open_id 是否匹配 Bot
```

### 验证 Bot 的 open_id
```python
r = requests.get("https://open.feishu.cn/open-apis/bot/v3/info", headers=headers)
# 返回 bot.open_id，用户 @mention 时匹配此 ID
```

## 已知陷阱

1. **app status=1 不等于已发布**：API 返回 `status: 1` 但仍可能是开发模式。发布后 `app_versions` 中版本的 `audit_status` 才会变化。
2. **Gateway 重启清空 channel_directory.json**：需要每次重启后重新填充。
3. **群聊消息勾选项可能被灰掉**：先确认「事件订阅方式」已选择 WebSocket，且对应权限已添加。
4. **不要用 API 管理事件订阅**：飞书不提供事件订阅的 REST API，必须在后台网页操作。
