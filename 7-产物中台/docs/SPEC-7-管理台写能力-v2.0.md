# SPEC-7 产物中台「受控写」管理台 v2.0（完整实施基线）

> 状态：评审通过 · 定稿 · 2026-11-15
> 范围：`7-产物中台/系统研究索引体系`（Next.js 14，端口 3456）`/admin` 与 `/api/admin/**`
> 关联系统：`27-策略治理审批系统`（8094，审批/审计/回滚）、`4-MEMORY/9-工具与接口/param_center`、`3.1-FRONTEND /api/config/*` + `classic-system-bridge`
> 评审记录：[REVIEW-20261115-管理台写能力.md](./REVIEW-20261115-管理台写能力.md)（8 项问题已全部在本版闭环）
> 上游硬约束：云端为唯一生产写入口；本地禁写生产表；**禁止 `prisma migrate` / `db push`**（库存在 drift，认知库 VM-1791896024014）

---

## 0. 版本与决策台账

| 版本 | 变更 |
|---|---|
| v1.0 | 初稿 |
| v1.1 | 按评审修订 8 项（鉴权、bridge、审计 outbox、并发、部署、范围、决策回填、负载评估） |
| **v2.0** | **完整实施基线**：补齐 5 项评审遗留的可执行细节（27 审计加锁补丁、approvals 执行端点契约、Prisma 单例与连接池、confirmToken 一次性语义、逐操作 CAS 语句）；积分阈值定稿；所有未决问题关闭；v1.0/v1.1 归档删除 |

### 0.1 已确认决策（不可回退）

| # | 决策 | 落点 |
|---|---|---|
| D1 | 最终部署**云端**，先本地跑通 | §12 |
| D2 | 角色提升 ADMIN **不需第二管理员复核** | §5.2 |
| D3 | 积分调账分档，**单次上限 5000**（>5000 拒绝，P1 转审批，审批上限 20000），**日累计 20000** | §6.3 |
| D4 | `monitor_config.json` **在线生效**（下一轮，≤60 分钟） | §10 |

---

## 1. 目标与非目标

### 1.1 目标

把只读的 `/admin` 升级为**受控可写**运营台：高频低风险动作在 UI 完成，每次写操作**有鉴权、有原因、有前后值、可审计、可回滚、下游已同步**。

### 1.2 非目标

- ❌ 通用 SQL / 任意表浏览 / 任意文件读写
- ❌ 密钥明文查看或编辑（`encryptedData/iv/authTag/passwordHash`）
- ❌ 策略算法参数、回测参数、模型权重编辑（只读 + 跳 `27` changeset）
- ❌ 替代 `3.1` 用户自助设置页
- ❌ 本地实例写生产库

---

## 2. 现状基线（事实与证据）

