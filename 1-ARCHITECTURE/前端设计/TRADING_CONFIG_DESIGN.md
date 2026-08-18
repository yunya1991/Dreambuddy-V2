# 交易参数配置详细设计

> 版本: v1.1 | 日期: 2026-05-13 | 所属: Dream Universal Gateway
> **核心定位**: 交易API设置 ≠ API密钥管理。本模块定义用户交易行为的边界约束，是下单门禁的配置来源
> **v1.1变更**: 新增与策略设置模块(STRATEGY_CONFIG_DESIGN.md)的集成关系

---

## 1. 设计哲学

### 1.1 为什么需要独立模块？

用户在系统中配置交易所API后，系统会根据A系列策略自动生成交易决策。但**交易行为必须在用户设定的安全边界内执行**。

```
传统做法:
  配置API → 直接交易（无边界约束）

本系统做法:
  配置API → 配置交易参数 → 系统在安全边界内执行 → 门禁过滤

  交易参数 = 用户的"安全宣言"
  门禁过滤 = 系统对"安全宣言"的严格执行
```

### 1.2 两个独立功能

| 功能 | 定位 | 入口 | 数据存储 |
|------|------|------|----------|
| **通信渠道** | 消息推送配置 | 📡 通信渠道 | channels.enc |
| **交易API设置** | 交易所连接+交易参数 | ⚙️ 交易设置 | api-keys.enc + trading-params.json |
| **策略设置** | 交易策略选择+定时执行 | 🎯 策略设置 | strategies.json |

**通信渠道**、**交易API设置**和**策略设置**是三个完全独立的功能设置面板，用户可以只配置其中之一。

### 1.3 交易参数 = 下单门禁的配置源

```
用户配置交易参数
      │
      ▼
┌──────────────────────────────────────┐
│  TradingParamsRegistry               │
│  (用户交易参数注册表)                  │
│                                      │
│  UID → {                             │
│    maxDailyLoss,                     │
│    maxAccountLoss,                   │
│    leverageRange,                    │
│    allowedTradeType,                 │
│    ...                               │
│  }                                   │
└──────────────┬───────────────────────┘
               │
               │ 策略触发交易
               ▼
┌──────────────────────────────────────┐
│  TradingGate (下单门禁)               │
│                                      │
│  1. 查询UID对应TradingParams          │
│  2. 校验交易参数 vs 配置边界           │
│  3. 全部通过 → 允许下单               │
│  4. 任一越界 → 拦截+告警              │
└──────────────────────────────────────┘
```

---

## 2. 交易参数Schema

### 2.1 完整定义

```typescript
interface TradingParams {
  // ========== 身份标识 ==========
  uid: string;                          // 用户唯一标识
  exchangeConfigId: string;             // 关联的交易所API配置ID
  exchange: 'okx';                      // 交易所（目前仅支持OKX）
  symbol: 'BTC-USDT-SWAP';             // 交易品种（目前仅BTC）

  // ========== 交易金额 ==========
  tradeAmountMode: 'percentage';        // 交易金额模式（固定为百分比）
  tradePercentage: number;             // 每次交易使用账户余额的百分比 (1-100)
  // 系统默认: 所有用户统一百分比，由系统管理员设定
  // 用户不可自定义百分比，确保策略一致性

  // ========== 交易类型 ==========
  tradeType: 'spot' | 'swap';          // 交易类型
  // 当前默认: spot（现货交易）
  // 后期扩展: swap（合约交易）

  // ========== 杠杆设置 ==========
  leverageMin: number;                  // 最小杠杆倍数 (1)
  leverageMax: number;                  // 最大杠杆倍数 (1-5)
  // 当前范围: 1x - 5x
  // 后期扩展: 可能支持更高倍率，但需要额外风控审查

  // ========== 亏损限制 ==========
  maxDailyLoss: number;                 // 允许最大日亏损 (USDT)
  maxDailyLossPercent: number;          // 允许最大日亏损占账户余额百分比 (1-100)
  maxAccountLoss: number;               // 允许最大账户亏损 (USDT)
  maxAccountLossPercent: number;        // 允许最大账户亏损占账户余额百分比 (1-100)
  // 两个维度: 绝对金额 + 百分比，取更严格者

  // ========== 元数据 ==========
  createdAt: string;                    // 创建时间
  updatedAt: string;                    // 最后更新时间
  updatedBy: 'system' | 'user';        // 更新来源
  status: 'active' | 'paused' | 'frozen'; // 状态
}
```

