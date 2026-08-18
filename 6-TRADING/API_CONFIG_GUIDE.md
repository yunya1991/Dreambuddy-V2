# 6-TRADING API Key 配置指南

> **版本**: v1.0
> **日期**: 2026-05-15
> **用途**: A1调研、OKX实盘、通知服务的API Key配置说明

---

## 一、环境变量配置总览

### 1.1 必需的环境变量

```bash
# ==================== 数据源配置 ====================

# 1. Tavily API (A1调研 - 联网搜索)
export TAVILY_API_KEY="tvly-xxxxxxxxxxxx"

# 2. OKX API (行情 + 实盘交易)
export OKX_API_KEY="your_okx_api_key"
export OKX_SECRET_KEY="your_okx_secret_key"
export OKX_PASSPHRASE="your_passphrase"

# ==================== 通知服务配置 ====================

# 3. 企业微信 Webhook
export WECOM_WEBHOOK="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx"

# 4. 钉钉 Webhook
export DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=xxxxx"

# 5. Telegram Bot
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF"
export TELEGRAM_CHAT_ID="123456789"

# ==================== 百炼API配置 ====================

# 6. 阿里百炼 API (已内置，可选自定义)
export BAILIAN_API_KEY="sk-c233489e73e94b9591e4776d89ec8cb8"
```

---

## 二、Tavily API 配置 (A1调研)

### 2.1 获取 Tavily API Key

