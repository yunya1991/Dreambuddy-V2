# 用户体系与UID关联设计

> 版本: v1.0 | 日期: 2026-05-14 | 所属: Dream Universal Gateway
> **核心变更**: 用户首次点击"我的积分"触发注册登录(邮箱优先)，分配UID，UID关联API配置/可用资金/杠杆/策略等，形成用户配置列表

---

## 1. 设计哲学

### 1.1 为什么需要用户体系？

Gateway从"个人工具"走向"批量用户SaaS"，必须解决三个核心问题：

```
1. 身份问题 — 谁在用？ → 注册登录 + UID
2. 配置问题 — 用什么？ → UID → 用户配置列表(资金/杠杆/策略)
3. 资产问题 — 有多少？ → UID → 积分账户(余额/充值/消耗)
```

### 1.2 核心原则

| 原则 | 说明 |
|------|------|
| **最小侵入** | 用户未登录时，仍可使用免费功能(行情/状态查询) |
| **首次触发** | 点击需登录的功能(积分/策略/交易设置)时才弹出登录 |
| **UID贯穿** | 所有用户配置(API/资金/杠杆/策略/积分)均以UID为主键关联 |
| **配置可迁移** | UID不变，配置可导入导出，支持多设备同步 |
| **渐进式认证** | 邮箱注册(P0) → 手机号(P1) → 微信OAuth(P2) |

---

## 2. 注册登录流程

### 2.1 触发时机

用户在**未登录状态**下，点击以下功能时触发登录弹窗：

| 触发入口 | 优先级 | 理由 |
|----------|--------|------|
| 💎 我的积分 | P0 | 积分是付费核心，必须登录 |
| 🎯 策略设置 | P0 | 策略关联UID，需身份识别 |
| 💰 交易设置 | P0 | 资金/杠杆等敏感配置 |
| ⚙️ API配置 | P0 | API密钥属用户私有数据 |
| 📡 通信渠道 | P1 | 推送配置属用户私有数据 |
| /分析 /推演 等付费命令 | P1 | 消耗积分的AI分析功能 |

**不触发登录的免费功能**：/行情、/状态、对话基础交互

### 2.2 登录弹窗设计

```
┌──────────────────────────────────────────────┐
│                                              │
│           🧠 Dream Gateway                   │
│                                              │
│        ─── 登录后解锁更多功能 ───             │
│                                              │
│  📧 邮箱登录                                 │
│  ┌────────────────────────────────────────┐  │
│  │  邮箱                                   │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │  your@email.com                  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  密码                                  │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │  ••••••••••                      │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  [登录]                                │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ─────────── 或 ──────────                   │
│                                              │
│  🆕 新用户？                                  │
│  ┌────────────────────────────────────────┐  │
│  │  邮箱                                   │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │  your@email.com                  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  设置密码                               │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │  至少8位，含字母和数字             │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  确认密码                               │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │  再次输入密码                      │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  ☑ 我已阅读并同意《用户协议》和        │  │
│  │    《隐私政策》                         │  │
│  │                                        │  │
│  │  [注册]                                │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ─────────── 其他方式 ──────────             │
│                                              │
│  📱 手机号登录 (即将支持)                     │
│  💬 微信登录 (即将支持)                        │
│                                              │
└──────────────────────────────────────────────┘
```

### 2.3 注册流程

```
用户点击注册
      │
      ▼
┌──────────────────────────────────────┐
│  Step 1: 输入校验                     │
│  · 邮箱格式校验 (正则)                │
│  · 密码强度校验 (≥8位, 含字母+数字)   │
│  · 两次密码一致性                     │
│  · 用户协议勾选检查                   │
└──────────┬───────────────────────────┘
           │ 校验通过
           ▼
┌──────────────────────────────────────┐
│  Step 2: 邮箱唯一性检查                │
│  · 查询数据库: email是否已注册？       │
│  · 已注册 → 提示"该邮箱已注册，请登录" │
│  · 未注册 → 继续                      │
└──────────┬───────────────────────────┘
           │ 邮箱可用
           ▼
┌──────────────────────────────────────┐
│  Step 3: 创建用户记录                 │
│  · 密码bcrypt加密存储(saltRounds=12)  │
│  · 生成UID (格式: U + 10位随机)       │
│  · 创建积分账户(赠送2000积分)         │
│  · 创建空的用户配置列表                │
│  · 发送验证邮件(含6位验证码)          │
└──────────┬───────────────────────────┘
           │ 创建成功
           ▼
┌──────────────────────────────────────┐
│  Step 4: 邮箱验证                     │
│  ┌──────────────────────────────┐     │
│  │  📧 验证邮件已发送！          │     │
│  │                              │     │
│  │  我们向 your@email.com       │     │
│  │  发送了6位验证码             │     │
│  │                              │     │
│  │  ┌──────────────────────┐   │     │
│  │  │  _ _ _ _ _ _        │   │     │
│  │  └──────────────────────┘   │     │
│  │                              │     │
│  │  [重新发送] (60s后)         │     │
│  │                              │     │
│  │  ⚠️ 未验证邮箱可登录但      │     │
│  │  无法使用交易/充值功能       │     │
│  └──────────────────────────────┘     │
└──────────┬───────────────────────────┘
           │ 验证成功
           ▼
┌──────────────────────────────────────┐
│  Step 5: 自动登录 + 跳转              │
│  · 设置Auth.js session               │
│  · 跳转到触发登录前的目标页面         │
│  · 显示欢迎提示: "注册成功！赠送     │
│    2000积分，邮箱已验证"              │
└──────────────────────────────────────┘
```

