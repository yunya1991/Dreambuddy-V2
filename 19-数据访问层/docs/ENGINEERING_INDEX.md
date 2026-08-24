# 19-数据访问层 工程索引

> **版本**: v3.0 | **日期**: 2026-08-24
> **状态**: P0→P3 全阶段交付完成（136 tests GREEN）
> **定位**: 本子系统文件级入口索引（找文件、找运行入口、找配置）
> **上一级索引**: 根目录 [ENGINEERING_INDEX.md](../ENGINEERING_INDEX.md) v3.0（全项目工程入口）
> **子系统 SSoT**: [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) v1.0

---

## 0. 使用规则（强制）

### 0.1 变更流程（对齐根工程索引 §0.1）

任何功能修改/扩展遵循：
1. **先读本文件** → 定位入口文件
2. **再读 TECHNICAL_DESIGN.md** → 确认设计/原则/非目标
3. **出方案**（影响范围、接口变更、验收、回滚）
4. **改代码 → 跑测试 → 验收 → 追加 CHANGELOG.md**

### 0.2 本索引权威边界（SSoT 层级内）

| 层级 | 文档 | 权威范围 |
|---|---|---|
| L1 | TECHNICAL_DESIGN.md v1.0 | 架构 / 机制 / 原则最高 |
| L1 | SCHEMA_DESIGN.md v1.0 | 表 / 字段 / 索引权威 |
| L1 | MIGRATION_PLAN.md v1.0 | 迁移 SOP / 门禁 / 回滚权威 |
| **L2** | **本文件（ENGINEERING_INDEX.md）** | **文件级导航 / 入口查找** |
| L2 | CHANGELOG.md | 代码级变更追踪（P0→P3 全阶段记录） |
| L3 | 内联 docstring | 函数级细节 |

### 0.3 阶段交付总览

| 阶段 | 状态 | 核心交付 | 测试数 |
|---|---|---|---|
| P0 | ✅ DONE | 4 dataclass SSoT + 6 Protocol + connection PRAGMA + di 三后端框架 + JsonLegacy × 6 + 消费方注释接入 | 52 |
| P1 | ✅ DONE | 21 表 Schema + 6 SqliteRepo + di dual_write 激活 + 三批 Import 幂等 + 消费方真实双写 | 53 |
| P2 | ✅ DONE | audit_summary + Shadow Read + gate_check G-1~G-5 + Alembic 首版迁移链 | 19 |
| P3 | ✅ DONE | backup AES256 + integrity + rotate + cron_runner CLI + 3 launchd plist | 12 |
| **合计** | **全完工** | | **136 GREEN** |

---

## 1. 子系统文件结构总览

