# API配置详细设计

> 版本: v2.0 | 日期: 2026-05-13 | 所属: Dream Universal Gateway
> **v2.0变更**: 明确本模块职责为"连接层密钥管理"，交易行为约束已分离至 [TRADING_CONFIG_DESIGN.md](TRADING_CONFIG_DESIGN.md)

---

## 1. 设计目标

提供一个统一的API**密钥**管理界面，让用户能够：
1. 配置交易所API（OKX/Binance/Bybit）用于实盘/模拟盘操作
2. 配置LLM API（OpenAI/Anthropic/百炼）用于对话推理
3. 配置数据源API（CoinGlass/Glassnode）用于市场数据获取
4. 所有密钥本地加密存储，前端只显示脱敏信息

> **职责边界**: 本模块仅负责API的**连接凭证管理**（密钥存储、连接测试、环境切换）。
> 交易行为约束（金额、杠杆、亏损限制等）由 [交易参数配置](TRADING_CONFIG_DESIGN.md) 独立管理。
> 通信渠道（TG/微信/Email推送）由 [通信渠道设计](CHANNEL_DESIGN.md) 独立管理。
> 三者互不耦合，用户可以只配置其中之一。

---

## 2. API配置Schema

### 2.1 交易所API

> **注意**: ExchangeAPIConfig仅管理连接凭证。交易行为参数（杠杆、亏损限制等）见 [TRADING_CONFIG_DESIGN.md](TRADING_CONFIG_DESIGN.md) 中的 `TradingParams`，通过 `exchangeConfigId` 关联本配置。

```typescript
interface ExchangeAPIConfig {
  id: string;                    // 唯一ID: "okx_main", "binance_spot"
  category: 'exchange';
  exchange: 'okx' | 'binance' | 'bybit';
  label: string;                 // 用户自定义名称: "OKX主账户"
  credentials: {
    apiKey: string;              // 加密存储
    secretKey: string;           // 加密存储
    passphrase?: string;         // OKX专用
  };
  environment: 'demo' | 'live'; // 模拟盘/实盘
  permissions: string[];         // ['read', 'trade', 'withdraw']
  verified: boolean;             // 是否已验证连接
  lastVerifiedAt?: string;       // 最后验证时间
  // ⚠️ 交易行为参数（杠杆/亏损限制/交易金额）不在此处，见 TradingParams
  createdAt: string;
  updatedAt: string;
}
```

### 2.2 LLM API

```typescript
interface LLMAPIConfig {
  id: string;
  category: 'llm';
  provider: 'openai' | 'anthropic' | 'aliyun';
  label: string;
  credentials: {
    apiKey: string;              // 加密存储
  };
  config: {
    model: string;               // gpt-4, claude-3-opus, qwen-plus
    apiBase?: string;            // 自定义endpoint
    maxTokens?: number;
    temperature?: number;
  };
  verified: boolean;
  lastVerifiedAt?: string;
  createdAt: string;
  updatedAt: string;
}
```

### 2.3 数据源API

```typescript
interface DataSourceAPIConfig {
  id: string;
  category: 'datasource';
  source: 'coinglass' | 'glassnode' | 'defillama' | 'dune';
  label: string;
  credentials: {
    apiKey: string;
  };
  config: {
    apiBase?: string;
    plan?: string;               // free/pro/enterprise
  };
  verified: boolean;
  lastVerifiedAt?: string;
  createdAt: string;
  updatedAt: string;
}
```

### 2.4 联合类型

```typescript
type APIConfig = ExchangeAPIConfig | LLMAPIConfig | DataSourceAPIConfig;

interface APIConfigStore {
  configs: APIConfig[];
  masterPasswordSet: boolean;    // 是否已设置主密码
  version: string;
}
```

---

## 3. 加密存储方案

### 3.1 存储文件

```
~/.workbuddy/config/
├── api-keys.enc           # AES-256-GCM 加密密钥库
├── api-keys.meta.json     # 元数据（不含密钥）
└── master-password.hash   # 主密码哈希（用于验证，不用于加密）
```

### 3.2 加密流程

```
用户设置主密码
      │
      ▼
┌──────────────────────────────────┐
│ 1. 主密码 + 设备指纹(Salt)        │
│ 2. PBKDF2 → 派生密钥(32bytes)    │
│ 3. AES-256-GCM 加密密钥库        │
│ 4. 写入 api-keys.enc             │
└──────────────────────────────────┘
```

### 3.3 解密流程

```
应用启动/用户输入主密码
      │
      ▼
┌──────────────────────────────────┐
│ 1. 主密码 + 设备指纹(Salt)        │
│ 2. PBKDF2 → 派生密钥(32bytes)    │
│ 3. 验证主密码哈希                  │
│ 4. AES-256-GCM 解密密钥库        │
│ 5. 密钥仅在内存中，不落盘         │
└──────────────────────────────────┘
```

### 3.4 元数据文件 `api-keys.meta.json`