### 2.4 登录流程

```
用户点击登录
      │
      ▼
┌──────────────────────────────────────┐
│  Step 1: 凭证校验                     │
│  · 查询数据库: email + bcrypt验证    │
│  · 失败 → "邮箱或密码错误"(模糊提示)  │
│  · 成功 → 继续                       │
└──────────┬───────────────────────────┘
           │ 验证通过
           ▼
┌──────────────────────────────────────┐
│  Step 2: 安全检查                     │
│  · 账户是否被封禁？                   │
│  · 连续失败次数 ≥5？→ 锁定30分钟     │
│  · IP异常？→ 触发验证码              │
└──────────┬───────────────────────────┘
           │ 安全通过
           ▼
┌──────────────────────────────────────┐
│  Step 3: 建立会话                     │
│  · Auth.js创建session                │
│  · session包含: uid, email, role     │
│  · JWT签名, HttpOnly Cookie          │
│  · 跳转到触发登录前的目标页面         │
└──────────────────────────────────────┘
```

### 2.5 认证方案技术栈

```json
{
  "auth_framework": "Auth.js v5 (NextAuth v5)",
  "strategy": "Credentials Provider (邮箱+密码)",
  "session": "JWT (HttpOnly Cookie)",
  "password_hash": "bcrypt (saltRounds=12)",
  "email_verify": "6位数字验证码 + SMTP",
  "session_duration": "7天 (可记住登录)",
  "csrf": "Auth.js内置CSRF保护",
  "rate_limit": "登录5次/分钟, 注册3次/小时"
}
```

---

## 3. UID体系设计

### 3.1 UID格式

```
U + 10位随机字母数字

示例: U3kR7mP2xQ
```

| 属性 | 说明 |
|------|------|
| **前缀** | `U` (User标识，区别于内部A系列ID) |
| **长度** | 11字符(1+10) |
| **字符集** | 0-9, a-z, A-Z (去除易混淆的0/O/1/l/I) → 56字符集 |
| **唯一性** | 数据库UNIQUE约束 + 应用层生成重试 |
| **不可变** | UID一旦分配，不可修改 |
| **对外展示** | 用户可见，用于分享策略/邀请好友 |

### 3.2 为什么不用自增ID？

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| 自增ID | 简单 | 暴露用户数量、可枚举、URL不友好 | ❌ |
| UUID | 全局唯一 | 太长(36字符)、不可读、索引性能差 | ❌ |
| **U+随机10位** | 短、可读、不可枚举 | 极小概率冲突(可重试) | ✅ |
| 邮箱哈希 | 无需额外ID | 邮箱变更后关联断裂 | ❌ |

### 3.3 UID在系统中的流转

```
                    ┌─────────────┐
                    │  User 表     │
                    │  uid (PK)    │
                    │  email       │
                    │  password    │
                    └──────┬───────┘
                           │ 1:1
          ┌────────────────┼────────────────┐
          │                │                │
   ┌──────▼───────┐ ┌─────▼──────┐ ┌───────▼──────┐
   │ UserProfile   │ │ ApiConfig  │ │ CreditsAcct  │
   │ uid (FK)      │ │ uid (FK)   │ │ uid (FK)     │
   │ 可用资金      │ │ OKX密钥    │ │ 积分余额     │
   │ 杠杆上限      │ │ LLM密钥    │ │ 积分流水     │
   │ 策略偏好      │ │ 数据源密钥 │ │ 充值记录     │
   └──────────────┘ └────────────┘ └──────────────┘
          │                                │
          │ 1:N                            │ 1:N
   ┌──────▼───────┐                 ┌─────▼──────┐
   │ TradingParams│                 │ Strategy   │
   │ uid (FK)     │                 │ uid (FK)   │
   │ 日亏损限制   │                 │ 推荐策略   │
   │ 账户亏损限制 │                 │ 自定义策略 │
   └──────────────┘                 └────────────┘
          │
          │ 1:N
   ┌──────▼───────┐
   │ ChannelConfig│
   │ uid (FK)     │
   │ TG/微信/Email│
   └──────────────┘
```

---

## 4. 用户配置列表 (UserProfile)

### 4.1 核心定义

**UserProfile是UID关联的所有配置的聚合视图**，是"记忆该uid、API、以及配置可用资金、杠杆、策略等"的具体实现。

