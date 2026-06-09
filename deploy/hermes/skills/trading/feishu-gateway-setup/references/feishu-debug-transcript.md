# Feishu Hermes Gateway 排错实录 (2026-06-03)

## 时间线

### 阶段 1：Gateway 启动崩溃
- **症状**：`send_message(action='list')` → "No messaging platforms connected"
- **日志**：`gateway-exit-diag.log` → `TypeError: string indices must be integers, not 'str'` at `HomeChannel.from_dict`
- **根因**：`config.yaml` 中 `home_channel` 缺少 `name` 字段
- **修复**：Gateway 重启后自动恢复（代码有 `data.get("name", "Home")` 容错，旧版可能无）

### 阶段 2：频道目录为空
- **症状**：`send_message` 可用但 `action='list'` 显示 0 targets
- **根因**：`channel_directory.json` 中 feishu 列表为空；`sessions.json` 不存在
- **修复**：手动写入 5 个交易群到 `channel_directory.json`
- **发现**：`send_message(target="feishu:oc_xxx", ...)` 即使 list 为空也能发消息

### 阶段 3：入站消息不工作
- **症状**：Bot 能发消息但收不到任何入站事件
- **验证**：REST API `GET /im/v1/messages` 能读到群消息 → 权限 OK
- **根因 1**：App 未发布（`status=1`）
- **根因 2**：事件订阅未在 Developer Console 添加
- **修复**：添加权限 → 添加事件订阅 → 创建版本 → 提交发布

### 阶段 4：单聊通 / 群聊不通
- **症状**：DM 消息正常接收和回复，群聊 @ 消息零事件
- **验证**：REST API 确认用户正确 @了 Bot（`mentions: [{name: "云涯Hermes"}]`）
- **根因**：事件订阅中"接收消息"未展开勾选群聊子项，或添加后未重新发布
- **修复**：Developer Console 展开"接收消息"事件 → 勾选群聊@消息 → 创建新版本 → 发布

### 阶段 5：频道目录被覆盖
- **症状**：每次 Gateway 重启，手动添加的群消失
- **根因**：`build_channel_directory()` 从 `sessions.json` 重建，群聊无记录
- **修复**：部署守护脚本 `channel_guard.py`，每 30s 检查并补全

## 关键 API 验证命令

```python
# 出站测试
POST /open-apis/im/v1/messages?receive_id_type=chat_id
{"receive_id": "oc_xxx", "msg_type": "text", "content": "{\"text\":\"test\"}"}

# 入站验证 — 读群消息
GET /open-apis/im/v1/messages?container_id_type=chat&container_id=oc_xxx&page_size=5&sort_type=ByCreateTimeDesc

# App 状态
GET /open-apis/application/v6/applications/{app_id}?lang=zh_cn
# status=1 未发布, status=2 已发布

# Bot 信息
GET /open-apis/bot/v3/info
# activate_status=2 表示已激活
```

## 飞书控制台快捷链接

- 权限管理：`https://open.feishu.cn/app/{app_id}/auth`
- 事件订阅：`https://open.feishu.cn/app/{app_id}/event`
- 版本发布：`https://open.feishu.cn/app/{app_id}/version`
