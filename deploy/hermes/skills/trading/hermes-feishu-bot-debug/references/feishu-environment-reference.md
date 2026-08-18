# 6-TRADING 飞书环境速查

## Hermes Bot 身份
- App ID: `cli_aa95b2dee3b85bd1`
- App Name: 云涯Hermes
- Bot open_id: `ou_bcf92b6057e502054ca32bcd8ebf6570`
- 激活状态: activate_status=2（已激活）

## 五群组 chat_id
| 群名称 | chat_id | 用途 |
|--------|---------|------|
| Trading-Research | `oc_36c575b6f39a8df3dd75057a96685a21` | Screen1 周线研判 |
| Trading-Desk | `oc_36c8543cea823b7546fcaad55d111f9f` | Screen2/3 执行 |
| Trading-Management | `oc_9cf9f141613b4e6a0f34651843cf8b9b` | 管理看板 |
| Trading-Review | `oc_8868a5c84f3d8427afa9ed1a9ad7fb76` | 复盘室 |
| Trading-RiskControl | `oc_20fcedf0c35035568ea8fa947380f75d` | 风控审批 |

## 关键文件路径
- Gateway 配置: `~/.hermes/config.yaml`
- 环境变量: `~/.hermes/.env`
- Channel Directory: `~/.hermes/channel_directory.json`
- Gateway 日志: `~/.hermes/logs/gateway.log`
- 错误日志: `~/.hermes/logs/errors.log`

## lark-cli 绑定状态
- 已绑定: `hermes` workspace, `bot-only` 身份
- 配置文件: `~/.lark-cli/hermes/config.json`

## 飞书后台链接
- 应用详情: `https://open.feishu.cn/app/cli_aa95b2dee3b85bd1`
- 权限管理: `https://open.feishu.cn/app/cli_aa95b2dee3b85bd1/auth`
- 事件订阅: `https://open.feishu.cn/app/cli_aa95b2dee3b85bd1/event`
- 版本发布: `https://open.feishu.cn/app/cli_aa95b2dee3b85bd1/version`

## feishu_notify.py（旧方案，凭证已失效）
- App ID: `cli_aa9442bde4b89be9`
- 状态: app secret invalid，需要更换为 Hermes Bot 凭证
- Bitable: `CMlnbvAKYafUL0sxLpFcxNfVnoc` / table `tblSDdfk2sbBAVsr`

## User open_id
- 用户 (LuckyAI): `ou_a7862ec46b0eeb32073f676439d8d9fe`