| # | 事实 | 证据 |
|---|---|---|
| F1 | Prisma `provider=postgresql`，与主前端共用业务库，20+ 模型 | [schema.prisma](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系/prisma/schema.prisma#L10-L18) |
| F2 | `User.role ∈ {FREE,PRO,ADMIN}`；`sessions` 字段 `id/uid/sessionToken/expiresAt`（非 Auth.js adapter 形状） | [schema.prisma](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系/prisma/schema.prisma#L577-L592) |
| F3 | `/admin` 已有 11 个只读页面 | [AdminSidebar.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系/components/admin/AdminSidebar.tsx#L10-L22) |
| F4 | `/api/admin/**` 全部只有 GET | [route.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系/app/api/admin/trading-params/route.ts#L7-L17) |
| F5 | 无 `middleware.ts`、无登录态、无角色校验 | [layout.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系/app/admin/layout.tsx#L9-L23) |
| F6 | 文档已承诺 POST/PATCH，实现缺失 | [TECHNICAL_DESIGN.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/docs/TECHNICAL_DESIGN.md#L469-L478) |
| F7 | `3.1` 用 next-auth **v5-beta + JWT**；写库后经 bridge PUT `27 /api/v1/config` | [auth.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/auth.ts#L117-L121)、[classic-system-bridge.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/classic-system-bridge.ts#L6-L36) |
| F8 | `27` 有 `POST/GET /api/v1/approvals`、`GET /api/v1/approvals/<id>`、`GET .../ok`，**无 decide/executor** | [app.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/27-策略治理审批系统/app.py#L250-L317) |
| F9 | 审计链为 `governance/audit/chain.py` + `audit_hash_chain.jsonl`，**无文件锁** | [chain.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/27-策略治理审批系统/governance/audit/chain.py#L60-L100) |
| F10 | `param_center` 已实现，`repository.py` 读写 `sl_floor/tp_floor` 等；`data/` 仅 `aggregated_params.json` | [repository.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/param_center/repository.py#L110-L145) |
| F11 | 监控每轮重建 `UnifiedMonitor()` 并重读配置 → 在线生效 | [scheduler.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/15-监控告警系统/scheduler.py#L189-L196)、[monitor_config.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/15-监控告警系统/config/monitor_config.json#L54-L55)（`interval_minutes=60`、`sync_interval_minutes=5`） |
| F12 | `deploy.sh` 默认 `next dev`，缺库自动 `prisma db push` | [deploy.sh](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系/deploy.sh#L110-L111) |
| F13 | 工程无 `next-auth/zod/bcryptjs`；测试为 `node --test` | [package.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系/package.json#L5-L39) |

---

## 3. 架构决策（ADR）

| ADR | 决策 | 理由 |
|---|---|---|
| ADR-1 | 原地扩展，不新建台 | 避免第三处真源 |
| ADR-2 | 写只走 `/api/admin/**`，页面禁止直连 8094 | 单一入口做鉴权/审计/限流 |
| ADR-3 | 审批复用 `27`，不自建审批引擎 | 避免第二套治理 |
| ADR-4 | 三级 L0/L1/L2 | 按风险分配摩擦 |
| ADR-5 | 文件配置白名单 key + zod + 快照 | 防任意文件写 |
| ADR-6 | 中台直写 Prisma，但**必须 BridgeSync 下发** 27 config | 否则"改了不生效" |
| ADR-7 | next-auth v5-beta + JWT，独立 cookie 名与 secret，**role 每请求查库** | `sessions` 表不兼容 adapter；Edge 无法查库 |
| ADR-8 | 审计 outbox（事务内 `PENDING_AUDIT` → 异步推送补偿） | 已提交事务无法回滚 |
| ADR-9 | `INSTANCE_ROLE` + `ADMIN_WRITE_ENABLED` + `ADMIN_ALLOWED_DB_HOSTS` 三重门禁 | host 可能同为 127.0.0.1，需显式允许清单 |
| ADR-10 | 只新增 1 张表；confirmToken 用 HMAC 无状态 + nonce 唯一；限流进程内 | 最小数据面，PM2 单实例 |

---

## 4. 分层与写流水线

```
表现层 app/admin/**（11 页 + 抽屉编辑 + /admin/audit）
接口层 app/api/admin/**（鉴权 → 校验 → 幂等 → CAS → dryRun → 统一错误码）
服务层 lib/admin/write/*
  ├─ RepoWriter        条件更新/CAS（见 §8.4）
  ├─ BridgeSync        写后 PUT 27 /api/v1/config
  ├─ FileConfigWriter  白名单 JSON + zod + 快照 + 回读
  ├─ GovernanceClient  approvals / audit（超时 2s）
  └─ ParamCenterReader 只读
数据层 Prisma（单例，connection_limit=5）+ .admin-backups/ + 27 审计链
```

### 4.1 写流水线（固定顺序）

```
1 鉴权：JWT cookie 存在 ? → auth() 取 uid → 查 users.role == ADMIN ?
2 分级：读取操作注册表 action → level(L0/L1/L2)
3 校验：zod schema / fileKey 白名单 / 状态机
4 幂等：Idempotency-Key 命中 admin_operation_logs → 直接返回
5 前置：读取目标 before（脱敏）+ 校验 expectedUpdatedAt
6 确认：L1 校验 confirmToken（HMAC + nonce 未使用过）
7 事务：条件更新/CAS + 写 opLog(PENDING_AUDIT)
8 提交后：BridgeSync 下发（交易类）→ 推 27 审计 → opLog=APPLIED / APPLIED_WITH_WARNINGS
```

**失败语义矩阵**

| 失败点 | 行为 | opLog |
|---|---|---|
| 鉴权/校验/幂等冲突 | 拒绝，不落库 | 不写（鉴权类写 `REJECTED` 便于审计计数） |
| CAS 失败（`count=0`） | 409 CONFLICT_STALE | 不写 |
| 事务内异常 | 回滚 | `FAILED` |
| BridgeSync 失败（交易类动作） | **整体回滚**，返回 502 | `FAILED` + `warnings` |
| BridgeSync 失败（非交易类） | 提交，待补偿 | `APPLIED_WITH_WARNINGS` |
| 27 审计失败 | 提交，待补偿 | `PENDING_AUDIT` + `warnings` |
| L2 执行前 27 不可达 | 拒绝执行 | `FAILED` |

---

## 5. 权限与安全

### 5.1 鉴权实现（评审项 1/2 修复）

| 项 | 规定 |
|---|---|
| 依赖 | `next-auth@5.0.0-beta`（与 3.1 同版本）、`bcryptjs`、`@types/bcryptjs`、`zod` |
| 会话策略 | **JWT**（`session.strategy='jwt'`，`maxAge=8h`）；不使用 database session / adapter |
| cookie | 名 `dream-admin-session`；`httpOnly`、`sameSite=lax`、`secure`（云端）；**path=`/`**（需同时覆盖 `/api/admin`） |
| secret | `ADMIN_AUTH_SECRET`（独立于 3.1 的 `AUTH_SECRET`）；禁止复用 |
| middleware | matcher `['/admin/:path*','/api/admin/:path*']`；**只判 cookie 是否存在**（Edge 不查库），无 cookie：页面 302 `/admin/login`，API 401 |
| 授权 | 每个 handler 调 `requireAdmin()`：`auth()` → `prisma.user.findUnique(uid)` → `role==='ADMIN'`，否则 403；`actorUid` 只来自 session |
| 登录 | Credentials：`email + bcrypt.compare(password, passwordHash)`；复用 `loginAttempts/lockedUntil` |
| 降权即时性 | JWT 不携带 role；每次请求查库 → 降权/禁用立即生效 |
| 跨应用隔离验证 | 用 3.1 的 cookie 请求 `/admin` 必须 401（CI 安全用例） |

### 5.2 分级矩阵

| 级别 | 摩擦 |
|---|---|
| L0 | 一次确认 |
| L1 | 二次确认 + 必填原因（≥10 字）+ CAS |
| L2 | `27` 审批 + 执行前健康检查 |

角色提升（→ADMIN）：按 D2 单管理员可操作，L0，强制留 `before/after`，可回滚；角色变更额外写一条结构化告警日志（不阻塞）。

### 5.3 安全硬要求

1. 鉴权/校验失败零落库。
2. 敏感字段在 `before/after/warnings` 中统一 `••••`（白名单脱敏器，非黑名单）。
3. CSRF：写接口校验 `Origin` 同源 + `SameSite=Lax`。
4. 限流：20 写/分钟/actor（进程内存；**强制 PM2 `instances=1`**，见 §12.3）。
5. 路径安全：`fileKey` 枚举 → 服务端常量映射；拒绝 `..`、绝对路径、符号链接。
6. 写接口响应 `Cache-Control: no-store`。
7. 日志不含密文、token、cookie。

---

## 6. 写操作清单

### 6.1 L0

| 动作 | 接口 | 目标 |
|---|---|---|
| 解锁用户 | `POST /api/admin/users/[uid]/unlock` | `lockedUntil=null, loginAttempts=0` |
| 角色 FREE↔PRO↔ADMIN | `PATCH /api/admin/users/[uid]` | `users.role` |
| API 校验状态 | `PATCH /api/admin/api-configs/[id]` | `isVerified/lastVerifiedAt/label` |
| 渠道启停/推送规则 | `PATCH /api/admin/channels/[id]` | `isOnline/pushRules/format/silent*` |
| 小额积分 | `POST /api/admin/credits/[uid]/adjust` | §6.3 |

### 6.2 L1

| 动作 | 接口 | 约束 | BridgeSync |
|---|---|---|---|
| 交易总开关 | `PATCH /api/admin/trading-params/[uid]` | `isTradingEnabled`；必填原因 | ✅ 失败即回滚 |
| 交易状态 | 同上 | `status`；`LOCKED` 仅系统置位 | ✅ |
| 日重置 | `POST .../reset-daily` | 同日幂等 | ❌ |
| 策略状态 | `PATCH /api/admin/strategies/[id]` | 状态机白名单 | ✅（启用/暂停） |
| 任务状态 | `PATCH /api/admin/tasks/[id]` | 同上 | ❌ |
| 中额积分 | `POST /api/admin/credits/[uid]/adjust` | §6.3 | ❌ |
| 订单修正 | `PATCH /api/admin/orders/[id]` | 仅 `PENDING→CANCELLED`、`PAID→COMPLETED`，CAS | ❌ |
| 监控开关 | `PATCH /api/admin/system-config?file=monitor` | 白名单 key | ❌ |

### 6.3 积分调账（D3 定稿）

| 档位 | 单次额度 | 级别 | 摩擦 |
|---|---|---|---|
| 小 | `≤ 500` | L0 | 一次确认，reason 可选 |
| 中 | `501 ~ 5000` | L1 | 二次确认 + 必填原因 |
| 大 | `> 5000` | — | **拒绝**（`RULE_BLOCKED`）；P1 起转 27 审批，审批后单次 ≤ 20000 |

- 单用户**日累计 ≤ 20000**（按 `credits_transactions.createdAt` 当日汇总），超限拒绝。
- 常量：`CREDITS_ADJUST_L0_MAX=500`、`CREDITS_ADJUST_L1_MAX=5000`、`CREDITS_ADJUST_DAILY_MAX=20000`、`CREDITS_ADJUST_APPROVAL_MAX=20000`（集中 `lib/admin/constants.ts`）。
- 事务：`UPDATE credits_accounts SET balance = balance + $delta WHERE uid=$uid AND balance + $delta >= 0` → 影响行数 0 则 `RULE_BLOCKED`；同事务插入 `credits_transactions(category=BONUS, description=reason)`。

### 6.4 L2（P1）

| 动作 | 接口 | 约束 |
|---|---|---|
| 资金调控参数 | `POST /api/admin/system-config/propose?file=capital_control` | 仅提案；27 裁决 |
| 移动止损参数 | 同上 `file=trailing_stop` | 同上 |
| param_center floor | 同上 `file=param_center` | 仅提案；需 param_center 增加 override 读取（外部依赖，见 §16） |

### 6.5 明确不做

算法参数、回测参数、模型权重、聚合缓存与适配器权重、密钥明文、任意 SQL/文件。

---

## 7. 数据模型（唯一新增表）

```prisma
model AdminOperationLog {
  id              String    @id @default(cuid())
  requestId       String    @unique
  idempotencyKey  String?   @unique
  nonce           String?   @unique          // confirmToken 一次性凭证
  actorUid        String
  actorRole       String
  level           String
  action          String
  targetType      String
  targetId        String
  reason          String?
  beforeData      Json?
  afterData       Json?
  diff            Json?
  status          String    @default("PENDING_AUDIT")
  warnings        Json?
  errorCode       String?
  errorMessage    String?
  approvalId      String?
  auditHash       String?
  snapshotPath    String?
  ip              String?
  userAgent       String?
  createdAt       DateTime  @default(now())
  appliedAt       DateTime?
  rolledBackAt    DateTime?
  auditFlushedAt  DateTime?

  @@index([status, createdAt])
  @@index([targetType, targetId])
  @@index([actorUid, createdAt])
  @@map("admin_operation_logs")
}
```

- 状态：`PENDING_AUDIT / APPLIED / APPLIED_WITH_WARNINGS / FAILED / ROLLED_BACK / PENDING_APPROVAL / REJECTED`。
- DDL 由云端 DBA 执行（禁 migrate/db push），两端 `npx prisma generate`。
- 快照：`7-产物中台/.admin-backups/<fileKey>/<ISO8601>.json`，保留 180 天，入 `.gitignore`。

---

## 8. API 契约

### 8.1 响应

```jsonc
{ "success": true,
  "data": { "opId": "op_x", "status": "APPLIED",
            "before": {...}, "after": {...}, "warnings": [],
            "requiresRestart": false },
  "requestId": "req_x", "message": "ok" }
```

错误码：`VALIDATION_FAILED(400)` `UNAUTHENTICATED(401)` `FORBIDDEN_ROLE(403)` `NOT_FOUND(404)` `CONFLICT_STALE(409)` `RULE_BLOCKED(422)` `RATE_LIMITED(429)` `BRIDGE_SYNC_FAILED(502)` `GOVERNANCE_UNAVAILABLE(503)`

### 8.2 通用规范

| 项 | 规定 |
|---|---|
| 幂等 | 写请求必带 `Idempotency-Key`（uuid）；命中直接回放首次结果 |
| 并发 | Body 必带 `expectedUpdatedAt`；统一用条件更新，`count===0` → 409 |
| 干跑 | `?dryRun=1`：返回 before/after/diff + 校验结果，不落库、不审计、不消耗 nonce |
| 原因 | L1/L2 ≥10 字 |
| 确认令牌 | `POST /api/admin/confirm-token` body `{action,targetId,payloadHash}` → `{token,nonce,exp}`；`token=HMAC-SHA256(ADMIN_CONFIRM_SECRET, JSON({uid,action,targetId,payloadHash,nonce,exp}))`，`exp=now+60s`；写入时校验签名 + `exp` + 插入 `nonce` 唯一冲突（冲突即重放，拒绝） |
| 限流 | 20 次/分钟/actor |
| 超时 | 27 调用 2s、Bridge 2s |

### 8.3 路由清单

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/admin/login` | POST | 登录（NextAuth） |
| `/api/admin/users/[uid]` | PATCH | role |
| `/api/admin/users/[uid]/unlock` | POST | 解锁 |
| `/api/admin/trading-params/[uid]` | PATCH | 开关/状态 |
| `/api/admin/trading-params/[uid]/reset-daily` | POST | 日重置 |
| `/api/admin/{strategies,tasks}/[id]` | PATCH | 状态 |
| `/api/admin/{api-configs,channels}/[id]` | PATCH | 校验状态/启停 |
| `/api/admin/credits/[uid]/adjust` | POST | 分档调账 |
| `/api/admin/orders/[id]` | PATCH | CAS 修正 |
| `/api/admin/system-config` | GET/PATCH | 白名单文件 |
| `/api/admin/system-config/propose` | POST | L2 提案 |
| `/api/admin/system-config/param-center` | GET | 只读 |
| `/api/admin/audit-logs`、`/[opId]` | GET | 审计查询 |
| `/api/admin/audit-logs/[opId]/rollback` | POST | 回滚 |
| `/api/admin/jobs/audit-flush` | POST | 内部补偿（`X-Internal-Token`，幂等批量 ≤50） |
| `/api/admin/confirm-token` | POST | 签发确认令牌 |

### 8.4 逐操作并发实现（评审项 6 修复）

| 目标 | 实现 |
|---|---|
| 积分 | `updateMany({where:{uid, balance:{gte: -delta}}, data:{balance:{increment:delta}}})`，事务内插流水 |
| 订单 | `updateMany({where:{id, status:from}, data:{status:to, updatedAt:now}})` |
| 交易参数/策略/任务 | `updateMany({where:{id, updatedAt:expected}, data:{...}})` → 0 行 409 |
| 用户 role | `updateMany({where:{id, role:{in:allowedFrom}}, data:{role}})` |
| 文件配置 | `opLog` 悲观标记 + 文件 `flock`（Node `fs.open` + 重命名原子写） |

---

## 9. 审计与回滚（outbox，评审项 4/5 修复）

1. 事务内写 `admin_operation_logs(PENDING_AUDIT)`，保证库变更与留痕原子。
2. 提交后尽力：`BridgeSync` → 27 `/api/v1/audit/event`；成功 `APPLIED`，失败保留 `PENDING_AUDIT` + `warnings`。
3. 补偿：云端 `dreambuddy-admin-audit-flush.timer`（每分钟）/ 本地 launchd，调 `POST /api/admin/jobs/audit-flush`；指数退避，24h 未成功告警。
4. L2：执行前 `GET 27 /health` 必须 200，否则拒绝（FAIL-CLOSED）。
5. **27 审计链加锁（外部改造，M3 前置）**：`governance/audit/chain.py` 追加时对 `audit_hash_chain.jsonl.lock` 执行 `fcntl.flock(LOCK_EX)`（超时 2s 返回 503）、`open(...,'a')` + `write` + `flush` + `os.fsync`、`LOCK_UN`；顺序：取锁 → 读 tail hash → 写新行 → fsync → 释放。
6. 回滚：由 `beforeData` 生成逆操作（同样走 CAS）；生成新 opLog（`action=rollback`，`targetId=原 opId`）；目标 `updatedAt` 已变 → 409 拒绝自动回滚。
7. 回滚支持范围：L0/L1；L2 引导 `27 gate/rollback`。

---

## 10. 文件型配置

| fileKey | 路径 | 可写 key | 生效 |
|---|---|---|---|
| `monitor` | `15-监控告警系统/config/monitor_config.json` | `systems.*.enabled`、`systems.*.max_idle_minutes` | **在线**：下一轮重读（`interval_minutes=60`；`sync_interval_minutes=5`） |
| `trailing_stop` | `16-调控系统/config/trailing_stop.json` | `trigger_cooldown_sec`、`auto_close_after_sec`、`report.*` | 需重启 |
| `capital_control` / `capital_allocator` | 同目录 | 仅 L2 提案 | 需重启 |

- `monitor` 的 `interval_minutes` / `sync_interval_minutes` **非白名单**（结构键需重启）。
- 每次写：zod 校验 → 快照 → 原子替换（临时文件 + `rename`）→ 回读比对 → `requiresRestart`。

---

## 11. 前端交互

1. 行尾操作按钮按级别着色（L0 常规 / L1 警示 / L2 "需审批"）。
2. 抽屉：当前值 + 影响说明 + reason + `dryRun` diff → 提交。
3. 对象详情新增「操作记录」Tab。
4. 新增 `/admin/audit`：检索、回滚、27 链校验状态、待补偿计数。
5. `ADMIN_WRITE_ENABLED=false`：写按钮禁用 + "当前实例只读"。
6. `warnings` 非空：黄色横幅"已生效，下游同步待补偿"。

---

## 12. 部署、环境与负载（D1）

### 12.1 环境矩阵

| 环境 | `INSTANCE_ROLE` | `ADMIN_WRITE_ENABLED` | `ADMIN_ALLOWED_DB_HOSTS` | 用途 |
|---|---|---|---|---|
| 本地 | `local` | `1` | `localhost,127.0.0.1` | 先跑通/联调/E2E |
| 云端正向 | `cloud` | `1` | 云端库 host | 唯一生产写入口 |
| 云端只读旁路 | `cloud` | `0` | — | 演示/审计查看 |

启动自检（`instrumentation.ts`）：从 `DATABASE_URL` 解析 host，若不在 `ADMIN_ALLOWED_DB_HOSTS` → 写服务拒绝启用（日志 ERROR，UI 只读）。

### 12.2 负载评估

| 项 | 评估 |
|---|---|
| 进程 | 复用 3456 Next 进程，不新增；增量内存 < 50MB |
| CPU | 仅管理员请求；补偿每分钟 1 次轻请求 |
| 数据库 | Prisma 单例 + `connection_limit=5`；写入低频 |
| 磁盘 | 快照 KB 级，180 天归档 |
| 结论 | 同机增量 **< 5%**，可接受；不为管理台单开实例 |

真实压力源是 `next dev`（常驻 300–800MB）。必须改为 `build + start`：PM2 `instances=1`、`max_memory_restart=600M`。

### 12.3 部署改造（评审项 7 修复）

`deploy.sh` 必改三点：

1. 默认 `pnpm build && pnpm start`（删除 `next dev` 分支）。
2. **删除所有 `prisma db push` 分支**；缺表直接报错退出（DDL 走云端 DBA）。
3. 新增 `ecosystem.config.js`：`instances=1`、`max_memory_restart:'600M'`、`env.ADMIN_WRITE_ENABLED`。

Prisma 单例：新建 `lib/prisma.ts`（`globalThis.__prisma ??= new PrismaClient({datasourceUrl: url+'?connection_limit=5'})`），替换 admin 路径下的多处 `new PrismaClient()`。

### 12.4 本地跑通（D1 前置）

`pnpm dev` + 本地 postgres + `INSTANCE_ROLE=local`；用 3.1 的种子账号提升为 ADMIN 后登录；跑通 M1a 后按 §13 G0/G1 验收，再 commit → push → 云端 pull。

---

## 13. 里程碑与门禁

### M0 地基

依赖安装；登录 + middleware + `requireAdmin()`；`AdminOperationLog` DDL；opLog 服务；幂等；CAS 工具；dryRun；confirmed-token；审计 outbox + `audit-flush` + timer；`/admin/audit` 骨架；`deploy.sh` 三点改造；`lib/prisma.ts`。

**G0 验收命令**
```bash
pnpm tsc --noEmit && pnpm lint
curl -i localhost:3456/api/admin/users          # 401
curl -i -b "<3.1 cookie>" localhost:3456/admin  # 401（跨应用隔离）
curl -i -b "<PRO cookie>" localhost:3456/api/admin/users  # 403
grep -n "db push" deploy.sh                      # 无输出
```

### M1a 首条竖切
解锁用户 + 积分调账（§6.3 分档）+ 审计页 + 回滚。

**G1**：每次写 1 条 opLog；dryRun 不落库；同 Idempotency-Key 回放同 opId；`expectedUpdatedAt` 过期 409；积分 500/501/5001/日累计 20001 四个边界分别 L0/L1/拒绝/拒绝；余额不足拒绝；回滚复原；响应无密文；27 `audit/verify` 通过。

### M1b 其余 L0/L1
交易开关/状态（含 BridgeSync）、日重置、策略/任务、渠道、API 配置、订单 CAS、monitor 在线生效。

**G1b**：交易开关写库后 27 config 已变更且交易侧生效；Bridge 断连 → 回滚 + 502；非交易类 Bridge 失败 → `APPLIED_WITH_WARNINGS` 且补偿成功；monitor 改动 ≤60 分钟生效。

### M2 文件型参数
**G2**：非白名单 key 400；类型错误 400；快照可回滚；原子写无中间态；`trailing_stop` 返回 `requiresRestart=true`。

### M3 L2 审批闭环
**G3**：无 approvalId → 403；27 不可达 → 拒绝；审批人与发起人相同 → 403；param_center 覆盖不突破 SL≥4%/TP≥12%/RR≥2/ATR∈[2,6]。

### M4 治理收尾
文档同步（消除 F6）；bridge 语义收敛；27 审计加锁上线；孤儿扫描；认知记录。

---

## 14. 测试与验收

1. 单测（`node --test`）：validate / authorize / idempotency / CAS / diff / rollback / 脱敏 / 白名单 / 积分分档 / 状态机 / confirmToken 重放。
2. 安全：无 cookie、伪造 body actor、跨站 Origin、限流、越权 target、`?file=../etc/passwd`、3.1 cookie 串号。
3. 集成：L1 写 → opLog → 27 verify → 回滚 → 复原；Bridge 断连 → 回滚/补偿。
4. 前端（BrowserSkill）：每页写入、dryRun、只读模式、错误文案。
5. 回归：11 个只读页数据不变；`pnpm build` 成功。

---

## 15. 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 中台与 3.1 写语义漂移 | 常量集中 + M4 收敛 |
| R2 | Prisma drift | 禁 migrate/db push；DDL 走 DBA |
| R3 | 本地误写生产库 | 三重门禁（§12.1） |
| R4 | ADMIN 单点（D2 已接受） | 全量审计 + 可回滚 + 角色变更告警 |
| R5 | 27 不可用 | outbox 不阻塞；L2 FAIL-CLOSED |
| R6 | 审计表膨胀 | 180 天归档 |
| R7 | 审计链并发分叉 | 27 `chain.py` 加 flock（§9.5） |
| R8 | 限流仅进程内 | 强制 `instances=1`；扩容再改 Redis |
| R9 | `next dev` 高内存 | §12.3 改造 |
| R10 | Bridge 契约变更 | 与 3.1 共用同一 config key 常量；变更需双端同步评审 |

**无未决问题**（v1.0 的四项已由 D1–D4 关闭，积分阈值已定稿）。

---

## 16. 影响面与外部依赖

**本仓改动**：`app/api/admin/**`、`app/admin/**`、`lib/admin/**`、`lib/prisma.ts`、`middleware.ts`、`instrumentation.ts`、`prisma/schema.prisma`(+1 model)、`deploy.sh`、`ecosystem.config.js`、`package.json`。

**外部改造（阻塞项）**
1. `27/governance/audit/chain.py` 加 `flock`（M3 前）。
2. `27` 新增 `POST /api/v1/approvals/<id>/decide`（`X-Admin-Token`）：body `{decision:'APPROVE'|'REJECT', comment, actor}`；APPROVE 后置 `approved` 并写审计；中台轮询或回调执行 L2。
3. `param_center` 增加 override 文件读取（`16-调控系统/config/param_center_override.json`），仅在 M3 需要。

**文档**：`docs/API_SPEC.md`、`docs/TECHNICAL_DESIGN.md`、`docs/ENGINEERING_INDEX.md`。

**认知**：落地后 `record` 四条硬约束（写边界 / 27 复用口径 / 禁 migrate / 积分分档阈值）。
