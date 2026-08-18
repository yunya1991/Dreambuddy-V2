# 云涯Hermes App 权限清单

> App ID: cli_aa95b2dee3b85bd1
> 查询时间: 2026-06-03
> 状态: 开发中 (status=1)，需发布后才能接收消息事件

## 消息类权限（全部已配置）

| Scope | 级别 | 说明 |
|-------|------|------|
| `im:message.group_at_msg:readonly` | L1 | 获取群组中用户@机器人消息 |
| `im:message.group_at_msg.include_bot:readonly` | L1 | 获取群组中其他机器人和用户@当前机器人的消息 |
| `im:message.group_msg` | L2 | 获取群组中所有消息（敏感权限） |
| `im:message.p2p_msg:readonly` | L1 | 读取用户发给机器人的单聊消息 |
| `im:message:readonly` | L1 | 获取单聊、群组消息 |
| `im:message:send_as_bot` | L1 | 以应用的身份发消息 |
| `im:message:send_multi_users` | L1 | 给多个用户批量发消息 |
| `im:message:send_sys_msg` | L2 | 发送特定模板系统消息 |
| `im:message:update` | L1 | 更新消息 |
| `im:message.pins:read` | L1 | 查看 Pin 消息 |
| `im:message.pins:write_only` | L1 | 添加、取消 Pin 消息 |
| `im:message.reactions:read` | L1 | 查看消息表情回复 |
| `im:message.reactions:write_only` | L1 | 发送、删除消息表情回复 |

## 群聊类权限

| Scope | 级别 | 说明 |
|-------|------|------|
| `im:chat:read` | L2 | 查看群信息 |
| `im:chat:update` | L2 | 更新群信息 |
| `im:chat:create` | L2 | 创建群 |
| `im:chat.members:bot_access` | L1 | 订阅机器人进、出群事件 |

## 通讯录/日历/任务

| Scope | 级别 | 说明 |
|-------|------|------|
| `contact:contact.base:readonly` | L1 | 获取通讯录基本信息 |
| `calendar:calendar:readonly` | L1 | 获取日历、日程及忙闲信息 |
| `task:task:read` | L1 | 查看任务信息 |

## 文档/云空间

| Scope | 级别 | 说明 |
|-------|------|------|
| `docx:document:readonly` | L2 | 查看新版文档 |
| `docx:document:create` | L2 | 创建新版文档 |
| `docx:document:write_only` | L2 | 编辑新版文档 |
| `docx:document.block:convert` | L2 | 转换文本为云文档块 |
| `docs:document.comment:create` | L2 | 添加、回复云文档中的评论 |
| `docs:document.comment:delete` | L2 | 删除云文档中的评论 |
| `docs:document.comment:read` | L2 | 获取云文档中的评论 |
| `docs:document.comment:update` | L2 | 修改云文档中的评论 |
| `docs:document.comment:write_only` | L2 | 回复、修改、删除云文档中的评论 |
| `drive:drive.metadata:readonly` | L2 | 查看云空间中文件元数据 |
| `space:document.event:read` | L2 | 订阅文件夹下的文件相关事件 |

## 多维表格/Base

| Scope | 级别 | 说明 |
|-------|------|------|
| `base:record:read` | L2 | 检索特定记录 |
| `base:field:read` | L2 | 获取字段信息 |

**缺失**: `base:app:read`、`base:table:read`、`base:workflow:write` — 需要添加才能操作多维表格自动化

## 其他

| Scope | 级别 | 说明 |
|-------|------|------|
| `application:application:self_manage` | L1 | 管理应用自身资源 |
| `application:bot.menu:write` | L1 | 创建、更新、删除机器人菜单 |
| `application:bot.basic_info:read` | L2 | 获取机器人的基本信息 |
| `cardkit:card:write` | L1 | 创建与更新卡片 |
| `cardkit:card:read` | L1 | 获取卡片信息 |
| `im:resource` | L2 | 获取与上传图片或文件资源 |
| `offline_access` | L2 | 持续访问已授权的数据 |
| `vc:note:read` | L2 | 获取智能纪要 |
| `vc:meeting.meetingevent:read` | L2 | 获取会议信息 |
| `minutes:minutes.basic:read` | L2 | 获取妙记的基本信息 |

## 发布状态

- App 状态: 1（开发中）
- **开发模式下 WebSocket 只推送管理事件**（`bot.added/deleted`），不推送消息内容事件（`im.message.receive_v1`）
- 权限齐全（43 scopes）+ 事件已添加 + App 已发布 = 消息事件正常推送

### 激活消息事件的完整流程（三步缺一不可）

**Step 1: 添加事件订阅**
```
打开: https://open.feishu.cn/app/cli_aa95b2dee3b85bd1/event
→ 确认订阅方式为「使用长连接接收事件」（WebSocket）
→ 点击「添加事件」→「以应用身份订阅(tenant)」
→ 展开「消息」分类 → 勾选「接收消息」(im.message.receive_v1)
→ 确认添加
```

**Step 2: 创建版本**
```
打开: https://open.feishu.cn/app/cli_aa95b2dee3b85bd1/version
→ 右上角「创建版本」
→ 版本号: 1.0.0
→ 更新说明: 添加消息事件订阅，启用双向通信
→ 可用范围: 全部成员
→ 保存
```

**Step 3: 提交发布**
```
→ 点击「提交审核」
→ 等待管理员审批（企业自建应用，内部审批即可）
→ 审批通过后 App 自动发布，status 变为已发布
```

**官方文档引用**（`https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/subscription-event-case`）:
> 「即使相关权限已开通，在填写事件订阅方式和添加事件后，仍需发布应用才能使配置生效。」

**验证**: 发布后在群里 @Bot，Gateway 日志应出现 `im.message.receive_v1` 事件。**需要重启 Gateway** 以建立新的 WebSocket 连接（权限变更后旧连接不自动感知）。\n\n**注意**: REST API `GET /open-apis/application/v6/applications/{app_id}` 返回的 `app.status` 在发布后可能延迟更新或保持为 `1`。更可靠的验证方式是检查 `app_versions` 数量变化 + 实测消息接收。不要在 API status 字段上死等。\n\n## 常见混淆\n\n### `im:message:read_as_bot` 不存在\n飞书开放平台中**没有**名为 `im:message:read_as_bot` 的独立 scope。\n消息接收通过以下组合实现:\n- **权限**: `im:message.group_at_msg:readonly`（群@消息）或 `im:message.group_msg`（群全部消息）\n- **事件订阅**: 在 Console 添加 `im.message.receive_v1` 事件\n- **发布**: App 发布后事件才推送\n\n如果在 Console 搜不到 `im:message:read_as_bot`，不要反复搜索——按上述三步走即可。