```typescript
interface UserProfile {
  // === 基础信息 ===
  uid: string;                          // 用户ID (U3kR7mP2xQ)
  email: string;                        // 登录邮箱
  displayName?: string;                 // 显示名称 (可选)
  avatarUrl?: string;                   // 头像URL (可选)
  role: 'free' | 'pro' | 'admin';      // 角色
  emailVerified: boolean;               // 邮箱是否已验证
  createdAt: string;                    // 注册时间

  // === 交易配置 (从TradingParams关联) ===
  tradingConfig: {
    availableCapital?: number;          // 可用资金 (USDT)
    capitalPercentage: number;         // 交易百分比 (默认10%)
    tradeType: 'spot' | 'swap';        // 交易类型 (默认spot)
    leverageMax: number;               // 杠杆上限 (1-5x, 默认3x)
    dailyLossLimit: number;             // 日亏损限制 (USDT, 默认500)
    dailyLossPercent: number;          // 日亏损限制 (%), 默认5%
    accountLossLimit: number;          // 账户亏损限制 (USDT, 默认2000)
    accountLossPercent: number;        // 账户亏损限制 (%), 默认20%
    allowedSymbols: string[];          // 允许交易品种 (默认["BTC-USDT-SWAP"])
    isTradingEnabled: boolean;        // 交易是否启用 (默认false)
  };

  // === API配置状态 (从ApiConfig关联) ===
  apiConfigStatus: {
    exchange: {
      provider: string;                // 'okx' | 'binance' | 'bybit'
      isConfigured: boolean;           // 是否已配置
      isVerified: boolean;             // 是否已验证
      environment: 'demo' | 'live';    // 环境
      lastVerifiedAt?: string;         // 最近验证时间
    } | null;
    llm: {
      provider: string;               // 'openai' | 'anthropic' | 'bailian'
      isConfigured: boolean;
    } | null;
    dataSource: {
      provider: string;               // 'coinglass' | 'glassnode'
      isConfigured: boolean;
    } | null;
  };

  // === 策略配置 (从Strategy关联) ===
  strategyConfig: {
    activeStrategyCount: number;       // 运行中策略数
    totalStrategyCount: number;        // 总策略数
    activeStrategies: {
      strategyId: string;
      strategyName: string;
      direction: 'BUY' | 'SHORT' | 'SKIP';
      executionFrequency: '1h' | '4h' | '1d';
      nextExecutionAt: string;
    }[];
  };

  // === 积分信息 (从CreditsAccount关联) ===
  creditsInfo: {
    balance: number;                   // 可用积分余额
    totalEarned: number;               // 累计获得
    totalSpent: number;                // 累计消耗
    expiringCredits: number;           // 即将过期积分数
  };

  // === 通信渠道 (从ChannelConfig关联) ===
  channelConfig: {
    activeChannels: ('telegram' | 'wechat' | 'email')[];
    channelCount: number;
  };
}
```

### 4.2 配置列表的管理视图

管理员(后期)可查看所有用户的配置列表：

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  👥 用户列表                                                    🔍 搜索...    │
├──────┬──────────────┬──────────┬────────┬─────────┬─────────┬──────────────┤
│ UID  │ 邮箱          │ 注册时间  │ 积分余额 │ 可用资金  │ 策略数 │ 状态        │
├──────┼──────────────┼──────────┼─────────┼─────────┼─────────┼──────────────┤
│ U3kR │ a@xxx.com    │ 05-14    │ 12,580  │ 5,000U  │ 2(1活跃)│ ✅ 正常      │
│ U7mP2│ b@xxx.com    │ 05-13    │ 45      │ 未配置   │ 0       │ ⚠️ 积分不足  │
│ UxQ9 │ c@xxx.com    │ 05-12    │ 0       │ 10,000U │ 1(暂停) │ 🔴 策略暂停  │
└──────┴──────────────┴──────────┴─────────┴─────────┴─────────┴──────────────┘
```

### 4.3 用户自己的配置概览

用户登录后，在左侧栏或个人中心可查看自己的配置状态：

```
┌──────────────────────────────┐
│  👤 U3kR7mP2xQ              │
│  a@xxx.com                  │
│  ────────────────────────── │
│                              │
│  ✅ 已完成配置               │
│  ├─ ⚙️ API配置     ✅ OKX   │
│  ├─ 💰 交易设置     ✅ 已配置│
│  └─ 📡 通信渠道     ✅ TG    │
│                              │
│  ⚠️ 待完善                   │
│  └─ 🎯 策略设置   尚未应用  │
│                              │
│  💎 积分: 12,580             │
│  💵 资金: 5,000 USDT        │
│  ⚡ 杠杆上限: 3x             │
│                              │
│  [编辑配置]  [退出登录]      │
└──────────────────────────────┘
```

---

## 5. 数据库模型 (Prisma Schema)

### 5.1 完整Prisma模型

```prisma
// prisma/schema.prisma

generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

// ============================================
// 核心用户模型
// ============================================

model User {
  uid           String    @id       // UID: U + 10位随机
  email         String    @unique   // 登录邮箱
  emailVerified Boolean   @default(false)
  passwordHash  String              // bcrypt加密的密码
  displayName   String?            // 显示名称
  avatarUrl     String?            // 头像
  role          UserRole  @default(FREE)

  // 安全字段
  loginAttempts Int       @default(0)
  lockedUntil   DateTime?
  lastLoginAt   DateTime?

  // 时间戳
  createdAt     DateTime  @default(now())
  updatedAt     DateTime  @updatedAt

  // 关联
  profile       UserProfile?
  apiConfigs    ApiConfig[]
  tradingParams TradingParams?
  strategies    Strategy[]
  channels      ChannelConfig[]
  creditsAccount CreditsAccount?
  creditsTransactions CreditsTransaction[]
  orders        Order[]
  sessions      Session[]

  @@map("users")
}