```
19-数据访问层/
├── README.md                              # 入口导航（文档金字塔 + 阶段 + 环境变量）
│
├── docs/                                  # 文档三件套 + 索引 + 变更日志
│   ├── TECHNICAL_DESIGN.md                # ⭐ 架构设计（§0-§8 全文）v1.0
│   ├── SCHEMA_DESIGN.md                   # ⭐ 21 表字段字典 + 20 索引 + 4 触发器
│   ├── MIGRATION_PLAN.md                  # ⭐ 迁移 SOP + 5 项门禁 Checklist
│   ├── ENGINEERING_INDEX.md               # 本文件（L2 文件级索引）
│   └── CHANGELOG.md                       # 变更日志（P0→P3 全阶段记录）
│
├── dreambuddy_dal/                        # ⭐ Python 包主目录
│   ├── __init__.py                        # 对外公开：from dreambuddy_dal import get_trade_repo
│   ├── unified_models.py                  # ★ SSoT 唯一数据模型出口（TradeRecord 等 4 类 + 6 enums）
│   ├── connection.py                      # SQLite 连接生命周期（PRAGMA 8 条 + auto_retry_locked）
│   ├── di.py                              # 依赖注入入口（三后端 + Kill-Switch + DualWrapper shadow read）
│   ├── compat.py                          # 旧 TradeRecord 兼容导入（DeprecationWarning）
│   ├── cron_runner.py                     # P3 Cron 三件套 CLI（backup/integrity/rotate/checkpoint）
│   │
│   ├── protocols/                         # 6 个 Repository Protocol（ABC）
│   │   ├── __init__.py
│   │   ├── trade_repo.py                  # TradeRepository Protocol
│   │   ├── position_repo.py               # PositionRepository Protocol
│   │   ├── market_macro_repo.py           # MarketMacroRepository Protocol
│   │   ├── risk_repo.py                   # RiskRepository Protocol
│   │   ├── config_repo.py                 # ConfigRepository Protocol
│   │   └── kg_repo.py                     # KnowledgeGraphRepository Protocol
│   │
│   ├── implementations/                   # 2 种实现（按 DB_BACKEND 选）
│   │   ├── json_legacy/                   # P0 现状薄适配（接入现有 JSON / 散库）
│   │   │   ├── __init__.py
│   │   │   ├── trade_impl.py              # JsonLegacyTradeRepository
│   │   │   ├── position_impl.py            # JsonLegacyPositionRepository
│   │   │   ├── market_macro_impl.py       # JsonLegacyMarketMacroRepository
│   │   │   ├── risk_impl.py               # JsonLegacyRiskRepository
│   │   │   ├── config_impl.py             # JsonLegacyConfigRepository
│   │   │   └── kg_impl.py                # JsonLegacyKnowledgeGraphRepository
│   │   │
│   │   └── sqlite_unified/               # 统一 dreambuddy_core.db 实现
│   │       ├── __init__.py                # re-export schema_init + 6 Repo + import_runner
│   │       ├── schema_init.py             # 21 表 + 20 索引 + 4 触发器 + 4 migration_helpers
│   │       ├── trade_impl.py              # SqliteTradeRepository（6 方法 + Decimal→TEXT）
│   │       ├── position_impl.py           # SqlitePositionRepository（upsert + version 自增）
│   │       ├── risk_impl.py               # SqliteRiskRepository（乐观锁 expected_version）
│   │       ├── market_macro_impl.py       # SqliteMarketMacroRepository（12 方法）
│   │       ├── config_impl.py             # SqliteConfigRepository（activate_version 单例触发器）
│   │       ├── kg_impl.py                # SqliteKnowledgeGraphRepository（FTS5 BM25 + BFS N 跳）
│   │       ├── import_runner.py           # P1 三批 Import 幂等脚本（INSERT OR IGNORE + ma_migration_audit）
│   │       ├── audit_summary.py           # P2 门禁测量引擎（G-1 双写差异率 + G-3 影子读一致率）
│   │       ├── gate_check.py              # P2 五项门禁一键检查（G-1~G-5 → all_pass）
│   │       ├── backup.py                  # P3 全量备份（VACUUM INTO + SHA256 + AES256-GCM）
│   │       ├── integrity.py               # P3 PRAGMA integrity_check + ma_integrity_log
│   │       └── rotate.py                  # P3 WAL checkpoint + 备份轮转保留 N 份
│   │
│   └── migrations/                        # Alembic 迁移链（P2 接入）
│       ├── __init__.py
│       ├── alembic.ini                    # version_table=ma_schema_version
│       ├── env.py                         # SQLAlchemy engine + PRAGMA 4 条事件注入
│       └── versions/
│           ├── __init__.py
│           └── 0001_v1_initial_schema.py  # 首版 revision（DDL 从 schema_init 引入，单一事实源）
│
├── launchd/                               # P3 macOS launchd plist 模板
│   ├── com.dreambuddy.dal.backup.plist    # 每天 04:00 全量备份
│   ├── com.dreambuddy.dal.integrity.plist # 每 6 小时完整性检查
│   └── com.dreambuddy.dal.rotate.plist    # 每天 05:00 备份轮转
│
└── tests/                                 # TDD 测试（136 tests GREEN）
    ├── conftest.py                        # SUBMODULES 注册
    ├── test_di_p1.py                      # P1 di.py dual_write + Kill-Switch（5 GREEN）
    ├── protocols/
    │   └── test_protocols.py              # 6 Protocol 层 15 GREEN
    ├── compat/
    │   └── test_di_and_compat.py          # 旧 import DeprecationWarning 兼容
    ├── unified_models/
    │   └── test_models.py                 # 数据模型序列化/反序列化 16 GREEN
    └── implementations/sqlite_unified/
        ├── test_schema_init.py            # 21 表 + 幂等性 + 种子 12 GREEN
        ├── test_trade_repo.py             # SqliteTradeRepository 8 GREEN
        ├── test_position_risk_repo.py     # Position + Risk 8 GREEN
        ├── test_other_repos.py            # MarketMacro + Config + KG 12 GREEN
        ├── test_import_runner.py          # 三批 Import 幂等 4 GREEN
        ├── test_audit_summary.py          # G-1/G-3 测量引擎 6 GREEN
        ├── test_shadow_read.py            # Shadow Read + next_gen 切读 4 GREEN
        ├── test_gate_check.py             # G-1~G-5 五项门禁 6 GREEN
        ├── test_alembic.py                # Alembic upgrade head 3 GREEN
        ├── test_backup.py                 # 备份 + AES256 roundtrip 4 GREEN
        ├── test_integrity.py              # PRAGMA integrity_check 4 GREEN
        ├── test_rotate.py                 # WAL checkpoint + 轮转 4 GREEN
        └── test_connection.py            # PRAGMA + auto_retry 12 GREEN
```

