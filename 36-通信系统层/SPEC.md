# 通信传递层（Signal Bus）完整规格说明书

> 版本：v1.0 | 日期：2026-10-14 | 状态：设计定稿，待评审

## 1. 背景与目标

### 1.1 现状问题

当前系统的信号产生与通知发送散落在各模块，无统一收口：

| 信号源 | 位置 | 现有通知方式 | 问题 |
|---|---|---|---|
| Freqtrade 交易事件（entry/exit/cancel/fill/status） | 28-策略信号触发模块（:8096） | 路由到下游，无统一通知 | 通知逻辑分散 |
| 监控告警（heartbeat/trading/model/position/system/performance） | 15-监控告警系统 | feishu_alert.py 直推飞书 | 硬编码凭证与群路由 |
| 三屏趋势信号（4h/1h 持仓判断、wave_signal） | 12-三屏趋势系统 / three-screens-mapper | 无通知 | 信号未触达用户 |
| 策略执行事件（Gate-C/A9 评估、SKIP episode） | 3.1-FRONTEND 策略步骤 + Hermes | 依赖 Hermes（需大模型） | 模型不可达时全部瘫痪 |
| 风控告警 | 13-通用风控模块 | 无统一通知 | 信号未触达用户 |
| 定时报告（daily_report） | 3.1-FRONTEND 任务管理器 | 无通知 | 信号未触达用户 |

### 1.2 设计目标

1. 统一收口：所有信号经通信传递层（Signal Bus）汇总，一处进、多处出
2. 双通道分发：Hermes 智能通道（需大模型，负责交互类）+ API 直推通道（无需大模型，负责通知类），静态划分消息类型，自动降级
3. 信号分类体系：区分信号类别与严重级别，按类别路由到不同接收端
4. Hermes 可配置：用户可通过 Hermes 对话完成信号订阅设置、定时任务接收配置（如开仓/平仓信号推送）
5. 复用现有资产：复用 3.1-FRONTEND 已有的 ChannelConfig 存储（PostgreSQL + 加密凭证）、15 号模块的飞书直推实现、Hermes 的群配置

## 2. 业界方案调研结论

### 2.1 传统金融信息服务模式（Bloomberg/Reuters 发布-订阅总线）
- Topic 订阅模型：信号按主题（如 EQUITY.TRADE、FX.ALERT）发布，订阅方按主题过滤接收
- 消息分类与优先级：Market Data / News / Alert 分通道，Alert 内分严重级别，级别决定推送方式（弹窗/消息/静默）
- FIX 通知类消息设计：结构化消息头（MsgType + MsgSeqNum + SendingTime）保证可追溯、可重放

借鉴点：信号采用 topic + severity 的二维分类；每条信号带唯一 ID、时间戳、来源，支持追溯与重放。

### 2.2 Novu（GitHub 45k+ star，统一通知基础设施）
- 统一 API + 统一会话模型：一次接入，多渠道分发（Inbox/Email/SMS/Push/Chat）
- 工作流引擎：通知模板 + 分支条件 + 按渠道过滤
- 摘要引擎（Digest）：同类通知聚合为一条，避免轰炸
- ACI（Agent 通信基础设施）：双向消息——入站消息归一化后路由给 Agent，Agent 回复经同一层发出

借鉴点：信号模板（template）+ 订阅偏好（preference）模型；Hermes 作为 ACI 中的 Agent 接入，双向消息统一经传递层。

### 2.3 Apprise（GitHub 12k+ star，轻量统一推送库）
- 统一 URL 语法：所有渠道用一致格式描述（如 tgram://token/chat_id）
- 异步发送：所有消息异步投递，不阻塞业务
- 插件式渠道适配器：新增渠道只需实现一个插件类

借鉴点：渠道适配器（adapter）插件化；发送异步化，业务方不等待投递结果。

### 2.4 本系统选型结论

不直接引入 Novu（过重，含自建控制台与多租户），采用自建轻量 Signal Bus：
- 参考 Novu 的 template + preference 模型
- 参考 Apprise 的适配器插件化 + 异步发送
- 参考金融总线的 topic + severity 分类与消息头设计
- 落地为 3.1-FRONTEND 内的独立文件夹『通信传递层』，与现有 ChannelConfig 打通

## 3. 架构设计

### 3.1 总体架构

```
信号源（Producers）
  28-信号触发(freqtrade事件)  15-监控告警  12-三屏趋势
  13-风控  3.1-策略执行(Gate-C/A9/SKIP)  定时报告  系统
        |
        |  POST /api/signal-bus/emit
        v
通信传递层（Signal Bus）★ 本 spec 核心
  [信号校验] → [分类路由] → [模板渲染] → [摘要聚合]
  [分发决策：静态划分 + 健康检查]
        |
        +-- 通知类（直推）→ API 直推通道（飞书/Telegram/邮件，无需大模型）
        +-- 交互类（智能）→ Hermes 智能通道（评估分析/审批/对话，需大模型，降级挂起）
```

### 3.2 目录结构

