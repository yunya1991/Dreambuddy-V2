# lark-cli 绑定 Hermes 配置流程

> 适用: 首次使用 lark-cli 操作飞书多维表格/审批/流程时
> 前置: Hermes Bot 已在 `~/.hermes/.env` 中配置 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`

## 绑定命令

```bash
# bot-only 模式（推荐，最安全）
lark-cli config bind --source hermes --identity bot-only

# user-default 模式（需要访问用户个人资源如日历/邮件/云盘时）
lark-cli config bind --source hermes --identity user-default
```

绑定后 lark-cli 自动读取 Hermes 的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`。
配置写入 `~/.lark-cli/hermes/config.json`。

## 验证

```bash
lark-cli config show
# 应显示: identity: bot, workspace: hermes
```

## 常见问题

| 问题 | 解决 |
|------|------|
| `not_configured` / `not bound to it` | 执行 `lark-cli config bind --source hermes --identity bot-only` |
| `strict mode is "bot"` | bot-only 模式只能执行 bot 身份命令。需要 user 命令时切换到 user-default |
| `access denied: scope` | 去飞书开发者后台给 App 添加对应 scope |

## 相关链接

- 飞书开发者后台: `https://open.feishu.cn/app/{APP_ID}/auth`
- Bitable scope: `bitable:app`, `base:app:read`, `base:table:read`, `base:workflow:write`
- Approval scope: `approval:instance:write`, `approval:instance:read`
