# 7-产物中台 — API 规格说明

> **版本**: v1.0  
> **更新日期**: 2026-09-30  
> **实现工程**: `dream-product-hub` v0.2.0  
> **基础路径**: `http://localhost:3456`

---

## 1. 接口概览

本模块为 Next.js 应用，通过 Route Handlers（`app/api/*/route.ts`）对外提供 HTTP API。所有路由均声明 `export const dynamic = "force-dynamic"` 强制动态渲染。

| 分组 | 路由 | 方法 | 说明 |
|------|------|------|------|
| 产物统计 | `/api/stats` | GET | 产物统计聚合 |
| 缓存 | `/api/refresh` | GET/POST | 查询 / 手动刷新产物缓存 |
| 推荐引擎 | `/api/recommendation-engine/trigger` | POST | 手动触发推荐引擎 |
| 推荐引擎 | `/api/recommendation-engine/current-strategy` | GET | 当前推荐策略 |
| 推荐引擎 | `/api/recommendation-engine/library` | GET | 策略库 |
| 推荐引擎 | `/api/recommendation-engine/backtests` | GET | 回测历史（分页） |
| 推荐引擎 | `/api/recommendation-engine/internal/strategy` | — | 内部策略接口 |
| Dream Agent | `/api/dream-agent/invoke` | POST | 调用 Dream Agent |
| 实时流 | `/api/realtime/stream` | GET | 实时事件 SSE 流 |
| 会议流 | `/api/meeting/stream` | GET | 会议辩论 SSE 流 |
| 后台总览 | `/api/admin/stats/overview` | GET | 业务数据总览 |
| 后台管理 | `/api/admin/*` | GET/POST/PATCH | 用户/策略/订单/积分等 |

---

## 2. 认证方式

当前 API 路由未实现鉴权中间件，为内部服务接口。推荐引擎内部接口（`/api/recommendation-engine/internal/*`）通过环境变量 `RECOMMENDATION_ENGINE_API_KEY` 配置 API Key（见 `engine.py`）。

- **生产部署**：应在反向代理层（如 Nginx）添加访问控制
- **内部调用**：`engine.py` 通过 `INTERNAL_API_KEY` 环境变量传递密钥

---

## 3. 接口详情

### 3.1 产物统计 — `GET /api/stats`

调用 `getArtifactsData()`，返回产物统计聚合。

**响应**：

```json
{
  "total": 128,
  "departments": 5,
  "by_department": { "research": 40, "trading": 30, "..." },
  "by_type": { "strategy": 20, "report": 50, "..." },
  "by_status": { "active": 100, "archived": 28 }
}
```

**错误**：HTTP 500 `{ "total": 0, "departments": 0, "error": "Failed to load stats" }`

---

### 3.2 缓存管理 — `/api/refresh`

#### `GET /api/refresh` — 查询缓存状态

**响应**：

```json
{
  "ok": true,
  "total": 128,
  "generated_at": "2026-09-30T08:00:00.000Z",
  "statistics": { "by_department": {}, "by_type": {}, "by_status": {}, "..." }
}
```

#### `POST /api/refresh` — 手动刷新缓存

调用 `invalidateCache()` 后重新扫描。

**响应**：

```json
{
  "ok": true,
  "message": "Cache invalidated and rescanned",
  "total": 128,
  "generated_at": "2026-09-30T08:01:00.000Z"
}
```

**错误**：HTTP 500 `{ "ok": false, "message": "Refresh failed", "error": "..." }`

---

### 3.3 推荐引擎 — `POST /api/recommendation-engine/trigger`

手动触发一轮推荐策略生成，spawn `engine.py` 子进程。

**请求体**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `force` | `boolean` | 否 | `false` | 是否强制刷新（绕过 5 日限制） |
| `baseline` | `string` | 否 | `v9` | 基线版本 |

**响应（成功）**：

```json
{
  "success": true,
  "runId": "manual-1727952000000",
  "message": "引擎运行成功",
  "output": "..."
}
```

**响应（失败）**：

| HTTP | 场景 | body |
|------|------|------|
| 404 | 引擎脚本不存在 | `{ success: false, error, hint }` |
| 500 | 引擎运行失败 | `{ success: false, runId, error, output, stderr }` |
| 504 | 超时（5 分钟） | `{ success: false, runId, error: "引擎运行超时（5分钟）", output }` |

