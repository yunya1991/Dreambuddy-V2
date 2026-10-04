# SPEC-20260929 — L1 可观测性试点：trace_id 全链路 + JSONL 事件流 + 中台 ops 看板

**版本**: v1.0
**日期**: 2026-09-29
**作者**: Trae + User
**状态**: Draft（待用户评审）
**关联**: SPEC-20260928-POSTGRESQL-CENTRALIZATION（数据底座姊妹篇） · VM-1790608324891（架构盘点） · VM-1790605574698（数据库反模式）

---

## Executive Summary

本 SPEC 规划 **L1 可观测性试点**，选择 1 条用户核心链路（"分析比特币价格"）打通 **trace_id 全链路 + JSONL 事件流落盘 + 产物中台 ops/traces 看板**，验证"4 系统统一可观测"的技术可行性，为后续 L2 自检测 / L3 自修复 / L4 自迭代打底。

**4 系统现状结论**：
- ✅ **3.1 前端**：`monitor-bus.ts` 已定义完整 `MonitorEvent` schema（含 trace_id / layer / phase / status / duration_ms），但事件**只在 RingBuffer(500) 内存中，不落盘、不跨进程**
- ✅ **DreamOS**：Flask API server 在 8000 端口（`/api/v1/chat`），`GraphExecutor.execute()` 是核心执行器，但**无 trace_id 参数、无节点级事件**
- ✅ **DSH**：canon_intent_bridge + intent-schema.ts SSOT，但**无 trace_id 概念**
- ❌ **产物中台**：**无 /ops/traces 接口，无 trace 可视化页面**

**关键设计原则**：
1. **最小侵入**：复用已有 monitor-bus 事件 schema，仅在 emit 时**追加 JSONL 落盘**
2. **统一规范**：trace_id 格式 + JSONL 文件路径 + 事件字段全集
3. **可追溯**：任何一次 SACG 循环、任何一次 HTTP 调用、任何一次节点执行，都能在中台通过 trace_id 一键还原
4. **可回滚**：所有改动向后兼容，禁用开关即可回到现状

---

## 1. 背景与目标

### 1.1 背景

**当前可观测性缺陷**：
- 用户在前端输入"分析比特币价格"，到拿到响应，**经过 4 个系统但无统一视图**
- 出问题时无法回答：慢在哪一环？失败在哪一环？是哪个节点报错？
- 已有 `~/.workbuddy/audit-log/YYYY-MM-DD.jsonl` 文件格式参考（按日期分文件，append-only）

**试点链路选择理由**：
- "分析比特币价格" = 高频 + 短链路 + 涉及全部 4 系统（前端意图识别 → DSH Agent 执行层 → DreamOS SACG → 中台产物归档）
- 已有成熟的 market_query 意图处理路径
- 触发成本低，可反复验证

### 1.2 目标

| # | 目标 | 验收指标 |
|---|------|---------|
| 1 | trace_id 全链路贯通 | 任一 trace_id 可在 4 系统的 JSONL 中都找到 ≥1 条事件 |
| 2 | JSONL 事件落盘 | `~/.workbuddy/events/{system}/{date}.jsonl` 实时追加，无丢失 |
| 3 | 中台 traces 查询 | `GET /api/ops/traces?trace_id=xxx` 返回按时间排序的完整事件列表 |
| 4 | 中台 traces 看板 | `/ops/traces` 页面可视化 timeline，支持搜索/过滤 |
| 5 | 端到端验证 | 输入"分析比特币价格"，5 秒内可在中台看到完整 trace |

### 1.3 范围与不范围

**范围内（L1 试点）**：
- 单一链路："分析比特币价格"（market_query 意图）
- 4 系统的 JSONL 事件落盘（frontend / dreamos / dsh / hub）
- trace_id 生成与传递规范
- 产物中台 `/api/ops/traces` 查询 API + `/ops/traces` 可视化页面
- 端到端验收报告

**范围外（不在 L1 试点）**：
- PostgreSQL 持久化（归 SPEC-20260928 P0 处理，本试点先用 JSONL 文件）
- L2 自检测（测试金字塔）/ L3 自修复（Trace Replay）/ L4 自迭代
- 其他用户链路（trade / strategy / chat）
- 全链路压测与性能基准
- 认知库 record 自动写入（仍由人工触发）