enum UserRole {
  FREE      // 免费用户
  PRO       // 专业用户(付费)
  ADMIN     // 管理员
}

// ============================================
// 用户配置列表 (1:1 with User)
// ============================================

model UserProfile {
  uid           String    @id      // 关联User.uid
  user          User      @relation(fields: [uid], references: [uid], onDelete: Cascade)

  // === 交易配置 ===
  availableCapital    Float?                   // 可用资金(USDT)
  capitalPercentage   Float    @default(0.10)  // 交易百分比(默认10%)
  tradeType           TradeType @default(SPOT) // 交易类型
  leverageMax         Int      @default(3)     // 杠杆上限(1-5x)
  dailyLossLimit      Float    @default(500)   // 日亏损限制(USDT)
  dailyLossPercent    Float    @default(0.05)  // 日亏损限制(%)
  accountLossLimit    Float    @default(2000)  // 账户亏损限制(USDT)
  accountLossPercent  Float    @default(0.20)  // 账户亏损限制(%)
  allowedSymbols      String[] @default(["BTC-USDT-SWAP"])
  isTradingEnabled    Boolean  @default(false) // 交易开关

  // === 策略偏好 ===
  preferredFrequency  Frequency? @default(FOUR_H) // 首选执行频率
  riskTolerance       RiskTolerance @default(MODERATE) // 风险偏好

  // 时间戳
  createdAt     DateTime  @default(now())
  updatedAt     DateTime  @updatedAt

  @@map("user_profiles")
}

enum TradeType {
  SPOT      // 现货
  SWAP      // 合约
}

enum Frequency {
  ONE_H     // 1小时
  FOUR_H    // 4小时
  ONE_D     // 1天
}

enum RiskTolerance {
  CONSERVATIVE  // 保守
  MODERATE      // 适中
  AGGRESSIVE    // 激进
}

// ============================================
// API配置 (1:N with User — 一个用户可配多个API)
// ============================================

model ApiConfig {
  id            String   @id @default(cuid())
  uid           String                           // 关联User.uid
  user          User      @relation(fields: [uid], references: [uid], onDelete: Cascade)

  category      ApiCategory                       // API类别
  provider      String                            // 提供商: okx/openai/coinglass
  label         String                            // 用户自定义标签: "主账户"

  // 加密存储的凭证 (AES-256-GCM加密后的JSON)
  encryptedData String                            // {apiKey, secretKey, passphrase, ...}
  iv            String                            // 加密IV
  authTag       String                            // GCM认证标签

  // 元数据 (脱敏，可搜索)
  keyHint       String?                           // 密钥提示: "••••kT9x"
  environment   String?                           // 环境: demo/live
  baseUrl       String?                           // 自定义API地址

  // 验证状态
  isVerified    Boolean  @default(false)
  lastVerifiedAt DateTime?

  createdAt     DateTime  @default(now())
  updatedAt     DateTime  @updatedAt

  @@unique([uid, category, provider, label])
  @@map("api_configs")
}

enum ApiCategory {
  EXCHANGE       // 交易所
  LLM            // AI模型
  DATA_SOURCE    // 数据源
}

// ============================================
// 交易参数 (1:1 with User)
// ============================================

model TradingParams {
  id            String   @id @default(cuid())
  uid           String   @unique                     // 关联User.uid
  user          User      @relation(fields: [uid], references: [uid], onDelete: Cascade)

  // 实时亏损追踪 (每日重置)
  todayLoss     Float    @default(0)
  todayTradeCount Int    @default(0)
  lastResetDate String                              // "2026-05-14"

  // 累计追踪
  totalLoss     Float    @default(0)
  totalTradeCount Int    @default(0)

  // 状态
  status        TradingStatus @default(ACTIVE)

  createdAt     DateTime  @default(now())
  updatedAt     DateTime  @updatedAt

  @@map("trading_params")
}

enum TradingStatus {
  ACTIVE     // 正常运行
  PAUSED     // 用户暂停
  FROZEN     // 冻结(需解冻操作)
  LOCKED     // 系统锁定(亏损超限)
}

// ============================================
// 策略 (1:N with User)
// ============================================

model Strategy {
  id            String   @id @default(cuid())
  uid           String                           // 关联User.uid
  user          User      @relation(fields: [uid], references: [uid], onDelete: Cascade)

  type          StrategyType                     // 推荐策略/自定义策略
  name          String                           // 策略名称
  description   String?                          // 策略描述

  // 策略参数
  direction     Direction                        // BUY/SHORT/SKIP
  symbol        String   @default("BTC-USDT-SWAP")
  tradeType     TradeType @default(SPOT)
  leverage      Int      @default(1)
  positionSize  Float    @default(0)
  stopLoss      Float?
  takeProfit    Float?
  confidence    Int?
  edgeScore     Int?

  // 推荐策略特有
  regime        String?                          // 市场状态
  source        String?                          // 来源: A4
  isRead        Boolean  @default(false)

  // 自定义策略特有
  rawInput      String?                          // 用户自然语言输入
  parsedIntent  Json?                            // IntentParser解析结果
  backtestResult Json?                           // 回测结果

  // 策略状态
  status        StrategyStatus @default(DRAFT)

  // 关联定时任务
  tasks         StrategyTask[]

  createdAt     DateTime  @default(now())
  updatedAt     DateTime  @updatedAt

  @@map("strategies")
}