---

### 3.4 推荐引擎 — `GET /api/recommendation-engine/current-strategy`

获取当前推荐策略（`type=RECOMMENDED` 且 `status in (APPROVED, APPLIED)` 的最新策略），含最近 5 条回测记录。

**响应**：

```json
{
  "success": true,
  "strategy": {
    "id": "...",
    "name": "...",
    "direction": "BUY",
    "symbol": "BTC-USDT-SWAP",
    "regime": "...",
    "status": "APPROVED",
    "recommendedDays": 3,
    "isBetterThanBaseline": true,
    "backtestRecords": [ ... ]
  },
  "meta": {
    "recommendedDays": 3,
    "daysUntilForcedRefresh": 2,
    "isBetterThanBaseline": true,
    "libraryCount": 12
  }
}
```

**错误**：HTTP 500 `{ success: false, error: "获取推荐策略失败" }`

---

### 3.5 推荐引擎 — `GET /api/recommendation-engine/library`

查询策略库（`isInLibrary=true` 的策略），按 `libraryScore` 降序，含每条策略最新回测记录。

**查询参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `includeArchived` | `boolean` | `false` | 是否包含已归档（`libraryActive=false`）策略 |

**响应**：

```json
{
  "success": true,
  "items": [
    {
      "id": "...",
      "name": "...",
      "direction": "BUY",
      "symbol": "BTC-USDT-SWAP",
      "regime": "...",
      "backtestSharpe": 1.8,
      "backtestMaxDrawdown": -5.2,
      "backtestTotalReturn": 23.5,
      "baselineVersion": "v9",
      "isBetterThanBaseline": true,
      "libraryScore": 85.5,
      "libraryActive": true,
      "libraryArchivedAt": null,
      "generation": 3,
      "sourceEngine": "recommendation-engine",
      "createdAt": "...",
      "lastDailyBacktestDate": "...",
      "consecutiveBelowBaseline": 0,
      "latestRecord": {
        "backtestDate": "...",
        "isBetterThanBaseline": true,
        "sharpeRatio": 1.8
      }
    }
  ],
  "total": 12,
  "activeCount": 10,
  "archivedCount": 2
}
```

**错误**：HTTP 500 `{ success: false, error: "获取策略库失败" }`

---

### 3.6 推荐引擎 — `GET /api/recommendation-engine/backtests`

分页查询回测历史记录。

**查询参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | `number` | `1` | 页码 |
| `pageSize` | `number` | `20` | 每页条数（最大 100） |
| `strategyId` | `string` | — | 按策略过滤 |
| `baselineVersion` | `string` | — | 按基线版本过滤 |

**响应**：

```json
{
  "success": true,
  "items": [
    {
      "id": "...",
      "strategyId": "...",
      "strategyName": "...",
      "strategyDirection": "BUY",
      "backtestDate": "2026-09-29T00:00:00.000Z",
      "backtestPeriod": "7D",
      "baselineVersion": "v9",
      "symbol": "BTC-USDT-SWAP",
      "sharpeRatio": 1.8,
      "maxDrawdown": -5.2,
      "winRate": 58.0,
      "profitFactor": 1.6,
      "totalReturn": 23.5,
      "tradeCount": 42,
      "baselineSharpe": 1.2,
      "baselineMaxDD": -8.1,
      "baselineTotalReturn": 12.0,
      "isBetterThanBaseline": true,
      "runId": "...",
      "sharpeDiff": 0.6,
      "ddDiff": 2.9,
      "returnDiff": 11.5
    }
  ],
  "total": 100,
  "page": 1,
  "pageSize": 20,
  "totalPages": 5
}
```

**错误**：HTTP 500 `{ success: false, error: "获取回测历史失败" }`

---

### 3.7 Dream Agent — `POST /api/dream-agent/invoke`

调用 Dream Agent 后端（`DREAM_AGENT_API_BASE`，默认 `http://127.0.0.1:5001`），并发布实时事件。

**请求体**：`DreamAgentInvokeInput`（见 `lib/types.ts`）

**响应**：透传 `invokeDreamAgent` 结果。

**错误**：HTTP 502 `{ success: false, error: "..." }`

---

### 3.8 实时事件流 — `GET /api/realtime/stream`

SSE（Server-Sent Events）实时事件流。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `channel` | `string` | 是 | 通道：`dream-agent` / `meeting` / `system` |