```
36-通信系统层/（Dreambuddy 根目录下，与其他编号模块并列）
├── SPEC.md                    # 本规格说明书
├── README.md                  # 使用指南
├── src/
│   ├── types.ts               # 信号类型定义（SignalType/Severity/SignalEnvelope）
│   ├── bus.ts                 # 核心：emit() 收口 + 分类路由 + 分发决策
│   ├── templates.ts           # 信号模板（按类型渲染 CONCISE/DETAILED 格式）
│   ├── digest.ts              # 摘要聚合（同类信号窗口内合并）
│   ├── health.ts              # Hermes 健康检查（模型端点探测 + 降级标记）
│   ├── adapters/
│   │   ├── feishu.ts          # 飞书直推适配器（复用 15 号模块凭证模式）
│   │   ├── telegram.ts        # Telegram 适配器
│   │   ├── hermes.ts          # Hermes 适配器（投递到 Hermes 网关/队列）
│   │   └── index.ts           # 适配器注册表
│   └── store.ts               # 订阅偏好读写（对接 ChannelConfig + SignalSubscription）
└── tests/
    └── bus.test.ts            # 单元测试
```

同时新增 API 路由：src/app/api/signal-bus/emit/route.ts（信号收口入口）与 src/app/api/signal-bus/subscriptions/route.ts（订阅管理，供 Hermes 与前端调用）。

## 4. 信号分类体系

### 4.1 信号类型（SignalType，topic 维度）

| 类型 | 代码 | 说明 | 默认通道 |
|---|---|---|---|
| 交易信号-开仓 | trade_signal.open | Gate-C 通过、批准入场 | 交易台群 + API 直推 |
| 交易信号-平仓 | trade_signal.close | A9 离场触发 | 交易台群 + API 直推 |
| 交易信号-跳过 | trade_signal.skip | 评估拒绝，写 SKIP episode | API 直推 |
| 风险告警 | risk_alert | 风控阈值触发、回撤超限 | 风控群 + API 直推 |
| 策略更新 | strategy_update | 策略创建/修改/审批 | API 直推 |
| 策略执行 | strategy_executed | 入场/离场执行结果 | 交易台群 + API 直推 |
| 情报更新 | intel_update | Screen1 研究结论、市场情报 | 研究群（Hermes） |
| 每日报告 | daily_report | 定时汇总报告 | API 直推（邮件/飞书） |
| 系统通知 | system_notice | 服务状态、降级/恢复通知 | 管理群 + API 直推 |

### 4.2 严重级别（Severity）

critical / error / warning / info（沿用 15 号模块既有定义与颜色映射）

### 4.3 信号信封（SignalEnvelope，消息头设计）

```typescript
interface SignalEnvelope {
  id: string;            // 唯一 ID（ULID），支持追溯与重放
  type: SignalType;      // 信号类型（topic）
  severity: Severity;    // 严重级别
  source: string;        // 来源模块（如 m28-freqtrade、m15-monitor）
  ts: number;            // 发出时间戳（ms）
  payload: Record<string, unknown>;  // 类型化负载（见 4.4）
  dedupKey?: string;     // 幂等键，防重复投递
}
```

### 4.4 关键负载定义

```typescript
// trade_signal.open / close
interface TradeSignalPayload {
  symbol: string; direction: 'LONG' | 'SHORT';
  entryPrice?: number; exitPrice?: number;
  confidence?: number; reason?: string;
  strategyName?: string; orderId?: string;
}
// risk_alert
interface RiskAlertPayload { metric: string; value: number; threshold: number; positionId?: string; }
// 其余类型负载见 types.ts，均要求 JSON 可序列化
```

## 5. 分发决策

### 5.1 静态通道划分（默认规则）

| 信号类别 | 通道 | 理由 |
|---|---|---|
| 通知类（trade_signal.*、risk_alert、strategy_update、strategy_executed、daily_report、system_notice） | API 直推（飞书/Telegram/邮件） | 确定性通知，不依赖大模型，稳定优先 |
| 交互类（intel_update 及用户显式订阅给 Hermes 的类型） | Hermes 智能通道 | 需要理解、分析、对话 |

用户可通过订阅偏好覆盖默认划分（如把 trade_signal 也订阅给 Hermes 做深度解读）。

### 5.2 降级与恢复

- health.ts 每 60 秒探测模型端点连通性（HEAD 请求，超时 5s）
- 连续 2 次失败 → 标记 Hermes 降级，发一条 system_notice（severity=warning）到管理群
- 降级期间：交互类信号进入挂起队列（持久化到 PostgreSQL SignalOutbox 表），不丢弃、不降级为模板消息
- 恢复后：自动重放挂起队列（按 ts 顺序），并发送恢复通知
- API 直推通道不受降级影响，始终可用

### 5.3 摘要聚合（Digest）

- 同一 type + severity 的信号在 5 分钟窗口内超过 10 条时，聚合为一条摘要（计数 + 最新一条详情）
- critical 级别不聚合，逐条投递