---

## 2. 运行入口 & 调度

> 本子系统是**基础设施服务层**（非独立进程），被其他业务模块 `import` 调用。没有自己的主进程，但有 3 个 Cron 运维任务。

### 2.1 依赖注入入口（业务代码唯一入口）

所有业务代码（polling_trader / V15 / 风控 / 18 数据采集）**必须**通过下列函数取 Repository 实例（永不直连 `sqlite3.connect` / `json.load`）：

```python
from dreambuddy_dal import (
    get_trade_repo, get_position_repo, get_market_macro_repo,
    get_risk_repo, get_config_repo, get_kg_repo,
)

# 示例（易经推理开仓后写入）
trade_repo = get_trade_repo()  # 按 DB_BACKEND 环境变量自动选 json_legacy/dual_write/sqlite_unified
trade_repo.add_trade(my_trade_record)
```

| 入口函数 | 文件 | 对应 Protocol | 典型调用方 |
|---|---|---|---|
| `get_trade_repo()` | `dreambuddy_dal/di.py` | TradeRepository | 易经推理（register_trade_to_l4 双写）/ V15（_dal_write_martin_trade_if_enabled 双写） |
| `get_position_repo()` | 同上 | PositionRepository | 易经推理 / V15 |
| `get_market_macro_repo()` | 同上 | MarketMacroRepository | **18-数据获取中心**（写）+ 易经推理（读） |
| `get_risk_repo()` | 同上 | RiskRepository | 13-通用风控 |
| `get_config_repo()` | 同上 | ConfigRepository | 各策略加载 baseline |
| `get_kg_repo()` | 同上 | KnowledgeGraphRepository | CBR 记忆 / 知识线 / DreamOS KG |

### 2.2 消费方双写接入点（P1 落地）

| 消费方 | 文件 | 接入函数 | 触发条件 |
|---|---|---|---|
| 易经推理 | `11-易经推理系统/scripts/memory_l4/trading_utils.py` | `_dal_write_trade_if_enabled()` | `DB_BACKEND ∈ {dual_write, sqlite_unified}` |
| V15 马丁 | `14-V15经典马丁策略/core/v15_trader.py` | `_dal_write_martin_trade_if_enabled()` | 同上 |