---

## 2. 现状调研

### 2.1 前端 monitor-bus 现状

**文件**: `3.1-FRONTEND/src/lib/monitor-bus.ts`

```typescript
export interface MonitorEvent {
  id: string;
  trace_id: string;           // 全链路追踪ID (= task_id)
  uid: string;
  timestamp: string;          // ISO8601
  layer: 'frontend' | 'gateway' | 'artifact_hub' | 'workbuddy' | 'intent' | 'router';
  phase: 'user_input' | 'intent_recognized' | 'recognized' | ... | 'result_displayed';
  status: 'received' | 'processing' | 'completed' | 'failed' | 'timeout' | 'denied';
  intent?: string;
  thinking_mode?: string;
  chain?: string[];
  duration_ms?: number;
  error?: string;
  artifact_file?: string;
  message_preview?: string;
}
```

**已有能力**：
- RingBuffer(500) 内存存储
- SSE 推送（最多 30 连接）
- `/api/monitor/events` REST 查询接口

**缺失**：
- 不落盘（重启即丢失）
- 只覆盖前端层（layer 只有 frontend 真实产生事件，其他 layer 字段预留但未启用）

### 2.2 DreamOS 现状

**入口**: `1-ARCHITECTURE/dreamos/apps/api_server.py`（Flask，端口 8000）

**核心执行器**: `1-ARCHITECTURE/dreamos/core/compute/graph_executor.py::GraphExecutor.execute(graph, state, plan, budget, total_budget, graph_store)`

**关键观察**：
- 方法签名中**无 trace_id 参数**
- 节点执行通过 `self._runner.run(current, state, allocated)` 触发
- 已有 checkpointer 机制在 pre_gate / pre_reflect / post_node / post_gate 四个点位写 G 层存储
- **可以把 checkpointer 视为天然的"事件发射点"**——在 checkpoint 时同步写 JSONL

### 2.3 DSH 现状

**位置**: `18-数据获取中心/dsh_runtime/canon_intent_bridge.py` + 前端 `3.1-FRONTEND/src/lib/bridge-client.ts`（HTTP 3847）

**SSOT**: `intent-schema.ts` 定义意图 schema，Python 侧 canon_intent_bridge 是内存映射

**关键观察**：
- 前端 → DSH 通过 HTTP POST 到 `127.0.0.1:3847`
- 无 trace_id 传递约定

### 2.4 产物中台现状

**位置**: `7-产物中台/系统研究索引体系/`（Next.js，端口 3456，腾讯云 49.233.123.96:3456）

**关键观察**：
- `app/api/` 下无 ops/traces 目录
- 已有 admin/users/admin/orders 等管理页面，**缺 traces 看板**
- 已有反代 `/api/chain/artifacts` `/api/feed` 给前端

---

## 3. 设计

### 3.1 trace_id 规范

**格式**：`{YYYYMMDD}-{HHMMSS}-{SYS}-{NANOID8}`

| 字段 | 取值 | 说明 |
|------|------|------|
| YYYYMMDD | 20260929 | 日期，便于按天索引 |
| HHMMSS | 143022 | 时间，秒级 |
| SYS | FE / DOS / DSH / HUB | **生成系统码**（不是当前所在系统） |
| NANOID8 | a3f9k2m1 | 8 位 nanoid，避免冲突 |

**生成规则**：
- **生成时机**：用户请求首次进入系统的时刻（前端 POST /api/task）
- **生成者**：3.1 前端（FE）
- **传递方式**：HTTP header `X-Trace-Id` + 请求体 `trace_id` 字段**双轨**
- **不变性**：同一用户请求，trace_id 全程不变

**示例**：`20260929-143022-FE-a3f9k2m1`

### 3.2 JSONL 事件流规范

**目录结构**：
```
~/.workbuddy/events/
├── frontend/
│   └── 2026-09-29.jsonl
├── dreamos/
│   └── 2026-09-29.jsonl
├── dsh/
│   └── 2026-09-29.jsonl
└── hub/
    └── 2026-09-29.jsonl
```