enum StrategyType {
  RECOMMENDED    // 推荐策略
  CUSTOM         // 自定义策略(信号策略)
}

enum Direction {
  BUY
  SHORT
  SKIP
}

enum StrategyStatus {
  DRAFT          // 草稿
  APPROVED       // 已审批(回测通过)
  APPLIED        // 已应用
  PAUSED         // 已暂停
  EXPIRED        // 已过期
}

// ============================================
// 策略定时任务 (1:N with Strategy)
// ============================================

model StrategyTask {
  id            String   @id @default(cuid())
  strategyId    String                           // 关联Strategy.id
  strategy      Strategy @relation(fields: [strategyId], references: [id], onDelete: Cascade)
  uid           String                           // 冗余字段，便于按用户查询

  exchangeConfigId String?                       // 关联ApiConfig.id
  executionFrequency Frequency

  // 执行状态
  status        TaskStatus @default(ACTIVE)
  nextExecutionAt DateTime?
  lastExecutionAt DateTime?
  executionCount Int      @default(0)
  skipCount     Int      @default(0)
  tradeCount    Int      @default(0)

  createdAt     DateTime  @default(now())
  updatedAt     DateTime  @updatedAt

  @@map("strategy_tasks")
}

enum TaskStatus {
  ACTIVE
  PAUSED
  COMPLETED
  FAILED
}

// ============================================
// 通信渠道配置 (1:N with User)
// ============================================

model ChannelConfig {
  id            String   @id @default(cuid())
  uid           String                           // 关联User.uid
  user          User      @relation(fields: [uid], references: [uid], onDelete: Cascade)

  channelType   ChannelType                      // 渠道类型
  encryptedData String                           // 加密的Token/配置
  iv            String                           // 加密IV
  authTag       String                           // GCM认证标签

  // 推送规则
  pushRules     Json                             // 推送规则配置
  silentStart  String?                           // 静默开始 "23:00"
  silentEnd    String?                           // 静默结束 "07:00"
  format       PushFormat @default(CONCISE)      // 推送格式

  // 状态
  isOnline     Boolean  @default(false)
  lastTestAt   DateTime?

  createdAt    DateTime  @default(now())
  updatedAt    DateTime  @updatedAt

  @@map("channel_configs")
}

enum ChannelType {
  TELEGRAM
  WECHAT_SERVERCHAN
  WECHAT_WORK
  EMAIL_SMTP
  DISCORD
  SLACK
}

enum PushFormat {
  CONCISE      // 简洁
  DETAILED     // 详细
}

// ============================================
// 积分账户 (1:1 with User)
// ============================================

model CreditsAccount {
  id            String   @id @default(cuid())
  uid           String   @unique                     // 关联User.uid
  user          User      @relation(fields: [uid], references: [uid], onDelete: Cascade)

  balance       Float    @default(0)                 // 可用积分余额
  totalEarned   Float    @default(0)                 // 累计获得
  totalSpent    Float    @default(0)                 // 累计消耗
  pendingCredits Float   @default(0)                 // 待生效积分

  // 新用户赠送
  signupBonus   Boolean  @default(false)             // 是否已领取注册赠送

  createdAt     DateTime  @default(now())
  updatedAt     DateTime  @updatedAt

  @@map("credits_accounts")
}

// ============================================
// 积分流水 (1:N with User)
// ============================================

model CreditsTransaction {
  id            String   @id @default(cuid())
  uid           String                           // 关联User.uid
  user          User      @relation(fields: [uid], references: [uid], onDelete: Cascade)

  type          CreditsType                      // 收入/支出
  category      CreditsCategory                  // 分类
  amount        Float                            // 变动数量(正数)
  balanceAfter  Float                            // 变动后余额
  description   String                           // 描述

  // 关联
  relatedId     String?                          // 关联ID(策略ID/订单ID)
  expiresAt     DateTime?                        // 过期时间(赠送积分)

  createdAt     DateTime  @default(now())

  @@map("credits_transactions")
}

enum CreditsType {
  EARN          // 收入
  SPEND         // 支出
}

enum CreditsCategory {
  // 收入
  RECHARGE          // 充值
  SIGNIN            // 签到
  REFERRAL          // 邀请好友
  BONUS             // 活动赠送
  SIGNUP_BONUS      // 注册赠送

  // 支出
  STRATEGY_EXECUTION // 策略执行
  ANALYSIS_REPORT    // 分析报告
  INTEL_BRIEF        // 情报快报
}

// ============================================
// 订单 (充值订单)
// ============================================