### 2.2 系统默认值

```typescript
const DEFAULT_TRADING_PARAMS: Omit<TradingParams, 'uid' | 'exchangeConfigId'> = {
  exchange: 'okx',
  symbol: 'BTC-USDT-SWAP',
  tradeAmountMode: 'percentage',
  tradePercentage: 10,                 // 默认每次交易使用10%余额
  tradeType: 'spot',                    // 默认现货
  leverageMin: 1,
  leverageMax: 3,                       // 默认最大3x
  maxDailyLoss: 500,                   // 默认最大日亏损500 USDT
  maxDailyLossPercent: 5,              // 默认最大日亏损5%
  maxAccountLoss: 2000,                // 默认最大账户亏损2000 USDT
  maxAccountLossPercent: 20,           // 默认最大账户亏损20%
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  updatedBy: 'system',
  status: 'active',
};
```

### 2.3 约束规则

| 参数 | 当前约束 | 后期扩展 | 校验规则 |
|------|----------|----------|----------|
| exchange | 仅OKX | Binance/Bybit | 配置时校验API Config存在 |
| symbol | 仅BTC-USDT-SWAP | ETH/SOL/多品种 | 按品种分别维护参数 |
| tradePercentage | 系统统一设定 | 用户可自定义 | 1 ≤ x ≤ 100 |
| tradeType | spot | swap | swap需额外风控 |
| leverageMax | 1-5x | 可能更高 | 1 ≤ x ≤ 5 (当前) |
| maxDailyLossPercent | 1-100% | - | maxDailyLoss与maxDailyLossPercent取更严 |
| maxAccountLossPercent | 1-100% | - | maxAccountLossPercent > maxDailyLossPercent |

---

## 3. 用户交易参数注册表 (TradingParamsRegistry)

### 3.1 设计目标

后期需要维护一个用户配置列表，交易策略触发后系统检索此列表，根据用户UID查询对应配置，下单时进行门禁过滤。

### 3.2 注册表Schema

```typescript
interface TradingParamsRegistry {
  version: string;                     // 注册表版本
  updatedAt: string;                   // 最后更新时间

  // 用户交易参数列表
  entries: TradingParamsEntry[];
}

interface TradingParamsEntry {
  uid: string;                         // 用户UID
  displayName: string;                  // 用户显示名
  exchangeAccountId: string;           // 交易所账户ID（API Config ID）

  // 交易参数
  params: TradingParams;

  // 门禁状态
  gateStatus: {
    lastGateCheckAt: string;           // 最近一次门禁检查时间
    dailyLossUsed: number;             // 今日已用日亏损额度 (USDT)
    dailyLossResetAt: string;          // 日亏损重置时间（每日00:00 UTC）
    accountLossUsed: number;           // 累计账户亏损 (USDT)
    isDailyLimited: boolean;           // 今日是否已触及日亏损限制
    isAccountLimited: boolean;         // 是否已触及账户亏损限制
    freezeReason?: string;             // 冻结原因
  };

  // 审计
  lastTradeAt?: string;               // 最近交易时间
  totalTrades: number;                // 总交易次数
  totalGateBlocks: number;            // 被门禁拦截次数
}
```

### 3.3 存储文件

```
~/.workbuddy/config/
├── trading-params.json              # 用户交易参数注册表（明文，非敏感）
├── trading-params.audit.json        # 门禁审计日志
└── trading-params.defaults.json     # 系统默认参数模板
```

