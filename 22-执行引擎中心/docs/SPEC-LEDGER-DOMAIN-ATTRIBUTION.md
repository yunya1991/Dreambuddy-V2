# SPEC：多域账本归因（五层模型）

> **状态**：Approved v0.2（2026-11-23 用户确认；已并入 `TECHNICAL_DESIGN.md` §8，本文件为详细设计来源）
> **日期**：2026-11-23（v0.2 评审修订）
> **范围**：22 执行引擎中心 `PositionLedger` / `TradeExecutionGateway` / 只读巡检链路
> **关联代码**：[position_ledger.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/22-执行引擎中心/position_ledger.py)、[trade_execution_gateway.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/22-执行引擎中心/trade_execution_gateway.py)、[ledger_guards.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/execution/ledger_guards.py)
> **触发背景**：23 域无 close 事件，25 个历史持仓被判 stale 后仍以 `qty>0` 占用子池，导致 23 无法开新仓；根因是“归属只有单值 source、stale 不落库、容量闸门与监控口径脱节”。

---

## 1. 目标与非目标

### 1.1 目标

1. **成交可归因**：任一时刻能回答“哪个域、哪笔决策、持有多少、成本多少、已实现盈亏多少”。
2. **状态可判定**：`open / stale / closed` 由账本持久化，所有消费方读同一份事实，禁止各自推算。
3. **容量口径统一**：开仓闸门只统计“有效持仓”（`status=open` 且最近一次交易所确认在 TTL 内），stale 不占容量但保留审计。
4. **异常可闭环**：对账差异进 `recon_breaks` 工单，有状态、有 owner、有 SLA、有解决记录。
5. **单一事件流 + 受控写入口**：所有成交/状态变更必须进入同一 `fills` 事件流，只允许三个写入口——`TradeExecutionGateway`（下单成交）、drop-copy 适配器（他域/交易所侧成交）、janitor（对账状态迁移）；巡检其余部分只读。

### 1.2 非目标

- 不改造交易所接入层与下单协议。
- 不做跨域的收益分成/资金划转（只做归因记账）。
- P1 不引入“同标的多域共持”（Mode B 列为 P2 可选项）。

---

## 2. 术语与域编码

| 术语 | 定义 |
|---|---|
| Domain（域） | 产生交易决策的归属单元，规范值：`11` / `23` / `50` / `6` / `22`（对账与 janitor） |
| source | 原始来源标签（`23-evolution` / `11-yijing` / `50-nn` / `6-trading` / `22-reconciled`），保留用于追溯，不再作为归属主键 |
| Effective Position | `qty>0 && status='open' && verified_at` 在 TTL 内 |
| Stale | 账本有仓、交易所连续 K 轮确认无仓；不占容量，可被 janitor 关闭 |
| Lot | 一次开仓形成的持仓批次，用于 FIFO 平仓与均价计算 |
| Break | 账本与交易所/审计流不一致的记录，进入工单状态机 |

**source → domain 映射（唯一口径）**

| source 前缀/取值 | domain |
|---|---|
| `23-evolution` / `23` / `evolution` / `bcrm` / `strategy` / `event_arbitrage` | `23` |
| `11-yijing` / `11-*` | `11` |
| `50-nn` / `50-*` | `50` |
| `6-trading` / `6-*` | `6` |
| `22-reconciled` / `22-janitor` / `22-*` | `22` |
| 其他/空 | `legacy` |

---

## 3. 五层模型

```
L5 消费方   开仓闸门(按域限额)   只读巡检/监控   前端/复盘
              ↑ 只读视图 v_effective_positions / v_domain_positions
L4 状态与异常  verified_at / miss_count / stale_since / status   recon_breaks
L3 事件流     fills(append-only, id 即单调 seq, 含 domain/decision_id)
L2 域子账     domain_positions + position_lots ← 成交分配
L1 账户总账   positions(omnibus, 只由成交/对账驱动)
L0 交易所快照  OKX positions + 成交（drop copy 等价物）
```

### 3.1 三条铁律

1. **单一事件流 + 三个受控写入口**：所有成交先写 `fills`（`id` 为单调序号，`exchange_fill_id` 为幂等键），同一事务内更新 L1/L2/L4；写入口仅 gateway、drop-copy 适配器、janitor 三者，其余链路只读视图。传统金融中持仓账本由 order entry 与 drop copy 两条通道共同喂养、在账本层合流——约束点是“账本唯一”，不是“网关唯一”。
2. **归属用子账**：`domain_positions` 记录域份额；`positions.source` 降级为展示字段。
3. **stale 是一等状态**：由唯一 janitor 依据交易所快照写入，禁止读侧推测；容量闸门只认 effective position。

### 3.2 状态机

```
positions / domain_positions:
  open --(连续 K 轮交易所缺失)--> stale --(连续 M 轮缺失或人工确认)--> closed
  open --(成交全平)--> closed
  stale --(交易所重新出现)--> open

recon_breaks:
  OPEN --> ACK --> RESOLVED
                 \--> WAIVED
```