**事件字段（统一 schema）**：
```json
{
  "v": 1,
  "id": "uuid-v4",
  "trace_id": "20260929-143022-FE-a3f9k2m1",
  "span_id": "n8-char",
  "parent_span_id": "n8-char-or-null",
  "ts": "2026-09-29T14:30:22.123Z",
  "system": "frontend|dreamos|dsh|hub",
  "layer": "sense|arrange|compute|graph_store|api|ui",
  "node": "intent_engine|graph_planner|c1_technical|...",
  "event_type": "request_received|node_start|node_end|llm_call|llm_response|error|response_sent",
  "status": "ok|fail|skip",
  "duration_ms": 0,
  "payload_ref": "sha1-or-null",
  "error": "string-or-null",
  "meta": {}
}
```

**写入约束**：
- append-only，永不修改历史行
- 单行 JSON，无换行符（用 `JSON.stringify` + `\n`）
- 文件锁：写入用 `O_APPEND` 模式，避免并发损坏
- 文件滚动：按日期自动滚动（`YYYY-MM-DD.jsonl`）
- 失败兜底：JSONL 写失败**不能**阻断业务流程（降级为 console.warn）

### 3.3 trace_id 传递链路

```
[用户] 输入"分析比特币价格"
   │
   ▼
[3.1 前端] POST /api/task
   │  1. 生成 trace_id = 20260929-143022-FE-a3f9k2m1
   │  2. 写事件: frontend/api/request_received
   │  3. 意图识别 (FE)
   │  4. 写事件: frontend/intent/intent_recognized
   │
   ├── HTTP → http://127.0.0.1:3847 (DSH Flask)
   │     Header: X-Trace-Id: 20260929-143022-FE-a3f9k2m1
   │     Body:   { trace_id, intent, ... }
   │
   ▼
[DSH] canon_intent_bridge
   │  1. 从 header 读 trace_id
   │  2. 写事件: dsh/bridge/intent_received
   │  3. 桥接到 DreamOS
   │
   ├── HTTP → http://127.0.0.1:8000/api/v1/chat (DreamOS Flask)
   │     Header: X-Trace-Id: 20260929-143022-FE-a3f9k2m1
   │
   ▼
[DreamOS] api_server.py
   │  1. 从 header 读 trace_id，注入 state.metadata['trace_id']
   │  2. 写事件: dreamos/api/request_received
   │  3. 调用 TradingAgent → SACG
   │     ├─ Sense:    dreamos/sense/intent_engine.node_end
   │     ├─ Arrange:  dreamos/arrange/graph_planner.node_end
   │     ├─ Compute:  dreamos/compute/<node_id>.node_start / .node_end
   │     └─ GraphStore: dreamos/graph_store/checkpoint.saved
   │  4. 写事件: dreamos/api/response_sent
   │
   ├── HTTP 响应（带回 trace_id header）
   │
   ▼
[3.1 前端]
   │  1. 接收响应
   │  2. 写事件: frontend/api/response_received
   │  3. 触发产物归档 → HTTP POST 中台 /api/chain/artifacts
   │     Header: X-Trace-Id: 20260929-143022-FE-a3f9k2m1
   │
   ▼
[产物中台] /api/chain/artifacts
   │  写事件: hub/artifact/received
   │
   ▼
[中台看板] /ops/traces?trace_id=20260929-143022-FE-a3f9k2m1
   读取 4 个系统的 JSONL，按 ts 排序，可视化 timeline
```

### 3.4 前端改动（最小集）

**改动 1：monitor-bus 落盘**
- 文件：`3.1-FRONTEND/src/lib/monitor-bus.ts`
- 改动：新增 `writeJsonlEvent(event)` 私有方法，在 `emitMonitorEvent` 末尾同步调用
- 文件路径：`~/.workbuddy/events/frontend/{YYYY-MM-DD}.jsonl`

**改动 2：trace_id 生成器**
- 文件：`3.1-FRONTEND/src/lib/trace-id.ts`（新建，约 30 行）
- 提供 `generateTraceId(sysCode: 'FE'): string`