> **设计决策**: 交易参数不含API密钥等敏感信息，使用明文JSON存储。API密钥仍在 api-keys.enc 中加密存储。

### 3.4 注册表示例

```json
{
  "version": "1.0",
  "updatedAt": "2026-05-13T20:00:00+08:00",
  "entries": [
    {
      "uid": "user_001",
      "displayName": "张江涛",
      "exchangeAccountId": "okx_main",
      "params": {
        "uid": "user_001",
        "exchangeConfigId": "okx_main",
        "exchange": "okx",
        "symbol": "BTC-USDT-SWAP",
        "tradeAmountMode": "percentage",
        "tradePercentage": 10,
        "tradeType": "spot",
        "leverageMin": 1,
        "leverageMax": 3,
        "maxDailyLoss": 500,
        "maxDailyLossPercent": 5,
        "maxAccountLoss": 2000,
        "maxAccountLossPercent": 20,
        "createdAt": "2026-05-13T10:00:00+08:00",
        "updatedAt": "2026-05-13T20:00:00+08:00",
        "updatedBy": "user",
        "status": "active"
      },
      "gateStatus": {
        "lastGateCheckAt": "2026-05-13T19:45:00+08:00",
        "dailyLossUsed": 120.5,
        "dailyLossResetAt": "2026-05-13T00:00:00Z",
        "accountLossUsed": 350.0,
        "isDailyLimited": false,
        "isAccountLimited": false
      },
      "lastTradeAt": "2026-05-13T18:30:00+08:00",
      "totalTrades": 15,
      "totalGateBlocks": 2
    }
  ]
}
```

---

## 4. 下单门禁过滤 (TradingGate)

### 4.1 门禁流程

```
策略触发交易信号 (BUY/SHORT)
      │
      ▼
┌──────────────────────────────────────┐
│  Step 1: 查询用户配置                  │
│  · 从 TradingParamsRegistry 查 UID    │
│  · 检查 status = active?             │
│  · 如果 paused/frozen → 拒绝         │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Step 2: 交易所连接校验                │
│  · API Config是否存在且verified?      │
│  · environment = demo/live?          │
│  · live环境需额外确认                 │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Step 3: 交易类型校验                  │
│  · 请求的tradeType在允许范围内?        │
│  · swap需额外风控审查                  │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Step 4: 杠杆校验                      │
│  · 请求的leverage在[1, max]范围内?    │
│  · leverage > 3x需用户确认           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Step 5: 交易金额校验                  │
│  · 计算本次交易金额                    │
│  · 金额 ≤ 账户余额 × tradePercentage │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Step 6: 日亏损校验                    │
│  · 今日已亏 + 本次预估亏损 ≤ 日限?     │
│  · 绝对值 vs 百分比 取更严            │
│  · 超限 → isDailyLimited = true       │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Step 7: 账户亏损校验                  │
│  · 累计亏损 + 本次预估 ≤ 账户限?       │
│  · 超限 → isAccountLimited = true     │
│  · 触发账户级冻结                      │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Step 8: 品种校验                      │
│  · 请求的symbol在允许列表内?           │
│  · 当前仅BTC-USDT-SWAP               │
└──────────────┬───────────────────────┘
               │
         全部通过 ✅
               │
               ▼
         允许下单 → 执行
```

### 4.2 门禁代码实现

