# 通信渠道详细设计

> 版本: v2.1 | 日期: 2026-05-13 | 所属: Dream Universal Gateway
> **v2.0变更**: 明确与交易参数配置的独立性，补充交易事件→通知的联动关系
> **v2.1变更**: 新增策略事件→通知的联动关系

---

## 1. 设计目标

让AI决策结果、交易信号、风险告警能通过用户配置的通信渠道自动推送，实现"AI思考→用户通知→行动确认"的闭环。

> **独立性声明**: 通信渠道是独立功能设置，与API配置、交易参数配置互不耦合。用户可以只配置通信渠道（如仅接收情报推送）而不配置交易API，也可以只配置交易API而不配置推送渠道。

### 1.1 三大独立功能

| 功能 | 定位 | 入口 | 配置文件 |
|------|------|------|----------|
| **API配置** | 连接凭证管理 | ⚙️ API配置 | api-keys.enc |
| **交易参数** | 交易行为约束 | 💰 交易设置 | trading-params.json |
| **策略设置** | 交易策略选择+定时执行 | 🎯 策略设置 | strategies.json |
| **通信渠道** | 消息推送通道 | 📡 通信渠道 | channels.enc |

> 详见 [API_CONFIG_DESIGN.md](API_CONFIG_DESIGN.md) 和 [TRADING_CONFIG_DESIGN.md](TRADING_CONFIG_DESIGN.md)

---

## 2. 渠道适配器架构

### 2.1 统一接口

```typescript
interface ChannelAdapter {
  type: ChannelType;
  name: string;
  
  // 生命周期
  connect(): Promise<void>;
  disconnect(): Promise<void>;
  testConnection(): Promise<TestResult>;
  
  // 消息推送
  send(message: PushMessage): Promise<SendResult>;
  
  // 状态查询
  getStatus(): ChannelStatus;
}

type ChannelType = 'telegram' | 'wechat_serverchan' | 'wecom' | 'email' | 'discord' | 'slack' | 'feishu';

interface ChannelStatus {
  connected: boolean;
  latency?: number;          // ms
  lastMessageAt?: string;
  errorCount: number;
}
```

### 2.2 推送消息格式

```typescript
interface PushMessage {
  type: PushMessageType;
  priority: 'P0' | 'P1' | 'P2';
  title: string;
  body: string;
  metadata?: {
    chainPhase?: string;         // A0-A9
    symbol?: string;             // BTC-USDT-SWAP
    artifactId?: string;         // 关联产物
    sessionId?: string;          // 关联会话
  };
  actions?: PushAction[];
  timestamp: string;
}

type PushMessageType = 
  | 'trade_signal'        // 交易信号（BUY/SHORT/SKIP）
  | 'risk_alert'          // 风险告警（清算/回撤/门禁拦截）
  | 'intel_update'        // 情报更新（A6产物）
  | 'daily_report'        // 每日报告
  | 'dream_insight'       // 做梦部洞察
  | 'strategy_update'    // 策略更新推荐（A4推送）
  | 'strategy_executed'  // 策略执行结果
  | 'system_notice'       // 系统通知
  | 'verification_code';  // 验证码（用于渠道绑定）

interface PushAction {
  label: string;           // "确认执行" "查看详情" "忽略"
  action: string;          // callback_data
  style: 'primary' | 'danger' | 'default';
}

interface SendResult {
  success: boolean;
  messageId?: string;
  error?: string;
  latency: number;         // ms
}
```

---

## 3. Telegram Bot 适配器 (P0)

### 3.1 配置

```typescript
interface TelegramConfig {
  id: string;
  type: 'telegram';
  label: string;               // "我的交易信号群"
  credentials: {
    botToken: string;           // 加密存储
    chatId: string;             // 个人/群组 Chat ID
  };
  pushRules: TelegramPushRules;
}

interface TelegramPushRules {
  enabledTypes: PushMessageType[];
  silentHours?: {
    start: string;             // "23:00"
    end: string;               // "07:00"
  };
  format: 'compact' | 'detailed';
  includeChart: boolean;       // 是否附带K线图
  interactiveButtons: boolean; // 是否显示交互按钮
}
```

### 3.2 消息模板

#### 交易信号 (compact)

```
🔴 SHORT 信号 | BTC-USDT-SWAP
━━━━━━━━━━━━━━━━━━
评分: 12/80 | Edge: -35
Regime: RANGE_BOUND
止损: $82,100 | 止盈: $78,500
━━━━━━━━━━━━━━━━━━
A2矛盾: 宏观转鹰+CPI超预期
[确认执行] [查看详情] [忽略]
```

