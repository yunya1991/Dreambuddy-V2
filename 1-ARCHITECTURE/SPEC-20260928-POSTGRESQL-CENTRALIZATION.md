# SPEC-20260928 — PostgreSQL 中心化迁移

**版本**: v1.0
**日期**: 2026-09-28
**作者**: Trae + User (方案1 决策)
**状态**: Draft（待用户评审）
**关联**: 方案1（PostgreSQL 中心化） · USER_SYSTEM_DESIGN.md v1.0 · 3.0 用户体系 §5.1

---

## Executive Summary

本 SPEC 规划将 3.1 前端 + 7-产物中台 的双 SQLite 数据库合并迁移到中心化 PostgreSQL，并对齐传统金融产品设计理念（DECIMAL 铁律 / 复式记账 / 三账户隔离 / 操作留痕 / 订单状态机），分 3 期（P0/P1/P2）落地。DreamOS 与 DSH 当前为内存+文件存储，无直接冲突，不在本期强行迁移，仅在 P2 期评估 session 持久化。

**4 系统冲突结论**：
- ✅ **3.1 前端 ↔ 产物中台**：schema 超集关系（产物中台是 3.1 超集 + 4 独有模型），合并到 PostgreSQL 无破坏性冲突，统一以产物中台 schema 为基础
- ✅ **DreamOS ↔ PostgreSQL**：无直接冲突（DreamOS 是内存+文件），可选 session 持久化延后到 P2
- ✅ **DSH ↔ PostgreSQL**：无直接冲突（canon_intent_bridge 是内存映射，SSOT 是 intent-schema.ts），任务状态可选持久化延后到 P2

**核心金融改造（8 项缺陷）**：
1. 资金字段全 Float 违反 DECIMAL 铁律
2. 无 AuditLog 表违反操作留痕
3. CreditsTransaction 单式记账需重构为复式记账
4. User 单表需拆分为 Customer + FundsAccount + TradingAccount 三账户隔离
5. Order 缺状态机
6. 无 Position 持仓表
7. 无 KYC/KYC 事件表
8. 无 RiskRule/RiskEvent 风控表

---

## 1. 背景与目标

### 1.1 背景

**3.1 前端 vs 产物中台承接关系真相**（已闭环调研结论）：
- 两个独立 SQLite 数据库（不共享）：
  - 3.1 前端：`DATABASE_URL="file:/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/dev.db"`
  - 产物中台：`DATABASE_URL="file:/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系/data/business.db"`