> 两处均为 **Fail-Open**：DAL 写入失败只 `logger.warning`，不阻塞 L4 Case 注册。

### 2.3 定时任务（P3 落地）

| 任务 | launchd plist | CLI 子命令 | 频率 | 说明 |
|---|---|---|---|---|
| 全量备份 | `com.dreambuddy.dal.backup.plist` | `cron_runner backup` | **每日 04:00** | VACUUM INTO + SHA256 + AES256-GCM |
| 完整性检查 | `com.dreambuddy.dal.integrity.plist` | `cron_runner integrity` | **每 6 小时**（00:30/06:30/12:30/18:30） | PRAGMA integrity_check + ma_integrity_log |
| 备份轮转 | `com.dreambuddy.dal.rotate.plist` | `cron_runner rotate` | **每日 05:00** | 保留最新 7 份，删除其余 |
| WAL Checkpoint | — | `cron_runner checkpoint` | 按需 | PRAGMA wal_checkpoint(TRUNCATE) |

> 部署：`cp launchd/com.dreambuddy.dal.*.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.dreambuddy.dal.*.plist`
> 卸载：`launchctl unload ~/Library/LaunchAgents/com.dreambuddy.dal.*.plist`

---

## 3. 配置落地点（排障先看）

### 3.1 环境变量（全清单）

| 变量 | 默认值 | 影响范围 | 紧急修改生效方式 |
|---|---|---|---|
| `DB_BACKEND` | `json_legacy` | 所有 6 Repo 后端实现（json_legacy / dual_write / sqlite_unified） | 修改 env 后重启进程 |
| `READ_SOURCE` | （未设=legacy） | DualWrapper 读路径：`shadow`=双读比对+审计；`next_gen`=读走新库 | 同上 |
| `DATA_DIR` | `./data` | 库文件 / 备份 / 日志 / Kill-Switch 根 | 同上；需保证目录存在且可写 |
| `DAL_DB_PATH` | `$DATA_DIR/dreambuddy_core.db` | 统一库路径（测试可覆盖） | 同上 |
| `BACKUP_DIR` | `$DATA_DIR/backups` | 备份输出目录 | 同上 |
| `BACKUP_PASSPHRASE` | （未设=明文） | AES256-GCM 加密口令 | 同上 |
| `BACKUP_KEEP` | `7` | 轮转保留份数 | 同上 |

### 3.2 Kill-Switch 物理文件

| 路径 | 存在含义 | 优先级 | 快速创建（紧急切 json_legacy） |
|---|---|---|---|
| `$DATA_DIR/DISABLE_DAL_NEW` | 忽略 DB_BACKEND 强制走 json_legacy | **最高**（高于任何 env） | `touch $DATA_DIR/DISABLE_DAL_NEW`（进程下一次 di.py 初始化时生效；无需重启） |

### 3.3 数据 & 日志路径

| 路径（相对 $DATA_DIR） | 内容 | 备份策略 |
|---|---|---|
| `dreambuddy_core.db` | **主库文件**（核心） | 04:00 每日 VACUUM INTO + AES256 加密 |
| `dreambuddy_core.db-wal` | WAL 预写日志（运行期） | 备份前自动 checkpoint，不单独保存 |
| `dreambuddy_core.db-shm` | WAL 共享内存文件（运行期） | 不备份（临时） |
| `backups/` | 每日备份（.db / .enc + .sha256 sidecar） | 保留最新 7 份，异地额外 1 份 |
| `logs/dal_*.jsonl` | DAL 层结构化日志（WARN+） | 保留 90 天 |
| `archive/` | 迁移前 JSON/旧库归档 | 永久（SHA256 校验同步存） |

---

## 4. 故障排查入口（DR 快速定位）

