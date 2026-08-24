# 19-数据访问层 变更日志

> **规范**: 对齐 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式 + SemVer 版本语义
> **关联 SSoT**: [TECHNICAL_DESIGN.md §6.3](./TECHNICAL_DESIGN.md#63-alembic-迁移链schema-演进-sla) Schema SemVer 与 SemVer 同号联动
> **版本 = 代码 + Schema 同步**：MAJOR.MINOR.PATCH 同时指代 DAL 代码版本与 `ma_schema_version.schema_semver`

---

## [Unreleased]（P3 完成：Cron 三件套 + AES256 加密备份 + launchd 调度 — 2026-08-24）

> 🧪 **阶段**: P3 100%（backup + integrity + rotate + cron_runner CLI + 3 个 launchd plist 模板）。全阶段 P0→P3 完成。
> **TDD 覆盖率**: 136 tests, 136 passed (100%)

### Added（P3 全部新增）
- **Added** [backup.py](../dreambuddy_dal/implementations/sqlite_unified/backup.py) — 全量备份 + SHA256 + AES256-GCM：
  - `backup_database(db_path, backup_dir, *, encrypt=True, passphrase)` → VACUUM INTO 在线备份（不锁库）+ SHA256 sidecar + AES256-GCM 加密（passphrase 未设则明文）
  - `verify_backup(backup_path, *, passphrase)` → SHA256 校验 + 解密验证（SQLite 魔数 `SQLite format 3\x00`）
  - 文件名 `dreambuddy_core_YYYYmmdd_HHMMSS.db[.enc]`
- **Added** [integrity.py](../dreambuddy_dal/implementations/sqlite_unified/integrity.py) — PRAGMA 完整性检查：
  - `run_integrity_check(db_path) → IntegrityResult`：PRAGMA integrity_check + PRAGMA foreign_key_check
  - 结果写入 `ma_integrity_log`（run_at + integrity_result + db_size_bytes + wal_size_bytes + schema_version + checkpoint_result）
  - 连续运行追加审计行（不幂等，需历史轨迹）
- **Added** [rotate.py](../dreambuddy_dal/implementations/sqlite_unified/rotate.py) — WAL checkpoint + 备份轮转：
  - `wal_checkpoint(db_path) → int`：PRAGMA wal_checkpoint(TRUNCATE) 合并 WAL 到主库
  - `rotate_backups(backup_dir, keep=7) → list[Path]`：按 mtime 排序保留最新 keep 份，删除其余（含 .sha256 sidecar）
- **Added** [cron_runner.py](../dreambuddy_dal/cron_runner.py) — Cron 三件套统一 CLI 入口：
  - 4 子命令：`backup` / `integrity` / `rotate` / `checkpoint`
  - 环境变量驱动：`DAL_DB_PATH` / `BACKUP_DIR` / `BACKUP_PASSPHRASE` / `BACKUP_KEEP`
  - launchd plist 调用 `python3 -m dreambuddy_dal.cron_runner <command>`
- **Added** 3 个 launchd plist 模板：
  - [com.dreambuddy.dal.backup.plist](../launchd/com.dreambuddy.dal.backup.plist) — 每天 04:00 全量备份
  - [com.dreambuddy.dal.integrity.plist](../launchd/com.dreambuddy.dal.integrity.plist) — 每 6 小时完整性检查（00:30/06:30/12:30/18:30）
  - [com.dreambuddy.dal.rotate.plist](../launchd/com.dreambuddy.dal.rotate.plist) — 每天 05:00 轮转（备份后 1 小时）
- **Added** 12 新 TDD 单测：
  - [test_backup.py](../tests/implementations/sqlite_unified/test_backup.py) 4 GREEN（明文备份 + 加密 roundtrip + 错误 passphrase 失败 + 备份是合法 SQLite）
  - [test_integrity.py](../tests/implementations/sqlite_unified/test_integrity.py) 4 GREEN（健康 DB ok + 写 log + 连续追加 + 时间戳）
  - [test_rotate.py](../tests/implementations/sqlite_unified/test_rotate.py) 4 GREEN（WAL checkpoint 非负 + keep=7 删 3 + keep=0 删全 + 空目录不报错）

### 经验教训落实
- VACUUM INTO 是 SQLite 在线备份的标准方式（不阻塞写，WAL-safe）；比 `cp` + `sqlite3 .backup` 更简洁
- AES256-GCM 用 `cryptography.hazmat.primitives.ciphers.aead.AESGCM`；密钥派生用 SHA256(passphrase) → 32 字节；nonce 12 字节随机
- ma_integrity_log 的 schema 列名（run_at / integrity_result / db_size_bytes / wal_size_bytes / schema_version / checkpoint_result）与最初设想不同，实现时须对齐 schema_init.py 实际 DDL
- launchd plist 的 `$(VAR)` 变量在 EnvironmentVariables 中不自动展开，实际部署时需用绝对路径或 shell wrapper 替换

---

## [Unreleased]（P2 完成：门禁检查 + Shadow Read + Alembic — 2026-08-24）

> 🧪 **阶段**: P2 100%（G-1~G-5 门禁 + Shadow Read + next_gen 切读 + Alembic 首版迁移链）。下一阶段：P3 运维加固 + 历史归档
> **TDD 覆盖率**: 124 tests, 124 passed (100%)

### Added（P2 全部新增）
- **Added** [audit_summary.py](../dreambuddy_dal/implementations/sqlite_unified/audit_summary.py) — P2 门禁测量引擎：
  - `compute_audit_summary(db_path, window_hours=72) → AuditSummary`：G-1 双写差异率（category='dual_write' FAILED/total）+ G-3 影子读一致率（category='shadow_read' MATCH/total）
  - 空 DB 安全默认值：write_diff_rate=0.0, read_consistency_rate=1.0（不炸除零）
  - 时间窗口过滤：只计 72h 内审计行（`run_at` 列），旧数据自动排除
  - `.g1_pass` / `.g3_pass` 布尔属性，直接用于 gate_check 判定
- **Added** [gate_check.py](../dreambuddy_dal/implementations/sqlite_unified/gate_check.py) — G-1~G-5 五项门禁一键检查：
  - `run_gate_check(db_path, log_dir, rollback_drill_pass, backup_db_path) → GateCheckResult`
  - G-1/G-3：委托 audit_summary 计算
  - G-2：扫描 log_dir 下 *.log/*.jsonl/*.txt，regex 匹配 "database is locked"
  - G-4：手动传入 rollback_drill_pass（现场操作 30 分钟回滚演练）
  - G-5：PRAGMA integrity_check + 抽样 10 条
  - `.all_pass` 属性：5 项全 True 才允许切读；`.summary()` 输出文本报告
- **Added** Alembic 首版迁移链：
  - [alembic.ini](../dreambuddy_dal/migrations/alembic.ini) — 配置文件，version_table=ma_schema_version
  - [env.py](../dreambuddy_dal/migrations/env.py) — SQLAlchemy engine + PRAGMA 4 条（WAL/foreign_keys/busy_timeout/synchronous）连接事件注入
  - [0001_v1_initial_schema.py](../dreambuddy_dal/migrations/versions/0001_v1_initial_schema.py) — 首版 revision：从 schema_init.py 引入 DDL（单一事实源），upgrade() 建表 + 种子，downgrade() DROP 全表
- **Added** 6+4+3=13 新 TDD 单测：
  - [test_audit_summary.py](../tests/implementations/sqlite_unified/test_audit_summary.py) 6 GREEN（空 DB 安全 + G-1 0 fail + G-1 1/100 fail + G-3 100 match + G-3 1 diff + window 过滤）
  - [test_shadow_read.py](../tests/implementations/sqlite_unified/test_shadow_read.py) 4 GREEN（READ_SOURCE 未设无审计 + shadow 写审计 + 双 None MATCH + next_gen 读新库）
  - [test_gate_check.py](../tests/implementations/sqlite_unified/test_gate_check.py) 6 GREEN（全 PASS + G-1 FAIL + G-2 FAIL + G-2 PASS + G-4 FAIL + G-5 PASS）
  - [test_alembic.py](../tests/implementations/sqlite_unified/test_alembic.py) 3 GREEN（revision 文件存在 + alembic.ini 存在 + upgrade head 建表 + 种子）

### Changed
- **Changed** [di.py](../dreambuddy_dal/di.py) `_DualWrapper`：
  - 新增 `READ_SOURCE=shadow`：读方法执行后额外调 new 库 → 比对（MATCH/DIFF）→ 写 `ma_migration_audit(category='shadow_read')`；比对失败不影响主流程（Fail-Open）
  - 新增 `READ_SOURCE=next_gen`：读方法直接走 new 库（不再走 legacy），实现切读
  - `_sqlite_db_path()` 改为优先读 `DAL_DB_PATH` 环境变量 → fallback `DATA_DIR/dreambuddy_core.db`（测试可覆盖）
- **Changed** [schema_init.py](../dreambuddy_dal/implementations/sqlite_unified/schema_init.py) `ma_migration_audit`：
  - CHECK 约束 category 新增 `'dual_write'` + `'shadow_read'`
  - CHECK 约束 result 新增 `'MATCH'` + `'DIFF'`

### 经验教训落实
- Alembic env.py 必须用 SQLAlchemy `create_engine`（Alembic context.configure 需要 `.dialect`），不能传裸 sqlite3.Connection
- ma_schema_version 是单行表 `CHECK(id=1)`，种子数据只能 1 行；Alembic revision 的 INSERT OR IGNORE 确保幂等
- Schema DDL 单一事实源：Alembic revision 从 schema_init.py 引入 `_CREATE_TABLES_SQL` + `_CREATE_INDEXES_SQL`，不复制 SQL 文本

---

## [Unreleased]（P1 完成：统一 SQLite + 三批 Import 幂等 + 消费方双写 — 2026-08-24）

> 🧪 **阶段**: P1 100%（21 表 Schema + 6 SqliteImpl + 三批 Import + di dual_write 激活 + polling_trader/v15_trader 真实双写）。下一阶段：P2 对账门禁 + 切读 + 断旧写
> **TDD 覆盖率**: 105 tests, 105 passed (100%)

### Added（P1 全部新增，按文件系统展开）
- **Added** [schema_init.py](../dreambuddy_dal/implementations/sqlite_unified/schema_init.py) — 21 表 + 20 索引 + 4 触发器 + 4 migration_helpers：
  - 7 域 × 21 张表：ma_* 3 / tr_* 3 / po_* 2 / mm_* 6 / rs_* 2 / cv_* 1 / kg_* 4（含 FTS5 `kg_terms_fts` 虚拟表 content=kg_entities）
  - 4 触发器：rs_state UPDATE 自动刷 updated_at/version（乐观锁）；cv_config_versions 全局唯一 is_active=1；tr_daily_stats_overrides 覆盖自动回灌主表；ma_schema_version 写一条 UPDATE 时禁冲突
  - 幂等 helpers：`_add_column_if_missing` / `_create_index_if_not_exists` / `_rebuild_table_if_schema_differs` / `_ensure_singleton_row`；schema 初始化 per-db-path 锁（跨 :memory: 测试隔离）
  - 种子数据：`ma_schema_version` 预置两条（v0.0.0 BASELINE + v1.0.0 P1 SCHEMA DONE）；rs_state 单行种子（id=1 + CHECK id=1 保证单行）；`tr_trades.__NO_LINK__` 虚拟行（FK 约束下 po_positions 可存在无 trade_id 链接的行）
- **Added** [trade_impl.py](../dreambuddy_dal/implementations/sqlite_unified/trade_impl.py) — SqliteTradeRepository：
  - 6 方法全实现：add_trade（35 列 INSERT OR IGNORE + ADR-19-004 Decimal→TEXT）/ get_trade / query_trades（direction/strategy/closed 复合索引命中）/ close_position（乐观锁 WHERE trade_id + 不存在 is_closed 幂等）/ add_or_update_daily_stats（UNIQUE date 冲突 DO UPDATE SET）/ get_daily_stats
- **Added** [position_impl.py](../dreambuddy_dal/implementations/sqlite_unified/position_impl.py) + [risk_impl.py](../dreambuddy_dal/implementations/sqlite_unified/risk_impl.py)：
  - Position：upsert_position（UNIQUE 3-key → upsert + version 自增）；get_position / list_positions / refresh_mark_price（单列轻刷新，避免全行重写）
  - Risk：get_state 自动回种单例行；update_state（WHERE version=expected_version 乐观锁 NOTHING → 抛 ConcurrencyError）；add_case INSERT OR IGNORE；query_cases(min_severity 过滤 ORDER BY occurred_at DESC)
- **Added** [market_macro_impl.py](../dreambuddy_dal/implementations/sqlite_unified/market_macro_impl.py) + [config_impl.py](../dreambuddy_dal/implementations/sqlite_unified/config_impl.py) + [kg_impl.py](../dreambuddy_dal/implementations/sqlite_unified/kg_impl.py)：
  - MarketMacro 6×2 方法：upsert/query 时间窗口；WITHOUT ROWID 复合索引；Decimal/TEXT 双向转换
  - Config：get_active_version（is_active=1 单例触发器）；activate_version（旧激活自动取消）；get_specific_version / create_version 单调递增
  - KG：upsert_entity（UNIQUE id OR DO UPDATE）；add_alias / add_triple；kg_terms_fts BM25 排名近似；query_subgraph_by_entity BFS N 跳 direction 三向 min_confidence 过滤
- **Added** [import_runner.py](../dreambuddy_dal/implementations/sqlite_unified/import_runner.py) — 三批 Import 幂等脚本（对齐 MIGRATION_PLAN §3）：
  - 入口 `import_all_batches(data_dir, db_path, *, dry_run=False) → list[ImportReport]`（严格顺序 BATCH-1-core → BATCH-2-risk → BATCH-3-macro/kg）
  - 幂等保证：所有行 INSERT OR IGNORE / 乐观锁；每批次在 `ma_migration_audit(category='migration_script')` 写审计（checksum 后缀 + applied/skipped/failed 统计）；重复执行 run2/run3 APPLIED=0 + 核心业务表行数不变
  - dry_run：BEGIN + ROLLBACK 保证 0 业务行写；ma_migration_audit 独立事务照常写（事后审计可见）
  - 数据源 fallback：data_dir JSON 文件存在读文件 → 否则 JsonLegacy*Repository 内存薄实现 → 两者皆空 applied=0（不失败）
- **Added** 8+8+12+5+4=37 新 TDD 单测文件（RED→GREEN 严格顺序）：
  - [test_schema_init.py](../tests/implementations/sqlite_unified/test_schema_init.py) 12 GREEN（21 表存在断言 + _add_column_if_missing 幂等 + 种子 semver 回读 + FK 触发器行级断言）
  - [test_trade_repo.py](../tests/implementations/sqlite_unified/test_trade_repo.py) 8 GREEN（add/get/query/close_position 命中复合索引 + 幂等 close_position 无副作用 + daily_stats upsert 覆盖）
  - [test_position_risk_repo.py](../tests/implementations/sqlite_unified/test_position_risk_repo.py) 8 GREEN（position upsert 同键版本自增；expected_version 错乐观锁抛错；refresh_mark_price 不扰动 version；severity 过滤 query_cases）
  - [test_other_repos.py](../tests/implementations/sqlite_unified/test_other_repos.py) 12 GREEN（mm_* upsert+时间窗口 + config activate_version 自动取消旧激活 + kg fts BM25 order 不变）
  - [test_di_p1.py](../tests/test_di_p1.py) 5 GREEN（dual_write/json_legacy/sqlite_unified 三后端 + Kill-Switch 物理文件回退 + di 线程安全单例）
  - [test_import_runner.py](../tests/implementations/sqlite_unified/test_import_runner.py) 4 GREEN（三批严格顺序 + 幂等 run3 applied=0 行数不变 + dry_run 0 业务行 + ma_migration_audit 至少 3 条）

### Changed（di 双写激活 + 消费方真实切换 + 最小侵入双写）
- **Changed** [di.py](../dreambuddy_dal/di.py)：
  - P0 期 NotImplementedError → P1 真实实例化：`backend=dual_write → _DualWrapper(legacy + sqlite)`；`backend=sqlite_unified → Sqlite*Repository`
  - `_DualWrapper` 动态代理：所有 Protocol 方法串行 → 两后端都调用；SQLite 端失败记 warning，不影响 JSON（Fail-Open）；Protocol 类通过 ABC.register() 注册为虚拟子类，`isinstance(x, TradeRepository)` 正确成立
  - 每 db_path schema init 缓存路径锁，`:memory:` 与文件库相互隔离（避免 schema 初始化污染）
- **Changed** [trading_utils.py](/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/trading_utils.py)：
  - `register_trade_to_l4()` 首行加 `_dal_write_trade_if_enabled(trade)`：
    - 仅当 DB_BACKEND ∈ {dual_write, sqlite_unified} 触发；默认 json_legacy 零成本
    - `_convert_tradingutils_trade_to_unified()` 25+ 列字段漂移 adapter（enums 容错、缺失字段默认值）
    - 所有 DAL 调用 try/except logger.warning（不阻塞 L4 Case 注册，Fail-Open）
- **Changed** [v15_trader.py](/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/core/v15_trader.py)：
  - `_register_martin_trade_to_l4()` 在构造 TradeEvent 之后、注册 Case 之前注入 `_dal_write_martin_trade_if_enabled(...)`
  - 马丁 v15 无独立置信度 → 中性 0.5；strategy_source='martin_v15'；reduce_count=addon_level；martin_config/grid_params/regime/vol/sz/margin 快照全进 extra_payload JSONB
  - 同 Fail-Open：任何 DAL 失败只 `_log`，不影响 Case 注册与运行时

### Deprecated 不变（对齐 P0）
- 5 处独立 TradeRecord 定义，2026-09-30 清理；本 P1 不修改它们（仅通过 adapter 双写 SSoT 侧）

### 经验教训落实
- Experience 1040063：Schema 建表 SQL 严格 match SCHEMA_DESIGN.md §3；tr_daily_stats.extra_payload 漏列已通过 _add_column_if_missing 幂等补回；ma_migration_audit 审计链已建（后续 P2 对账可追溯）
- FK 约束 FOREIGN KEY po_positions.trade_id → tr_trades(trade_id)：空 FK 会失败 → 引入 tr_trades.__NO_LINK__ 虚拟种子行；此经验写入 SCHEMA_DESIGN 隐含 FK 约束注意事项
- 枚举/大小写 drift：TradeDirection enum 存小写（CHECK 约束里是 'long','short'）→ _from_enum(case_insensitive=True) + enum serialize 统一 `.lower()`，所有 Repo 层一致处理
- Performance：105 tests 全量 7.5s（P1 新增 49 测试），远低于 60s 预算；WAL + 连接池 PRAGMA 全局生效

---

## [Unreleased]（P0 代码基建完成 — 2026-08-24）

> 🧪 **阶段**: P0 代码基建 100%（文档 → 代码落地）。下一阶段：P1 SqliteImpl + 21 表 Schema + 三批 Import
> **TDD 覆盖率**: 56 tests, 56 passed (100%)
> **Ruff**: 0 errors, 0 warnings
> **Bytecode compile**: 0 errors

### Added（P0 全部新增，按文件系统展开）
- **Added** [unified_models.py](../dreambuddy_dal/unified_models.py) — 唯一数据模型 SSoT（解决 Experience 698940 5 处字段漂移）：
  - 6 枚举：`TradeDirection(LONG/SHORT)` / `TradeStatus(OPEN/CLOSED/PARTIAL)` / `ExitReason(7 种)` / `RiskLevel(4 档)` / `TrialStatus(6 状态含 NOT_APPLICABLE/EVAL_PASS)` / `PositionStyle(2 档)`
  - 4 核心 dataclass：`TradeRecord`（35+ 列 + 易经五计 war_state/strategy_mask/style_exposure + XAG 轻仓试错 4 列）/ `PositionState`（稳定 position_id 生成）/ `DailyStats` / `RiskState`（CHECK id=1 + 乐观锁 version）
  - 2 辅助：`RiskCaseRecord`（rs_cases 0-100 severity_score）/ `CloseInfo`（离场结果）
  - `_JsonSerdeMixin`：Decimal→TEXT / datetime→UTC ISO8601-Z / Enum→value，保证 JSON 往返无精度损失；`TradeRecord.close_info` 嵌套 `CloseInfo` 自动重建
- **Added** 6 个 [protocols/*.py](../dreambuddy_dal/protocols/) ABC（对齐 TECHNICAL_DESIGN §2.2 完整方法签名）：
  - `TradeRepository`：add_trade / get_trade / query_trades(6 参数 O(log n) 命中复合索引) / close_position / get_daily_stats / add_or_update_daily_stats
  - `PositionRepository`：upsert_position / get_position(symbol, sub, dir 唯一) / list_positions(sub/symbol 两维) / **refresh_mark_price 轻量刷新**（避免全行重写）
  - `MarketMacroRepository`：6 宏观表 × 2 方法（upsert_* / query_*_by_time）= 12 个 @abstractmethod
  - `RiskRepository`：**get_state(id=1 默认)** / **update_state(new_state, expected_version 乐观锁)** / add_case / query_cases(min_severity 过滤)
  - `ConfigRepository`：get_active_version / activate_version(取消旧激活 = DB 触发器唯一 is_active=1) / get_specific_version / create_version（单调递增）
  - `KnowledgeGraphRepository`：upsert_entity / add_alias / add_triple / **fts_search_entities（近似 BM25 排名）** / query_subgraph_by_entity(N 跳 direction 三向)
- **Added** [connection.py](../dreambuddy_dal/connection.py) — SQLite 连接生命周期：
  - `SQLiteErrorCategory` 5 类（BUSY/CONSTRAINT/CORRUPT/IO_ERROR/OTHER）+ `classify_sqlite_exception()` 关键词映射
  - `@auto_retry_locked(max_retries=3, backoff_ms=(100,300,900))`：指数退避，仅 BUSY 重试，UNIQUE/CORRUPT/IO 直通不重试；支持 @ 无括号和 @(params) 两种装饰语法
  - `get_sqlite_connection(db_path)` 上下文管理器：**8 PRAGMA（journal_mode=WAL / foreign_keys=ON / busy_timeout=5000 / synchronous=NORMAL 4 critical + temp_store=MEMORY/mmap=256MB/cache_size=-20000/soft_heap_limit=128MB 4 perf）**，critical 4 条回读断言失败立刻抛 AssertionError
  - `Decimal` TEXT 适配：`sqlite3.register_adapter(Decimal, str)` + `register_converter("DECIMAL")`，避免 REAL 精度丢失
- **Added** [di.py](../dreambuddy_dal/di.py) — 6 工厂函数依赖注入：
  - 后端选择 3 级优先级：**1) `$DATA_DIR/DISABLE_DAL_NEW` 物理文件（最高，强制 json_legacy）** → 2) backend=显式参数 → 3) DB_BACKEND 环境变量（默认 json_legacy）
  - 线程安全单例：`_lock + _INSTANCES[(backend,repo_type)]` 双重检查锁
  - P0 期 sqlite_unified/dual_write 两后端抛 `NotImplementedError`（含明确 P1 启用提示）；非法后端抛 `ValueError` 枚举 3 值
  - 包 [dreambuddy_dal/__init__.py](../dreambuddy_dal/__init__.py) 顶层 re-export：6 工厂函数 / 6 Protocol / 12 数据模型枚举（消费方唯一导入入口）
- **Added** [compat.py](../dreambuddy_dal/compat.py) — 兼容层懒转发：
  - Python 3.7+ 模块级 `__getattr__`：**真正访问符号才触发 DeprecationWarning（每符号仅一次）**，不是模块加载就警告
  - 所有符号 `is dreambuddy_dal.unified_models.TradeRecord`（类型完全等价，不是山寨类）
  - `LEGACY_TRADE_RECORD_SYMBOLS` 注册表：已登记 dreambuddy_dal.compat.TradeRecord，2026-09-30 清理截止
- **Added** 6 个 JsonLegacyImpl 薄适配器（P0 内存实现；P1 接真实 JSON/散库）：
  - [json_legacy/trade_impl.py](../dreambuddy_dal/implementations/json_legacy/trade_impl.py)：幂等 add_trade / close_position 改 status=CLOSED / query_trades 多条件链式筛选
  - [json_legacy/position_impl.py](../dreambuddy_dal/implementations/json_legacy/position_impl.py)：position_id 稳定生成；get_position 同 symbol 多子系统抛 ValueError 不歧义
  - [json_legacy/market_macro_impl.py](../dreambuddy_dal/implementations/json_legacy/market_macro_impl.py)：6 宏观列表 append + 时间窗口全扫
  - [json_legacy/risk_impl.py](../dreambuddy_dal/implementations/json_legacy/risk_impl.py)：乐观锁 version+1（Python 层模拟 DB 触发器）；query_cases severity 过滤
  - [json_legacy/config_impl.py](../dreambuddy_dal/implementations/json_legacy/config_impl.py)：单调递增版本号；activate_version 自动取消旧激活（全局唯一 is_active=1）
  - [json_legacy/kg_impl.py](../dreambuddy_dal/implementations/json_legacy/kg_impl.py)：别名累积；FTS 近似字符串匹配 BM25 分近似排名；N 跳子图 BFS（direction 三向 min_confidence 过滤）

### Changed（最小侵入接入，不破坏生产）
- **Changed** 根 [conftest.py](/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/conftest.py) SUBMODULES：加入 `"19-数据访问层"`（全局 pytest 可 `import dreambuddy_dal`，无需单独 sys.path 插入）
- **Changed** 根 [pyproject.toml](/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/pyproject.toml) `[tool.ruff.lint.isort]` known-first-party：加入 `"dreambuddy_dal"`（与 dreamos 并列一等公民）
- **Changed** [polling_trader.py](/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py) 模块头部 docstring：新增 DAL 接入点注释（P1 后 `from dreambuddy_dal import get_trade_repo, get_position_repo, get_risk_repo`），不修改任何运行时逻辑
- **Changed** [v15_trader.py](/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/core/v15_trader.py) 模块头部 docstring：新增 DAL 接入点注释（P1 后 `from dreambuddy_dal import get_trade_repo, get_position_repo, get_config_repo`），不修改任何运行时逻辑
- **Changed** [trading_utils.py](/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/trading_utils.py) 模块 docstring：新增 Experience 698940 Deprecation 注释，截止 2026-09-30，附 SCHEMA_DESIGN.md SSoT 链接

### Deprecated（5 处独立 TradeRecord 定义，2026-09-30 清理）
- **Deprecated** `11-易经推理系统/scripts/memory_l4/trading_utils.py::TradeRecord`（字段：coin / float price / pnl_pct 等 → 与 SSoT drift 23+ 处，切 `dreambuddy_dal.unified_models.TradeRecord`）
- **Deprecated** `1-ARCHITECTURE/dreamos/cli/dreamos_backtester.py::TradeRecord`（下次 P1 接入时同步替换）
- **Deprecated** `11-易经推理系统/scripts/memory_l4/yijing_trainer.py::TradeRecord`（下次 P1 接入时同步替换）
- **Deprecated** `1-ARCHITECTURE/dreamos/capabilities/trading/backtest/engine.py::TradeRecord`（下次 P1 接入时同步替换）
- **Deprecated** `experiments/ab-trading/core/dual_channel/ab_comparison.py::TradeRecord`（下次 P1 接入时同步替换）

### 经验教训落实
- Experience 698940：统一出口 `from dreambuddy_dal import TradeRecord` + compat.py DeprecationWarning 懒转发 + 2026-09-30 截止日期
- Experience 1040063：SCHEMA_DESIGN 中已冻结 CREATE TABLE 最终 Schema + _add_column_if_missing helper 4 入口契约（P1 schema_init.py 将严格实现）
- Project Memory XAG 轻仓试错：TradeRecord.is_trial / trial_status / trial_open_ts / trial_eval_done / trial_eval_result 5 列全进 tr_trades；PositionState.is_trial 冗余便于持仓快查

---

## [v1.0.0] — 2026-08-24

> 📌 **里程碑**: 文档阶段完成（架构设计 + Schema 设计 + 迁移计划全部书面冻结，等待 PM 批准代码落地）。代码层无变更（无实现）。

### 文档新增（三件套 + 2 索引 + 入口 README）
- **Added**: [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) v1.0 —— 8 章节完整覆盖：
  - §0 文档范围/SSoT 层级/关键术语表
  - §1 4 大痛点量化 + 5 SMART 设计目标 + 5 设计原则（黄金约束 4 条）+ YAGNI 非目标
  - §2 四层架构图 + 6 Repository 完整方法签名协议 + DualWrite 装饰器对账算法 + 1 库 7 域前缀分区 + 18-数据采集中心边界
  - §3 9 周 P0-P4 路线图 + 三批迁移 ROI 顺序 + 5 项人工门禁 Checklist + 5 场景回滚 RTO
  - §4 Fail-Closed / Fail-Open 矩阵 + 5 类 SQLite 异常分类 + auto_retry_locked 退避 + 结构化日志规范 + Kill-Switch 物理双保险
  - §5 TDD 测试金字塔（单元 60% / 集成 25% / 迁移 10% / 故障注入 5%）+ 性能基线 3 条
  - §6 Cron 三件套（backup/integrity/rotate）+ 三级数据生命周期（热/冷/归档）+ Alembic SemVer 迁移链
  - §7 PG 触发 5 条件 + 切换流程 + 方言兼容层设计
  - §8 ADR-19-001 ~ ADR-19-005（5 条架构决策记录，含理由/反对理由/缓解措施）
- **Added**: [SCHEMA_DESIGN.md](./SCHEMA_DESIGN.md) v1.0 —— 7 域 × 21 张表完整字段字典：
  - PRAGMA 8 条连接参数 + 断言验证脚本
  - ma_ 审计域（3 表：schema_version / migration_audit / integrity_log）
  - tr_ 交易域（3 表：trades / daily_stats / daily_stats_overrides）
  - po_ 持仓域（2 表：positions / price_refresh_log）
  - mm_ 宏观域（6 表：fear_greed / funding / open_interest / liquidation / long_short_ratio / taker_volume，5 张 WITHOUT ROWID 覆盖索引）
  - rs_ 风控域（2 表：state 单行表 CHECK(id=1) + cases）含 rs_state UPDATE 自动刷时间戳/乐观锁触发器 + cv_config_versions 全局唯一激活版本触发器
  - kg_ 知识图谱域（4 表：entities / aliases / triples + FTS5 全文索引）
  - 22 个索引总览表 + EXPLAIN QUERY PLAN 性能回归断言脚本
  - migration_helpers（4 个统一补列/补索引/重建表/单例行函数）契约
- **Added**: [MIGRATION_PLAN.md](./MIGRATION_PLAN.md) v1.0 —— 可执行级 SOP：
  - §0 迁移前准备（Day -1）：5 项冷备份/磁盘/依赖预检 + 3 个数据质量修复脚本（坏 JSON / 必填缺失 / 重复 ID）
  - §1 P0 基建 5 天逐天 RACI + 验证 + 回滚动作
  - §2 P1 三批 import SOP（precheck → 事务导入 → 独立对账）+ DualWrite 接入生产 5 步 SOP
  - §3 P2 5 项门禁 Checklist（双人签字）+ 切读 SOP + 断旧写 SOP + Alembic 首版接入
  - §4 P3 Cron 三件套 launchd plist 完整 XML + 串行脚本 + 历史归档 AES256 加密 SHA256 流程
  - §5 P4 PG 触发 pgloader 迁移脚本骨架
  - §6 周级 RACI 矩阵（9 周全流程）
- **Added**: [README.md](../README.md) 入口导航：文档金字塔 + 阶段看板 + 环境变量速查 + 兄弟系统边界 + 参考依据
- **Added**: [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) v1.0 文件级索引：完整文件树结构 + 6 个依赖注入入口签名 + 5 个环境变量配置表 + 5 个典型症状 DR 排障路径 + 自检 6 条命令 + 文件快查 13 行索引表

### 决策记录
- **ADR-19-001（架构选型）**: 选 SQLite 统一库而非直接 PG（写并发 < 1/s；运维成本 PG=SQLite×10；协议层预留切换 3 人日成本）
- **ADR-19-002（实现风格）**: Repository Protocol + 原生 sqlite3，不引入 ORM（项目"代码驱动"偏好；精确控制 WITHOUT ROWID 复合索引）
- **ADR-19-003（单库 vs 3 库）**: 1 库 + 表名前缀分区（备份极简；跨域 JOIN 可用；PRAGMA 一处设置）
- **ADR-19-004（双写/断旧写节奏）**: 双写 ≥ 2 周 + 切读后再双写 14 天（覆盖加密货币周内周期性模式）
- **ADR-19-005（Schema 演进策略）**: CREATE TABLE = 最终目标 Schema + 幂等 helper 补列（避免新库/旧库双路径 Schema 漂移，源自 Experience 1040063 失败教训）

### 已知限制 / 未来工作
- 当前为纯文档阶段，代码层（dreambuddy_dal/ / scripts/ / tests/）文件树待 P0 启动后创建
- PostgreSQL 桥接（P4）待 5 触发条件任意 1 条真实成立时再启动

---

## 格式说明（提交 CHANGELOG 时必填）

每个版本条目按下列格式填写组内项：

```
### 类型标签（增/删/改/弃/修/安全）
- **影响范围**: 一句话描述（涉及的文件/模块）
  - 关联 Issue / Spec 链接
  - Schema 影响（若有）：MAJOR / MINOR / PATCH，并说明对应 Alembic revision
```

**类型标签**：
- `Added` — 新功能 / 新表 / 新索引 / 新 Repo 方法
- `Changed` — 行为变更（兼容范围内）/ 性能优化
- `Deprecated` — 即将移除的功能，附移除日期（如 2026-09-30）
- `Removed` — 已移除的功能
- `Fixed` — Bug 修复（附复现条件 + 修复后验证）
- `Security` — 安全相关修复（如：注入风险 / 默认权限过宽）

> **版本冻结原则**：每一个 [vx.y.z] 条目**写入后不再修改**；追加改动写在新的 Unreleased → 下次发版时汇总。严禁追溯修改已发布版本条目。