**改动 3：task route 生成 trace_id**
- 文件：`3.1-FRONTEND/src/app/api/task/route.ts`
- 替换现有 `task_${Date.now()}_pending` 为规范格式

**改动 4：bridge-client 传 trace_id**
- 文件：`3.1-FRONTEND/src/lib/bridge-client.ts`
- 调用 DSH 时在 header 加 `X-Trace-Id`

### 3.5 DreamOS 改动（最小集）

**改动 1：JSONL writer**
- 文件：`1-ARCHITECTURE/dreamos/shared/event_writer.py`（新建，约 80 行）
- 提供 `emit_event(trace_id, system, layer, node, event_type, status, **kw)`

**改动 2：api_server 接收 trace_id**
- 文件：`1-ARCHITECTURE/dreamos/apps/api_server.py`
- 从 `X-Trace-Id` header 读取，注入 `state.metadata['trace_id']`

**改动 3：GraphExecutor 嵌入事件**
- 文件：`1-ARCHITECTURE/dreamos/core/compute/graph_executor.py`
- 在 `execute()` 入口、`self._runner.run()` 前后、`store.checkpoint()` 后写事件
- **不修改方法签名**——通过 `state.metadata.get('trace_id')` 读取

**改动 4：checkpoint 同步写事件**
- 文件：`1-ARCHITECTURE/dreamos/core/graph_store/store.py`
- 在 `checkpoint()` 末尾写 `dreamos/graph_store/checkpoint.saved` 事件

### 3.6 DSH 改动（最小集）

**改动 1：canon_intent_bridge 接收 trace_id**
- 文件：`18-数据获取中心/dsh_runtime/canon_intent_bridge.py`
- 从 HTTP header 读取，写 `dsh/bridge/intent_received` 事件

### 3.7 产物中台改动（最小集）

**改动 1：traces 查询 API**
- 文件：`7-产物中台/系统研究索引体系/app/api/ops/traces/route.ts`（新建）
- 接受 `?trace_id=xxx` 或 `?date=YYYY-MM-DD&system=xxx`
- 实现：扫描 `~/.workbuddy/events/*/{date}.jsonl`，按 ts 排序返回

**改动 2：traces 看板页面**
- 文件：`7-产物中台/系统研究索引体系/app/ops/traces/page.tsx`（新建）
- 顶部：trace_id 搜索框 + 日期选择 + 系统过滤
- 主体：timeline 可视化（垂直时间轴 + 系统泳道 + 节点状态色块）
- 底部：原始 JSON 折叠面板

### 3.8 验收链路

**触发**：用户在 3.1 前端输入"分析比特币价格"

**预期 JSONL 事件序列**（关键节点）：
| # | system | layer | node | event_type | duration_ms 期望 |
|---|--------|-------|------|------------|------------------|
| 1 | frontend | api | /api/task | request_received | - |
| 2 | frontend | intent | intent_engine | intent_recognized | <50 |
| 3 | dsh | bridge | canon_intent_bridge | intent_received | <20 |
| 4 | dreamos | api | /api/v1/chat | request_received | - |
| 5 | dreamos | sense | intent_engine | node_end | <100 |
| 6 | dreamos | arrange | graph_planner | node_end | <200 |
| 7 | dreamos | compute | market_data | node_end | <2000 |
| 8 | dreamos | compute | llm_analysis | node_end | <3000 |
| 9 | dreamos | graph_store | checkpointer | checkpoint.saved | <50 |
| 10 | dreamos | api | /api/v1/chat | response_sent | - |
| 11 | frontend | api | /api/task | response_received | <6000 |
| 12 | hub | artifact | /api/chain/artifacts | received | <500 |

**通过标准**：12 个事件全部存在，按 ts 严格递增，总时长 < 10 秒。

---

## 4. 验收标准