```typescript
interface GateCheckResult {
  passed: boolean;
  reason?: string;                      // 拒绝原因（用户可见）
  internalReason?: string;             // 内部原因（日志用）
  warnings?: string[];                  // 警告（不阻断但需注意）
  checkedAt: string;
}

interface TradeRequest {
  uid: string;                         // 用户UID
  symbol: string;                      // 交易品种
  direction: 'BUY' | 'SHORT';         // 方向
  tradeType: 'spot' | 'swap';         // 交易类型
  leverage: number;                    // 杠杆倍数
  estimatedAmount: number;             // 预估交易金额(USDT)
  estimatedLoss: number;               // 预估最坏亏损(USDT)
}

async function tradingGateCheck(request: TradeRequest): Promise<GateCheckResult> {
  const warnings: string[] = [];
  const now = new Date().toISOString();

  // Step 1: 查询用户配置
  const entry = await registry.findByUid(request.uid);
  if (!entry) {
    return { passed: false, reason: '未找到交易配置，请先完成交易设置', internalReason: 'UID_NOT_FOUND', checkedAt: now };
  }
  if (entry.params.status !== 'active') {
    return { passed: false, reason: '交易功能已暂停', internalReason: 'STATUS_NOT_ACTIVE', checkedAt: now };
  }

  // Step 2: 交易所连接校验
  const apiConfig = await getAPIConfig(entry.exchangeAccountId);
  if (!apiConfig || !apiConfig.verified) {
    return { passed: false, reason: '交易所API未验证，请检查API配置', internalReason: 'API_NOT_VERIFIED', checkedAt: now };
  }

  // Step 3: 交易类型校验
  if (request.tradeType !== entry.params.tradeType) {
    return { passed: false, reason: `当前仅支持${entry.params.tradeType === 'spot' ? '现货' : '合约'}交易`, internalReason: 'TRADE_TYPE_MISMATCH', checkedAt: now };
  }
  if (request.tradeType === 'swap') {
    warnings.push('合约交易风险较高，请确认');
  }

  // Step 4: 杠杆校验
  if (request.leverage < entry.params.leverageMin || request.leverage > entry.params.leverageMax) {
    return { passed: false, reason: `杠杆倍数需在${entry.params.leverageMin}x-${entry.params.leverageMax}x之间`, internalReason: 'LEVERAGE_OUT_OF_RANGE', checkedAt: now };
  }
  if (request.leverage > 3) {
    warnings.push(`当前杠杆${request.leverage}x，风险较高`);
  }

  // Step 5: 交易金额校验
  const accountBalance = await getAccountBalance(apiConfig);
  const maxTradeAmount = accountBalance * (entry.params.tradePercentage / 100);
  if (request.estimatedAmount > maxTradeAmount) {
    return { passed: false, reason: `交易金额超出允许范围（最大${entry.params.tradePercentage}%余额）`, internalReason: 'AMOUNT_EXCEEDS_LIMIT', checkedAt: now };
  }

  // Step 6: 日亏损校验
  const dailyLossLimit = Math.min(
    entry.params.maxDailyLoss,
    accountBalance * (entry.params.maxDailyLossPercent / 100)
  );
  if (entry.gateStatus.dailyLossUsed + request.estimatedLoss > dailyLossLimit) {
    await registry.updateDailyLimited(request.uid, true);
    return { passed: false, reason: '今日亏损已达上限，请明日再试', internalReason: 'DAILY_LOSS_EXCEEDED', checkedAt: now };
  }

  // Step 7: 账户亏损校验
  const accountLossLimit = Math.min(
    entry.params.maxAccountLoss,
    accountBalance * (entry.params.maxAccountLossPercent / 100)
  );
  if (entry.gateStatus.accountLossUsed + request.estimatedLoss > accountLossLimit) {
    await registry.updateAccountLimited(request.uid, true);
    return { passed: false, reason: '账户亏损已达上限，交易功能已冻结', internalReason: 'ACCOUNT_LOSS_EXCEEDED', checkedAt: now };
  }

  // Step 8: 品种校验
  if (request.symbol !== entry.params.symbol) {
    return { passed: false, reason: `当前仅支持${entry.params.symbol}交易`, internalReason: 'SYMBOL_NOT_ALLOWED', checkedAt: now };
  }

  // 更新门禁检查时间
  await registry.updateGateCheckTime(request.uid, now);

  return {
    passed: true,
    warnings: warnings.length > 0 ? warnings : undefined,
    checkedAt: now,
  };
}
```

### 4.3 门禁结果映射（用户语言）