- 判定采用**时间 + 确认次数**，不采用轮数（兼容不同巡检周期）：连续缺失 ≥ `stale_after_seconds`（默认 600s）且确认次数 ≥ `min_confirmations`（默认 3）→ `stale`；连续缺失 ≥ `close_after_seconds`（默认 3600s）→ `closed`。参数存 `ledger_settings`。
- **查询失败 ≠ 缺失**：交易所持仓接口失败/超时不得累加 `miss_count`，只记录 `feed_state=degraded`。
- **feed 陈旧保护**：若 janitor 心跳超过 2 个周期，闸门回退到原始 `positions(qty>0)` 口径（保守，不会被 stale 视图放开超限），并告警；禁止在 feed 不可信时使用 `v_effective_positions`。
- **账务修正不触发冷却**：janitor 关闭 stale 行属于账务校正，不写 `cooldowns`；只有真实成交平仓才写冷却。
- 状态写权限：`open→closed` 由成交或 owner 域触发；`open→stale→closed` 只允许 janitor；其他域只能提交 break 或请求关闭。

---

## 4. 数据模型（完整 DDL）

> 约束：全部为**增量变更**（ADD COLUMN / CREATE TABLE），旧代码可继续运行；SQLite 不执行破坏性迁移。

### 4.1 主账扩展

```sql
-- L1 positions：增加状态、确认时间、缺失计数、事件序号
ALTER TABLE positions ADD COLUMN seq INTEGER NOT NULL DEFAULT 0;
ALTER TABLE positions ADD COLUMN verified_at TEXT;
ALTER TABLE positions ADD COLUMN stale_since TEXT;
ALTER TABLE positions ADD COLUMN miss_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE positions ADD COLUMN status TEXT NOT NULL DEFAULT 'open';
-- status 取值 open|stale|closed，由代码枚举校验（SQLite ALTER 不加 CHECK）

CREATE INDEX IF NOT EXISTS idx_positions_effective
    ON positions (status, verified_at);
CREATE INDEX IF NOT EXISTS idx_positions_source
    ON positions (source);

-- L3 fills：域、分配与幂等键（id 已为 INTEGER PRIMARY KEY AUTOINCREMENT，作单调 seq）
ALTER TABLE fills ADD COLUMN domain TEXT NOT NULL DEFAULT '';
ALTER TABLE fills ADD COLUMN alloc_id TEXT NOT NULL DEFAULT '';
ALTER TABLE fills ADD COLUMN exchange_fill_id TEXT NOT NULL DEFAULT '';
ALTER TABLE fills ADD COLUMN parent_fill_id INTEGER;

CREATE INDEX IF NOT EXISTS idx_fills_domain
    ON fills (domain, inst_id, pos_side, id DESC);
-- 同一交易所成交只能入账一次（drop-copy 重放安全）
CREATE UNIQUE INDEX IF NOT EXISTS uq_fills_exchange_fill
    ON fills (exchange_fill_id)
    WHERE exchange_fill_id <> '';
```

### 4.2 域子账（L2）

```sql
CREATE TABLE IF NOT EXISTS domain_positions (
    inst_id       TEXT NOT NULL,
    pos_side      TEXT NOT NULL,
    domain        TEXT NOT NULL,
    qty           REAL NOT NULL DEFAULT 0,
    avg_entry     REAL NOT NULL DEFAULT 0,
    realized_pnl  REAL NOT NULL DEFAULT 0,
    entry_known   INTEGER NOT NULL DEFAULT 1,
    source_detail TEXT DEFAULT '',
    opened_at     TEXT,
    updated_at    TEXT,
    closed_at     TEXT,
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open','stale','closed')),
    PRIMARY KEY (inst_id, pos_side, domain)
);
CREATE INDEX IF NOT EXISTS idx_domain_positions_effective
    ON domain_positions (domain, status, updated_at);
-- P1 不变量：一个 (inst,side) 同时只能有一个活跃归属域（多域共持留 P2）
CREATE UNIQUE INDEX IF NOT EXISTS uq_domain_positions_active_domain
    ON domain_positions (inst_id, pos_side)
    WHERE qty > 1e-9 AND status IN ('open','stale');

-- 批次账（FIFO 平仓与域内均价）
CREATE TABLE IF NOT EXISTS position_lots (
    lot_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    inst_id       TEXT NOT NULL,
    pos_side      TEXT NOT NULL,
    domain        TEXT NOT NULL,
    qty           REAL NOT NULL,
    remaining_qty REAL NOT NULL,
    px            REAL NOT NULL,
    opened_at     TEXT NOT NULL,
    source_detail TEXT DEFAULT '',
    decision_id   TEXT DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open','closed'))
);
CREATE INDEX IF NOT EXISTS idx_lots_open
    ON position_lots (inst_id, pos_side, domain, status, lot_id);
```

