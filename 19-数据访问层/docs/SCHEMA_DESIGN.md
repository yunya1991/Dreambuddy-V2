# 19-数据访问层 · 数据库 Schema 设计文档

> **版本**: v1.0 | **日期**: 2026-08-24
> **权威等级**: L1（本子系统 Schema 最高），与 [TECHNICAL_DESIGN.md §2.4](./TECHNICAL_DESIGN.md#24-sqlite-单库-schema-分区策略1-库--7-域前缀--约-21-张表) 表分区完全对齐
> **Schema 版本**: `ma_schema_version.version = 1`（对应 Alembic 首版迁移 revision）
> **适用文件**: `dreambuddy_core.db` — 单文件 WAL 模式统一库
> **关联 ADR**: ADR-19-003（1 库前缀分区） / ADR-19-005（CREATE TABLE 即最终目标 Schema + _add_column_if_missing 补列）

---

## 0. 使用规则（强制）

### 0.1 Schema 演进 SLA（严格执行，违者 P0 事故）

1. **Schema 变更唯一出口 = Alembic**。禁止手动 `ALTER TABLE`；禁止在生产 `sqlite3` CLI 里改表
2. **MAJOR.MINOR.PATCH 语义**（对齐 TECHNICAL_DESIGN §6.3）：
   - MAJOR：破坏性变更（删列 / 改列类型 / 改主键 / 删表）→ 必须配合数据迁移脚本 + 双写回滚演练
   - MINOR：向后兼容（加列带 DEFAULT / 加索引 / 加 VIEW）→ 业务代码零改可跑
   - PATCH：调优（重建索引 / 重写统计信息 / ANALYZE）
3. **任何加列必须带安全默认值**（经验 698940 / 1040063）：
   ```sql
   -- ✅ 正确：NOT NULL + DEFAULT + 注释
   ALTER TABLE tr_trades ADD COLUMN regime_pred TEXT NOT NULL DEFAULT 'UNKNOWN';
   -- ❌ 错误：会让历史行变成 NULL，后续 NOT NULL 查询爆炸
   ALTER TABLE tr_trades ADD COLUMN regime_pred TEXT NOT NULL;  -- 禁用
   ```

### 0.2 数据库级 PRAGMA（连接时必须第一时间执行）

```sql
-- 连接参数（sqlite3.connect 后第一时间执行，顺序严格）
PRAGMA journal_mode = WAL;                  -- Write-Ahead Logging（并发读+写性能 3x+）
PRAGMA synchronous = NORMAL;                -- 配合 WAL = 性能+安全平衡（宕机最多丢最后一次检查点事务）
PRAGMA busy_timeout = 5000;                 -- 锁等待超时5秒（配合 DAL auto_retry_locked 退避）
PRAGMA foreign_keys = ON;                   -- ⭐ 必须开启！否则 FK 约束不生效（SQLite 默认关闭）
PRAGMA temp_store = MEMORY;                 -- 临时表/排序放内存，减少磁盘 IO
PRAGMA cache_size = -262144;                -- 页缓存 = 262144×4KB ≈ 1GB（按机器内存调，mac mini 8G/16G 足够）
PRAGMA mmap_size = 2147483648;              -- 内存映射 IO = 2GB（读性能大幅提升）
```

**PRAGMA 验证脚本**（连接后立即断言，未设置抛 `DalMisconfigurationError`）：
```python
required = {
    "journal_mode": "wal",
    "foreign_keys": 1,
    "busy_timeout": 5000,
}
for k, expected in required.items():
    actual = conn.execute(f"PRAGMA {k}").fetchone()[0]
    if str(actual).lower() != str(expected).lower():
        raise DalMisconfigurationError(f"PRAGMA {k}={actual}≠{expected}；请检查连接初始化")
```

---

## 1. 表域分区总览

按 TECHNICAL_DESIGN §2.4 前缀约定：

| 前缀 | 域 | 表数 | 典型写入频率 | 容量预估（3 年 × 5× 增长） |
|---|---|---|---|---|
| `ma_` | Meta 审计域 | 3 | 低（Cron + 迁移期） | < 20 MB |
| `tr_` | 交易域 | 3 | 极高（交易触发 + 每日聚合） | < 1 GB |
| `po_` | 持仓域 | 2 | 高（每分钟刷价） | < 200 MB |
| `mm_` | 宏观域 | 6 | 中（15m / 1h 级） | < 1 GB（核心瓶颈域） |
| `rs_` | 风控域 | 2 | 低（事件触发） | < 50 MB |
| `cv_` | 配置版本域 | 1 | 极低（发版） | < 20 MB |
| `kg_` | 知识图谱域 | 4 | 中（知识线写入） | < 2 GB |
| **合计** | 7 域 | **21** | — | **~ 4.3 GB**（远低于 SQLite 官方 280TB 理论上限） |

---

## 2. Meta 审计域表（`ma_*`，共 3 张）

### 2.1 ma_schema_version（Schema 版本登记，单行表）

```sql
CREATE TABLE IF NOT EXISTS ma_schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- 永远单行锁（Singleton Enforcer）
    version INTEGER NOT NULL,               -- 对应 Alembic head 版本号
    schema_semver TEXT NOT NULL,            -- 人类可读 SemVer（如 "1.0.0"）
    upgraded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- ISO UTC
    upgraded_by TEXT NOT NULL DEFAULT 'system',           -- system / alembic / script_xxx
    notes TEXT                                          -- 升级说明（首次建表 = "v1.0 初始化"）
);
-- 初始值：schema_init.py 首次执行写入 (1, 1, '1.0.0', ...)
```

### 2.2 ma_migration_audit（迁移 + DualWrite 对账差异日志）

```sql
CREATE TABLE IF NOT EXISTS ma_migration_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    category TEXT NOT NULL CHECK (category IN (
        'migration_script',   -- Alembic 迁移 / import_all_from_json.py
        'legacy_write_fail',  -- DualWrite 装饰器：旧写失败（严重）
        'next_gen_write_fail',-- DualWrite 装饰器：新写失败
        'next_gen_read_fail', -- DualWrite 装饰器：新读失败
        'id_mismatch',        -- DualWrite：旧新返回 ID 不一致
        'read_diff',          -- DualWrite：影子读 CRC32 差异
        'integrity_check',    -- Cron 完整性检查结果
        'schema_upgrade'      -- Alembic upgrade/downgrade 执行
    )),
    event_name TEXT NOT NULL,                  -- 如 "add_trade" / "import_batch1"
    entity_key TEXT,                            -- 如 trade_id / batch_id
    result TEXT NOT NULL CHECK (result IN ('APPLIED', 'SKIPPED', 'FAILED', 'WARN')),
    severity INTEGER NOT NULL DEFAULT 0 CHECK (severity BETWEEN 0 AND 3),
                                              -- 0=INFO / 1=WARN / 2=ERROR / 3=CRITICAL
    details TEXT,                               -- JSON 字符串（差异列表/错误堆栈）
    latency_ms INTEGER                          -- 本次操作耗时（ms）
);
-- 索引：按时间 + 严重级别 + 类别（Cron 每日报告查询路径）
CREATE INDEX IF NOT EXISTS idx_ma_audit_time_sev ON ma_migration_audit(run_at, severity);
CREATE INDEX IF NOT EXISTS idx_ma_audit_category ON ma_migration_audit(category, run_at DESC);
```

### 2.3 ma_integrity_log（每日 `PRAGMA integrity_check` 结果）

```sql
CREATE TABLE IF NOT EXISTS ma_integrity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    integrity_result TEXT NOT NULL,            -- "ok" 或具体错误串（如 "missing index entry"）
    db_size_bytes INTEGER NOT NULL,             -- 主库文件大小（趋势观察）
    wal_size_bytes INTEGER,                     -- WAL 文件大小（检查点积压预警阈值 = 10% × db_size）
    schema_version INTEGER NOT NULL,            -- 冗余复制（跨报告 JOIN 方便）
    checkpoint_result TEXT,                     -- "PASS" / "timeout(5000ms)" 等
    free_disk_pct REAL                          -- 所在卷剩余空间百分比（<20% 预警）
);
CREATE INDEX IF NOT EXISTS idx_ma_integrity_time ON ma_integrity_log(run_at DESC);
```

---

## 3. 交易域表（`tr_*`，共 3 张）

### 3.1 tr_trades（每笔交易的生命周期记录 = 核心事实表）

```sql
CREATE TABLE IF NOT EXISTS tr_trades (
    -- ===== 主键 =====
    trade_id TEXT PRIMARY KEY,                  -- 业务 ID：TRD-SMK-B1 / TRD-YIJ-20260824001
    -- ===== 基础维度 =====
    symbol TEXT NOT NULL,                       -- "BTC-USDT-SWAP"（对齐 OKX instId 格式）
    inst_id TEXT,                               -- OKX 返回的唯一 instId（可能 = symbol，冗余索引列）
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short')),
    strategy_source TEXT NOT NULL DEFAULT 'unknown'
        CHECK (strategy_source IN ('yijing','v15','classic','triple_screen','manual','unknown')),
    -- ===== 价格/时间 =====
    entry_price REAL NOT NULL CHECK (entry_price > 0),
    entry_time TEXT NOT NULL,                   -- ISO UTC："2026-08-24T07:30:00+0000"
    exit_price REAL CHECK (exit_price IS NULL OR exit_price > 0),
    exit_time TEXT,                             -- NULL = 持仓中
    -- ===== 盈亏 =====
    pnl REAL NOT NULL DEFAULT 0,                -- 绝对盈亏（USDT）
    pnl_pct REAL NOT NULL DEFAULT 0,            -- 相对盈亏百分比
    exit_reason TEXT,                           -- "stop_loss" / "take_profit" / "timeout" / "manual" / ...
    -- ===== 置信度 / 信号 =====
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    hexagram TEXT,                              -- 易经卦象："乾为天" / "火地晋"
    regime_pred TEXT,                           -- BCRM 2.0 市态预测（冗余列）
    -- ===== 风控参数（冗余快照，便于独立复盘）=====
    base_sl_roi REAL,                           -- 止损 ROI（如 -0.015 = -1.5%）
    base_tp_roi REAL,                           -- 止盈 ROI（如 0.03 = +3%）
    -- ===== 轻仓试错（XAG 新增）=====
    is_trial INTEGER NOT NULL DEFAULT 0 CHECK (is_trial IN (0,1)),
    trial_open_ts TEXT,                         -- 试错开仓时刻（30min 评估基准）
    trial_eval_done INTEGER NOT NULL DEFAULT 0 CHECK (trial_eval_done IN (0,1)),
    trial_eval_result TEXT CHECK (trial_eval_result IS NULL OR trial_eval_result IN ('add','close','hold')),
    -- ===== 半结构化兜底（YAGNI 新增字段不用改表）=====
    liangyi_state TEXT,                         -- JSON 字符串：两仪状态快照
    market_snapshot TEXT,                       -- JSON 字符串：开仓瞬间市场快照（20+特征）
    scale_params TEXT,                          -- JSON 字符串：马丁加仓参数/易经 scale
    extra_payload TEXT,                         -- JSON 字符串：未来任意扩展字段（推荐 90% 新字段先进这里）
    -- ===== 审计列 =====
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ========== 索引设计（覆盖 95% 真实查询，经验 1040063：CREATE INDEX IF NOT EXISTS 幂等）==========
CREATE INDEX IF NOT EXISTS idx_tr_trades_symbol_entry_time
    ON tr_trades(symbol, entry_time DESC);       -- ★ 最常用：某币种最近 N 笔交易 → 走覆盖索引
CREATE INDEX IF NOT EXISTS idx_tr_trades_open    -- 持仓中查询（exit_time IS NULL 优化）
    ON tr_trades(exit_time) WHERE exit_time IS NULL;
CREATE INDEX IF NOT EXISTS idx_tr_trades_is_trial ON tr_trades(is_trial, trial_eval_done);
CREATE INDEX IF NOT EXISTS idx_tr_trades_strategy ON tr_trades(strategy_source, entry_time);
CREATE INDEX IF NOT EXISTS idx_tr_trades_daily ON tr_trades(DATE(entry_time));  -- 每日绩效快速 GROUP BY
```

**字段注释（业务语义）**：
- `trade_id`：各子系统自己生成（如易经 TRD-YIJ-YYYYMMDDNNN / V15 TRD-V15-XXX），DAL 不生成
- `extra_payload`：未来 80% 新字段先放这里（JSON），稳定后再 ALTER 正式列。避免 schema churn
- `base_sl_roi / base_tp_roi`：**静态风控参数快照**，事后复盘不依赖当时 `risk_state` 配置

### 3.2 tr_daily_stats（每日绩效快照，按天预聚合 = 仪表盘直接读）

```sql
CREATE TABLE IF NOT EXISTS tr_daily_stats (
    date TEXT PRIMARY KEY,                      -- "2026-08-24"（本地时区日期，和日报一致）
    -- ===== 交易笔数 =====
    total_trades INTEGER NOT NULL DEFAULT 0,
    win_trades INTEGER NOT NULL DEFAULT 0,
    loss_trades INTEGER NOT NULL DEFAULT 0,
    open_trades INTEGER NOT NULL DEFAULT 0,     -- 当日未平仓数（结束时刻）
    -- ===== 盈亏金额 =====
    total_pnl REAL NOT NULL DEFAULT 0,
    win_pnl REAL NOT NULL DEFAULT 0,
    loss_pnl REAL NOT NULL DEFAULT 0,
    avg_win REAL NOT NULL DEFAULT 0,
    avg_loss REAL NOT NULL DEFAULT 0,
    max_single_win REAL NOT NULL DEFAULT 0,
    max_single_loss REAL NOT NULL DEFAULT 0,
    -- ===== 组合质量指标 =====
    win_rate REAL NOT NULL DEFAULT 0,           -- win/total，total=0 时为 0
    profit_factor REAL NOT NULL DEFAULT 0,      -- win_pnl / ABS(loss_pnl)
    avg_r_multiple REAL NOT NULL DEFAULT 0,     -- 平均 R 倍数（pnl / initial_risk）
    -- ===== 权益曲线（含时间序列）=====
    starting_equity REAL NOT NULL DEFAULT 0,    -- 当日开盘前权益
    ending_equity REAL NOT NULL DEFAULT 0,      -- 当日收盘后权益
    peak_equity REAL NOT NULL DEFAULT 0,        -- 历史峰值权益（计算 DD 用）
    max_drawdown REAL NOT NULL DEFAULT 0,       -- 当日历史最大回撤（%，-0.10 = -10%）
    daily_drawdown REAL NOT NULL DEFAULT 0,     -- 当日内部回撤（相对日内峰值）
    -- ===== 风控熔断统计 =====
    circuit_breaker_triggered INTEGER NOT NULL DEFAULT 0, -- 0/1 是否触发日回撤熔断
    consecutive_losses_end INTEGER NOT NULL DEFAULT 0,    -- 当日结束时连亏笔数
    -- ===== 审计列 =====
    computed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, -- 聚合计算完成时刻
    source TEXT NOT NULL DEFAULT 'agg_trades'  -- "agg_trades"（自动算）/ "manual_override"（人工覆盖）
);
```

### 3.3 tr_daily_stats_overrides（人工覆盖某日统计，OKX 对账差异场景）

```sql
CREATE TABLE IF NOT EXISTS tr_daily_stats_overrides (
    date TEXT PRIMARY KEY REFERENCES tr_daily_stats(date) ON DELETE CASCADE,
    -- 覆盖列 = 和 tr_daily_stats 字段一一对应（仅填需要覆盖的字段，其余 NULL 表示用原值）
    total_pnl_override REAL,
    ending_equity_override REAL,
    win_rate_override REAL,
    max_drawdown_override REAL,
    -- 元信息
    reason TEXT NOT NULL,                       -- 例如："OKX 手工平仓遗漏记录，补 1 笔亏损-52.3USDT"
    operator TEXT NOT NULL,                     -- 执行人（zhangjiangtao / system）
    overridden_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    evidence_url TEXT                           -- 飞书文档/对账截图 URL（审计链）
);
```

**查询优先级**：`get_daily_stats(date)` → 先查 tr_daily_stats → 再 JOIN overrides 覆盖对应字段（`COALESCE(override, original)` 语义）。

---

## 4. 持仓域表（`po_*`，共 2 张）

### 4.1 po_positions（当前持仓快照，exit_time IS NULL）

```sql
CREATE TABLE IF NOT EXISTS po_positions (
    inst_id TEXT PRIMARY KEY,                   -- OKX 唯一持仓 ID（Fail-Closed 唯一键）
    trade_id TEXT NOT NULL REFERENCES tr_trades(trade_id),  -- 关联开仓记录
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long','short')),
    -- ===== 开仓信息 =====
    entry_price REAL NOT NULL,
    quantity REAL NOT NULL,                     -- 合约张数
    opened_at TEXT NOT NULL,                    -- 开仓时刻（ISO UTC）
    -- ===== 实时行情（每分钟刷新）=====
    mark_price REAL NOT NULL,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    unrealized_pnl_pct REAL NOT NULL DEFAULT 0,
    liquidation_price REAL,                     -- OKX 强平价
    -- ===== 风控参数 =====
    stop_loss_price REAL,
    take_profit_price REAL,
    current_leverage REAL,
    -- ===== 试错标记（同 tr_trades.is_trial，冗余便于查询）=====
    is_trial INTEGER NOT NULL DEFAULT 0,
    trial_open_ts TEXT,
    trial_eval_done INTEGER NOT NULL DEFAULT 0,
    -- ===== 审计列 =====
    last_price_refresh_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_po_positions_symbol ON po_positions(symbol);
CREATE INDEX IF NOT EXISTS idx_po_positions_open_time ON po_positions(opened_at DESC);
```

### 4.2 po_price_refresh_log（价格刷新心跳日志，排障定位用）

```sql
-- 用于排障："为什么 14:30-15:00 mark_price 没变？" — 轮询任务是不是挂了？
CREATE TABLE IF NOT EXISTS po_price_refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    positions_updated INTEGER NOT NULL,         -- 本批次刷新了多少条持仓
    latency_ms INTEGER NOT NULL,                -- 本批次总耗时（ms）
    okx_api_error TEXT,                         -- 本次 OKX REST API 错误（无错误 = NULL）
    source TEXT NOT NULL DEFAULT 'polling_trader'
);
CREATE INDEX IF NOT EXISTS idx_po_refresh_time ON po_price_refresh_log(refresh_at DESC);
```

---

## 5. 宏观域表（`mm_*`，共 6 张 — 合并 14×macro_*.db）

### 设计原则（所有 6 张表共享）：
- **指标类（无 symbol）**：如恐惧贪婪指数 — 主键 = `timestamp`
- **币种类（有 symbol）**：如资金费率 — 主键 = `(symbol, timestamp)` WITHOUT ROWID（= 覆盖索引，零回表查）
- **统一 upsert 语义**：`INSERT OR REPLACE`（幂等写入，`macro_data_fetcher.py` 重复跑无副作用）
- **所有金额/比率 = REAL**（你们现有 pd.read_sql 期望浮点列）

### 5.1 mm_fear_greed（全局恐惧贪婪指数，无 symbol）

```sql
CREATE TABLE IF NOT EXISTS mm_fear_greed (
    timestamp INTEGER PRIMARY KEY,              -- UNIX 秒
    fear_greed_index INTEGER NOT NULL CHECK (fear_greed_index BETWEEN 0 AND 100),
    value_classification TEXT,                  -- "Extreme Fear" / "Fear" / "Neutral" / "Greed" / ...
    trend_7d REAL,                              -- 7 日滑动均值趋势
    raw_payload TEXT,                           -- 原始 API 返回 JSON（诊断用）
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 5.2 mm_funding_rate（资金费率，按币种）

```sql
CREATE TABLE IF NOT EXISTS mm_funding_rate (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,                  -- UNIX 秒
    funding_rate REAL NOT NULL,                  -- e.g. 0.0001 = 0.01%/8h
    funding_interval_hours INTEGER DEFAULT 8,   -- OKX 默认 8h（冗余列）
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
) WITHOUT ROWID;
-- ⭐ WITHOUT ROWID = 主键即聚簇索引。查询 "BTC 最近 7 天 funding" → 零回表顺序扫
CREATE INDEX IF NOT EXISTS idx_mm_funding_time ON mm_funding_rate(timestamp DESC);
```

### 5.3 mm_open_interest（未平仓合约量，按币种）

```sql
CREATE TABLE IF NOT EXISTS mm_open_interest (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open_interest REAL NOT NULL,                -- 合约面值（USDT 名义）
    oi_change_pct_24h REAL,                     -- 24h OI 变化率（预计算列，方便查询）
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
) WITHOUT ROWID;
```

### 5.4 mm_liquidation（爆仓数据，按币种）

```sql
CREATE TABLE IF NOT EXISTS mm_liquidation (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    liq_long_usdt REAL NOT NULL DEFAULT 0,      -- 多单爆仓 USDT 名义
    liq_short_usdt REAL NOT NULL DEFAULT 0,     -- 空单爆仓 USDT 名义
    liq_total_usdt REAL NOT NULL DEFAULT 0,     -- 合计（预计算冗余）
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
) WITHOUT ROWID;
```

### 5.5 mm_long_short_ratio（多空持仓人数比，按币种）

```sql
CREATE TABLE IF NOT EXISTS mm_long_short_ratio (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    long_short_ratio REAL NOT NULL,             -- e.g. 1.25 = 多:空 = 1.25:1
    long_accounts INTEGER,
    short_accounts INTEGER,
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
) WITHOUT ROWID;
```

### 5.6 mm_taker_volume（主动买卖成交量，按币种）

```sql
CREATE TABLE IF NOT EXISTS mm_taker_volume (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    taker_buy_vol REAL NOT NULL DEFAULT 0,      -- 主动买（USD 名义）
    taker_sell_vol REAL NOT NULL DEFAULT 0,     -- 主动卖（USD 名义）
    taker_buy_sell_ratio REAL,                  -- buy/sell（预计算）
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
) WITHOUT ROWID;
```

> **宏观容量说明**：14 币种 × 6 指标 × 4 次/小时 × 24h × 365 天 × 3 年 = ≈ 2650 万行。WITHOUT ROWID + 整数主键 = 每行 ≈ 40-60 bytes，总容量 ≈ 1~1.5 GB（完全在 SQLite 性能甜点）。

---

## 6. 风控域表（`rs_*`，共 2 张）

### 6.1 rs_state（风控引擎状态，强制单行表）

```sql
CREATE TABLE IF NOT EXISTS rs_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),      -- ★ 强制单例（Singleton Check 约束）
    -- ===== 日内盈亏 & 熔断 =====
    daily_pnl REAL NOT NULL DEFAULT 0,          -- 当日累计盈亏（USDT）
    daily_loss_limit REAL NOT NULL DEFAULT -1000,  -- 亏损熔断阈值（负）
    loss_limit_pct REAL NOT NULL DEFAULT 0.20,  -- 易经推理风控：可用资金 20% 亏损触发（project_memory 硬约束）
    daily_drawdown_pct REAL NOT NULL DEFAULT 0,
    circuit_breaker_active INTEGER NOT NULL DEFAULT 0 CHECK (circuit_breaker_active IN (0,1)),
    circuit_breaker_reason TEXT,                -- 熔断原因
    circuit_breaker_at TEXT,                    -- 熔断时刻
    -- ===== 连亏统计 =====
    current_consecutive_losses INTEGER NOT NULL DEFAULT 0,
    max_consecutive_losses INTEGER NOT NULL DEFAULT 0,
    -- ===== 交易暂停 =====
    trading_halted INTEGER NOT NULL DEFAULT 0 CHECK (trading_halted IN (0,1)),
    halt_reason TEXT,                           -- 手工暂停原因
    halt_by TEXT,                               -- 执行人
    halt_at TEXT,
    -- ===== 仓位参数 =====
    position_size_pct REAL NOT NULL DEFAULT 1.0,-- 全局仓位缩放系数（易经五计庙算 cap）
    min_position_usdt REAL NOT NULL DEFAULT 10, -- 最小开仓单位（USDT）
    -- ===== 易经风控特有：五计庙算（project_memory 硬约束）=====
    five_domain_score REAL,                     -- 总分 0-100
    war_state TEXT DEFAULT 'ALLOW' CHECK (war_state IN ('ALLOW','DEFEND','SURRENDER')),
    strategy_mask TEXT,                         -- JSON 数组：各策略启用掩码
    style_exposure_weights TEXT,                -- JSON：策略权重和=1.0（极差态 emergency+volatility>0.5）
    -- ===== 审计列 =====
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT NOT NULL DEFAULT 'system',
    _version INTEGER NOT NULL DEFAULT 1         -- 乐观锁：UPDATE ... WHERE _version = old_ver
);