| 内部原因 | 用户可见消息 | 严重度 |
|----------|-------------|--------|
| UID_NOT_FOUND | 未找到交易配置，请先完成交易设置 | 🔴阻断 |
| STATUS_NOT_ACTIVE | 交易功能已暂停 | 🔴阻断 |
| API_NOT_VERIFIED | 交易所API未验证，请检查API配置 | 🔴阻断 |
| TRADE_TYPE_MISMATCH | 当前仅支持现货/合约交易 | 🔴阻断 |
| LEVERAGE_OUT_OF_RANGE | 杠杆倍数需在1x-5x之间 | 🔴阻断 |
| AMOUNT_EXCEEDS_LIMIT | 交易金额超出允许范围 | 🔴阻断 |
| DAILY_LOSS_EXCEEDED | 今日亏损已达上限，请明日再试 | 🔴阻断 |
| ACCOUNT_LOSS_EXCEEDED | 账户亏损已达上限，交易功能已冻结 | 🔴阻断 |
| SYMBOL_NOT_ALLOWED | 当前仅支持BTC交易 | 🔴阻断 |

---

## 5. 交易参数与A系列策略的关系

### 5.1 策略触发 → 配置检索 → 门禁过滤

```
A5执行决策: BUY BTC-USDT-SWAP, 2x, 0.3x仓位
      │
      ▼
┌──────────────────────────────────────┐
│  策略 → 交易参数适配器                 │
│                                      │
│  输入: A5决策 (BUY, 2x, 0.3x)        │
│                                      │
│  1. 检索用户TradingParams             │
│  2. 将A5策略参数映射到交易参数:         │
│     · direction → BUY                │
│     · leverage → 2x (≤ leverageMax)  │
│     · position → 0.3x               │
│     · 计算estimatedAmount            │
│     · 计算estimatedLoss (最坏情况)    │
│                                      │
│  3. 构造TradeRequest                  │
│  4. 调用tradingGateCheck()            │
│                                      │
│  输出: GateCheckResult               │
└──────────────┬───────────────────────┘
               │
        ┌──────┴──────┐
        │             │
     passed=true   passed=false
        │             │
        ▼             ▼
   执行下单      拦截+通知用户
```

### 5.2 A5策略参数 vs 用户交易参数

| A5策略输出 | 用户交易参数 | 门禁校验 |
|-----------|-------------|----------|
| direction (BUY/SHORT) | (无限制) | 方向不限制 |
| leverage | leverageMin - leverageMax | 杠杆必须在范围内 |
| position (0.3x) | tradePercentage (10%) | 仓位金额≤余额×百分比 |
| symbol (BTC-USDT-SWAP) | symbol (BTC-USDT-SWAP) | 品种必须在允许列表 |
| tradeType (spot/swap) | tradeType (spot) | 类型必须匹配 |
| (风险估算) | maxDailyLoss | 预估亏损≤日限额 |
| (风险估算) | maxAccountLoss | 累计亏损≤账户限额 |

### 5.3 策略参数越界时的处理

```typescript
// 当A5策略要求的参数超出用户配置边界时
function adaptStrategyToParams(
  strategyOutput: StrategyOutput,
  userParams: TradingParams
): TradeRequest {
  
  // 杠杆越界 → 降级到用户允许的最大值
  let leverage = strategyOutput.leverage;
  if (leverage > userParams.leverageMax) {
    leverage = userParams.leverageMax;  // 降级
    // 记录: 策略要求5x但用户限制3x，已降级
  }
  
  // 仓位比例 → 转换为交易金额
  const accountBalance = await getAccountBalance(userParams.exchangeConfigId);
  const maxTradeAmount = accountBalance * (userParams.tradePercentage / 100);
  const requestedAmount = accountBalance * strategyOutput.position;
  const actualAmount = Math.min(requestedAmount, maxTradeAmount);
  
  // 估算最坏亏损
  const estimatedLoss = actualAmount * leverage * 0.1; // 简化: 假设最坏10%波动
  
  return {
    uid: userParams.uid,
    symbol: userParams.symbol,
    direction: strategyOutput.direction,
    tradeType: userParams.tradeType,
    leverage,
    estimatedAmount: actualAmount,
    estimatedLoss,
  };
}
```