### 4.3 额度预占（并发防超限）

```sql
CREATE TABLE IF NOT EXISTS reservations (
    reservation_id TEXT PRIMARY KEY,
    domain         TEXT NOT NULL,
    inst_id        TEXT NOT NULL,
    pos_side       TEXT NOT NULL,
    notional       REAL NOT NULL,
    state          TEXT NOT NULL DEFAULT 'held'
                   CHECK (state IN ('held','consumed','released','expired')),
    decision_id    TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reservations_active
    ON reservations (domain, inst_id, pos_side, state, expires_at);
```

### 4.4 对账工单（L4）

```sql
CREATE TABLE IF NOT EXISTS recon_breaks (
    break_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL
                  CHECK (kind IN ('missing_in_ledger','orphan_in_ledger','qty_drift',
                                  'price_drift','stale_position','over_close','duplicate_open')),
    inst_id       TEXT NOT NULL,
    pos_side      TEXT NOT NULL,
    domain        TEXT NOT NULL DEFAULT '',
    detected_at   TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'OPEN'
                  CHECK (state IN ('OPEN','ACK','RESOLVED','WAIVED')),
    owner_domain  TEXT DEFAULT '',
    evidence_json TEXT DEFAULT '',
    sla_due_at    TEXT,
    resolved_at   TEXT,
    resolution    TEXT DEFAULT ''
);
-- 同一差异只允许一条活跃工单，避免告警风暴
CREATE UNIQUE INDEX IF NOT EXISTS uq_recon_breaks_active
    ON recon_breaks (kind, inst_id, pos_side, domain)
    WHERE state IN ('OPEN','ACK');
CREATE INDEX IF NOT EXISTS idx_recon_breaks_sla
    ON recon_breaks (state, sla_due_at);
```

### 4.5 域注册表与运行参数

```sql
CREATE TABLE IF NOT EXISTS domain_registry (
    domain        TEXT PRIMARY KEY,
    enabled       INTEGER NOT NULL DEFAULT 1,
    owner_contact TEXT DEFAULT '',
    limits_json   TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

初始化数据（幂等）：

```sql
INSERT OR IGNORE INTO domain_registry(domain, enabled, limits_json, created_at, updated_at)
VALUES
  ('11', 1, '{"max_positions":6,"max_notional":2000}', datetime('now'), datetime('now')),
  ('23', 1, '{"subpool_max":5,"probe_max":2,"max_direction_ratio":0.70}', datetime('now'), datetime('now')),
  ('50', 1, '{"max_positions":12,"position_scope":"registry"}', datetime('now'), datetime('now')),
  ('6',  1, '{}', datetime('now'), datetime('now')),
  ('22', 1, '{"role":"janitor"}', datetime('now'), datetime('now')),
  ('legacy', 0, '{}', datetime('now'), datetime('now'));

INSERT OR IGNORE INTO ledger_settings(key, value) VALUES
  ('effective_ttl_seconds', '7200'),
  ('stale_after_seconds', '600'),
  ('close_after_seconds', '3600'),
  ('min_confirmations', '3'),
  ('feed_guard_action', 'fallback_raw'), -- fallback_raw | block_open
  ('lot_close_policy', 'fifo'),          -- fifo | pro_rata
  ('janitor_enforce', 'off'),            -- off=只标记；on=允许置 stale/closed
  ('janitor_heartbeat_seconds', '60');
```

### 4.6 只读视图（消费方唯一读口径）

```sql
-- 有效持仓：容量/子池/限额只能读这个视图
CREATE VIEW IF NOT EXISTS v_effective_positions AS
SELECT p.*
FROM positions p
JOIN ledger_settings s ON s.key = 'effective_ttl_seconds'
WHERE p.qty > 1e-9
  AND p.status = 'open'
  AND p.verified_at IS NOT NULL
  AND (julianday('now') - julianday(p.verified_at)) * 86400.0 <= CAST(s.value AS REAL);

-- 域视角
CREATE VIEW IF NOT EXISTS v_domain_positions AS
SELECT d.*, r.enabled AS domain_enabled, r.limits_json
FROM domain_positions d
LEFT JOIN domain_registry r ON r.domain = d.domain
WHERE d.qty > 1e-9 AND d.status IN ('open','stale');
```

### 4.7 迁移与回填（幂等，只执行一次）

```sql
-- 1) 归属回填：一个 (inst,side) 按其 source 归到单域
INSERT INTO domain_positions(
    inst_id, pos_side, domain, qty, avg_entry, realized_pnl, entry_known,
    source_detail, opened_at, updated_at, closed_at, status)