#### 交易信号 (detailed)

```
🔴 SHORT 信号 | BTC-USDT-SWAP
━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 评分详情:
  · 宏观: 3/10 (CPI 3.8%超预期)
  · 技术: 5/10 (200日SMA下方)
  · 情绪: 4/10 (FGI=42 Fear)
  · 总分: 12/80 → SHORT区间

📐 Edge分析:
  · Edge: -35 (强SHORT信号)
  · 衰减监控: L1级

⚡ 执行建议:
  · 杠杆: 2x (合规上限)
  · 仓位: 0.3x (PTJ保守模式)
  · 止损: $82,100 (-1.8%)
  · 止盈: $78,500 (+2.6%)

🧠 思维链路:
  A1→A2→A3(概率:下行65%)→A4(验证通过)

📎 产物: a2_first_principles_20260513
━━━━━━━━━━━━━━━━━━━━━━━━━━
[确认执行] [查看A2详情] [忽略]
```

#### 风险告警

```
⚠️ P0 风险告警
━━━━━━━━━━━━━━━━━━
类型: Edge衰减 L2级
品种: BTC-USDT-SWAP
当前Edge: -28 (4h内从-35衰减)
建议: 减仓50%

持仓: SHORT 0.3x @ $80,630
浮盈: +$189 (+0.23%)
━━━━━━━━━━━━━━━━━━
[立即减仓] [查看详情] [继续观察]
```

#### A6情报更新

```
📡 A6 情报快报 | 20:30
━━━━━━━━━━━━━━━━━━
宏观: CPI 3.8%落地，Fed降息预期归零
费率: +0.0034% (微弱正，恢复中)
FGI: 42 (Fear)
ETF: 昨日净流入$2.1M

显著变化:
  · 费率从负转正(翻转信号)
  · Warsh 5/15接任预期(鹰派)
━━━━━━━━━━━━━━━━━━
SI_Index: +9 (偏多)
[查看完整报告]
```

### 3.3 交互按钮回调

```typescript
// Telegram InlineKeyboard 回调处理
interface TelegramCallback {
  action: 'confirm_execute' | 'view_detail' | 'dismiss' 
        | 'reduce_position' | 'close_position' | 'view_report';
  metadata: {
    signalId: string;
    symbol: string;
    direction: 'BUY' | 'SHORT';
  };
}

// 回调处理流程:
// 1. 用户点击TG按钮
// 2. TG Bot API → Webhook → 后端
// 3. 后端验证 → 执行/跳转
// 4. 推送执行结果到TG
```

### 3.4 Bot设置指引

```
步骤1: 在Telegram中搜索 @BotFather，创建新Bot
步骤2: 获取Bot Token
步骤3: 将Bot添加到目标群组/频道
步骤4: 发送任意消息给Bot，获取Chat ID
步骤5: 在配置面板填入Bot Token和Chat ID
步骤6: 点击"测试连接"验证
```

---

## 4. Server酱(微信) 适配器 (P0)

### 4.1 配置

```typescript
interface WeChatServerChanConfig {
  id: string;
  type: 'wechat_serverchan';
  label: string;
  credentials: {
    sendKey: string;           // Server酱 SendKey
  };
  pushRules: WeChatPushRules;
}

interface WeChatPushRules {
  enabledTypes: PushMessageType[];
  format: 'compact' | 'detailed';
  // Server酱限制: 无交互按钮，纯通知
}
```

### 4.2 消息模板

```
标题: 【SHORT信号】BTC-USDT-SWAP 评分12

内容:
评分: 12/80 | Edge: -35
Regime: RANGE_BOUND
止损: $82,100 | 止盈: $78,500

A2矛盾: 宏观转鹰+CPI超预期
产物: a2_first_principles_20260513

⚠️ 请在AI对话界面确认执行
```

> **限制**: 微信模板消息不支持交互按钮，仅作通知。交易确认需回到Chat界面操作。

---

## 5. Email 适配器 (P1)

### 5.1 配置