---

## 6. 后端API接口

### 6.1 获取用户交易参数

```
GET /api/config/trading-params

Response 200:
{
  "params": {
    "uid": "user_001",
    "exchangeConfigId": "okx_main",
    "exchange": "okx",
    "symbol": "BTC-USDT-SWAP",
    "tradePercentage": 10,
    "tradeType": "spot",
    "leverageMin": 1,
    "leverageMax": 3,
    "maxDailyLoss": 500,
    "maxDailyLossPercent": 5,
    "maxAccountLoss": 2000,
    "maxAccountLossPercent": 20,
    "status": "active"
  },
  "gateStatus": {
    "dailyLossUsed": 120.5,
    "isDailyLimited": false,
    "accountLossUsed": 350.0,
    "isAccountLimited": false
  }
}
```

### 6.2 更新交易参数

```
PATCH /api/config/trading-params

Body:
{
  "leverageMax": 5,
  "maxDailyLoss": 800,
  "maxDailyLossPercent": 8,
  "maxAccountLoss": 3000,
  "maxAccountLossPercent": 25
}

Response 200:
{
  "success": true,
  "updatedFields": ["leverageMax", "maxDailyLoss", "maxDailyLossPercent", "maxAccountLoss", "maxAccountLossPercent"],
  "warnings": ["杠杆上限提升至5x，风险较高，请谨慎操作"]
}
```

### 6.3 重置日亏损计数

```
POST /api/config/trading-params/reset-daily

Response 200:
{
  "success": true,
  "dailyLossUsed": 0,
  "isDailyLimited": false
}
```

### 6.4 暂停/恢复交易

```
POST /api/config/trading-params/pause

Body:
{ "reason": "用户主动暂停" }

Response 200:
{ "success": true, "status": "paused" }
```

```
POST /api/config/trading-params/resume

Response 200:
{ "success": true, "status": "active" }
```

### 6.5 门禁检查（内部接口，供A5调用）

```
POST /api/trading/gate-check

Body:
{
  "uid": "user_001",
  "symbol": "BTC-USDT-SWAP",
  "direction": "BUY",
  "tradeType": "spot",
  "leverage": 2,
  "estimatedAmount": 1000,
  "estimatedLoss": 100
}

Response 200:
{
  "passed": true,
  "warnings": [],
  "checkedAt": "2026-05-13T20:00:00+08:00"
}
```

### 6.6 获取门禁审计日志

```
GET /api/config/trading-params/audit?limit=50

Response 200:
{
  "logs": [
    {
      "timestamp": "2026-05-13T18:30:00+08:00",
      "uid": "user_001",
      "action": "gate_check",
      "result": "passed",
      "details": { "direction": "BUY", "leverage": 2, "amount": 1000 }
    },
    {
      "timestamp": "2026-05-13T15:00:00+08:00",
      "uid": "user_001",
      "action": "gate_check",
      "result": "blocked",
      "reason": "DAILY_LOSS_EXCEEDED",
      "details": { "dailyLossUsed": 480, "dailyLossLimit": 500 }
    }
  ]
}
```

---

## 7. 当前约束与扩展路径

### 7.1 v1.0 约束（当前）

| 维度 | 约束 | 说明 |
|------|------|------|
| 交易所 | 仅OKX | 通过okx-trade-cli交互 |
| 品种 | 仅BTC-USDT-SWAP | A系列策略围绕BTC设计 |
| 交易类型 | 仅现货(spot) | 后期扩展合约(swap) |
| 杠杆 | 1x - 5x | 超过3x需额外确认 |
| 交易金额 | 百分比模式，系统统一定 | 所有用户一致 |
| 用户数 | 单用户 | 后期多用户 |

### 7.2 扩展路径