-- ⭐ rs_state 触发器：任何 UPDATE 自动刷 updated_at + _version 自增（应用层不用手动写）
CREATE TRIGGER IF NOT EXISTS trg_rs_state_update
AFTER UPDATE ON rs_state
BEGIN
    UPDATE rs_state SET
        updated_at = CURRENT_TIMESTAMP,
        _version = _version + 1
    WHERE id = 1;
END;
```

### 6.2 rs_cases（风控告警案例 = CBR 风控记忆）

```sql
CREATE TABLE IF NOT EXISTS rs_cases (
    case_id TEXT PRIMARY KEY,                   -- RSK-YYYYMMDD-NNN
    case_type TEXT NOT NULL,                    -- "position_size_breach" / "consecutive_losses" / ...
    severity INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 5),
    symbol TEXT,
    related_trade_id TEXT REFERENCES tr_trades(trade_id),
    alert_ts TEXT NOT NULL,                     -- 触发时刻
    state_snapshot TEXT NOT NULL,               -- JSON：触发时的 rs_state + 持仓 + 市场快照
    rule_params TEXT,                           -- JSON：触发时参数值（阈值/实际值）
    action_taken TEXT NOT NULL,                 -- 实际采取动作："reject_open" / "halve_size" / "close_pos"
    outcome INTEGER,                            -- 事后评估 1=有效/0=误报（CBR学习用）
    notes TEXT,                                 -- 人工复盘注释
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rs_cases_severity ON rs_cases(severity DESC, alert_ts DESC);
CREATE INDEX IF NOT EXISTS idx_rs_cases_type ON rs_cases(case_type, alert_ts DESC);
```

---

## 7. 配置版本域表（`cv_*`，1 张 = 替代 258× releases/*.json）

### 7.1 cv_config_versions（策略配置全历史，不可篡改语义 = version 唯一）

```sql
CREATE TABLE IF NOT EXISTS cv_config_versions (
    version TEXT PRIMARY KEY,                   -- "v0.1.258"（SemVer 命名，唯一）
    schema_major INTEGER NOT NULL DEFAULT 1,
    schema_minor INTEGER NOT NULL DEFAULT 0,
    schema_patch INTEGER NOT NULL DEFAULT 0,
    config_family TEXT NOT NULL DEFAULT 'baseline'
        CHECK (config_family IN ('baseline','v15','yijing','risk_params','classic','global')),
    payload TEXT NOT NULL,                       -- JSON 全文（原 v0.1.xxx.json 内容，≥ 98% 压缩比）
    changelog TEXT,                              -- 本版本变更说明
    released_by TEXT NOT NULL DEFAULT 'system',
    released_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0,1)),  -- 当前生效版本 = 1
    archived INTEGER NOT NULL DEFAULT 0         -- 归档版本不参与 list_versions 默认查询
);