## 6. API 设计

### 6.1 信号收口

```
POST /api/signal-bus/emit
Body: SignalEnvelope
响应: { success: true, data: { id, dispatched: string[], queued?: string[] } }
```

- 幂等：携带 dedupKey 的重复信号在 10 分钟内只投递一次
- 异步：校验通过即返回 202 语义，实际投递在后台执行

### 6.2 订阅管理（前端设置页 + Hermes 均调用）

```
GET    /api/signal-bus/subscriptions          # 查询当前用户订阅
POST   /api/signal-bus/subscriptions          # 新增订阅 { signalType, channel: HERMES|API, target? }
PATCH  /api/signal-bus/subscriptions          # 修改
DELETE /api/signal-bus/subscriptions?id=      # 删除
```

数据模型（Prisma 新增 SignalSubscription 表）：

```prisma
model SignalSubscription {
  id         String   @id @default(cuid())
  uid        String
  signalType String
  channel    String   // HERMES | API
  target     String?  // API 通道时为渠道配置ID；HERMES 时为群 chat_id
  createdAt  DateTime @default(now())
  updatedAt  DateTime @updatedAt
  @@unique([uid, signalType, channel, target])
}
```

另新增 SignalOutbox 表（降级挂起队列）：

```prisma
model SignalOutbox {
  id        String   @id @default(cuid())
  envelope  Json
  status    String   @default("PENDING") // PENDING | REPLAYED | FAILED
  createdAt DateTime @default(now())
}
```

## 7. Hermes 集成设计

### 7.1 Hermes 作为接收端（智能通道）

- adapters/hermes.ts 将交互类信号投递到 Hermes：写入 Hermes 的 gateway 消息队列（或调用其本地 HTTP 接口），由 Hermes 消费并生成分析/汇报
- 投递目标群按信号类型映射：intel_update → 研究群；trade_signal（若订阅给 Hermes）→ 交易台群

### 7.2 用户通过 Hermes 完成设置

- Hermes 侧新增 SKILL：signal-bus-settings，支持自然语言操作订阅：
  - 『订阅开仓信号到交易台群』→ 调用 POST /api/signal-bus/subscriptions
  - 『每天 8 点接收每日报告』→ 创建定时任务 + daily_report 订阅
  - 『查看我的信号订阅』→ GET 查询并格式化回复
- 该 SKILL 通过本机 HTTP 调用 3.1-FRONTEND 的订阅 API，无需大模型也可执行查询类操作（设置变更仍需模型理解指令）

### 7.3 定时任务信号接收

- 交易系统开仓/平仓信号：28 号模块 freqtrade webhook 处理器在路由下游的同时调用 POST /api/signal-bus/emit（type=trade_signal.open/close）
- 用户在 Hermes 中说『开仓平仓信号推送到飞书』→ SKILL 创建订阅（channel=API，target=飞书渠道）

## 8. 与现有系统的对接改造点

| 改造点 | 内容 | 工作量 |
|---|---|---|
| 28 号模块 webhook.py | 事件处理中追加 emit 调用 | 小 |
| 15 号模块 feishu_alert.py | send_alert 内部改为调用 emit（保留原直推为兜底） | 小 |
| 3.1 前端 ChannelManager.tsx | 新增 FEISHU 渠道类型 + 订阅管理 Tab | 中 |
| 3.1 前端 types/index.ts | ChannelType 增加 FEISHU；新增 SignalType/Severity | 小 |
| Prisma schema | 新增 SignalSubscription、SignalOutbox 表 + 迁移 | 中 |
| Hermes | 新增 signal-bus-settings SKILL | 中 |

## 9. 安全设计

- 飞书凭证沿用 15 号模块的环境变量方式（FEISHU_APP_ID/SECRET），不硬编码入库；前端渠道凭证沿用 ChannelConfig 加密存储
- emit 接口加内部 Token 鉴权（环境变量 SIGNAL_BUS_TOKEN），防止外部伪造信号
- 信号负载中的敏感字段（apiKey 等）在入队前脱敏

## 10. 验收标准

1. 28 号模块产生一条 freqtrade entry 事件 → 交易台飞书群收到开仓通知（API 直推，无需大模型）
2. 停掉模型端点访问 → 交互类信号进入挂起队列 → 恢复后自动重放并送达
3. 用户在 Hermes 说『订阅开仓信号』→ 订阅生效，后续开仓信号送达指定渠道
4. 同类信号 5 分钟内超 10 条 → 收到聚合摘要而非逐条轰炸
5. 前端设置页可管理 FEISHU 渠道与信号订阅，测试按钮可验证连通

## 11. 实施阶段

- P0（本次落地）：types.ts + bus.ts + feishu 适配器 + emit API + 订阅 API + Prisma 表 + 28 号模块对接 → 验收标准 1、5
- P1：health.ts 降级挂起 + hermes 适配器 + outbox 重放 → 验收标准 2
- P2：Hermes signal-bus-settings SKILL + digest 聚合 → 验收标准 3、4