model Order {
  id            String   @id @default(cuid())
  uid           String                           // 关联User.uid
  user          User      @relation(fields: [uid], references: [uid], onDelete: Cascade)

  orderNo       String   @unique                  // 订单号: CG202605140001
  packageId     String                           // 套餐ID

  // 订单金额
  amount        Float                            // 支付金额(¥)
  credits       Float                            // 积分数
  bonusCredits  Float    @default(0)              // 赠送积分

  // 支付信息
  paymentMethod PaymentMethod                     // 支付方式
  paymentNo     String?                           // 第三方支付流水号

  // 状态
  status        OrderStatus @default(PENDING)

  // 时间
  paidAt        DateTime?
  completedAt   DateTime?
  expiredAt     DateTime?                         // 订单过期时间(15分钟)

  createdAt     DateTime  @default(now())
  updatedAt     DateTime  @updatedAt

  @@map("orders")
}

enum PaymentMethod {
  WECHAT_PAY
  ALIPAY
  APPLE_PAY
}

enum OrderStatus {
  PENDING       // 待支付
  PAID          // 已支付
  COMPLETED     // 已完成(积分已到账)
  CANCELLED     // 已取消
  REFUNDED      // 已退款
  FAILED        // 支付失败
}

// ============================================
// 验证码 (邮箱验证/密码重置)
// ============================================

model VerificationCode {
  id            String   @id @default(cuid())
  email         String                           // 目标邮箱
  code          String                           // 6位验证码
  type          CodeType                         // 验证类型
  attempts      Int      @default(0)              // 尝试次数
  maxAttempts   Int      @default(5)              // 最大尝试次数

  expiresAt     DateTime                          // 过期时间(10分钟)
  usedAt        DateTime?                         // 使用时间

  createdAt     DateTime  @default(now())

  @@map("verification_codes")
}

enum CodeType {
  EMAIL_VERIFY      // 邮箱验证
  PASSWORD_RESET    // 密码重置
  LOGIN_2FA         // 登录二次验证
}

// ============================================
// 会话 (Auth.js 自动管理)
// ============================================

model Session {
  id            String   @id @default(cuid())
  uid           String                           // 关联User.uid
  user          User      @relation(fields: [uid], references: [uid], onDelete: Cascade)

  sessionToken  String   @unique
  expiresAt     DateTime

  createdAt     DateTime  @default(now())

  @@map("sessions")
}
```

### 5.2 数据库ER关系图

```
┌─────────────┐     1:1     ┌──────────────┐     1:1     ┌───────────────┐
│   User       │────────────►│ UserProfile  │             │ CreditsAccount│
│              │             │ (交易配置)    │             │ (积分账户)    │
│ uid (PK)     │             │ 可用资金     │             │ 余额/流水     │
│ email        │             │ 杠杆上限     │             └───────┬───────┘
│ passwordHash │             │ 策略偏好     │                     │
└──────┬───────┘             └──────────────┘              1:N   │
       │                                                       │
       │ 1:N                                             ┌─────▼────────┐
       │                                                 │ CreditsTxn  │
       │                                                 │ 积分流水     │
       │                                                 └──────────────┘
       │
  ┌────┼────────────────┬────────────────┬─────────────────┐
  │    │                │                │                 │
  │  1:N             1:N              1:N               1:N
  │    │                │                │                 │
  ▼    ▼                ▼                ▼                 ▼
┌──────────┐   ┌──────────────┐   ┌──────────┐    ┌──────────┐
│ ApiConfig│   │TradingParams │   │ Strategy │    │ Channel  │
│ (API配置) │   │ (交易参数)    │   │ (策略)   │    │ (渠道)   │
│ OKX密钥  │   │ 日亏损限制   │   │ 方向/杠杆│    │ TG/微信  │
│ LLM密钥  │   │ 账户亏损限制 │   │ 回测结果 │    │ 推送规则 │
└──────────┘   └──────────────┘   └────┬─────┘    └──────────┘
                                       │
                                     1:N
                                       │
                                 ┌─────▼──────┐
                                 │StrategyTask│
                                 │(定时任务)  │
                                 │ 执行频率   │
                                 │ 执行状态   │
                                 └────────────┘