```json
{
  "version": "1.0",
  "configs": [
    {
      "id": "okx_main",
      "category": "exchange",
      "exchange": "okx",
      "label": "OKX主账户",
      "environment": "demo",
      "verified": true,
      "lastVerifiedAt": "2026-05-13T18:00:00+08:00",
      "maskedApiKey": "••••••••kT9x"
    },
    {
      "id": "openai_gpt4",
      "category": "llm",
      "provider": "openai",
      "label": "OpenAI GPT-4",
      "verified": true,
      "maskedApiKey": "••••••••3Abm"
    }
  ]
}
```

---

## 4. 连接测试方案

### 4.1 OKX 测试

```typescript
async function testOKXConnection(config: ExchangeAPIConfig): Promise<TestResult> {
  // 使用 okx-trade-cli 验证
  // 1. 调用 okx account balance --profile <profile>
  // 2. 检查返回状态
  // 3. 返回: { success, account, balance, latency }
}
```

### 4.2 LLM 测试

```typescript
async function testLLMConnection(config: LLMAPIConfig): Promise<TestResult> {
  // 发送一个简单prompt: "Hello, respond with 'OK'"
  // 检查是否能正常返回
  // 返回: { success, model, latency }
}
```

### 4.3 数据源测试

```typescript
async function testDataSourceConnection(config: DataSourceAPIConfig): Promise<TestResult> {
  // 发送一个简单查询（如获取BTC价格）
  // 返回: { success, data, latency }
}
```

---

## 5. 后端API接口

### 5.1 获取配置列表

```
GET /api/config/api-keys

Response 200:
{
  "configs": [
    {
      "id": "okx_main",
      "category": "exchange",
      "exchange": "okx",
      "label": "OKX主账户",
      "environment": "demo",
      "verified": true,
      "maskedApiKey": "••••••••kT9x",
      "lastVerifiedAt": "2026-05-13T18:00:00+08:00"
    }
  ]
}
```

### 5.2 保存配置

```
POST /api/config/api-keys

Body:
{
  "category": "exchange",
  "exchange": "okx",
  "label": "OKX主账户",
  "credentials": {
    "apiKey": "xxx",
    "secretKey": "xxx",
    "passphrase": "xxx"
  },
  "environment": "demo"
}

Response 201:
{
  "id": "okx_main",
  "maskedApiKey": "••••••••kT9x",
  "verified": false
}
```

### 5.3 测试连接

```
POST /api/config/api-keys/test

Body:
{ "id": "okx_main" }

Response 200:
{
  "success": true,
  "message": "连接成功",
  "details": {
    "account": "dreamdemo",
    "balance": "$10,000.00",
    "latency": "156ms"
  }
}
```

### 5.4 更新配置

```
PATCH /api/config/api-keys/:id

Body:
{
  "credentials": { "apiKey": "new-xxx" },
  "environment": "live"
}
```

### 5.5 删除配置

```
DELETE /api/config/api-keys/:id

Response 200:
{ "success": true }
```

---

## 6. 前端组件设计

### 6.1 SettingsAPI 组件树

```
SettingsAPI
├── APICategorySection (交易所)
│   ├── APIConfigCard (OKX)
│   │   ├── CredentialInput (API Key)
│   │   ├── CredentialInput (Secret Key)
│   │   ├── CredentialInput (Passphrase) [OKX only]
│   │   ├── EnvironmentToggle (Demo/Live)
│   │   └── ActionBar (测试/保存/删除)
│   └── APIConfigCard (Binance) [折叠]
├── APICategorySection (LLM)
│   └── APIConfigCard (OpenAI)
└── APICategorySection (数据源)
    └── APIConfigCard (CoinGlass)
```

### 6.2 安全交互规则

1. **首次使用**: 引导用户设置主密码
2. **查看密钥**: 点击"显示"按钮，需二次确认
3. **修改密钥**: 必须输入主密码验证
4. **删除密钥**: 二次确认弹窗
5. **复制密钥**: 不支持复制完整密钥到剪贴板
6. **切到Live**: 弹窗警告"实盘操作有真实资金风险"
7. **配置交易参数**: API验证通过后，引导用户进入 [交易参数配置](TRADING_CONFIG_DESIGN.md) 完成交易行为约束设置

---

## 7. 模块关系

```
┌─────────────────────┐     exchangeConfigId     ┌─────────────────────────┐
│ API_CONFIG (本模块)  │◄────────────────────────│ TRADING_CONFIG           │
│ · 连接凭证管理       │                          │ · 交易行为约束           │
│ · 密钥加密存储       │                          │ · 杠杆/亏损限制          │
│ · 连接测试          │                          │ · 下单门禁              │
└─────────────────────┘                          └─────────────────────────┘

┌─────────────────────┐     门禁事件推送          ┌─────────────────────────┐
│ TRADING_CONFIG      │─────────────────────────►│ CHANNEL                  │
│ · 门禁拦截事件       │                          │ · 风险告警推送           │
│ · 冻结通知          │                          │ · 交易确认推送           │
└─────────────────────┘                          └─────────────────────────┘

三大独立模块: API配置(连接) / 交易参数(约束) / 通信渠道(通知)
用户可只配置其中之一，互不阻塞。
```