SELECT
    p.inst_id, p.pos_side,
    CASE
      WHEN p.source LIKE '23%' OR p.source IN ('evolution','bcrm','strategy','event_arbitrage') THEN '23'
      WHEN p.source LIKE '11%' THEN '11'
      WHEN p.source LIKE '50%' THEN '50'
      WHEN p.source LIKE '6%'  THEN '6'
      WHEN p.source LIKE '22%' THEN '22'
      ELSE 'legacy'
    END,
    p.qty, p.avg_entry, 0, p.entry_known,
    p.source, p.opened_at, p.updated_at, p.closed_at,
    CASE WHEN p.closed_at IS NULL AND p.qty > 1e-9 THEN 'open' ELSE 'closed' END
FROM positions p
WHERE p.qty > 1e-9 OR p.closed_at IS NOT NULL
ON CONFLICT(inst_id, pos_side, domain) DO UPDATE SET
    qty = excluded.qty,
    avg_entry = excluded.avg_entry,
    updated_at = excluded.updated_at,
    closed_at = excluded.closed_at,
    status = excluded.status;

-- 2) 历史持仓补一条迁移批次，使 FIFO 可启动（重复执行不新增）
INSERT INTO position_lots(inst_id, pos_side, domain, qty, remaining_qty, px, opened_at,
                          source_detail, decision_id, status)
SELECT d.inst_id, d.pos_side, d.domain, d.qty, d.qty, d.avg_entry,
       COALESCE(d.opened_at, datetime('now')), 'migration', '', 'open'
FROM domain_positions d
WHERE d.status = 'open' AND d.qty > 1e-9
  AND NOT EXISTS (
      SELECT 1 FROM position_lots l
      WHERE l.inst_id = d.inst_id AND l.pos_side = d.pos_side
        AND l.domain = d.domain AND l.source_detail = 'migration'
  );

-- 3) 主账状态初始化 + 修正 ADD COLUMN 默认值带来的历史状态错误
UPDATE positions SET status = 'open', verified_at = COALESCE(verified_at, updated_at)
WHERE qty > 1e-9 AND status = 'open';
UPDATE positions SET status = 'closed'
WHERE qty <= 1e-9 AND closed_at IS NOT NULL;
```

**迁移限制（必须写进评审结论）**

- 历史 `realized_pnl` 是账户级汇总，无法精确拆分到域；回填时统一记 0，**不得用于绩效结算**。绩效口径从切换后由 `fills + position_lots` 派生。
- 回填按“最后 source 即归属”近似；若同一 `(inst,side)` 历史上被多个域操作过，迁移后归属可能偏后开仓域。允许人工在评审期修正一次。

---

## 5. 写入路径改造（TradeExecutionGateway）

### 5.1 成交落账（P1 核心）

`_record_ledger` 改为调用 `ledger.record_fill(...)`，单事务内完成：

1. `INSERT fills(domain, alloc_id, exchange_fill_id, action, qty, px, source, decision_id)`（返回 `fill_id` 作为 seq；`exchange_fill_id` 唯一冲突即幂等跳过）。
2. `open`：`record_open` 更新 L1；`upsert domain_positions`；插入 `position_lots`；消费 reservation。
3. `close/reduce`：按 `lot_close_policy` 在 `(inst,side,domain)` 内扣减批次；每批 `pnl=(exit_px-lot.px)*qty*sign-fee_alloc`，fee 按 qty 比例摊到批次，尾差记入最后一笔批次；同步扣减 `domain_positions`；最后 `apply_partial_close` 更新 L1；L1 归零时写 cooldown。
4. 域内可平数量不足 → **不跨域借仓**，写 `recon_breaks(kind='over_close')` 并按可用量截断。
5. `positions.seq` 更新为本次 `fill_id`；`exchange_fill_id` 冲突即幂等跳过（不重复扣仓）。
6. **drop-copy 适配器**（他域成交/交易所侧 SL/TP/手工单）：以 `exchange_fill_id` 为幂等键写同一条 `fills` 流，`domain` 按 §2 映射；同一笔交易所成交若同时被 gateway 与 drop-copy 看到，只入账一次，另一条用 `alloc_id/parent_fill_id` 关联。

### 5.2 关闭权限

```python
def close_position(self, domain: str, inst_id: str, pos_side: str, qty: float,
                   set_cooldown: bool = True, ...):
    # 只允许关闭本域份额；janitor 走独立 principal，且 set_cooldown=False
