# 三端联通规划：3-FRONTEND — 7-ARTIFACT-HUB-V2 — 6-TRADING

> 任务: task-connectivity-gap-trading-hub-001
> 日期: 2026-05-20
> 状态: 评审中（未实施）

---

## 一、现状梳理

### 1.1 三模块端口与前端

| 模块 | 技术 | 服务端口 | 前端入口 |
|---|---|---|---|
| **3-FRONTEND** | Next.js | 3000 | `http://localhost:3000/dashboard` `/chain` `/feed` `/market/*` `/board/*` `/ops/*` |
| **7-ARTIFACT-HUB-V2** | Express (Node.js/TypeScript) | 3456（配置文件） | `http://127.0.0.1:3456/ui-map` `/ops` `/board` |
| **6-TRADING** | Flask (Python) | 3847 | `http://127.0.0.1:3847/` — 纯 API，无独立前端 |

### 1.2 现有连通性

#### 3-FRONTEND → 7-ARTIFACT-HUB-V2（已打通）

前端 `route.ts` 文件通过 HTTP fetch 代理到 Hub（`ARTIFACT_HUB_URL` 环境变量，默认 `http://127.0.0.1:3456`）：

| 前端路由 | 代理到 Hub 路径 | 功能 |
|---|---|---|
| `/api/chain/artifacts` | `GET /chain/artifacts` | 工作流产物列表 |
| `/api/feed` | `GET /api/artifacts` | 产物 Feed 流 |
| `/api/task` | Hub 路由 | 任务管理 |
| `/api/reports` | Hub 路由 | 报告查询 |
| `/api/board/*` | `/board/*` | 董事会控制台 |
| `/api/ops/queues` | `/ops/queues` | 队列监控 |
| `/api/ops/decision-levels` | `/ops/decision-levels` | 决策级别 |

#### 3-FRONTEND → 6-TRADING（**绕过了** 6-TRADING Flask）

| 前端路由 | 实际行为 | 备注 |
|---|---|---|
| `/api/trade/balance` | **直接调 OKX API / okx CLI** | 不走 Flask bridge |
| `/api/config/trading-params/*` | 本地 Prisma 数据库 | 不走 Flask bridge |
| `/api/config/strategies/*` | 本地 Prisma 数据库 | 不走 Flask bridge |

**关键发现**: 前端的交易功能没有经过 6-TRADING 的 Flask 服务（3847），而是直接调交易所 API。Flask bridge 是一个**未被前端使用的独立服务**。

#### 7-ARTIFACT-HUB-V2 → 6-TRADING（未连通）

- Hub 的 `types.ts` 中有 `WorkflowType = "legacy_chain" | "trading_v2"` 类型定义
- 但 Hub **没有任何代码**调用 6-TRADING Flask 的任何 API
- Hub 不知道 6-TRADING 服务的存在

#### 6-TRADING → 7-ARTIFACT-HUB-V2（单向文件投递）

- `mailbox_scanner.py` 扫描交易邮箱后，写入 `~/.workbuddy/artifacts/trading/` 本地文件
- Hub 的 `ArtifactStore` 扫描 artifacts 目录时可读取这些文件
- **这是文件级别的单向管道，不是实时 API**

---

## 二、问题分析

### 问题 1: Hub 无法调用 6-TRADING

Hub 作为中台，应该统一管理前后端数据流，但当前无法：
- 获取实时行情数据（K线、ticker）
- 查看交易账户状态
- 执行 SKILL（A1-A9）
- 获取交易策略信息

### 问题 2: Trading 无法实时通知 Hub

mailbox_scanner 只写本地文件，Hub 只能在下一次 artifact 扫描时发现新数据：
- 延迟高（文件轮询，非实时）
- 无法支持事件驱动
- 前端无法通过 Hub SSE 实时接收交易信号

### 问题 3: 前端交易功能绕过 Hub

前端 `/api/trade/balance` 直接调 OKX API，不经过 Hub：
- 交易数据不经过 Hub，Hub 无法审计交易记录
- 无法在 `/dashboard` 中展示 Hub 侧的 governance 标签（L1/L2/L3）
- 交易决策链路断裂

---

## 三、改动方案（评审后实施）

### 3.1 Hub → 6-TRADING：新增 `/api/trading/*` 代理路由

**目标**: 在 Hub 的 Express 服务器中新增代理层，将 `/api/trading/*` 请求转发到 6-TRADING Flask 服务（3847）。

**新增文件**:
- `7-ARTIFACT-HUB-V2/src/trading-bridge.ts` — Hub→Trading 代理模块

**修改文件**:
- `7-ARTIFACT-HUB-V2/src/index.ts` — 新增路由处理逻辑
- `7-ARTIFACT-HUB-V2/src/types.ts` — 新增 Trading 相关类型

**路由映射表**:

| Hub 路径 | 代理到 Flask | 方法 | 功能 |
|---|---|---|---|
| `GET /api/trading/health` | `GET /api/health` | GET | Flask bridge 健康检查 |
| `GET /api/trading/market/*` | `GET /api/market/*` | GET | 行情数据（K线/ticker） |
| `POST /api/trading/trade/*` | `POST /api/trade/*` | POST | 交易执行（下单/撤单） |
| `GET /api/trading/skill/*` | `GET /api/skill/*` | GET/POST | A0-A9 SKILL 路由 |
| `POST /api/trading/intent/*` | `POST /api/intent/*` | POST | 意图路由 |
| `GET /api/trading/bridge/*` | `GET /api/bridge/*` | GET | 桥接管理/配置 |
| `GET /api/trading/realtime/*` | `GET /api/realtime/*` | GET | 实时数据 |

**技术实现**:
- 使用 Node.js 原生 `http`/`https` 模块转发请求，零新增依赖
- 支持 GET/POST 方法透传
- 超时时间 15 秒，返回 502 当 Flask 不可达
- Hub CORS 已覆盖 Flask 端口（需确认）

### 3.2 Trading → Hub：mailbox_scanner 实时推送

**目标**: mailbox_scanner 完成文件投递后，通过 HTTP POST 将交易摘要实时推送到 Hub。

**修改文件**:
- `6-TRADING/scripts/mailbox_scanner.py` — 新增 `push_to_hub()` 函数

**新增 Hub 端点**:
- `POST /api/trading/mailbox-scan` — Hub 接收交易摘要推送

**推送内容**:
```json
{
  "source": "mailbox_scanner",
  "scanned_at": "2026-05-20T10:00:00",
  "screen1": { "direction": "LONG", "confidence": 0.75, "inst_id": "BTC-USDT-SWAP" },
  "screen2": { ... },
  "signals": [ { "skill": "A4", "confidence": 80 } ],
  "execution_log": [ ... ]
}
```

**Hub 侧处理**:
1. 将摘要存入 MetaStore 作为 MarketIntel
2. 通过 EventBus 发布 `trading:mailbox` 事件
3. 前端可通过 `/events/stream?traceId=trading:mailbox` 实时接收

### 3.3 CORS 配置调整

**修改文件**:
- `6-TRADING/bridge/api/dream_api_server.py` — Flask CORS 添加 Hub 端口白名单

在 `origins` 列表中新增 `http://localhost:3456` 和 `http://127.0.0.1:3456`。

---

## 四、不在此范围内（后续任务）

以下内容**本次不实施**，记录为后续改进方向：

1. **前端 `/api/trade/balance` 改走 Hub**: 需要修改 Next.js 前端路由，将 OKX 直接调用改为通过 Hub → Flask bridge。涉及前端代码改动，需要单独评审。

2. **WebSocket 实时行情推送**: Flask bridge 支持 SocketIO，Hub 需要 WebSocket 客户端桥接到 Hub 的 SSE 流。涉及架构重构。

3. **交易决策链路治理**: Hub 接收交易请求后，自动打 L1/L2/L3 决策标签，写入 governance 审计日志。需要与 Governance AGENT 协作设计。

---

## 五、已改动代码（标注）

> 以下代码已在本次对话中新增/修改，**尚未评审确认，暂不应合并**。

| 文件 | 类型 | 改动内容 |
|---|---|---|
| `7-ARTIFACT-HUB-V2/src/trading-bridge.ts` | **新增文件** | Hub→Trading 代理模块，`proxyToTrading()` 和 `checkBridgeHealth()` 函数 |
| `7-ARTIFACT-HUB-V2/src/index.ts` | 修改 | 新增 import `trading-bridge.js`；新增 `/api/trading/*` 路由处理 + `/api/trading/mailbox-scan` 接收端点 |
| `6-TRADING/scripts/mailbox_scanner.py` | 修改 | 新增 `urllib` import；新增 `HUB_URL`/`HUB_TRADING_ENDPOINT` 配置；新增 `push_to_hub()` 函数；main() 增加 Hub 推送调用和报告字段 |
| `7-ARTIFACT-HUB-V2/src/types.ts` | 修改 | 新增 `TradingBridgeStatus` 和 `MailboxScanPayload` 接口 |
| `6-TRADING/bridge/api/dream_api_server.py` | 修改 | CORS origins 新增 Hub 端口 3456 |

---

## 六、验证计划

评审通过后，按以下步骤验证：

1. **Hub TypeScript 编译**: `cd 7-ARTIFACT-HUB-V2 && npx tsc --noEmit` — 无报错
2. **Hub 服务启动**: `cd 7-ARTIFACT-HUB-V2 && npm start` — 服务监听 3456
3. **Flask 服务启动**: `cd 6-TRADING && python3 bridge/run_server.py` — 服务监听 3847
4. **Hub→Trading 代理**: `curl http://127.0.0.1:3456/api/trading/health` — 应返回 Flask 健康信息
5. **Trading→Hub 推送**: 手动运行 `mailbox_scanner.py --verbose` — 日志显示 "Hub 推送成功"
6. **前端页面**: 访问 `http://localhost:3000/dashboard` — 页面正常加载