```typescript
interface EmailConfig {
  id: string;
  type: 'email';
  label: string;
  credentials: {
    smtpHost: string;
    smtpPort: number;
    smtpUser: string;
    smtpPassword: string;      // 加密存储
    fromAddress: string;
  };
  recipients: string[];
  pushRules: EmailPushRules;
}

interface EmailPushRules {
  enabledTypes: PushMessageType[];
  format: 'compact' | 'detailed' | 'html';
  includeAttachment: boolean;  // 是否附加产物PDF
  schedule?: {
    dailyReport: boolean;      // 每日报告
    reportTime: string;        // "22:00"
  };
}
```

---

## 6. 推送规则引擎

### 6.1 规则定义

```typescript
interface PushRule {
  id: string;
  channelId: string;            // 关联渠道
  enabled: boolean;
  
  // 触发条件
  conditions: {
    messageTypes: PushMessageType[];
    priorities?: ('P0' | 'P1' | 'P2')[];  // 空=全部
    symbols?: string[];                    // 空=全部品种
    chainPhases?: string[];                // 空=全部阶段
  };
  
  // 过滤
  filters: {
    silentHours?: { start: string; end: string; };
    minInterval?: number;       // 同类型消息最小间隔(秒)
    dedupWindow?: number;       // 去重窗口(秒)
  };
  
  // 格式
  format: {
    style: 'compact' | 'detailed';
    locale: 'zh' | 'en';
    includeActions: boolean;
  };
}
```

### 6.2 推送流程

```
事件触发 (交易信号/告警/情报)
      │
      ▼
┌──────────────────┐
│  PushRuleEngine   │
│  1. 匹配规则      │
│  2. 检查过滤条件  │
│  3. 去重          │
│  4. 静默时段检查  │
└────────┬─────────┘
         │ 匹配的渠道列表
         ▼
┌──────────────────┐
│  ChannelRouter    │
│  1. 按渠道分发    │
│  2. 格式化消息    │
│  3. 调用Adapter   │
│  4. 记录结果      │
└────────┬─────────┘
         │
    ┌────┼────┐
    ▼    ▼    ▼
   TG  微信  Email
```

### 6.3 默认规则

| 消息类型 | 优先级 | 默认渠道 | 格式 |
|----------|--------|----------|------|
| 交易信号 | P0 | TG + 微信 | compact |
| 风险告警 | P0 | TG + 微信 | compact |
| 情报更新 | P1 | TG | compact |
| 策略更新推荐 | P1 | TG | compact |
| 策略执行结果 | P1 | TG + 微信 | compact |
| 每日报告 | P2 | Email | detailed |
| 做梦洞察 | P2 | TG | compact |
| 系统通知 | P1 | 全部 | compact |

---

## 7. 渠道配置存储

### 7.1 存储文件

```
~/.workbuddy/config/
├── channels.enc          # 加密存储（含Bot Token等）
├── channels.meta.json    # 元数据
└── push-rules.json       # 推送规则（非敏感，明文）
```

### 7.2 元数据文件

```json
{
  "version": "1.0",
  "channels": [
    {
      "id": "tg_signals",
      "type": "telegram",
      "label": "交易信号群",
      "connected": true,
      "lastMessageAt": "2026-05-13T20:00:00+08:00",
      "maskedToken": "••••••••1234:ABC"
    },
    {
      "id": "wechat_notice",
      "type": "wechat_serverchan",
      "label": "微信通知",
      "connected": true,
      "maskedKey": "••••••••xYz8"
    }
  ]
}
```

---

## 8. 后端API接口

### 8.1 渠道管理

```
GET    /api/config/channels              # 列表
POST   /api/config/channels              # 添加
PATCH  /api/config/channels/:id          # 更新
DELETE /api/config/channels/:id          # 删除
POST   /api/config/channels/:id/test     # 测试连接
```

### 8.2 推送规则

```
GET    /api/config/channels/:id/rules    # 获取规则
PATCH  /api/config/channels/:id/rules    # 更新规则
```

### 8.3 推送历史

```
GET    /api/config/channels/:id/history  # 推送历史
GET    /api/config/channels/stats        # 渠道统计
```

---

## 9. Telegram Bot Webhook 集成

### 9.1 Webhook设置

```typescript
// 启动时注册Webhook
async function setupTelegramWebhook(botToken: string): Promise<void> {
  const webhookUrl = `${PUBLIC_URL}/api/webhook/telegram`;
  await fetch(
    `https://api.telegram.org/bot${botToken}/setWebhook`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: webhookUrl }),
    }
  );
}
```

### 9.2 Webhook处理

```
POST /api/webhook/telegram

Body: Telegram Update对象