```

---

## 6. 登录状态与功能访问控制

### 6.1 功能访问矩阵

| 功能 | 未登录 | 已登录(未验证邮箱) | 已登录(已验证) |
|------|--------|--------------------|----------------|
| /行情 基础对话 | ✅ | ✅ | ✅ |
| /状态 查询状态 | ✅ | ✅ | ✅ |
| 💎 我的积分 | 🔒→登录 | ✅ 查看 | ✅ 查看+充值 |
| ⚙️ API配置 | 🔒→登录 | ✅ 配置 | ✅ 配置 |
| 💰 交易设置 | 🔒→登录 | ⚠️ 仅查看 | ✅ 完整操作 |
| 🎯 策略设置 | 🔒→登录 | ⚠️ 仅推荐 | ✅ 完整操作 |
| 📡 通信渠道 | 🔒→登录 | ✅ 配置 | ✅ 配置 |
| /分析 付费命令 | 🔒→登录 | ⚠️ 需验证邮箱 | ✅ 消耗积分 |
| 💳 充值 | 🔒→登录 | 🔒→需验证 | ✅ 充值 |
| 策略执行 | 🔒→登录 | 🔒→需验证 | ✅ 执行 |

### 6.2 前端路由守卫

```typescript
// middleware.ts (Next.js App Router)
export function middleware(request: NextRequest) {
  const session = getToken({ req: request });
  const path = request.nextUrl.pathname;

  // 公开路由: 无需登录
  const publicPaths = ['/', '/login', '/register', '/api/auth'];
  if (publicPaths.some(p => path.startsWith(p))) {
    return NextResponse.next();
  }

  // 受保护路由: 需要登录
  const protectedPaths = ['/credits', '/settings', '/recharge', '/api/config'];
  if (protectedPaths.some(p => path.startsWith(p))) {
    if (!session) {
      const loginUrl = new URL('/login', request.url);
      loginUrl.searchParams.set('callbackUrl', path);
      return NextResponse.redirect(loginUrl);
    }
  }

  // 需要邮箱验证的路由
  const verifiedPaths = ['/recharge', '/api/config/strategies/*/apply'];
  if (verifiedPaths.some(p => path.startsWith(p.replace('/*', '')))) {
    if (session && !session.emailVerified) {
      return NextResponse.redirect(new URL('/verify-email', request.url));
    }
  }

  return NextResponse.next();
}
```

---

## 7. 与现有四大独立功能的集成

### 7.1 UID关联关系表

| 功能模块 | 存储方式 | UID关联 | 迁移前(v1.x) | 迁移后(v2.0) |
|----------|----------|---------|--------------|--------------|
| API配置 | AES-256加密文件 | uid字段 | 全局共享 | 按UID隔离 |
| 交易参数 | JSON文件 | uid字段 | 全局统一 | 按UID独立 |
| 策略设置 | JSON文件 | uid字段 | 全局共享 | 按UID隔离 |
| 通信渠道 | AES-256加密文件 | uid字段 | 全局共享 | 按UID隔离 |
| 积分体系 | (新增) | uid字段 | 无 | 按UID独立 |

### 7.2 从单用户到多用户的数据迁移

```
v1.x (单用户文件存储)                    v2.0 (PostgreSQL多用户)
─────────────────────────────          ──────────────────────────
~/.workbuddy/config/                   
├── api-keys.enc        ──────迁移──►  ApiConfig {uid: "U3kR7mP2xQ", ...}
├── trading-params.json ──────迁移──►  TradingParams {uid: "U3kR7mP2xQ", ...}
├── strategies.json     ──────迁移──►  Strategy[] {uid: "U3kR7mP2xQ", ...}
├── strategy-tasks.json ──────迁移──►  StrategyTask[] {uid: "U3kR7mP2xQ", ...}
└── channels.enc        ──────迁移──►  ChannelConfig {uid: "U3kR7mP2xQ", ...}
```

**迁移脚本**: `scripts/migrate-single-to-multiuser.ts`
- 读取现有文件配置
- 创建管理员账户 (UID: U0000000001)
- 将现有配置关联到管理员UID
- 写入PostgreSQL
- 备份原文件到 `~/.workbuddy/config/backup_v1/`

### 7.3 API路由变更

```
v1.x (无用户概念):
GET  /api/config/api-keys        → 返回全局配置
POST /api/config/api-keys        → 保存全局配置

v2.0 (多用户):
GET  /api/config/api-keys        → 从session取uid → 返回该用户配置
POST /api/config/api-keys        → 从session取uid → 保存到该用户配置
GET  /api/user/profile           → 返回当前用户完整配置列表(新增)
```

---

## 8. 后端API接口

### 8.1 认证相关

```
POST /api/auth/register
Body: { email, password }
Response: { uid, email, message: "验证邮件已发送" }

POST /api/auth/login
Body: { email, password, rememberMe? }
Response: { user: { uid, email, role, emailVerified }, token }

POST /api/auth/verify-email
Body: { email, code }
Response: { verified: true, signupBonus: 2000 }

POST /api/auth/logout
Response: { success: true }

POST /api/auth/reset-password
Body: { email }
Response: { message: "重置密码邮件已发送" }

POST /api/auth/reset-password/confirm
Body: { email, code, newPassword }
Response: { success: true }
```

### 8.2 用户配置列表

```
GET /api/user/profile
→ 返回当前登录用户的完整配置列表(UserProfile)

PATCH /api/user/profile
Body: {
  displayName?: string,
  tradingConfig?: {
    availableCapital?: number,
    leverageMax?: number,
    dailyLossLimit?: number,
    ...
  }
}
→ 更新用户配置

GET /api/user/profile/completeness
→ 返回配置完成度(引导用户补全)
Response: {
  overall: 60,           // 总完成度
  steps: [
    { key: "email_verify", label: "验证邮箱", completed: true },
    { key: "api_config", label: "配置交易所API", completed: true },
    { key: "trading_params", label: "设置交易参数", completed: true },
    { key: "strategy_apply", label: "应用策略", completed: false },
    { key: "channel_setup", label: "配置通知渠道", completed: false },
  ]
}
```

---

## 9. 配置可用资金、杠杆、策略的门禁联动

### 9.1 TradingGate增强 — UID配置查询

```
A5决策输出 → TradingGate(查询UID配置 → 8步校验)
                   │
                   ▼
            ┌──────────────────────────────────────┐
            │  Step 0: 查询用户配置 (v2.0新增)      │
            │  · SELECT * FROM trading_params       │
            │    WHERE uid = ?                       │
            │  · SELECT * FROM user_profiles         │
            │    WHERE uid = ?                       │
            │  · 如果查询不到 → 拦截: "请先完成     │
            │    交易参数配置"                       │
            └──────────────────────────────────────┘
                   │
                   ▼
            ┌──────────────────────────────────────┐
            │  Step 1: 可用资金检查                  │
            │  · user.availableCapital >= 交易金额？ │
            │  · 资金不足 → 拦截                     │
            └──────────────────────────────────────┘
                   │
                   ▼
            ┌──────────────────────────────────────┐
            │  Step 2: 杠杆上限检查                  │
            │  · 策略leverage <= user.leverageMax？  │
            │  · 越界 → 降级到用户上限               │
            └──────────────────────────────────────┘
                   │
                   ▼
            ... (后续6步与原TradingGate一致)