```
v1.0 (当前)              v1.5                v2.0
─────────────────────────────────────────────────────
OKX only         →  OKX + Binance  →  多交易所
BTC only         →  BTC + ETH     →  多品种
Spot only        →  Spot + Swap   →  全交易类型
1-5x leverage    →  1-10x         →  自定义范围
系统统一百分比    →  用户可自定义   →  策略自适应
单用户           →  多用户         →  用户组+权限
```

### 7.3 扩展预留点

```typescript
// v1.5 扩展: 多品种
interface TradingParamsV15 extends TradingParams {
  symbols: TradingSymbolConfig[];       // 多品种参数
  defaultSymbol: string;                // 默认品种
}

interface TradingSymbolConfig {
  symbol: string;                       // BTC-USDT-SWAP | ETH-USDT-SWAP | ...
  tradeType: 'spot' | 'swap';
  leverageRange: [number, number];
  maxPosition: number;                  // 最大仓位比例
}

// v2.0 扩展: 多用户
interface TradingParamsRegistryV2 {
  version: string;
  entries: TradingParamsEntry[];
  groups: TradingGroup[];               // 用户组
  adminSettings: AdminSettings;         // 管理员设置
}
```

---

## 8. 与其他模块的集成

### 8.1 与API_CONFIG_DESIGN.md的关系

```
API_CONFIG_DESIGN (连接层)          TRADING_CONFIG (业务层)
┌─────────────────────┐            ┌─────────────────────────┐
│ ExchangeAPIConfig   │◄──────────│ TradingParams            │
│ · apiKey            │  关联ID    │ · exchangeConfigId       │
│ · secretKey         │            │ · tradePercentage       │
│ · passphrase        │            │ · leverageMax           │
│ · environment       │            │ · maxDailyLoss          │
│ · verified          │            │ · maxAccountLoss        │
└─────────────────────┘            └─────────────────────────┘
      密钥管理                        交易行为约束
      (敏感,加密)                     (非敏感,明文)
```

**关系**: 一个ExchangeAPIConfig可以关联一个TradingParams。TradingParams通过`exchangeConfigId`引用API配置。

### 8.2 与CHANNEL_DESIGN.md的关系

```
TRADING_CONFIG (业务层)            CHANNEL (通知层)
┌─────────────────────────┐      ┌─────────────────────────┐
│ TradingGate              │─────►│ PushRuleEngine           │
│ · 门禁拦截 → 通知用户    │      │ · 风险告警推送           │
│ · 日亏损超限 → 告警     │      │ · 交易确认推送           │
│ · 账户冻结 → 紧急通知   │      │ · 冻结通知               │
└─────────────────────────┘      └─────────────────────────┘
```

**关系**: 交易门禁事件通过通信渠道通知用户。门禁拦截=风险告警(P0)；账户冻结=紧急通知(P0)。

### 8.3 与INTENT_ROUTER.md的关系

```
INTENT_ROUTER (路由层)             TRADING_CONFIG (约束层)
┌─────────────────────────┐      ┌─────────────────────────┐
│ IntentRouter            │      │ TradingGate               │
│ · 交易执行意图识别      │─────►│ · 交易前门禁检查          │
│ · 映射到trade_execution │      │ · 参数越界降级           │
│ · 触发内部链路          │      │ · 拦截/放行              │
└─────────────────────────┘      └─────────────────────────┘
```

**关系**: IntentRouter识别到交易执行意图后，触发A系列策略，策略输出需通过TradingGate门禁校验。

### 8.4 与CHAIN_ORCHESTRATOR.md的关系

