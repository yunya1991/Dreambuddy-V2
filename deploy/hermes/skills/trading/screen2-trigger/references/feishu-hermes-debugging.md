# Hermes Gateway ↔ Feishu 双向通信调试清单

> 更新：2026-06-03 | 基于实际排错经历

## 快速诊断三步

```
1. Gateway 是否连接？    → gateway.log 搜 "✓ feishu connected"
2. 出站是否通？          → send_message(action='send', target='feishu:<chat_id>', ...)
3. 入站是否通？          → gateway.log 搜 "Inbound dm/group message received"
```

## 常见问题及修复

### 1. "No messaging platforms enabled"

**根因**：Gateway 启动时 `config.yaml` 中 `home_channel` 解析崩溃。

**修复**：`hermes gateway stop && hermes gateway run --replace`

### 2. send_message 找不到目标

**快速修复**：直接用显式 chat_id：
```
send_message(action='send', target='feishu:oc_36c8543cea823b7546fcaad55d111f9f', message='test')
```

**持久修复**：手动写入 `~/.hermes/channel_directory.json` 的 `platforms.feishu[]`

### 3. 单聊通、群聊不通

**根因**：飞书事件订阅中「接收消息」需单独勾选群聊类型。

**修复流程**：
1. https://open.feishu.cn/app/cli_aa95b2dee3b85bd1/event → 找到「接收消息」→ 展开勾选全部三种
2. 版本管理页创建新版本 → 提交发布
3. 重启 Gateway

### 4. 入站完全不工作

**完整流程**：权限scope → 控制台加事件 → 创建版本 → 提交发布 → 重启Gateway

### 5. lark-cli 未绑定

```bash
lark-cli config bind --source hermes --identity bot-only
```

### 6. feishu_notify.py 凭证失效

将 `FEISHU_APP_ID`/`FEISHU_APP_SECRET` 更新为 Hermes Bot 凭证（`~/.hermes/.env`）

## 5 个交易群 chat_id

```
Research     oc_36c575b6f39a8df3dd75057a96685a21
Desk         oc_36c8543cea823b7546fcaad55d111f9f
Management   oc_9cf9f141613b4e6a0f34651843cf8b9b
Review       oc_8868a5c84f3d8427afa9ed1a9ad7fb76
RiskControl  oc_20fcedf0c35035568ea8fa947380f75d
```

## Bot 关键 ID

```
App ID:   cli_aa95b2dee3b85bd1
Bot name: 云涯Hermes
open_id:  ou_bcf92b6057e502054ca32bcd8ebf6570
```