```

### 9.2 用户配置变更的实时生效

```
用户修改交易参数 → PATCH /api/user/profile
      │
      ▼
┌──────────────────────────────────────┐
│  后端更新 UserProfile + TradingParams│
│  · 数据库事务写入                     │
│  · 发布Redis消息: user:config:updated│
│  · 审计日志记录                       │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  实时生效                            │
│  · 运行中的策略任务下次执行时         │
│    自动读取最新配置                   │
│  · SSE推送: 配置已更新               │
│  · 如果杠杆降低 → 已运行策略降级    │
│  · 如果资金减少 → 已运行策略检查余额 │
└──────────────────────────────────────┘
```

---

## 10. 安全设计

### 10.1 注册安全

| 措施 | 说明 |
|------|------|
| 密码强度 | ≥8位, 含字母+数字, bcrypt(saltRounds=12) |
| 邮箱验证 | 注册后6位验证码, 10分钟有效 |
| 注册频率 | 同一IP 3次/小时, 同一邮箱1次 |
| 图形验证码 | 注册/登录失败3次后触发 |
| 邮箱唯一 | 数据库UNIQUE约束 |

### 10.2 登录安全

| 措施 | 说明 |
|------|------|
| 暴力破解防护 | 连续5次失败锁定30分钟 |
| 模糊错误提示 | "邮箱或密码错误"(不透露哪个错) |
| JWT HttpOnly | Cookie不可JS访问 |
| CSRF保护 | Auth.js内置 |
| 记住登录 | 7天有效期, 不勾选24小时 |

### 10.3 数据隔离

| 措施 | 说明 |
|------|------|
| UID隔离 | 所有查询强制带uid条件, 不允许跨用户访问 |
| API密钥加密 | AES-256-GCM加密, 密钥派生自服务端密钥+uid |
| 积分操作事务 | 扣费+写入流水在同一事务, 防止余额不一致 |
| 审计日志 | 所有配置变更+交易操作记录uid+时间+操作内容 |

---

## 11. 扩展路径

### 11.1 认证方式扩展

```
v1.0 (当前)           v1.5               v2.0
────────────────────────────────────────────────────
邮箱+密码       →  +手机号验证码    →  +微信OAuth
                    (腾讯云SMS)        (企业资质)
                                       +Apple ID
```

### 11.2 用户角色扩展

```
v1.0 (当前)           v1.5               v2.0
────────────────────────────────────────────────────
FREE (免费)    →  +PRO (付费订阅) →  +ENTERPRISE
                    积分+订阅双轨      多子账户+权限组
```

### 11.3 用户配置列表扩展

```
v1.0 (当前)           v1.5               v2.0
────────────────────────────────────────────────────
单交易所(OKX)  →  多交易所         →  交易所路由
BTC only       →  BTC+ETH+SOL     →  自定义品种
单策略运行     →  多策略(优先级)   →  策略组合
文件配置       →  数据库配置       →  配置版本管理
```

---

## 12. 实施优先级

### 12.1 Phase 0 (P0 — 必须与Gateway同步上线)

| 任务 | 说明 | 预估 |
|------|------|------|
| P0-U1 | PostgreSQL + Prisma 初始化 | 0.5天 |
| P0-U2 | User + UserProfile + CreditsAccount 模型 | 0.5天 |
| P0-U3 | Auth.js v5 Credentials Provider (邮箱+密码) | 1天 |
| P0-U4 | 注册+邮箱验证+登录接口 | 1天 |
| P0-U5 | 前端登录弹窗组件 | 0.5天 |
| P0-U6 | 路由守卫中间件 | 0.5天 |
| P0-U7 | UID关联到现有ApiConfig/TradingParams/Strategy | 1天 |
| P0-U8 | 迁移脚本(单用户→多用户) | 0.5天 |

**总计: ~5.5天**

### 12.2 Phase 1 (P1 — 上线后1-2周)

| 任务 | 说明 |
|------|------|
| P1-U1 | 用户配置列表概览页面 |
| P1-U2 | 配置完成度引导 |
| P1-U3 | 管理员用户列表视图 |
| P1-U4 | 审计日志查询 |

### 12.3 Phase 2 (P2 — 扩展)

| 任务 | 说明 |
|------|------|
| P2-U1 | 手机号+验证码登录(腾讯云SMS) |
| P2-U2 | 密码重置 |
| P2-U3 | PRO订阅角色 |
| P2-U4 | 微信OAuth |