1. 访问 [Tavily AI](https://tavily.com) 注册账号
2. 进入 Dashboard → API Keys
3. 复制你的 API Key

### 2.2 配置方式

**方式1: 环境变量**
```bash
export TAVILY_API_KEY="tvly-xxxxxxxxxxxx"
```

**方式2: 在 SKILL 中配置**
Tavily 在 `dream-strategy-research` SKILL 中已配置，调用时会自动读取环境变量。

### 2.3 使用场景

| 场景 | 用途 | 优先级 |
|:---|:---|:---:|
| 宏观政策变化 | 央行政策、监管动态 | **Tavily优先** |
| 市场情绪分析 | 分析师观点、社交媒体 | **Tavily优先** |
| 新闻事件解读 | 突发事件、行业新闻 | **Tavily优先** |
| 链上数据 | 鲸鱼活动、ETF资金流 | Odaily补充 |

> ⚠️ **注意**: Odaily SSL超时率约30%，建议Tavily作为主力搜索。

---

## 三、OKX API 配置 (实盘交易)

### 3.1 获取 OKX API Key

1. 登录 [OKX](https://www.okx.com/cn) 账号
2. 进入 **账户与安全** → **API管理**
3. 创建 API Key:
   - 选择 **交易** 权限（启用读取、交易）
   - 设置 IP 白名单（如需要）
4. 复制 API Key、Secret Key 和 Passphrase

### 3.2 配置方式

**方式1: 前端配置 (推荐)**
```
localhost:3000/dashboard → 充值页面 → API配置 → 填写OKX API Key
```

**方式2: 环境变量**
```bash
export OKX_API_KEY="your_okx_api_key"
export OKX_SECRET_KEY="your_okx_secret_key"
export OKX_PASSPHRASE="your_passphrase"
```

**方式3: `~/.okx/config.toml` (推荐，支持 live/sim 多账户)**
```toml
# ~/.okx/config.toml
[live]
api_key    = "your_live_api_key"
secret_key = "your_live_secret_key"
passphrase = "your_passphrase"

[sim]
api_key    = "your_sim_api_key"
secret_key = "your_sim_secret_key"
passphrase = "your_passphrase"
```
使用 `--profile sim` 切换模拟盘，`--profile live` 切换实盘（默认 live）。
`dream_stop_loss_monitor.py` v1.1 起支持此方式。

**方式4: Bridge API**
```bash
curl -X POST http://127.0.0.1:3847/api/config/okx \
  -H "Content-Type: application/json" \
  -d '{"api_key":"xxx","secret_key":"xxx","passphrase":"xxx"}'
```

### 3.3 配置文件参考

```yaml
# config_44304/config.yaml
okx:
  project: dreamdemo  # 模拟盘
  # project: your_project  # 实盘
  inst_id: BTC-USDT-SWAP
  bar: 1H
```

### 3.4 模拟盘 vs 实盘

| 模式 | 配置 | 说明 |
|:---|:---|:---|
| **模拟盘** | `project: dreamdemo` | 无需真实资金 |
| **实盘** | `project: your_project` | 需要真实API Key |

---

## 四、通知服务配置

### 4.1 企业微信 Webhook

1. 企业微信群 → 群设置 → 添加群机器人
2. 复制 Webhook 地址

```bash
export WECOM_WEBHOOK="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx"
```

### 4.2 钉钉 Webhook

1. 钉钉群 → 群设置 → 智能群助手
2. 添加机器人 → 自定义机器人
3. 复制 Webhook 地址

```bash
export DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=xxxxx"
```

### 4.3 Telegram Bot

1. 与 [@BotFather](https://t.me/BotFather) 对话
2. 创建新机器人 `/newbot`
3. 获取 Bot Token
4. 与 [@userinfobot](https://t.me/userinfobot) 对话获取 Chat ID

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF"
export TELEGRAM_CHAT_ID="123456789"
```

---

## 五、快速配置脚本

### 5.1 一键配置脚本

```bash
cat > ~/.bash_profile_trading << 'EOF'
# ==================== 6-TRADING 环境变量 ====================

# Tavily API (A1调研)
export TAVILY_API_KEY="tvly-xxxxxxxxxxxx"

# OKX API (实盘)
export OKX_API_KEY="your_okx_api_key"
export OKX_SECRET_KEY="your_okx_secret_key"
export OKX_PASSPHRASE="your_passphrase"

# 通知服务
export WECOM_WEBHOOK="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx"
export DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=xxxxx"
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF"
export TELEGRAM_CHAT_ID="123456789"

# 百炼API (已内置)
export BAILIAN_API_KEY="sk-c233489e73e94b9591e4776d89ec8cb8"

echo "✅ 6-TRADING 环境变量已加载"
EOF

# 加载配置
source ~/.bash_profile_trading
```

### 5.2 验证配置

```bash
# 验证环境变量
echo $TAVILY_API_KEY
echo $OKX_API_KEY

# 验证OKX连接（在 6-TRADING 目录下）
python scripts/okx_cli.py --profile paper ticker BTC-USDT-SWAP
```

---

## 六、配置检查清单

| 配置项 | 状态 | 验证命令 |
|:---|:---:|:---|
| TAVILY_API_KEY | ⬜ | `echo $TAVILY_API_KEY` |
| OKX_API_KEY | ⬜ | `python -c "from okx import OkxAPI; print('OK')"` |
| WECOM_WEBHOOK | ⬜ | `curl -s $WECOM_WEBHOOK -d '{"msgtype":"text","text":{"content":"test"}}'` |
| DINGTALK_WEBHOOK | ⬜ | `curl -s $DINGTALK_WEBHOOK -d '{"msgtype":"text","text":{"content":"test"}}'` |
| TELEGRAM_BOT_TOKEN | ⬜ | `curl -s https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe` |

---

## 七、故障排查

| 问题 | 解决方案 |
|:---|:---|
| Tavily 搜索失败 | 检查 `TAVILY_API_KEY` 是否正确 |
| OKX 行情无数据 | 检查 API Key 权限是否包含"读取" |
| OKX 交易失败 | 检查 API Key 权限是否包含"交易" |
| Webhook 发送失败 | 检查网络和白名单设置 |
| Telegram 无法发送 | 检查 Bot Token 和 Chat ID |

---

*本文档由 WorkBuddy 自动生成*