处理流程:
1. 验证消息来源（Bot Token校验）
2. 解析CallbackQuery（按钮点击）
3. 路由到对应Handler
4. 返回200（Telegram要求5秒内响应）
```

### 9.3 双向通信

```
用户 ←──── Telegram ────→ AI后端

推送方向(AI→用户):
  交易信号/告警/报告 → Telegram消息 → 用户手机

回调方向(用户→AI):
  用户点击[确认执行] → Telegram CallbackQuery → AI后端
  → 执行交易 → 推送结果到Telegram
```

---

## 10. 安全与合规

| 措施 | 说明 |
|------|------|
| Token加密 | Bot Token/SendKey 与API Key同等加密保护 |
| 消息过滤 | 推送内容不含完整API Key、私钥等 |
| 操作确认 | P0交易操作必须用户二次确认 |
| 频率限制 | 每渠道每分钟≤10条 |
| 离线保护 | 渠道离线时消息队列缓存，重连后补发 |
| 审计日志 | 所有推送记录到 `~/.workbuddy/logs/push/` |

---

## 11. 交易事件通知联动

### 11.1 门禁事件 → 通信渠道映射

交易参数门禁（TradingGate）产生的事件，自动通过通信渠道推送：

| 门禁事件 | 推送优先级 | 推送渠道 | 消息模板 |
|----------|-----------|----------|----------|
| 交易信号(BUY/SHORT) | P0 | TG+微信 | 交易信号模板 |
| 日亏损达上限 | P0 | TG+微信 | "⚠️ 今日亏损已达上限，交易已暂停" |
| 账户亏损达上限 | P0 | TG+微信 | "🚨 账户亏损已达上限，交易功能已冻结" |
| 杠杆降级通知 | P1 | TG | "策略要求Nx但限制Mx，已降级执行" |
| 交易已暂停 | P1 | TG+微信 | "交易功能已暂停，原因: xxx" |
| 交易已恢复 | P1 | TG+微信 | "交易功能已恢复" |

### 11.4 策略事件 → 通信渠道映射

| 策略事件 | 推送优先级 | 推送渠道 | 消息模板 |
|----------|-----------|----------|----------|
| A4推送新推荐策略 | P1 | TG | "📋 新策略推荐: 区间震荡-观望防守策略" |
| 策略已应用 | P1 | TG+微信 | "✅ 策略已应用，将按4h频率自动执行" |
| 策略执行-交易成功 | P1 | TG+微信 | "📊 策略执行: BUY BTC 2x 成功" |
| 策略执行-条件不匹配 | P2 | TG | "⏭️ 策略跳过: 当前条件不匹配" |
| 策略执行-门禁拦截 | P0 | TG+微信 | "🚫 策略执行被风控拦截: [原因]" |
| 策略过期提醒 | P2 | TG | "⏰ 策略即将过期，请查看更新" |
| 自定义策略生成完成 | P1 | TG | "✅ 自定义策略已生成，请查看" |

### 11.5 策略事件联动流程

```
StrategyEngine 策略事件
      │
      ├── A4推送新策略 → 推送"新策略推荐"到TG
      │
      ├── 策略已应用 → 推送"策略已应用"到TG+微信
      │
      ├── 策略执行-交易成功 → 推送执行结果到TG+微信
      │
      ├── 策略执行-条件不匹配 → 推送跳过通知到TG
      │
      ├── 策略执行-门禁拦截 → 推送拦截通知到TG+微信
      │
      └── 自定义策略生成完成 → 推送生成通知到TG
```

### 11.2 联动流程

```
TradingGate 门禁检查
      │
      ├── passed=true → 执行下单 → 推送"交易已执行"到已配置渠道
      │
      ├── passed=false → 拦截 → 推送"交易被拦截"到已配置渠道
      │                    │
      │                    └── 推送内容含:
      │                         · 拦截原因(用户语言)
      │                         · 当前配置值
      │                         · [修改配置] [查看详情]
      │
      └── warnings → 推送警告到TG
                       · 如"杠杆3x以上风险较高"
```

### 11.3 用户在通信渠道中的操作

| 渠道 | 支持操作 | 说明 |
|------|----------|------|
| TG | [确认执行] [忽略] [查看详情] | 交互按钮回调 |
| TG | [修改配置] | 跳转Chat界面配置面板 |
| 微信 | 仅通知，无交互 | 需回Chat界面操作 |
| Email | [查看详情]链接 | 链接到Chat界面 |