```
CHAIN_ORCHESTRATOR (执行层)        TRADING_CONFIG (约束层)
┌─────────────────────────┐      ┌─────────────────────────┐
│ A5 综合判断执行          │─────►│ TradingGate               │
│ · 输出交易决策           │      │ · 校验A5决策合规性        │
│ · BUY/SHORT/SKIP        │      │ · 参数适配(降级)          │
│ · leverage + position   │      │ · 记录审计日志            │
└─────────────────────────┘      └─────────────────────────┘

A9 离场决策                 ─────►│ TradingGate               │
│ · 止盈/止损决策         │      │ · 离场也需门禁校验        │
│ · Edge衰减平仓          │      │ · 防止非授权离场          │
└─────────────────────────┘      └─────────────────────────┘
```

### 8.5 与STRATEGY_CONFIG_DESIGN.md的关系

```
STRATEGY_CONFIG (策略层)            TRADING_CONFIG (约束层)
┌─────────────────────────┐      ┌─────────────────────────┐
│ Strategy                 │─────►│ TradingGate               │
│ · 策略推荐杠杆/仓位     │      │ · 校验策略参数在边界内    │
│ · 策略推荐方向          │      │ · 越界时自动降级          │
│ · 策略执行频率          │      │ · 日/账户亏损检查         │
└─────────────────────────┘      └─────────────────────────┘

策略应用时:
  策略参数 → adaptStrategyToParams() → TradingGate门禁 → 通过/降级/拦截
```

---

## 9. 前端组件设计

### 9.1 SettingsTrading 组件树

```
SettingsTrading
├── TradingParamsHeader
│   ├── ExchangeStatus (OKX已连接 ✅)
│   └── SymbolBadge (BTC-USDT-SWAP)
│
├── TradeAmountSection
│   └── TradePercentageDisplay (系统设定: 10%余额)
│
├── TradeTypeSection
│   ├── TradeTypeToggle (现货 ● / 合约 ○)
│   └── TradeTypeNote ("当前仅支持现货交易")
│
├── LeverageSection
│   ├── LeverageSlider (1x ━━━━━●━ 3x)
│   └── LeverageWarning ("3x以上风险较高")
│
├── LossLimitSection
│   ├── DailyLossInput (最大日亏损: 500 USDT / 5%)
│   ├── AccountLossInput (最大账户亏损: 2000 USDT / 20%)
│   └── LossPreview (≈账户余额的5%/20%)
│
├── TradingStatusSection
│   ├── StatusToggle (● 运行中 / ○ 已暂停)
│   ├── DailyLossProgress (今日亏损: 120.5/500 USDT ▓▓▓░░)
│   └── AccountLossProgress (账户亏损: 350/2000 USDT ▓░░░░)
│
└── DangerZone
    ├── ResetDailyLoss [重置日亏损计数]
    └── FreezeAccount [冻结交易功能]
```

### 9.2 交互规则

1. **首次配置**: 引导用户先完成API配置，再设置交易参数
2. **修改杠杆**: ≥3x时弹窗警告
3. **修改亏损限额**: 实时显示对账户的影响预览
4. **暂停交易**: 二次确认
5. **冻结账户**: 需输入确认文字"冻结"
6. **tradePercentage**: 显示为只读（系统统一定），标注"系统统一设定，确保策略一致性"

---

## 10. 安全设计

### 10.1 参数安全

| 措施 | 说明 |
|------|------|
| 参数范围限制 | 前后端双重校验，杠杆1-5x、百分比1-100% |
| 双维度亏损限制 | 绝对金额+百分比取更严，防止单一维度绕过 |
| 日亏损自动重置 | 每日00:00 UTC自动重置dailyLossUsed |
| 账户冻结机制 | 触及账户亏损上限自动冻结，需人工解冻 |
| 降级而非拒绝 | 杠杆越界时降级到用户上限，而非直接拒绝交易 |

### 10.2 审计追踪

| 事件 | 记录内容 |
|------|----------|
| 门禁检查 | 时间+UID+请求参数+结果+原因 |
| 参数修改 | 时间+UID+修改字段+旧值+新值 |
| 状态变更 | 时间+UID+旧状态+新状态+原因 |
| 交易执行 | 时间+UID+交易参数+门禁结果 |
| 亏损累计 | 时间+UID+累计值+限额+百分比 |