**响应**：`text/event-stream`，每条事件为 `data: {json}\n\n` 格式。

**错误**：HTTP 400 `{ error: "Invalid channel" }`

---

### 3.9 后台管理 — `/api/admin/strategies`

#### `GET /api/admin/strategies` — 策略列表（分页）

**查询参数**（`parseListQuery` 解析，见 `lib/types/admin-api.ts`）：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | `number` | `1` | 页码 |
| `pageSize` | `number` | `20` | 每页（最大 100） |
| `search` | `string` | — | 搜索关键词 |
| `sort` | `string` | — | 排序字段 |
| `order` | `'asc' \| 'desc'` | `desc` | 排序方向 |
| `status` | `string` | — | 状态过滤 |
| `type` | `string` | — | 类型过滤 |
| `uid` | `string` | — | 用户过滤 |

**响应**：

```json
{
  "success": true,
  "data": [ /* Strategy 列表 */ ],
  "meta": { "page": 1, "pageSize": 20, "total": 50, "totalPages": 3 }
}
```

#### `GET /api/admin/strategies/[id]` — 单策略详情

#### `PATCH /api/admin/strategies/[id]` — 更新策略

---

### 3.10 其他后台路由

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/admin/stats/overview` | GET | 业务数据总览（`getBusinessDataView`） |
| `/api/admin/api-configs` | GET/POST | API 配置管理 |
| `/api/admin/channels` | GET/POST | 通信渠道管理 |
| `/api/admin/credits` | GET/POST | 积分管理 |
| `/api/admin/executions` | GET | 执行记录 |
| `/api/admin/orders` | GET | 订单管理 |
| `/api/admin/tasks` | GET/POST | 任务管理 |
| `/api/admin/trading-params` | GET/PATCH | 交易参数 |
| `/api/admin/users` | GET | 用户列表 |
| `/api/admin/users/[uid]` | GET/PATCH | 单用户详情 |

---

### 3.11 内部数据接口（`lib/prisma-data-hub.ts`）

非 HTTP 接口，供 API 路由内部调用。

| 函数 | 返回类型 | 说明 |
|------|---------|------|
| `getPrisma()` | `PrismaClient` | 单例 Prisma Client |
| `getStrategyBusinessStats()` | `StrategyBusinessStats` | 策略业务统计（按状态/类型分组、活跃任务、执行数） |
| `getUserContextBusinessStats()` | `UserContextBusinessStats` | 用户上下文统计（用户数、API 配置、渠道、积分余额、订单数） |

---

## 4. 错误码

HTTP 状态码用于区分错误类型：

| HTTP | 场景 | 响应结构 |
|------|------|---------|
| 200 | 成功 | 业务数据 |
| 400 | 参数非法（如 SSE channel 无效） | `{ error: "Invalid channel" }` |
| 404 | 资源不存在（如推荐引擎脚本缺失） | `{ success: false, error, hint }` |
| 500 | 服务端异常（Prisma/数据源/引擎失败） | `{ success: false, error }` 或 `{ total: 0, error }` |
| 502 | Dream Agent 后端不可达 | `{ success: false, error }` |
| 504 | 推荐引擎超时（5 分钟） | `{ success: false, runId, error, output }` |

**统一响应约定**：
- 成功：`{ success: true, data, meta? }`（admin 系列）或直接返回业务对象（stats/library/backtests）
- 失败：`{ success: false, error, message? }`

---

## 5. 版本管理

| 项 | 值 |
|----|-----|
| 工程版本 | `0.2.0`（`package.json` → `dream-product-hub`） |
| Prisma Schema 版本 | v1.0（`schema.prisma` 头部，2026-05-14） |
| 推荐引擎基线版本 | `v9`（`engine.py` `DEFAULT_CONFIG.baseline_version`） |
| 文档版本 | v1.0 |

**数据模型**：见 `prisma/schema.prisma`，核心模型包括 `User` / `UserProfile` / `ApiConfig` / `TradingParams` / `Strategy` / `StrategyTask` / `StrategyTaskOrder` / `StrategyExecutionRun` / `StrategyBacktestRecord` / `RecommendationEngineLog` / `ChannelConfig` / `CreditsAccount` / `CreditsTransaction` / `Order` / `VerificationCode` / `Session`。