```

- `close_ghost_position` 增加 `domain` 参数与归属校验；23 调不到别域的行。
- janitor 关闭 stale 行必须 `set_cooldown=False`；真实成交平仓才 `set_cooldown=True`。
- P1 默认 **一标的一域**：由 `uq_domain_positions_active_domain` 唯一索引在库层强制；若已存在其他域，开仓闸门拒绝。

### 5.3 预占额度

- 新增 `reserve(domain, inst_id, pos_side, notional, decision_id, ttl=300)` / `release(reservation_id)`。
- 闸门判定顺序：`effective 持仓 + active reservations` 一起算限额；下单失败/超时由 janitor 过期释放（`state='expired'`）。
- 强制范围：凡经 22 gateway 开仓的域（11/23/6）必须预占；50 在 drop-copy 并网前沿用自身 bridge 限额，并网后纳入。
- 保证多进程并发开仓不超 `limits_json` 上限。

### 5.4 对账接口调整

- `reconcile_ledger()` 只做 L0→L1 的补录、数量/均价校正、刷新 `verified_at`、`miss_count=0`，**不再决定关闭**；接口失败时返回 `feed_state=degraded`，不参与 miss 计数。
- 关闭统一走 janitor：
  - `miss_count >= K` → `status='stale'` + `stale_since` + break(`stale_position`)；
  - `miss_count >= M` 或人工确认 → `status='closed'` + 写 `fills(action='close', source='22-janitor', exit_reason='ghost_exchange_flat')` + cooldown + break `RESOLVED`。
- 保留“本对账源（`22-reconciled`）陈旧行”的直接关闭作为兼容路径，行为不变。

---

## 6. 巡检改造（唯一 janitor + 只读消费方）

### 6.1 新增 janitor（进程归属 15，账本 API 复用 22）

**职责分离**：execution（22）与 position control（15）分属前台/中台，janitor 由 15 监控侧部署运行，代码 import 22 的 `PositionLedger` 写 API；仅在生产云端运行（禁止本地与云端双实例）。

职责（唯一状态写入方）：

1. 拉取 OKX 持仓快照；与 L1/L2 逐 `(inst,side)` 比对。
2. 匹配：`verified_at=now`、`miss_count=0`、若之前 stale 则恢复 `open`。
3. 缺失：`miss_count += 1` 并记录首次缺失时间；满足时间与确认次数阈值后执行状态迁移（受 `janitor_enforce` 控制）。
4. 发现交易所存在但账本缺失 → 补录（`source='22-reconciled'`，domain=`22`）+ break(`missing_in_ledger`)。
5. 数量/均价漂移 → `qty_drift` / `price_drift` break。
6. 过期 reservation → `expired`。
7. 输出指标与审计（见 §9）。
8. 交易所接口失败 → 只记 `feed_state=degraded`，不累加 `miss_count`；连续失败超阈值告警并触发 §3.2 feed 陈旧保护。
9. 每轮写 `janitor_heartbeat_seconds` 时间戳（存 `ledger_settings` 或独立 heartbeat 表）。

调度：与 exit_runner 同周期或独立 systemd timer；**同一数据库只允许一个 janitor 实例**（文件锁），且仅生产云端运行。

### 6.2 消费方改造

| 位置 | 改造 |
|---|---|
| 23 [ledger_guards.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/execution/ledger_guards.py) | `_all_open_positions()` / `_open_positions()` 改读 `v_effective_positions`；`has_position` 仍按账户全部有效持仓 |
| 23 exit_runner `_on_ghost` | 删除直接 `close_ghost_position`；改为提交 break 或调用 janitor API，避免跨域写 |
| 23 exit_runner `collect_positions` | 读 `v_domain_positions`（含 `status`），stale 行不进入离场决策 |
| 15 [daily_insight.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/15-监控告警系统/scripts/daily_insight.py) | 继续 `mode=ro`；新增 breaks/stale/域份额统计 |
| 15 [business_metrics_exporter.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/15-监控告警系统/exporter/business_metrics_exporter.py) | 新增 `ledger_stale_positions`、`ledger_breaks_open`、`ledger_domain_qty_mismatch` 等指标 |
| 3.1 前端 / 19 DAL | 只读视图，展示 stale 与域归属，不直接读 `positions` 原始表 |

### 6.3 50 域处理（已决策：drop-copy 并网）

- **决策 A−**：保留 50 现有执行路径（`x1_live_executor` + `live_order_bridge`），新增 drop-copy 适配器把 `x1_live_fills.jsonl` 与交易所成交按 `exchange_fill_id` 幂等导入 22 账本，`domain='50'`；不要求 50 改走 gateway。
- 依据：传统金融中 order entry 与 position keeping 本就分离，账本由 drop copy 喂养；强行收口到单一网关会把“账本唯一”和“网关唯一”混淆，并迫使 50 大改。
- P1 过渡：50 未完成导入前，显式声明“50 不在 22 容量口径内”，janitor 只读对账并产出 `domain='50'` 的 break，不参与 23 子池计数。
- 目标态：50 与其他域一样出现在 `domain_positions`，容量口径统一；50 自身 `position_scope=registry` 的预检保留。

---

## 7. P0–P2 任务拆解

### P0 止血（先恢复可交易，不动模型）

| ID | 任务 | 交付物 | 验收 |
|---|---|---|---|
| P0-1 ✅ | SQLite 开启 WAL + `busy_timeout` | `position_ledger._connect` 改造 | 并发读写压测无 `database is locked`；只读进程不阻塞写 |
| P0-2 ✅ | 统一“有效持仓”口径 | `v_effective_positions` + LedgerGuards 改读 | 构造 stale 行后闸门不计入；25 假持仓场景重建后 23 可开仓 |
| P0-3 ✅ | 云端 ghost 核对（未发现需清理行） | 只读比对账本与 OKX | 账本 9 条 = 交易所 9 条，逐 `inst/side/qty` 一致；未执行删除 |
| P0-4 ✅ | 50 口径落地 | 按 §6.3 决策 A−，P1 过渡声明写入文档 | 巡检/限额口径无歧义 |
| P0-5 ✅ | feed 陈旧保护 | 心跳 + `feed_guard_action` | janitor 停摆时闸门回退 raw 口径并告警，不被 stale 视图放开 |

> **执行记录（2026-11-23）**：P0-1/P0-2/P0-4/P0-5 已落地；新增测试
> `tests/test_position_ledger_p0.py` 与 `test_ledger_guards.py::test_prefers_effective_positions_when_available`
> 全部通过。P0-3 云端只读核对：账本 9 条 open（8×`22-reconciled` + 1×`23-evolution`）与 OKX 9 条
> 逐 `inst/side/qty` 一致，**无 ghost 行可清理**；“25 条 stale”为历史/监控侧统计，账本层无需删除。
>
> **P1 执行记录（2026-11-23）**：P1-1..P1-7 代码落地，本地测试全绿（新增
> `tests/test_position_ledger_domain.py`、`tests/test_ledger_janitor.py`；旧
> `test_position_ledger*.py` 回归通过）。
> - P1-1/P1-4：`position_ledger._migrate_p1` 增量 DDL + 归属回填（`migrations/001_ledger_domain.py`
>   入口，`p1-001` 只执行一次）；本地合成库两次迁移 `balances=True`、批次不重复。
> - P1-2：`record_fill` 单事务写 fills+L1+L2+lots，FIFO 平仓、fee 按量摊销尾差入末批；
>   `exchange_fill_id` 幂等；`reserve/release/expire` + `recon_breaks` 状态机。
> - P1-3：`TradeExecutionGateway._record_ledger` 改走 `record_fill`；`close_ghost_position`
>   支持 `domain` 归属校验。
> - P1-5：23 `exit_runner.collect_positions` 优先 `list_effective_positions`（stale 不进入离场）。
> - P1-6：`15-监控告警系统/scripts/ledger_janitor.py`（shadow，`janitor_enforce=off`）+
>   单实例文件锁 + heartbeat + feed_state=degraded（失败不累加 miss）。
> - P1-7：`22-执行引擎中心/executors/drop_copy_adapter.py`，按 `exchange_fill_id` 幂等导入
>   50 审计流水/交易所成交，重放不重复入账。
> - 待办：云端部署（`git pull` + 重启 22/23 服务）因网络不可达暂缓；`janitor_enforce=on`
>   与 systemd timer 属 P2-1。

### P1 归因（五层模型落地）

| ID | 任务 | 交付物 | 验收 |
|---|---|---|---|
| P1-1 | 增量 DDL + 注册表 + settings | 迁移脚本 `migrations/001_ledger_domain.py` | 重复执行幂等；旧代码可运行 |
| P1-2 | `record_fill` / lots / domain_positions | `PositionLedger` 新 API | 单测覆盖开/加/部分平/全平/PnL |
| P1-3 | gateway 单写口接入 | `_record_ledger` 改造 | 11/23/6 成交后 L1=L2 合计（误差 ≤1e-9） |
| P1-4 | 历史回填 | §4.7 SQL | 回填前后总 qty 一致；重复执行无新增 |
| P1-5 | 只读视图与消费方切换 | LedgerGuards/exit_runner/15 | 全链路无直接读 `positions` 的容量判定 |
| P1-6 | 对账 breaks + janitor（shadow） | `15-监控告警系统/scripts/ledger_janitor.py`（`janitor_enforce=off`） | 只标记不关闭；breaks 可查、可 ACK |
| P1-7 | drop-copy 适配器 | `22-执行引擎中心/executors/drop_copy_adapter.py` | 重放同一 `exchange_fill_id` 不重复入账；50 历史成交可回放 |

### P2 闭环（真正防复发）

| ID | 任务 | 交付物 | 验收 |
|---|---|---|---|
| P2-1 | 启用 stale→closed 自动迁移 | `janitor_enforce=on` | 断链 K 轮变 stale、M 轮关闭；恢复自动回 open |
| P2-2 | 预占额度 + 限额统一 | reservations API + domain_registry | 双进程并发开仓不超限；失败自动释放 |
| P2-3 | 50 域并网（选 A 时） | gateway domain=50 | 50 持仓进入 L1/L2；容量口径统一 |
| P2-4 | 监控指标与告警 | 15 指标 + Lark 告警 | breaks 超 SLA、stale 超阈值可告警 |
| P2-5 | 文档并入 | `TECHNICAL_DESIGN.md` §8 + INDEX | 索引指向唯一依据；旧描述标注弃用 |
| P2-6 | 日终正式对账 | EOD 报告 + 控制总数 | 每日 qty/名义与交易所一致；差异全部有 break |

---

## 8. 测试清单

### 8.1 单元测试（22/tests/test_position_ledger_domain.py）

| ID | 用例 | 断言 |
|---|---|---|
| U1 | 开仓分配 | fills.domain 正确；domain_positions.qty=成交 qty；lot 生成 |
| U2 | 同域加仓 | 均价按 qty 加权；lot 数增加；L1=L2 |
| U3 | FIFO 部分平仓 | 先开批次先扣；逐批 PnL 正确；剩余 lot 正确 |
| U4 | 全平 | domain_positions 归零且 status=closed；L1 归零；cooldown 写入 |
| U5 | 跨域平仓拒绝 | 非 owner 调用 `close_position` 返回拒绝且账本不变 |
| U6 | 超额平仓 | 截断到可用量；写 `over_close` break |
| U7 | 域内份额不足 | 不跨域借仓；break 生成 |
| U8 | 预占 | reserve 后可用额度下降；release/expire 恢复 |
| U9 | 并发预占 | 两线程同时 reserve 不超限 |

### 8.2 状态机与巡检（22/tests/test_ledger_janitor.py）

| ID | 用例 | 断言 |
|---|---|---|
| J1 | 连续缺失 K 轮 | status=stale；stale_since 写入；break 生成 |
| J2 | stale 不占容量 | `v_effective_positions` 不含该行；23 子池计数不增 |
| J3 | 缺失 M 轮 | status=closed；写 ghost fills；cooldown；break RESOLVED |
| J4 | 恢复持仓 | stale→open；miss_count=0；break 自动 RESOLVED |
| J5 | 交易所多仓账本缺失 | 补录 + `missing_in_ledger` |
| J6 | 数量/均价漂移 | `qty_drift`/`price_drift` 各一条活跃工单（唯一索引生效） |
| J7 | janitor 单实例 | 第二个实例启动被文件锁拒绝 |
| J8 | 交易所接口失败 | `miss_count` 不增加；`feed_state=degraded` |
| J9 | feed 陈旧保护 | 心跳过期时闸门回退 raw 口径并告警 |
| J10 | 账务修正不写冷却 | janitor 关闭后 `cooldowns` 无新增 |

### 8.3 迁移与集成

| ID | 用例 | 断言 |
|---|---|---|
| M1 | DDL 幂等 | 连续执行两次无报错、无重复表/列 |
| M2 | 回填幂等 | 两次回填 qty 一致、无重复 lot |
| M3 | 回填限制 | 历史 realized_pnl 全为 0；文档声明生效 |
| I1 | gateway 全链路 | 11/23/6 各下一单，L1=L2、fills.domain 正确 |
| I2 | 23 子池恢复 | 重建 25 假持仓 → 标 stale → 23 可开仓 |
| I3 | exit_runner 不再跨域写 | 23 遇幽灵仓只提交 break/委托 janitor |
| I4 | 15 只读 | 全程 `mode=ro`；无写锁 |
| I5 | 50 口径（A−） | drop-copy 导入后进 L1/L2；过渡期不计容量且 breaks 标注 |
| I6 | drop-copy 幂等 | 同一 `exchange_fill_id` 重放两次只入账一次 |
| I7 | 历史关闭行迁移 | 迁移后 `qty<=0` 行为 `status='closed'` |

### 8.4 回归与不变量

- `Σ domain_positions.qty == positions.qty`（同 `inst,side`，误差 ≤1e-9）。
- `Σ position_lots.remaining_qty == domain_positions.qty`（同域）。
- 现有 `test_position_ledger.py` 全绿（兼容 `record_open/apply_partial_close` 旧 API）。
- 现有 23 `entry_loop` / `ledger_guards` 测试全绿。
- 25 假持仓场景：P0 后不再锁死子池。

---

## 9. 监控指标与可观测性

| 指标 | 含义 | 告警 |
|---|---|---|
| `ledger_stale_positions` | status=stale 行数 | > 阈值告警 |
| `ledger_breaks_open` | 活跃 break 数 | 按 kind 分阈值 |
| `ledger_breaks_overdue` | 超 SLA 的 break | >0 告警 |
| `ledger_miss_max` | 最大 miss_count | 接近 K 预警 |
| `ledger_reservations_held` | 活跃预占 | 异常增长告警 |
| `ledger_domain_qty_mismatch` | L1/L2 不平数 | >0 立即告警 |
| `ledger_janitor_age_seconds` | 巡检最近运行时间 | 超 2 个周期告警 |
| `ledger_feed_state` | ok / degraded / stale | degraded 持续超阈值告警 |

审计：所有状态迁移写 `fills`（janitor 使用 `source='22-janitor'`）或 `recon_breaks.resolution`，禁止无痕改账。

---

## 10. 风险、回滚与评审决策点

### 10.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| SQLite 多进程写冲突 | 落账失败/锁等待 | WAL + busy_timeout + 单实例 janitor |
| 双写不一致 | L1/L2 不平 | 同事务写入 + 不变量巡检 + 立即告警 |
| 时间/确认阈值不当 | 误判 stale 或长期不清理 | settings 可调；先 shadow 观察 1–2 天 |
| 历史 PnL 不可拆 | 绩效口径失真 | 回填 PnL=0，明确只从切换后派生 |
| 50 未并网 | 容量口径分裂 | P0 明确 A/B，文档声明 |
| 跨域代平 | 账本互相污染 | owner-only + janitor 唯一写状态 |

### 10.2 回滚

- 方案全部为增量表/列，回滚 = 停 janitor + 闸门读回 `positions`（保留 `LEDGER_GATE_EFFECTIVE=off` 一个开关即可），数据不删除。
- 清理的 25 条 ghost 行保留备份库与 fills 审计，可重放。

### 10.3 评审决策（依据传统金融实践，v0.2 已定）

| # | 决策 | 依据 |
|---|---|---|
| 1 | 50 域走 **A−（drop-copy 并网）**，不改其执行路径；P1 过渡期显式排除在 22 容量口径外 | 传统金融 order entry 与 position keeping 分离，账本由 drop copy 喂养；避免把“账本唯一”误做成“网关唯一” |
| 2 | stale/close 改为**时间 + 确认次数**：600s / 3600s，最少 3 次确认，不用轮数 | 盘中持仓对账惯例是分钟级、多次确认，避免单次快照不全误判；且兼容不同巡检周期 |
| 3 | P1 坚持“一标的一域”，用唯一索引在库层强制；多域共持留 P2 Mode B | 传统金融允许共持但必须做 allocation；缺少 lot 分配前共持会污染账本 |
| 4 | janitor 进程归属 **15（中台控制）**，账本写 API 复用 22 | 前台执行与中台持仓控制分离，避免执行引擎自证 |
| 5 | 历史归属**必须**做一次性控制总数对账 + 异常清单人工签字，之后才允许 `janitor_enforce=on` | 迁移必须有 control totals 与 sign-off；历史 PnL 不可拆，P&L 从切换日重新起算 |

---

## 11. 并入 TECHNICAL_DESIGN 的计划

已执行（2026-11-23）：

1. 在 `22-执行引擎中心/docs/TECHNICAL_DESIGN.md` 追加 **§8 多域账本归因（五层模型）**：模型图、状态机、写路径、读口径、janitor 职责，正文引用本 SPEC 作为细节来源。
2. 更新 §7 统一持仓账本的描述：明确 `source` 降级为展示字段，归属以 `domain_positions` 为准；`reconcile_ledger` 不再承担关闭职责。
3. 更新 `docs/ENGINEERING_INDEX.md` 与 `docs/README.md` 目录清单，标注本 SPEC 为“设计依据（评审通过）”。
4. 在 `docs/CHANGELOG.md` 记录变更；本 SPEC 状态改为 `Approved`，不再单独维护第二份架构描述。

---

## 12. 评审记录（v0.1 → v0.2）

| # | 评审发现 | 严重度 | 处置 |
|---|---|---|---|
| R1 | “单一写口=只能走 gateway”过窄，50/手工单/交易所 SLTP 无法入账 | P0 | 改为“单一事件流 + 三个受控写入口”，新增 drop-copy 与 `exchange_fill_id` 幂等 |
| R2 | 按轮数判定 stale 依赖巡检周期，且把 API 失败当缺失 | P0 | 改为时间 + 确认次数；查询失败只降级不计数 |
| R3 | feed 停摆时 `v_effective_positions` 变空，闸门可能放开超限 | P0 | 新增 heartbeat + `feed_guard_action=fallback_raw` |
| R4 | janitor 关闭 ghost 会写 cooldown，误伤可交易标的 | P1 | 账务修正 `set_cooldown=False` |
| R5 | ADD COLUMN 默认值导致历史已平行被标 `open` | P1 | 迁移补 `qty<=0 AND closed_at NOT NULL → closed` |
| R6 | 多域共持缺少库层约束 | P1 | 增加 `uq_domain_positions_active_domain` 部分唯一索引 |
| R7 | drop-copy 重放会重复扣仓 | P1 | `uq_fills_exchange_fill` 幂等键 |
| R8 | 批次 PnL 未定义费用与尾差 | P2 | 明确 fee 按 qty 摊、尾差入最后批次 |
| R9 | janitor 由执行侧自管，缺职责分离 | P1 | 进程归属 15，API 复用 22，仅云端单实例 |
| R10 | 缺日终正式对账 | P2 | 新增 P2-6 EOD 控制总数报告 |

**结论**：v0.2 无 P0 未决项；待用户确认 §10.3 五项决策后，按 P0 → P1 → P2 开工，并在完成后并入 `TECHNICAL_DESIGN.md` §8。