- 唯一真实承接通道：3.1 前端 HTTP 反代调用产物中台 API（`HUB_BASE_URL=http://127.0.0.1:8787`，board 治理层用 `49.233.123.96:3456`）
- 反代接口：/api/chain/artifacts, /api/feed, /api/ops/*, /api/market/*, /api/board/*（产物文件树+运营事件，非用户业务数据）

**产物中台与 3.1 前端不需要融合**（用户硬约束，2026-09-28 确认）：
- 产物中台给**运营**看，3.1 前端给**用户**使用
- board 治理层只是产物中台的展示入口迁移到 3.1

### 1.2 目标

1. **统一数据源**：3.1 前端 + 产物中台合并到中心化 PostgreSQL，消除双 SQLite 维护成本
2. **金融级合规**：对齐传统金融产品设计 7 条核心理念，补齐审计/复式记账/三账户隔离/DECIMAL/风控等金融级缺陷
3. **4 系统无冲突**：3.1 前端、产物中台、DreamOS、DSH 架构间无破坏性冲突
4. **分阶段可回滚**：3 期（P0/P1/P2）实施，每期独立验收、可独立回滚

### 1.3 范围与不范围

**范围内**：
- 3.1 前端 Prisma schema 从 SQLite 迁移到 PostgreSQL（17 模型）
- 产物中台 schema 合并到中心化 PostgreSQL（在 3.1 基础上 + 4 独有模型 + 17 推荐引擎扩展字段）
- 金融产品级 schema 改造（DECIMAL/AuditLog/复式记账/三账户隔离/Position/TradeOrder/KYC/RiskRule）
- 用户/运营数据通过 schema 内表分组隔离（不强制物理隔离）

**范围外**（本期不做，仅记录到 SPEC）：
- DreamOS 能力注册表/调度器状态/coin_pool.json 的 PostgreSQL 化（内存+文件运行稳定，无必要强行迁移）
- DSH canon_intent_bridge.py 的内存映射表迁移（SSOT 是 intent-schema.ts，保留内存）
- DSH 任务状态持久化到 PostgreSQL（P2 期评估）
- DreamOS sessions/ 目录数据持久化到 PostgreSQL（P2 期评估）

---

## 2. 4 系统现状调研

### 2.1 3.1 前端（3.1-FRONTEND/）

**技术栈**：Next.js 15.4 + React 19 + zustand + Prisma + SQLite

**Prisma schema**：`3.1-FRONTEND/prisma/schema.prisma`（17 模型，基于 USER_SYSTEM_DESIGN.md v1.0）

| 模型 | @@map 表名 | 关键字段 | 用途 |
|------|-----------|---------|------|
| User | users | uid PK, email unique, role enum | 用户主表 |
| UserProfile | user_profiles | uid PK→User, Float 资金字段, Json allowedSymbols | 用户配置 |
| ApiConfig | api_configs | cuid PK, encryptedData, unique[uid,category,provider,label] | API 凭证 |
| TradingParams | trading_params | cuid PK, uid unique, Float loss, status enum | 交易参数 |
| Strategy | strategies | cuid PK, Json parsedIntent/backtestResult, status enum | 策略 |
| StrategyTask | strategy_tasks | cuid PK, Frequency, TaskStatus | 定时任务 |
| StrategyTaskOrder | strategy_task_orders | strategyTaskOrderId PK, Json strategySnapshot | 任务单 |
| StrategyExecutionRun | strategy_execution_runs | strategyExecutionRunId PK | 执行记录 |
| ChannelConfig | channel_configs | cuid PK, encryptedData, ChannelType | 通信渠道 |
| CreditsAccount | credits_accounts | cuid PK, uid unique, Float balance | 积分账户 |
| CreditsTransaction | credits_transactions | cuid PK, CreditsType/CreditsCategory | 积分流水 |
| Order | orders | cuid PK, orderNo unique, OrderStatus | 充值订单 |
| VerificationCode | verification_codes | cuid PK, expiresAt | 验证码 |
| Session | sessions | cuid PK, sessionToken unique | 会话 |

**配置**（3.1-FRONTEND/.env）：
- DATABASE_URL=`file:/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/dev.db`
- HUB_BASE_URL=`http://127.0.0.1:8787`（产物中台反代）
- NEXT_PUBLIC_BRIDGE_URL=`http://127.0.0.1:3847`（DSH Flask）

**dev-user 机制**：`3.1-FRONTEND/src/lib/dev-user.ts`
- DEMO_UID=`Ur6GZTRLpum`（开发环境测试用户）
- `getDevelopmentUid()` 从 `x-uid` header 取 UID，无则用 DEMO_UID

**Prisma 单例**：`3.1-FRONTEND/src/lib/prisma.ts` 直接 `new PrismaClient()`

**API 路由依赖矩阵**（关键路径）：
| 路由 | 调用模型 | 反代产物中台 |
|------|---------|-------------|
| /api/config/strategies | Strategy, UserProfile | 否 |
| /api/config/trading-params | UserProfile, TradingParams, ApiConfig | 否 |
| /api/market/content | Strategy | 否 |
| /api/feed | - | 是（HUB /api/chain/artifacts） |
| /api/market/audit | - | 是（HUB，失败回退 mock） |
| /api/task | - | 是（DSH /api/task/create） |

### 2.2 7-产物中台（7-产物中台/系统研究索引体系/）

**技术栈**：独立 Next.js 应用，dev 端口 3456，腾讯云 `49.233.123.96:3456`

**Prisma schema**：`7-产物中台/系统研究索引体系/prisma/schema.prisma`（17 模型 + 4 独有 = 21 模型）

**与 3.1 schema 的差异**：

| 模型 | 3.1 | 产物中台 | 差异 |
|------|-----|---------|------|
| User | ✓ | ✓ | 一致 |
| UserProfile | ✓ | ✓ | 产物中台 `allowedSymbols Json` 而非 String，默认值 `"\"BTC-USDT-SWAP\""` |
| ApiConfig | ✓ | ✓ | 一致 |
| TradingParams | ✓ | ✓ | 一致 |
| Strategy | ✓ | ✓ | **产物中台多 17 个推荐引擎扩展字段**：backtestSharpe/backtestMaxDrawdown/backtestWinRate/backtestProfitFactor/backtestTotalReturn/backtestPeriod/backtestDate/baselineVersion/baselineSharpe/baselineMaxDrawdown/baselineTotalReturn/isBetterThanBaseline/sourceEngine/sourceReportIds/generation/parentStrategyId/isInLibrary/libraryScore/libraryActive/libraryArchived/recommendedDays/lastDailyBacktestDate/consecutiveBelowBaseline |
| StrategyTask | ✓ | ✓ | 一致 |
| StrategyTaskOrder | ✓ | ✓ | 一致 |
| StrategyExecutionRun | ✓ | ✓ | 一致 |
| ChannelConfig | ✓ | ✓ | 一致 |
| CreditsAccount | ✓ | ✓ | 一致 |
| CreditsTransaction | ✓ | ✓ | 一致 |
| Order | ✓ | ✓ | 一致 |
| VerificationCode | ✓ | ✓ | 一致 |
| Session | ✓ | ✓ | 一致 |
| **StrategyBacktestRecord** | ✗ | ✓ | **产物中台独有**：策略回测记录 |
| **RecommendationEngineLog** | ✗ | ✓ | **产物中台独有**：推荐引擎运行日志 |
| **TradingRanking** | ✗ | ✓ | **产物中台独有**：交易榜单 Top10 |
| **RankingMonitor** | ✗ | ✓ | **产物中台独有**：榜单监控指标 |

**关键文件**：
- 独立 Prisma：`7-产物中台/系统研究索引体系/lib/prisma-data-hub.ts` 的 `getPrisma()` 独立 PrismaClient
- admin 查询：`7-产物中台/系统研究索引体系/lib/admin-queries.ts` 的 `db.user.findMany` 查自己 business.db（非 3.1 dev.db）

### 2.3 DreamOS 操作系统（1-ARCHITECTURE/dreamos/）

**技术栈**：Python + CapabilityRegistry（内存）+ 文件存储

**数据存储分类**：

| 存储类型 | 用途 | 关键路径 | 迁移评估 |
|---------|------|---------|---------|
| 内存 Dict | 能力注册表 `_capabilities` | `1-ARCHITECTURE/dreamos/core/capability/registry.py:55-80` | 不迁（运行态） |
| 内存 Dict | 调度器 `jobs`/`_history` | `1-ARCHITECTURE/dreamos/cli/scheduler.py:160-173` | 不迁（运行态） |
| 文件 JSON | coin_pool 币池 | `scheduler_data/coin_pool.json` | 不迁（A 选币产物） |
| 文件 JSON | session 状态 | `sessions/<id>/session.json`（`4-MEMORY/9-工具与接口/cognitive_session.py:329-371`） | **P2 评估持久化** |
| 文件 | scheduler_data 历史任务 | `scheduler_data/` | 不迁（离线数据） |

**四大闭环数据流**：A 选币(coin_pool.json) → B 易经信号 → C V15 执行 → E 认知复盘，F 编排/D 路由驱动
- 闭环数据载体：coin_pool.json → 内存信号 → V15 执行 → sessions/ 文件
- 无 PostgreSQL 现有依赖

**与 3.1 前端的交互**：通过 DSH bridge（http://127.0.0.1:3847）间接调用

### 2.4 DSH 架构（1-ARCHITECTURE/dream-harness-bridge/）

**技术栈**：Flask :3847 统一入口 + DSH :3080 内部 + canon_intent_bridge.py + bridge-client.ts

**架构组件**：

| 组件 | 路径 | 存储 | 迁移评估 |
|------|------|------|---------|
| canon_intent_bridge.py | `1-ARCHITECTURE/dream-harness-bridge/integration/canon_intent_bridge.py` | **内存映射表**（CANON_TO_DREAMOS / DREAMOS_TO_CANON / KERNEL_TO_CANON / OBJECTIVE_9_TO_CANON 四张 dict） | 不迁（SSOT 是 intent-schema.ts，前端是 SSOT，Python 是镜像） |
| DSH Python server | `1-ARCHITECTURE/dream-harness-bridge/packages/python-server/server.py` | 调用 DreamOS IntentEngine，无独立数据库 | 不迁 |
| bridge-client.ts | `3.1-FRONTEND/src/lib/bridge-client.ts` | 前端调用 `http://127.0.0.1:3847`，封装 SkillAPI/IntentAPI/TaskAPI | 不迁（HTTP 客户端） |
| 3.1 /api/task 路由 | `3.1-FRONTEND/src/app/api/task/route.ts` | 创建并执行任务，返回 task_id/status/intent/poll_url | **P2 评估任务状态持久化** |

**endpoint 清单**（bridge-client.ts:136-234）：
- `/api/skill/status/{taskId}` — Skill 状态
- `/api/intent/route` — 意图路由
- `/api/task/create` — 任务创建
- SSE `/api/task/{taskId}/stream` — 任务流

**与 3.1 前端交互**：通过 bridge-client.ts 调用 3847
**与 DreamOS 交互**：DSH Python server 调用 DreamOS IntentEngine
**与产物中台交互**：无直接调用

---

## 3. 冲突点矩阵

### 3.1 3.1 前端 ↔ 产物中台 schema 合并冲突

| 冲突点 | 严重度 | 解决方案 |
|--------|-------|---------|
| Strategy 模型字段数差异（产物中台多 17 个推荐引擎字段） | 中 | 以产物中台 schema 为超集基础，3.1 前端 Strategy 模型补齐 17 字段（可选 nullable） |
| 产物中台 4 个独有模型（StrategyBacktestRecord/RecommendationEngineLog/TradingRanking/RankingMonitor） | 低 | 直接合入中心化 PostgreSQL，3.1 前端不查询这些表（运营专属） |
| UserProfile.allowedSymbols 类型差异（3.1 String vs 产物中台 Json） | 中 | 统一为 Json + PostgreSQL 原生 jsonb（性能更好） |
| Json 字段默认值语法（SQLite `"\"BTC-USDT-SWAP\""` 在 PG 不兼容） | 高 | 改为 `["BTC-USDT-SWAP"]` 数组语法 + PG jsonb |
| Prisma 单例（3.1 lib/prisma.ts vs 产物中台 lib/prisma-data-hub.ts） | 低 | 合并到中心化后，统一用 3.1 的 prisma.ts 单例（产物中台 lib/prisma-data-hub.ts 改为 re-export） |

### 3.2 3.1 前端 ↔ DreamOS 冲突

| 冲突点 | 严重度 | 解决方案 |
|--------|-------|---------|
| 无直接数据库共享 | - | DreamOS 通过 DSH bridge 间接交互，无冲突 |
| session 数据双轨（3.1 localStorage vs DreamOS sessions/ 文件） | 低 | P2 期评估统一到 PostgreSQL Session 表 |

### 3.3 3.1 前端 ↔ DSH 冲突

| 冲突点 | 严重度 | 解决方案 |
|--------|-------|---------|
| 任务状态当前在前端 /api/task 路由层创建执行返回，不持久化 | 低 | P2 期评估新增 TaskRecord 表持久化（可选） |
| canon_intent_bridge 内存映射表 | - | 不迁（SSOT 是 intent-schema.ts，前端是 SSOT） |

### 3.4 产物中台 ↔ DreamOS/DSH 冲突

| 冲突点 | 严重度 | 解决方案 |
|--------|-------|---------|
| 产物中台 admin/users 查自己 business.db 的 users 表 | 高（合并后路径变） | 合并后产物中台改查中心化 PostgreSQL 的 users 表，需保留 admin 视图层（限定 role=ADMIN 才能查询所有用户） |
| 产物中台 ui-map/org/meeting/chain/feed 模块 | 低 | 合并后这些模块继续访问中心化 PostgreSQL（业务数据共享） |

---

## 4. PostgreSQL 中心化架构设计

### 4.1 部署架构

```
┌─────────────────────────────────────────────────────────────┐
│           中心化 PostgreSQL (PG 14+)                        │
│  ┌────────────────────┐  ┌────────────────────────────┐    │
│  │ 用户业务域 schema  │  │ 运营治理域 schema          │    │
│  │  (public/users)    │  │  (public/ops)              │    │
│  │  - users           │  │  - strategy_backtest_*    │    │
│  │  - user_profiles    │  │  - recommendation_*      │    │
│  │  - api_configs      │  │  - trading_rankings       │    │
│  │  - trading_params   │  │  - ranking_monitors       │    │
│  │  - strategies       │  │                            │    │
│  │  - strategy_*       │  │                            │    │
│  │  - credits_*        │  │                            │    │
│  │  - orders           │  │                            │    │
│  │  - sessions         │  │                            │    │
│  │  - verification_*   │  │                            │    │
│  └────────────────────┘  └────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────┐    │
│  │ 金融级新增域 (P0-P2)                              │    │
│  │  - audit_logs (P0)                                │    │
│  │  - ledger_transactions / ledger_postings (P0)     │    │
│  │  - customers / kyc_events (P1)                    │    │
│  │  - funds_accounts / trading_accounts (P1)        │    │
│  │  - positions / trade_orders (P1)                 │    │
│  │  - risk_rules / risk_events (P2)                 │    │
│  │  - reconciliation_records / idempotency_keys (P2)│    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
            ▲                          ▲
            │                          │
   ┌────────┴────────┐        ┌────────┴─────────┐
   │ 3.1 前端         │        │ 产物中台          │
   │ (Next.js :3001)  │        │ (Next.js :3456)  │
   │ - 用户业务数据    │        │ - 运营视图层      │
   │ - 用户使用        │        │ - 运营使用        │
   └────────┬────────┘        └──────────────────┘
            │ HTTP 反代 HUB_BASE_URL
            ▼
   ┌─────────────────┐         ┌─────────────────┐
   │ DSH Flask :3847 │ ←─────  │ DreamOS         │
   │ (canon_intent_  │         │ (内存+文件)      │
   │  bridge 内存)   │         │ - 不在本期迁     │
   └─────────────────┘         └─────────────────┘
```

### 4.2 连接配置

**统一 DATABASE_URL**（建议）：
```bash
# .env (3.1-FRONTEND 与 7-产物中台 共享)
DATABASE_URL="postgresql://dreambuddy:****@127.0.0.1:5432/dreambuddy?schema=public"
```

**隔离策略**（不强制物理隔离）：
- 用户业务域：3.1 前端主要查询的表（users/user_profiles/api_configs/trading_params/strategies/strategy_tasks/strategy_task_orders/strategy_execution_runs/channel_configs/credits_accounts/credits_transactions/orders/sessions/verification_codes）
- 运营治理域：产物中台主要查询的表（strategy_backtest_records/recommendation_engine_logs/trading_rankings/ranking_monitors）+ admin 视图（限定 role=ADMIN）
- 金融级新增域：跨域共享（audit_logs/ledger_transactions/ledger_postings/customers/kyc_events/funds_accounts/trading_accounts/positions/trade_orders/risk_rules/risk_events/reconciliation_records/idempotency_keys）

### 4.3 Prisma schema 统一策略

**单一 schema 文件**：以产物中台 schema 为基础（超集），合并到 3.1 前端 `3.1-FRONTEND/prisma/schema.prisma`

**关键变更**（P0 必做）：
```prisma
datasource db {
  provider = "postgresql"  // ← 从 sqlite 改
  url      = env("DATABASE_URL")
}

// 1. UserProfile: allowedSymbols/String → Json
model UserProfile {
  // ...
  allowedSymbols      Json     @default(["BTC-USDT-SWAP"])      // ← PG jsonb
  allowedTradeModes   Json     @default(["SPOT_MODE"])          // ← PG jsonb
  // 资金字段 Float → Decimal（DECIMAL 铁律）
  availableCapital    Decimal? @db.Decimal(18, 8)
  capitalPercentage   Decimal  @default(0.10) @db.Decimal(5, 4)
  dailyLossLimit      Decimal  @default(500)   @db.Decimal(18, 8)
  dailyLossPercent    Decimal  @default(0.05)  @db.Decimal(5, 4)
  accountLossLimit    Decimal  @default(2000)  @db.Decimal(18, 8)
  accountLossPercent  Decimal  @default(0.20)  @db.Decimal(5, 4)
}

// 2. TradingParams: 资金字段 Float → Decimal
model TradingParams {
  todayLoss     Decimal  @default(0) @db.Decimal(18, 8)
  totalLoss     Decimal  @default(0) @db.Decimal(18, 8)
}

// 3. CreditsAccount: 资金字段 Float → Decimal
model CreditsAccount {
  balance         Decimal  @default(0) @db.Decimal(18, 8)
  totalEarned     Decimal  @default(0) @db.Decimal(18, 8)
  totalSpent      Decimal  @default(0) @db.Decimal(18, 8)
  pendingCredits  Decimal  @default(0) @db.Decimal(18, 8)
}

// 4. CreditsTransaction: 资金字段 Float → Decimal
model CreditsTransaction {
  amount        Decimal  @db.Decimal(18, 8)
  balanceAfter  Decimal  @db.Decimal(18, 8)
}

// 5. Order: 资金字段 Float → Decimal
model Order {
  amount        Decimal  @db.Decimal(18, 8)
  credits       Decimal  @db.Decimal(18, 8)
  bonusCredits  Decimal  @default(0) @db.Decimal(18, 8)
}

// 6. Strategy: 资金字段 Float → Decimal
model Strategy {
  positionSize  Decimal  @default(0) @db.Decimal(18, 8)
  stopLoss      Decimal? @db.Decimal(18, 8)
  takeProfit    Decimal? @db.Decimal(18, 8)
  // ...推荐引擎扩展字段同样 Float → Decimal
}
```

**新增模型（P0 必做 3 个）**：

```prisma
// 7. AuditLog（操作留痕，金融硬约束）
model AuditLog {
  id            String   @id @default(cuid())
  uid           String?  // 操作者（可空表示系统操作）
  action        String   // CREATE/UPDATE/DELETE/LOGIN/EXPORT...
  resource      String   // 资源类型：strategy/order/user...
  resourceId    String?  // 资源 ID
  before        Json?    // 变更前快照
  after         Json?    // 变更后快照
  ip            String?
  userAgent     String?
  traceId       String?  // 链路追踪
  createdAt     DateTime @default(now())

  @@index([uid, createdAt])
  @@index([resource, resourceId])
  @@map("audit_logs")
}

// 8. LedgerTransaction（复式记账父表）
model LedgerTransaction {
  id            String   @id @default(cuid())
  txId          String   @unique  // 业务事务 ID（幂等）
  uid           String                         // 所属用户
  type          String   // CREDIT/DEBIT/TRANSFER/ADJUST
  amount        Decimal  @db.Decimal(18, 8)    // 总额
  description   String?
  relatedType   String?  // 关联类型：order/strategy/credits
  relatedId     String?  // 关联 ID
  idempotencyKey String? @unique               // 幂等键
  status        String   @default("POSTED")    // PENDING/POSTED/REVERSED
  reversedBy    String?  // 红冲事务 ID
  createdAt     DateTime @default(now())
  postedAt      DateTime?

  postings      LedgerPosting[]

  @@index([uid, createdAt])
  @@index([relatedType, relatedId])
  @@map("ledger_transactions")
}

// 9. LedgerPosting（复式记账子表，DR/CR 配对）
model LedgerPosting {
  id            String   @id @default(cuid())
  transactionId String                            // 关联 LedgerTransaction.id
  transaction   LedgerTransaction @relation(fields: [transactionId], references: [id], onDelete: Cascade)
  accountCode   String   // 科目代码：ASSET/LIABILITY/EQUITY/REVENUE/EXPENSE
  accountUid    String?  // 子账户（用户 uid）
  direction     String   // DEBIT/CREDIT
  amount        Decimal  @db.Decimal(18, 8)
  createdAt     DateTime @default(now())

  @@index([transactionId])
  @@index([accountCode, accountUid])
  @@map("ledger_postings")
}
```

### 4.4 数据迁移策略

**重建策略**（dev.db 是开发库，仅 DEMO_UID='Ur6GZTRLpum' 测试用户，可丢弃）：
```bash
# 1. 启动 PostgreSQL（本机 docker 或 brew services start postgresql@14）
# 2. 创建库
createdb dreambuddy

# 3. 修改 .env
# 3.1-FRONTEND/.env:
#   DATABASE_URL="postgresql://user:pass@127.0.0.1:5432/dreambuddy?schema=public"
# 7-产物中台/系统研究索引体系/.env 同上（共享同一 DB）

# 4. 修改 prisma/schema.prisma 的 provider
# 5. 重置 + 迁移 + 种子
cd 3.1-FRONTEND && npx prisma migrate reset --force
npx prisma migrate dev --name init_postgresql_centralization
npx prisma db seed
```

---

## 5. 金融产品设计理念融入

### 5.1 7 条核心理念对标

| 理念 | 金融来源 | dreambuddy 现状 | SPEC 改造 |
|------|---------|----------------|----------|
| **双层账本** | 银行会计分账 | 无账本概念 | P0 新增 LedgerTransaction + LedgerPosting |
| **复式记账** | 银行 DR/CR 配对 | CreditsTransaction 单式记账 | P0 重构为 LedgerTransaction 父子表 |
| **不可变性** | 审计日志 append-only | 无 AuditLog | P0 新增 AuditLog 表 |
| **三账户隔离** | 券商客户/资金/交易账户 | User 单表混合 | P1 拆 Customer/FundsAccount/TradingAccount |
| **订单状态机** | 券商订单生命周期 | Order 仅 OrderStatus 枚举 | P1 新增 TradeOrder 表 + 状态机 |
| **DECIMAL 铁律** | 资金字段禁 Float | 17 个 Float 字段 | P0 全部 Float → Decimal(18, 8) |
| **风控三道防线** | 银行事前/事中/事后 | 仅有 dailyLossLimit 静态阈值 | P2 新增 RiskRule/RiskEvent/ReconciliationRecord |

### 5.2 12 个新增模型分阶段规划

**P0 核心（3 个）**：
1. AuditLog — 操作留痕（金融硬约束）
2. LedgerTransaction — 复式记账父表
3. LedgerPosting — 复式记账子表（DR/CR 配对）

**P1 完整（5 个）**：
4. Customer — 客户主表（从 User 拆分：实名/KYC 状态/风险等级）
5. KycEvent — KYC 事件（提交/审核/通过/拒绝）
6. FundsAccount — 资金账户（可用/冻结/待结算）
7. TradingAccount — 交易账户（持仓/保证金/平仓线）
8. Position — 持仓表（symbol/方向/数量/均价/未实现盈亏）
9. TradeOrder — 交易订单（带状态机：DRAFT→PENDING→PARTIAL_FILLED→FILLED→SETTLED→REVERSED）

**P2 风控/对账（4 个）**：
10. RiskRule — 风控规则（事前审批/事中监控/事后审计）
11. RiskEvent — 风控事件（触发记录+处置）
12. ReconciliationRecord — 对账记录（日终对账）
13. IdempotencyKey — 幂等键（防重复提交）

### 5.3 现有 17 模型金融级改造（8 项重点）

1. **User 拆分**：保留 User 作为登录账号，新增 Customer 作为客户主表（实名信息/KYC/风险等级）
2. **UserProfile 资金字段**：Float → Decimal(18, 8)（P0）
3. **TradingParams 资金字段**：Float → Decimal(18, 8)（P0）
4. **CreditsAccount**：Float → Decimal(18, 8)（P0）+ 关联 FundsAccount（P1）
5. **CreditsTransaction**：迁移到 LedgerTransaction + LedgerPosting 复式记账（P0，原表保留只读做历史）
6. **Order**：Float → Decimal(18, 8)（P0）+ 关联 TradeOrder 状态机（P1）
7. **Strategy**：positionSize/stopLoss/takeProfit Float → Decimal(18, 8)（P0）+ 17 推荐引擎扩展字段 Float → Decimal（P0）
8. **Session**：保留（Auth.js 自动管理），P2 评估是否迁到统一 Session 表

---

## 6. 分阶段实施计划

### 6.1 P0 — 核心金融改造 + SQLite→PostgreSQL 迁移

**目标**：完成 PostgreSQL 中心化 + DECIMAL 铁律 + AuditLog + 复式记账基础

**任务清单**：

| ID | 任务 | 文件 | 验收 |
|----|------|------|------|
| P0-1 | 启动 PostgreSQL，创建 dreambuddy 库 | 本机 docker / brew services | `psql -d dreambuddy -c "\l"` 成功 |
| P0-2 | 修改 .env DATABASE_URL（3.1 + 产物中台共享） | `3.1-FRONTEND/.env` + `7-产物中台/系统研究索引体系/.env` | 两个 .env 一致 |
| P0-3 | 修改 Prisma schema provider=postgresql | `3.1-FRONTEND/prisma/schema.prisma` L9-12 | provider 改为 postgresql |
| P0-4 | 合并产物中台 schema 到 3.1（超集基础） | `3.1-FRONTEND/prisma/schema.prisma` | 21 模型齐全 |
| P0-5 | 修复 Json 默认值语法（SQLite → PG） | schema.prisma UserProfile.allowedSymbols/allowedTradeModes | 默认值 `["BTC-USDT-SWAP"]` 数组语法 |
| P0-6 | Float → Decimal 改造（17 个资金字段） | schema.prisma 8 个模型 | 所有资金字段 @db.Decimal(18, 8) |
| P0-7 | 新增 AuditLog 模型 | schema.prisma 新增 | prisma migrate 成功 |
| P0-8 | 新增 LedgerTransaction + LedgerPosting 模型 | schema.prisma 新增 | prisma migrate 成功 |
| P0-9 | 产物中台 lib/prisma-data-hub.ts 改为 re-export 3.1 单例 | `7-产物中台/系统研究索引体系/lib/prisma-data-hub.ts` | `getPrisma()` 返回 3.1 单例 |
| P0-10 | prisma migrate reset + dev + seed | `3.1-FRONTEND/` | DB schema 初始化，种子数据齐全 |
| P0-11 | 3.1 前端启动验收 | `cd 3.1-FRONTEND && pnpm dev` | localhost:3001 可访问 |
| P0-12 | 产物中台启动验收 | `cd 7-产物中台/系统研究索引体系 && pnpm dev` | localhost:3456 可访问 |
| P0-13 | 关键 API 路由验证 | /api/config/strategies, /api/config/trading-params, /api/feed（反代）, /api/task（DSH） | 200 OK |
| P0-14 | BrowserSkill 真实验收（用户偏好硬约束） | 浏览器访问关键页面 | 用户配置/策略/积分/订单页面正常 |

### 6.2 P1 — 完整金融级用户/账户体系

**目标**：User 拆分三账户隔离 + Position + TradeOrder 状态机

**任务清单**（待 P0 验收后细化）：
- P1-1 新增 Customer 模型（KYC 状态/风险等级/实名信息）
- P1-2 新增 KycEvent 模型（KYC 提交/审核/通过/拒绝事件流）
- P1-3 新增 FundsAccount 模型（可用/冻结/待结算）
- P1-4 新增 TradingAccount 模型（持仓汇总/保证金/平仓线）
- P1-5 新增 Position 模型（symbol/方向/数量/均价/未实现盈亏）
- P1-6 新增 TradeOrder 模型（带状态机 DRAFT→PENDING→PARTIAL_FILLED→FILLED→SETTLED→REVERSED）
- P1-7 User 关联 Customer（1:1）
- P1-8 CreditsAccount 关联 FundsAccount（1:1）
- P1-9 数据迁移脚本：从 User 拆分 Customer 初值
- P1-10 API 路由改造：/api/customer, /api/kyc, /api/positions, /api/trade-orders
- P1-11 BrowserSkill 真实验收

### 6.3 P2 — 风控/对账/DreamOS session 持久化

**目标**：风控三道防线 + 对账 + 可选 DreamOS/DSH 数据持久化

**任务清单**（待 P1 验收后细化）：
- P2-1 新增 RiskRule 模型（事前审批/事中监控/事后审计规则）
- P2-2 新增 RiskEvent 模型（风控触发事件+处置）
- P2-3 新增 ReconciliationRecord 模型（日终对账）
- P2-4 新增 IdempotencyKey 模型（幂等键）
- P2-5 TradingParams 关联 RiskRule（用户级风控规则）
- P2-6 评估 DreamOS sessions/ 持久化到 PostgreSQL Session 表
- P2-7 评估 DSH 任务状态持久化到 PostgreSQL TaskRecord 表
- P2-8 对账脚本：dailyTotal = SUM(ledger_postings) 验证
- P2-9 BrowserSkill 真实验收

---

## 7. 验收与回滚

### 7.1 P0 验收清单

- [ ] PostgreSQL 库 dreambuddy 创建成功
- [ ] 两个 .env DATABASE_URL 一致（共享中心化 PG）
- [ ] `3.1-FRONTEND/prisma/schema.prisma` provider=postgresql
- [ ] 21 个模型齐全（17 原有 + 4 产物中台独有 + AuditLog + LedgerTransaction + LedgerPosting）
- [ ] 17 个资金字段全部 @db.Decimal(18, 8)
- [ ] Json 默认值语法修复（数组语法）
- [ ] `npx prisma migrate dev` 成功
- [ ] `npx prisma db seed` 成功
- [ ] 3.1 前端 localhost:3001 启动成功
- [ ] 产物中台 localhost:3456 启动成功
- [ ] 关键 API 路由 200 OK（/api/config/strategies, /api/config/trading-params, /api/feed, /api/task）
- [ ] BrowserSkill 验收：用户配置/策略/积分/订单页面正常
- [ ] record 经验（CLAUDE.md 硬约束）
- [ ] verify 升级记忆
- [ ] hermes 反思（是否形成新 SKILL）

### 7.2 回滚策略

**P0 回滚**：
1. 恢复 .env DATABASE_URL 为 SQLite
2. 恢复 prisma/schema.prisma provider=sqlite
3. `npx prisma migrate reset --force` 重建 SQLite
4. `npx prisma db seed` 重建种子数据

**P1/P2 回滚**：每期独立，新增模型不影响原有功能，可直接删除新增表

---

## 8. 风险与注意事项

### 8.1 已知风险

| 风险 | 严重度 | 缓解 |
|------|-------|------|
| Json 默认值语法差异（SQLite `"\"BTC-USDT-SWAP\""` vs PG `["BTC-USDT-SWAP"]`） | 高 | P0-5 显式修复 + 测试 |
| Float → Decimal 精度损失（已有数据迁移） | 中 | dev.db 仅测试数据，重建策略规避 |
| 产物中台 admin 视图权限（合并后所有用户共享库） | 中 | admin-queries.ts 限定 `role=ADMIN` 才能查所有用户 |
| Prisma 单例合并后并发性能 | 低 | Prisma 连接池默认 5+，可配置 |
| Prisma Json 字段在 PG 用 jsonb 性能更好 | 低 | 显式 `@db.JsonB` 注解 |

### 8.2 关键约束（硬约束，必须 record 到认知库）

1. **产物中台与 3.1 前端不需要融合**（用户确认 2026-09-28）— 但底层共享 PostgreSQL，逻辑层保持分离（运营 vs 用户）
2. **DECIMAL 铁律**：所有资金字段必须 Decimal(18, 8)，禁止 Float
3. **AuditLog 必须存在**：所有 CREATE/UPDATE/DELETE 操作必须留痕
4. **复式记账必须配对**：每笔 LedgerTransaction 必须有 ≥2 条 LedgerPosting（DR/CR 平衡）
5. **金融改造分 3 期**：P0/P1/P2 严格按顺序，每期验收后再启动下期

### 8.3 不在本期范围（明确记录）

- DreamOS 能力注册表/调度器状态/coin_pool.json 迁移到 PostgreSQL（运行稳定，无必要）
- DSH canon_intent_bridge.py 内存映射表迁移（SSOT 是 intent-schema.ts）
- DreamOS sessions/ 文件 → PostgreSQL（P2 评估）
- DSH 任务状态持久化到 PostgreSQL（P2 评估）

---

## 9. 引用与关联

### 9.1 关联文档
- `3-FRONTEND/dream-universal-gateway/docs/USER_SYSTEM_DESIGN.md` v1.0（3.0 用户体系设计源头）
- `3.1-FRONTEND/prisma/schema.prisma`（17 模型 SQLite）
- `7-产物中台/系统研究索引体系/prisma/schema.prisma`（21 模型 SQLite，超集）
- `7-产物中台/docs/TECHNICAL_DESIGN.md`（产物中台技术设计）
- `3.1-FRONTEND/docs/v3-frontend-architecture.md`（3.1 前端架构）

### 9.2 关联认知记忆
- `VM-1790605032943-c2937507`（产物中台不融合硬约束 B 级）
- `VM-1790605574698-faada5d4`（承接关系反转 B 级）
- `VM-1790605363449-72ad330c`（错误记忆已证伪 D 级）
- `VM-1790608350356-64f06e81`（金融产品设计理念调研经验 B 级）
- `VM-1790255435891-160b14ea`（SACG vs A/C/F 架构澄清 A 级）
- `VM-1790033750685-1552d66d`（Schema 兼容性检测经验 B 级）

### 9.3 适用 SKILL
- `dream-research-workflow` v1.0.0（深度调研/技术调研）
- `dream-tdd-dev-workflow` v1.0.0（TDD 开发 P0/P1/P2 任务）
- `dream-bugfix-workflow` v1.0.0（迁移中 bug 修复）
- `dream-doc-sync-workflow` v1.0.0（SPEC 文档同步）
- `dream-eng-mgmt-workflow` v1.0.0（P0/P1/P2 排期）

---

## 10. 评审签字

- [ ] 用户评审（采用方案1 决策者）
- [ ] 架构评审（确认 4 系统无冲突）
- [ ] P0 启动确认

---

**END OF SPEC**