| # | 验收项 | 方法 | 通过标准 |
|---|--------|------|---------|
| 1 | trace_id 格式规范 | 单元测试 | 匹配正则 `^\d{8}-\d{6}-(FE|DOS|DSH|HUB)-[a-z0-9]{8}$` |
| 2 | trace_id 全链路贯通 | E2E | 任一 trace_id 在 4 系统 JSONL 中都找到 ≥1 条事件 |
| 3 | JSONL 不丢失 | 压测 | 100 次请求 → 100 条 trace，事件完整率 100% |
| 4 | JSONL 写失败不阻断业务 | 故障注入 | chmod 000 ~/.workbuddy/events 后业务正常返回 |
| 5 | 中台查询性能 | 手测 | trace_id 查询 P95 < 500ms |
| 6 | 中台页面可用 | 手测 | timeline 渲染正确，支持搜索/过滤/复制 trace_id |
| 7 | BrowserSkill 端到端 | BrowserSkill | 真实打开前端输入"分析比特币价格"，5 秒内在中台看到完整 trace |

---

## 5. 回滚方案

| 改动 | 回滚方式 |
|------|---------|
| 前端 monitor-bus 落盘 | 设置环境变量 `MONITOR_JSONL_DISABLE=1`，emit 时跳过写文件 |
| 前端 trace_id 生成器 | 不影响（新增文件，删除即可） |
| DreamOS event_writer | 设置 `DREAMOS_EVENT_JSONL=0`，emit_event 变 no-op |
| GraphExecutor 嵌入事件 | 通过 `state.metadata.get('trace_id') is None` 自动跳过 |
| 中台 /ops/traces | 删除文件即可（新增页面） |
| DSH 桥接改动 | 通过 `if not trace_id: return` 自动跳过 |

**全局开关**：环境变量 `TRACE_PILOT_DISABLE=1` 一次性禁用所有试点功能。

---

## 6. 实施步骤

| 步骤 | 内容 | 预计产出 |
|------|------|---------|
| 1 | 起草并评审 SPEC（本文档） | 用户确认 v1.0 |
| 2 | 实现 trace_id 生成器 + 前端落盘 | 前端 JSONL 事件流 |
| 3 | 实现 DreamOS event_writer + 嵌入点 | DreamOS JSONL 事件流 |
| 4 | 实现 DSH 桥接改动 | DSH JSONL 事件流 |
| 5 | 实现中台 /api/ops/traces + /ops/traces 页面 | 中台看板可用 |
| 6 | 端到端验证 + BrowserSkill 验收 | 验证报告 |
| 7 | 产出可行性报告 + 认知库 record | 可行性结论 |

---

## 7. 开放问题

| # | 问题 | 待澄清 |
|---|------|--------|
| 1 | 中台服务器在腾讯云，JSONL 写在本地 `~/.workbuddy`——中台**如何读取**？ | 选项 A：中台只查本地（演示用）；选项 B：前端通过 HTTP 推送事件到中台；选项 C：腾讯云挂 NFS 共享。**L1 试点先用 A** |
| 2 | JSONL 文件大小增长 | 估算：1 事件约 500B，1 天 1000 请求 × 12 事件 = 6MB/天，月增 180MB。**无需滚动清理**（首期） |
| 3 | trace_id 是否要在 PostgreSQL 落表？ | SPEC-20260928 P0 一并处理；L1 试点先用 JSONL |
| 4 | 中台用户权限 | 首期无权限管控（只读，运营人员专用） |

---

## 8. 与已有方案的关系

- **SPEC-20260928 PostgreSQL 中心化**：本 SPEC 是其**前置依赖**（先证明可观测，再迁数据底座）；P0 期将 traces JSONL 落表
- **VM-1790608324891 架构盘点**：本 SPEC 落地其"前端图表层是开源空白，必须自建"的 P0 项
- **VM-1790605574698 数据库反模式**：本 SPEC 不改数据库，避免触碰反模式
- **monitor-bus.ts**：本 SPEC 是其**持久化扩展**，不重构其内存 RingBuffer

---

## 9. hermes 反思预案

任务完成后必须执行：
1. **record**：本次试点经验（成功 / 失败 / 关键坑）
2. **verify**：VM-1790608324891 中相关条目
3. **判断**：本流程是否值得形成 SKILL？
   - 触发条件：复用 ≥ 2 次 或 ≥ 3 步编排
   - 若满足 → 调用 skill-creator 创建 `dream-l1-trace-pilot` SKILL
   - 双位置存储：`.trae/skills/` + `1-ARCHITECTURE/skills/`