| 症状 | 第一动作 → 第二动作 → 第三动作 | 相关文档 |
|---|---|---|
| 业务日志大量出现 `database is locked` | ① `ls $DATA_DIR/DISABLE_DAL_NEW` 确认没切 → ② `lsof dreambuddy_core.db` 看连接数 → ③ `touch $DATA_DIR/DISABLE_DAL_NEW` 切 json_legacy | TECHNICAL_DESIGN §4.2 |
| DualWrite `next_gen_write_fail` 暴增 | ① `grep next_gen_write_fail logs/dal_*.jsonl \| head -5` → ② 跑 `cron_runner integrity` → ③ 若 corrupt = 切 json_legacy + 从最近备份还原 | MIGRATION_PLAN §3.3 |
| 完整性检查告警 | ① Kill-Switch 切 json_legacy → ② `cron_runner integrity` 看详情 → ③ `sqlite3 .recover` 从备份恢复 | TECHNICAL_DESIGN §3.5 |
| 备份目录 7 天无新文件 | ① `cat /tmp/dreambuddy_dal_backup.err` 看 Cron 错误 → ② `launchctl list \| grep dreambuddy` 看 plist 状态 → ③ 手动 `python -m dreambuddy_dal.cron_runner backup` | MIGRATION_PLAN §4.1 |
| 影子读一致率 < 99.99% | ① 确认 `READ_SOURCE=shadow` → ② 跑 `gate_check` 看 G-3 详情 → ③ 延长观察期不切读 | MIGRATION_PLAN §3.1 G-3 |

---

## 5. 改动后自检命令清单

```bash
# ====== 全量 TDD 回归（P0→P3，136 tests）======
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
python -m pytest 19-数据访问层/ -q
# 最低门槛：0 failed；136 passed

# ====== 分层单跑 ======
# P0：models + protocols + connection + di + compat
python -m pytest 19-数据访问层/tests/unified_models/ 19-数据访问层/tests/protocols/ 19-数据访问层/tests/compat/ 19-数据访问层/tests/implementations/sqlite_unified/test_connection.py 19-数据访问层/tests/test_di_p1.py -q

# P1：schema + 6 Repo + import
python -m pytest 19-数据访问层/tests/implementations/sqlite_unified/test_schema_init.py 19-数据访问层/tests/implementations/sqlite_unified/test_trade_repo.py 19-数据访问层/tests/implementations/sqlite_unified/test_position_risk_repo.py 19-数据访问层/tests/implementations/sqlite_unified/test_other_repos.py 19-数据访问层/tests/implementations/sqlite_unified/test_import_runner.py -q

# P2：门禁 + Shadow Read + Alembic
python -m pytest 19-数据访问层/tests/implementations/sqlite_unified/test_audit_summary.py 19-数据访问层/tests/implementations/sqlite_unified/test_shadow_read.py 19-数据访问层/tests/implementations/sqlite_unified/test_gate_check.py 19-数据访问层/tests/implementations/sqlite_unified/test_alembic.py -q

# P3：backup + integrity + rotate
python -m pytest 19-数据访问层/tests/implementations/sqlite_unified/test_backup.py 19-数据访问层/tests/implementations/sqlite_unified/test_integrity.py 19-数据访问层/tests/implementations/sqlite_unified/test_rotate.py -q

# ====== Lint ======
python -m ruff check 19-数据访问层/ --fix

# ====== Alembic 迁移 ======
cd 19-数据访问层
DAL_DB_PATH=./data/dreambuddy_core.db python -m alembic -c dreambuddy_dal/migrations/alembic.ini upgrade head
DAL_DB_PATH=./data/dreambuddy_core.db python -m alembic -c dreambuddy_dal/migrations/alembic.ini current
```

> 所有命令执行 **无红色 FAIL** 后，方可提交 PR / 合 main。

---

## 6. 文件级快速索引表（Find "xxx" 去哪找？）