-- ⭐ 业务约束触发器：任何时刻全局仅有 1 个 is_active = 1 版本 per family
CREATE TRIGGER IF NOT EXISTS trg_cv_version_uniq_active
AFTER INSERT ON cv_config_versions WHEN NEW.is_active = 1
BEGIN
    UPDATE cv_config_versions
    SET is_active = 0
    WHERE config_family = NEW.config_family
      AND version != NEW.version;
END;

CREATE INDEX IF NOT EXISTS idx_cv_versions_released ON cv_config_versions(released_at DESC);
CREATE INDEX IF NOT EXISTS idx_cv_versions_family ON cv_config_versions(config_family, released_at DESC);
```

---

## 8. 知识图谱域表（`kg_*`，共 4 张 = 沿用现有 kg_store.py 设计）

**完全对齐现有 [kg_store.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/kg_store.py#L61-L83) 的 Schema 设计**（已有实战验证，避免重写双时态 + FTS5）。仅加 `kg_` 前缀统一规范：

### 8.1 kg_entities（实体表）

```sql
CREATE TABLE IF NOT EXISTS kg_entities (
    entity_id TEXT PRIMARY KEY,                 -- "BTC" / "恐惧贪婪指数" / "Martin_Grid_Strategy"
    label TEXT NOT NULL,                        -- 人类可读标签
    category TEXT NOT NULL,                     -- "asset" / "macro_indicator" / "strategy" / ...
    metadata TEXT,                              -- JSON：描述、来源、别名来源
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 8.2 kg_entity_aliases（实体别名表，支持模糊搜索匹配）

```sql
CREATE TABLE IF NOT EXISTS kg_entity_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL REFERENCES kg_entities(entity_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,                        -- 如 "大饼" = BTC / "马丁" = Martin_Grid_Strategy
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
    UNIQUE(entity_id, alias)
);
CREATE INDEX IF NOT EXISTS idx_kg_aliases_alias ON kg_entity_aliases(alias);
```

### 8.3 kg_triples（SPO 三元组 + 双时态 = 核心事实存储）

```sql
-- 完全照搬 kg_store.py 设计：双时态（valid_time + transaction_time）
CREATE TABLE IF NOT EXISTS kg_triples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL REFERENCES kg_entities(entity_id),
    predicate TEXT NOT NULL,                    -- "has_correlation_with" / "belongs_to_sector" / ...
    object TEXT NOT NULL,                       -- 另一个 entity_id 或字面值
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    sources TEXT,                               -- JSON：来源列表（文档/交易ID/URL）
    valid_from TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- 事实生效起点
    valid_to TEXT,                                         -- 事实失效时间（NULL = 永久有效）
    tx_created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,    -- 入库时间（不可变）
    tx_retired TEXT                                       -- 被新知识替换时刻（版本化）
);
CREATE INDEX IF NOT EXISTS idx_kg_triples_spo ON kg_triples(subject, predicate, object);
CREATE INDEX IF NOT EXISTS idx_kg_triples_pred_obj ON kg_triples(predicate, object);
CREATE INDEX IF NOT EXISTS idx_kg_triples_valid ON kg_triples(valid_from, COALESCE(valid_to, '9999-12-31'));
```

### 8.4 kg_terms_fts（FTS5 全文索引，支持关键词 → 实体/三元组搜索）

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS kg_terms_fts USING fts5(
    term,                                       -- 索引列：实体标签、别名、三元组主宾词
    entity_id UNINDEXED,                        -- 附属：关联实体
    triple_id UNINDEXED,                        -- 附属：关联三元组
    content='kg_triples',                       -- 外部内容表（减少重复存储）
    content_rowid='id',
    tokenize = 'unicode61 remove_diacritics 2 tokenchars "_"'  -- 中文 + 数字 + 下划线混合支持
);

-- FTS5 触发器：kg_entities / kg_triples 写操作同步进全文索引（kg_store.py 已有逻辑同构）
CREATE TRIGGER IF NOT EXISTS trg_kg_entity_ai AFTER INSERT ON kg_entities BEGIN
    INSERT INTO kg_terms_fts(rowid, term, entity_id, triple_id)
    VALUES (new.rowid, NEW.label || ' ' || NEW.category, NEW.entity_id, NULL);
END;
-- kg_triples 同构触发器 3 条（INSERT/UPDATE/DELETE），同现有 kg_store.py 逻辑略
```

---

## 9. 索引总览 & 典型查询命中验证（性能基准）

### 9.1 索引清单（共 22 个，含 6 个 PRIMARY KEY）

| 表 | 索引名 | 索引列 | 场景 |
|---|---|---|---|
| ma_migration_audit | idx_ma_audit_time_sev | run_at, severity | 每日严重级别报告 |
| ma_migration_audit | idx_ma_audit_category | category, run_at DESC | 某类事件时间线 |
| ma_integrity_log | idx_ma_integrity_time | run_at DESC | 最近完整性报告 |
| tr_trades | idx_tr_trades_symbol_entry_time | symbol, entry_time DESC | ★ 最常用：某币种最近交易 |
| tr_trades | idx_tr_trades_open | exit_time WHERE NULL | 持仓中快速枚举 |
| tr_trades | idx_tr_trades_is_trial | is_trial, trial_eval_done | 待评估试错仓 |
| tr_trades | idx_tr_trades_strategy | strategy_source, entry_time | V15/易经策略分别统计 |
| tr_trades | idx_tr_trades_daily | DATE(entry_time) | 每日 GROUP BY 统计 |
| po_positions | idx_po_positions_symbol | symbol | 某币种持仓 |
| po_positions | idx_po_positions_open_time | opened_at DESC | 持仓时长排序 |
| po_price_refresh_log | idx_po_refresh_time | refresh_at DESC | 心跳是否正常 |
| mm_funding_rate | idx_mm_funding_time | timestamp DESC | 全局最新资金费率 |
| rs_cases | idx_rs_cases_severity | severity DESC, alert_ts DESC | 高危风控案例 |
| rs_cases | idx_rs_cases_type | case_type, alert_ts DESC | 某规则触发历史 |
| cv_config_versions | idx_cv_versions_released | released_at DESC | 最近发布 |
| cv_config_versions | idx_cv_versions_family | config_family, released_at DESC | 某家族配置历史 |
| kg_triples | idx_kg_triples_spo | s,p,o | 精确三元组查询 |
| kg_triples | idx_kg_triples_pred_obj | p,o | 反查主语 |
| kg_triples | idx_kg_triples_valid | valid_from, valid_to | 时态切片查询 |
| kg_entity_aliases | idx_kg_aliases_alias | alias | 别名反查实体 |

### 9.2 典型查询 EXPLAIN QUERY PLAN 验证脚本（性能回归测试必跑）

```python
# tests/perf/test_query_plans.py
ASSERTIONS = [
    ("某币种最近 30 笔交易",
     "SELECT * FROM tr_trades WHERE symbol='BTC-USDT-SWAP' ORDER BY entry_time DESC LIMIT 30",
     ["USING INDEX idx_tr_trades_symbol_entry_time"]),  # ✅ 应命中
    ("持仓中查询",
     "SELECT * FROM tr_trades WHERE exit_time IS NULL",
     ["USING INDEX idx_tr_trades_open"]),
    ("恐惧贪婪指数 24h 区间",
     "SELECT * FROM mm_fear_greed WHERE timestamp > 1750000000 ORDER BY timestamp",
     ["USING INTEGER PRIMARY KEY"]),  # WITHOUT ROWID/PK 等价覆盖
]
for name, sql, expected in ASSERTIONS:
    plan = conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    plan_str = "|".join(str(row[3]) for row in plan)
    for ex in expected:
        assert ex in plan_str, f"[{name}] 索引未命中! 期望 {ex} ∈ {plan_str}"
```

---

## 10. 迁移 helper 契约（_add_column_if_missing 等）

**经验落实（1040063 + 698940）**：`migration_helpers.py` 提供 4 个幂等原子操作，**所有 schema 补列/补约束必须经此 4 函数统一入口**（避免分散手写 ALTER 被追问"其他表呢"）：

| 函数 | 用途 | 事务要求 |
|---|---|---|
| `_add_column_if_missing(conn, table, column, ddl_with_default)` | PRAGMA table_info 探测缺列 → ALTER TABLE ADD；必须带 DEFAULT | 独立事务 |
| `_add_index_if_missing(conn, name, table, cols, unique=False)` | PRAGMA index_list 探测缺索引 → CREATE INDEX IF NOT EXISTS | 独立事务 |
| `_rebuild_table_with_new_schema(conn, table, target_ddl, copy_map)` | SQLite 不支持 ALTER ADD FK → 建 t_new → INSERT INTO t_new SELECT → DROP t_old → RENAME | 必须包裹一个 BIG TRANSACTION |
| `_ensure_singleton_row(conn, table, default_values)` | 对 rs_state / ma_schema_version 等单行表：空表时 INSERT 默认行 | 独立事务 |

> **使用黄金规则**：`schema_init.py` 中 `TARGET_CREATE_TABLES_SQL` 跑过之后，再跑 helpers 对旧库补列/补约束。**新库 = 零补列动作**，保证 CREATE TABLE = 最终 Schema（ADR-19-005）。

---

> **文档版本冻结**：v1.0 Schema 经 Alembic 首版 revision 写入生产后，任何字段调整必须走 Alembic + 更新本 SCHEMA_DESIGN.md；禁止私下改表不改文档。