| 你想找什么 | 位置（相对本子系统根） | 权威章节 / 函数名 |
|---|---|---|
| Repository 接口协议（方法签名） | `dreambuddy_dal/protocols/*.py` | TECHNICAL_DESIGN §2.2 |
| TradeRecord 字段定义（唯一出口） | `dreambuddy_dal/unified_models.py` | SCHEMA_DESIGN §3.1 tr_trades |
| SQLite PRAGMA 配置（WAL / FK / busy_timeout） | `dreambuddy_dal/connection.py` | SCHEMA_DESIGN §0.2 |
| Schema 初始化（21 表 + 20 索引 + 4 触发器） | `dreambuddy_dal/implementations/sqlite_unified/schema_init.py` | SCHEMA_DESIGN §2~§8 |
| 6 个 SqliteRepository 实现 | `dreambuddy_dal/implementations/sqlite_unified/*_impl.py` | — |
| 三批 Import 幂等脚本 | `dreambuddy_dal/implementations/sqlite_unified/import_runner.py` | MIGRATION_PLAN §2.2 |
| G-1/G-3 门禁测量引擎 | `dreambuddy_dal/implementations/sqlite_unified/audit_summary.py` | MIGRATION_PLAN §3.1 |
| G-1~G-5 五项门禁一键检查 | `dreambuddy_dal/implementations/sqlite_unified/gate_check.py` | MIGRATION_PLAN §3.1 |
| Shadow Read / next_gen 切读 | `dreambuddy_dal/di.py` `_DualWrapper` | MIGRATION_PLAN §3.2 |
| Alembic 首版迁移 | `dreambuddy_dal/migrations/versions/0001_v1_initial_schema.py` | TECHNICAL_DESIGN §6.3 |
| 全量备份 + AES256 加密 | `dreambuddy_dal/implementations/sqlite_unified/backup.py` | MIGRATION_PLAN §4.1 |
| PRAGMA 完整性检查 | `dreambuddy_dal/implementations/sqlite_unified/integrity.py` | MIGRATION_PLAN §4.2 |
| WAL checkpoint + 备份轮转 | `dreambuddy_dal/implementations/sqlite_unified/rotate.py` | MIGRATION_PLAN §4.3 |
| Cron 三件套 CLI 入口 | `dreambuddy_dal/cron_runner.py` | — |
| launchd plist 模板 | `launchd/com.dreambuddy.dal.*.plist` | MIGRATION_PLAN §4.1 |
| 消费方双写接入（易经） | `11-易经推理系统/scripts/memory_l4/trading_utils.py` `_dal_write_trade_if_enabled` | — |
| 消费方双写接入（V15） | `14-V15经典马丁策略/core/v15_trader.py` `_dal_write_martin_trade_if_enabled` | — |
| 旧 TradeRecord 兼容导入 | `dreambuddy_dal/compat.py` | — |
| 经验教训 ADR | `docs/TECHNICAL_DESIGN.md` §8 ADR-19-001 ~ 19-005 | ADR 全 5 条 |
| 未来 PostgreSQL 切换条件 | `docs/TECHNICAL_DESIGN.md` §7.1 PG 5 触发条件表 | ADR-19-001 |

---

## 7. 后续待办（非阻塞）

| 待办 | 截止 | 关联 |
|---|---|---|
| 5 处 Deprecated TradeRecord 定义清理 | 2026-09-30 | compat.py DeprecationWarning |
| 历史 JSON 归档 AES256 加密 | P3 后 | MIGRATION_PLAN §4.4 |
| G-4 回滚演练现场执行 | 切读前 | gate_check G-4 手动传入 |
| G-5 冷备份异地副本验证 | 切读前 | gate_check G-5 backup_db_path |
| DualWrite 14 天观察期 | 切读后 | MIGRATION_PLAN §3.3 |

---

> **维护原则**：
> 1. 文件新增 / 删除 / 改名 **必须同步更新本索引**（第 1 节文件树 + 第 6 节快速索引表）
> 2. 新接入消费方（新业务模块 import DAL）**必须同步更新 §2.1/§2.2** + 根工程 ENGINEERING_INDEX
> 3. 任何环境变量变动必须同步：§3.1 环境变量表 + [README.md](../README.md) 环境变量速查表
