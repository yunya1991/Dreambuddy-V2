# 19-数据访问层 · 迁移执行计划 SOP

> **版本**: v1.0 | **日期**: 2026-08-24
> **权威等级**: L1（迁移步骤唯一事实源），对齐 [TECHNICAL_DESIGN.md §3](./TECHNICAL_DESIGN.md#3-实施路线图与迁移步骤9-周可度量可回滚)
> **关联 ADR**: ADR-19-004（双写 2 周 + 断旧写延迟 2 周） / ADR-19-005（CREATE = 最终 Schema + helper 补列）
> **回滚总原则（GC1）**：任何阶段，`export DB_BACKEND=json_legacy` 重启进程 = 10 秒回滚。绝不裸操作，每步都有显式撤销动作。

---

## 0. 迁移前准备（P0 之前必须全部打勾 ✅）

### 0.1 环境与备份（Day -1，迁移前一天）

| # | 检查项 | 执行命令 / 方法 | 通过标准 | 确认 ▢ |
|---|---|---|---|---|
| 1 | **完整冷备份快照**（黄金约束 GC4 = 迁移的安全垫） | ```tar -czf backup/pre_migration_snapshot_20260824.tar.gz \
  11-易经推理系统/artifacts/*.json* \
  11-易经推理系统/scripts/memory_l4/data/*.json* \
  11-易经推理系统/scripts/memory_l4/*.db \
  14-V15经典马丁策略/data/*.json* \
  10-经典指标系统/user_data/*.json* \
  data/backups/ 2>/dev/null
mv backup/pre_migration_*.tar.gz backup/pre_migration_snapshot_AES256.tar.gz
# 加密（可选但推荐）：openssl enc -aes-256-cbc -salt -in ... -out ...``` | SHA256 校验和记录；tar -tzf 无缺失 | ▢ |
| 2 | **磁盘剩余空间 ≥ 5× 当前 JSON+DB 总和** | `df -h /path/to/data` | 剩余 ≥ 10GB（5×备份 + 新库 3GB + 冗余 2GB） | ▢ |
| 3 | **Python 依赖**（Alembic 首版引入） | ```cd 19-数据访问层 && python -c "import alembic, sqlalchemy, sqlite3" && echo OK``` | alembic ≥ 1.12；无 ImportError | ▢ |
| 4 | **全局 Kill-Switch 路径可达**（TECHNICAL_DESIGN §4.4） | ```touch /path/to/data/DISABLE_DAL_NEW && ls -la /path/to/data/DISABLE_DAL_NEW``` | 文件存在；非 root 进程可写目录 | ▢ |
| 5 | **停 30min 观察期**（不做迁移仅观察） | 暂停所有定时任务（`launchctl unload ...`）30 分钟后再启动 | 30 分钟内交易日志 0 笔；确认所有进程能正常停/起 | ▢ |

### 0.2 发现并修复数据质量问题（Day -1，防迁移时炸）

```bash
# 1. 坏 JSON 预检（逐文件）
python scripts/preflight/check_json_integrity.py \
  --paths="11-易经推理系统/artifacts/all_trades.jsonl,11-易经推理系统/artifacts/daily_stats.json,..." \
  --report data/dq_report_before.json

# 2. TradeRecord 必填字段完整性校验（防迁移时 NOT NULL 抛错）
python scripts/preflight/validate_trades_not_null.py \
  --input 11-易经推理系统/artifacts/all_trades.jsonl \
  --required-fields="trade_id,symbol,direction,entry_price,entry_time" \
  --fix=fill_default  # 缺失填默认值，生成 dq_fix_applied_before.log

# 3. 去重（同 trade_id 多行）
python scripts/preflight/dedupe_trade_ids.py \
  --input all_trades.jsonl --keep=latest
```

**必须 0 严重错误后才进入 P1。** 否则先修数据，不继续迁移。

---

## 1. P0 基建与抽象（W1~W2，2.5 人日）—— 代码改动 ≤ 15% 风险

| 日 | 任务 | 产出文件 | 验证命令 | 回滚动作 |
|---|---|---|---|---|
| **W1-D1** | 建 dreambuddy_dal Python 包；写 unified_models.py（4 核心 dataclass SSoT） | `dreambuddy_dal/__init__.py` <br> `dreambuddy_dal/unified_models.py` | `python -c "from dreambuddy_dal.unified_models import TradeRecord; print(TradeRecord.__dataclass_fields__.keys())"` → 50+ 字段全；5 处旧 import 路径测试兼容 | 删 `dreambuddy_dal/` 目录；恢复 5 处旧定义 |
| **W1-D2** | 写 6 个 Protocol（ABC） | `dreambuddy_dal/protocols/*.py`（6 文件） | TDD 跑协议层 `tests/protocols/test_all_repos_have_full_sig.py` | 同上 |
| **W2-D3** | JsonLegacyImpl 6 个实现（薄适配现有代码） | `dreambuddy_dal/implementations/json_legacy/*.py`（6 文件） | 对每个方法：JsonLegacyImpl 返回 vs 原 PerformanceTracker / PositionTracker 同输入结果 md5 匹配 | 同上 |
| **W2-D4** | 写 di.py 依赖注入入口；接入 2 处核心消费（polling_trader.py + V15_trader.py）仅改 import | `dreambuddy_dal/di.py` <br> 改 `polling_trader.py` 2 行 + `v15_trader.py` 2 行 | `DB_BACKEND=json_legacy python polling_trader.py --dry-run` 30 分钟：trade 数量与未接入前一致 | 还原 polling_trader.py + v15_trader.py 到 Git 上一版 |
| **W2-D5** | TDD + 回归 + 兼容导入清理 DeprecationWarning 全打日志 | `tests/compat/` + `tests/unified_models/` | `pytest tests/ -x -q` 100% pass；覆盖率报告 ≥ 92% | 未改任何业务逻辑，回滚 = 还原 2 处 import |

**P0 阶段验收：**
- ✅ 接入 2 天后，`DB_BACKEND=json_legacy` 运行与未接入前完全等价（无新增 Bug，指标无变化）
- ✅ DeprecationWarning 日志中 5 处旧定义被调用次数收敛

---

## 2. P1 统一库 + 首次迁移（W3~W5，3.5 人日）—— 风险最高阶段，每批都有对账门禁

### 2.1 核心文件清单

| 文件 | 职责 |
|---|---|
| `dreambuddy_dal/connection.py` | 连接生命周期管理（PRAGMA 自动执行 + 断言） |
| `dreambuddy_dal/implementations/sqlite_unified/schema_init.py` | 建 21 张表 + migration helpers 补列 |
| `dreambuddy_dal/implementations/sqlite_unified/*.py`（6 文件） | SqliteTradeRepo / ... 等实现 |
| `dreambuddy_dal/implementations/dual_write/*.py`（6 文件 + auditor.py） | DualWrite 装饰器 + ma_migration_audit 写入 |
| `scripts/migration/import_all_from_json.py` | **三批迁移脚本主入口**（核心交付物） |
| `scripts/migration/verify_migration.py` | 三向对账主入口（独立于 import 脚本，防止既当裁判又当运动员） |

### 2.2 三批迁移 SOP（独立事务，失败可单独回滚）

#### ★ Batch 1：最高 ROI（交易 + 每日统计 + 风控 + 持仓）= 解决 80% 痛点

```bash
# ── Step 1：预检查（不写库，只读 JSON）───
python scripts/migration/import_all_from_json.py batch1 \
  --mode=precheck \
  --json-trades="11-易经推理系统/artifacts/all_trades.jsonl,14-V15经典马丁策略/data/v15_trades.jsonl" \
  --json-daily="11-易经推理系统/artifacts/daily_stats.json" \
  --json-risk="11-易经推理系统/artifacts/risk_state.json,13-通用风控模块/data/risk_state.json" \
  --json-positions="11-易经推理系统/artifacts/position_tracker.json,14-V15经典马丁策略/data/v15_positions.json"
# → 输出：预计导入 N 行 / 必填字段缺失率 / 重复 ID 数
# → 通过标准：缺失率 < 0.1%；否则先跑 §0.2 数据质量修复

# ── Step 2：事务导入（原子性）───
python scripts/migration/import_all_from_json.py batch1 \
  --mode=import --db=/path/to/dreambuddy_core.db

# ── Step 3：独立对账（第三方脚本，不用 import 用的内存对象）───
python scripts/migration/verify_migration.py batch1 \
  --sources=$ALL_JSON_PATHS \
  --db=/path/to/dreambuddy_core.db \
  --sample-rate=0.1   # 随机抽 10% 行 md5 比对
# → 通过标准（任一不满足自动 ROLLBACK 并 exit(1)）：
#    COUNT(src.trades) == COUNT(tr_trades)
#    COUNT(src.daily_stats) == COUNT(tr_daily_stats)
#    SAMPLE 10% md5(TradeRecord.json()) = 100% 匹配
#    NOT NULL 列 0 条 NULL
```

#### ★☆ Batch 2：宏观 + 配置版本（中 ROI）

```bash
# 独立事务：Batch1 失败不影响 Batch2，反之亦然
python scripts/migration/import_all_from_json.py batch2 \
  --mode=precheck \
  --macro-dbs="11-易经推理系统/scripts/memory_l4/macro_BTC.db,...,macro_XAG.db(共14)" \
  --config-releases="constraints/releases/v*.json(共258)"
# 通过标准：
#   14×mm_* 表 COUNT 汇总 == 14 个旧 macro_*.db COUNT 之和
#   COUNT(cv_config_versions) == 258
python scripts/migration/import_all_from_json.py batch2 --mode=import
python scripts/migration/verify_migration.py batch2 --sample-rate=0.05  # 宏观抽样 5%
```

#### Batch 3：知识图谱 + 风控案例 + 30 天 polling trader 日志（可晚 1 周）

```bash
# 非核心；KG 数据量大，用 sqlite3 ATTACH 直接拷贝（比 parse 快 50 倍）
python scripts/migration/import_all_from_json.py batch3 \
  --kg-db="11-易经推理系统/scripts/memory_l4/knowledge_graph.db" \
  --risk-cases="13-通用风控模块/data/cases/*.json" \
  --polling-logs="11-易经推理系统/artifacts/trader_*.jsonl" --last-n-days=30
```

### 2.3 DualWrite 装饰器接入生产（W5-D5，周五非高峰时段）

```bash
# 1. 停 3 分钟交易进程
launchctl unload ~/Library/LaunchAgents/com.dreambuddy.polling-trader.plist
launchctl unload ~/Library/LaunchAgents/com.dreambuddy.v15.plist

# 2. 修改 launchd plist 注入环境变量（关键！）
plutil -replace EnvironmentVariables.DB_BACKEND -string "dual_write" \
  ~/Library/LaunchAgents/com.dreambuddy.polling-trader.plist
# 同理 V15 plist

# 3. Kill-Switch 验证（保险动作）
ls -la /path/to/data/DISABLE_DAL_NEW || echo "不存在 = 正常（默认 dual_write）"

# 4. 启动
launchctl load ~/Library/LaunchAgents/com.dreambuddy.polling-trader.plist
launchctl load ~/Library/LaunchAgents/com.dreambuddy.v15.plist

# 5. 30 分钟冒烟测试
tail -f /path/to/data/logs/dal_*.jsonl | grep -E "CRITICAL|next_gen_write_fail"
# → 任何 CRITICAL 立刻执行回滚：
#    launchctl unload → 删 DISABLE_DAL_NEW 反操作 → 还原 DB_BACKEND=json_legacy → load
```

**P1 阶段验收：**
- ✅ Batch1~3 三向对账 100% 匹配（0 行差异）
- ✅ DualWrite 上线后第一个周末（交易量低）`ma_migration_audit`：next_gen_write_fail = 0；severity ≥ ERROR = 0
- ✅ 回滚演练：手动跑 `DB_BACKEND=json_legacy` 30 分钟，行为与 P0 完全一致

---

## 3. P2 生产切流 + 观察（W6~W7，1.5 人日）—— 5 项门禁全打勾才切读

### 3.1 门禁 Checklist（技术负责人 + 执行双人签）

| # | 门禁项 | 测量脚本 | 通过标准 | 负责人 | 确认 |
|---|---|---|---|---|---|
| **G-1** | 双写差异率 < 0.001%（≤1 笔 / 10 万） | `python scripts/ops/audit_summary.py --window=72h --metric=write_diff_rate` | 连续 72h < 0.001% | ▢ | ▢ |
| **G-2** | "database is locked" 0 次 | `grep -i "database is locked" data/logs/trader_*.log data/logs/dal_*.jsonl \| wc -l` | 连续 72h = 0 行 | ▢ | ▢ |
| **G-3** | 影子读一致率 ≥ 99.99% | `python scripts/ops/audit_summary.py --window=72h --metric=read_consistency --enable-shadow-read=1` | 连续 72h ≥ 99.99% | ▢ | ▢ |
| **G-4** | 回滚演练 30 分钟零事故 | **现场操作**：临时切 `DB_BACKEND=json_legacy` 30min → 还原 | 开/平仓 5 笔与 dual_write 完全一致；无文件句柄泄漏 | ▢ | ▢ |
| **G-5** | 冷备份可用性 | `sqlite3 backups/dreambuddy_core_W6.db "PRAGMA integrity_check;"` + `SELECT COUNT(*) FROM tr_trades WHERE entry_time > '2026-08-20'` (抽样 10 条 vs JSON) | integrity = "ok"；抽样 100% 匹配 | ▢ | ▢ |

**G-1 ~ G-5 任意一项不达标 = 不切读，延长 DualWrite 观察期，找根因修复后重新计时。**

### 3.2 切读 SOP（W6 末，周日低波动时段）

```bash
# 前提：G-1~G-5 全勾确认书存档

# 1. 改环境变量：READ_SOURCE=next_gen（DualWrite 内部读取来源切换，仍保留双写！）
plutil -replace EnvironmentVariables.READ_SOURCE -string "next_gen" plist
# DB_BACKEND 仍然是 dual_write（写双份）→ 2 周保险

# 2. 滚动重启（一个进程一个进程切，不一次性停所有）
# → 停 polling_trader 30 分钟 → 启动 → 看 30 分钟日志 → 无异常 → 切 V15
```

### 3.3 断旧写 SOP（W7 末，确认读新 14 天无事故）

```bash
# 断旧写是黄金约束 GC4 的最后一道门，需额外 PM 签字
# 前提：连续 14 天 READ_SOURCE=next_gen 期间 0 CRITICAL
#       + 近 7 天 ma_migration_audit severity ≥ ERROR = 0

# 改环境变量：DB_BACKEND=sqlite（写单份新库，DualWrite 装饰器退出主链路）
plutil -replace EnvironmentVariables.DB_BACKEND -string "sqlite" plist
plutil -remove EnvironmentVariables.READ_SOURCE plist  # 删除冗余

# 滚动重启进程
# 旧 JSON 文件停止写入 → 下一步归档
```

### 3.4 Alembic 首版迁移链接入

```bash
# W6 接入：W1~W5 期间 schema_init.py = 手工 SQL（v1.0 初始版本），之后改动必须 Alembic
cd 19-数据访问层/dreambuddy_dal/migrations/
alembic init alembic        # 首版初始化
alembic revision -m "v1.0_initial_schema_21_tables_22_indexes" --autogenerate=false
# → 自动生成的迁移里空实现；我们手动把 schema_init.py 的 TARGET_CREATE_TABLES_SQL 拷进 upgrade()
#   downgrade() = 对应 DROP TABLE（慎用）
alembic upgrade head        # 首版执行（= 已建好的库打版本戳，无实际建表动作）
```

---

## 4. P3 运维加固 + 历史归档（W8~W9，1.5 人日）

### 4.1 Cron 三件套部署（SOP）

**macOS launchd plist = `com.dreambuddy.db-maintenance.plist`（优于 crontab）**：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>com.dreambuddy.db-maintenance</string>
    <key>ProgramArguments</key><array>
        <string>/bin/bash</string>
        <string>/path/to/scripts/ops/db_maintenance_chain.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key><string>/var/log/dreambuddy/maintenance_stdout.log</string>
    <key>StandardErrorPath</key><string>/var/log/dreambuddy/maintenance_stderr.log</string>
</dict></plist>
```

**Shell 主脚本（scripts/ops/db_maintenance_chain.sh）串行执行三件套（一环失败不跑下一环）**：
```bash
#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# ① 热备份
$SCRIPT_DIR/backup.sh --db=$DB --output=$BACKUP_DIR --keep-days=30
STATUS_BAK=$?

# ② 完整性检查（失败 = Kill-Switch 自动切 json_legacy + 飞书告警）
$SCRIPT_DIR/integrity.sh --db=$DB --log-table=ma_integrity_log --on-fail="touch $DATA_DIR/DISABLE_DAL_NEW"
STATUS_INT=$?
if [ "$STATUS_INT" != "0" ] && [ -f "$DATA_DIR/DISABLE_DAL_NEW" ]; then
  # TODO: 调飞书 webhook CRITICAL 告警（对齐你们现有告警链路）
  curl -s -X POST "https://open.feishu.cn/open-apis/bot/v2/hook/XXXX" \
    -H "Content-Type: application/json" \
    -d '{"msg_type":"text","content":{"text":"[CRITICAL DAL] integrity_check failed，已自动切 json_legacy，请登录排查"}}'
fi

# ③ 备份轮转（压缩 + 过期删）
$SCRIPT_DIR/rotate.sh --backup-dir=$BACKUP_DIR --gzip-after-days=7 --delete-after-days=30
STATUS_ROT=$?

echo "[$(date)] DONE: backup=$STATUS_BAK integrity=$STATUS_INT rotate=$STATUS_ROT"
```

### 4.2 历史 JSON/旧库归档

```bash
ARCHIVE_TS="pre_unification_$(date +%Y%m%d)"
mkdir -p data/archive/$ARCHIVE_TS
# 1. 搬入所有断旧写源 JSON/SQLite
rsync -av 11-易经推理系统/artifacts/*.jsonl 11-易经推理系统/artifacts/*.json \
        14-V15经典马丁策略/data/v15_state.json \
        11-易经推理系统/scripts/memory_l4/macro_*.db \
        11-易经推理系统/scripts/memory_l4/knowledge_graph.db \
        11-易经推理系统/scripts/memory_l4/bcrm_trades.db \
        data/archive/$ARCHIVE_TS/
# 2. AES-256 加密压缩（项目级敏感数据）
tar -czf - data/archive/$ARCHIVE_TS/ | openssl enc -aes-256-cbc -salt \
  -pass env:DAL_ARCHIVE_PASS -out data/archive/${ARCHIVE_TS}.tar.gz.enc
# 3. SHA256 校验
openssl dgst -sha256 data/archive/${ARCHIVE_TS}.tar.gz.enc \
  > data/archive/${ARCHIVE_TS}.tar.gz.enc.sha256
# 4. 30 天后执行删除（提前设日历提醒，绝不提前删）
# 5. 写 ENGINEERING_INDEX 归档记录（未来找数据有路可寻）
```

**P3 验收：**
- ✅ Cron 连续跑 7 天：0 非零 exit；backup 每日 1 文件；integrity 全部 = ok
- ✅ 冷备份还原演练成功：从 W8 备份还原 → integrity ok + 近 10 交易 md5 100% 匹配
- ✅ 根工程 [ENGINEERING_INDEX.md](../ENGINEERING_INDEX.md) §0.3 表追加 19-数据访问层入口行

---

## 5. （可选）P4 PostgreSQL 桥接迁移 SOP（待触发 §7.1 5 条件）

```bash
# 1. 实现层（PgRepo 6 类 + _sql_compat.py 方言兼容）
# 2. 数据迁移工具 pgloader（官方推荐 SQLite → PG 迁移器）
brew install pgloader  # macOS
cat > conf/sqlite_to_pg.load <<'EOF'
LOAD DATABASE
  FROM sqlite:///path/to/dreambuddy_core.db
  INTO postgresql://user:pass@rds.xxx:5432/dreambuddy

 WITH include drop, create tables, create indexes, reset sequences,
      foreign keys, batchrows=1000, prefetch rows=10000

 CAST type datetime to timestamptz drop default drop not null using zero-dates-to-null,
      type date to date drop not null using zero-dates-to-null,
      type integer when (= precision 1) to boolean using tinyint-to-boolean

 SET PostgreSQL PARAMETERS
      maintenance_work_mem to '256MB', work_mem to '8MB'
EOF
pgloader conf/sqlite_to_pg.load

# 3. 双写再跑 3 天（和 P1 同样流程，只是 backend=dual_write_pair_postgres）
# 4. 5 项门禁 → 切读 → 断 SQLite 写 → 归档 dreambuddy_core.db
```

---

## 6. 迁移总 Timeline & RACI 矩阵

| 周/阶段 | 主要动作 | 负责人（R=执行/A=批准/C=咨询/I=知会） | 里程碑产物 |
|---|---|---|---|
| W0 Day -1 | §0 准备：备份 + DQ 修复 + 环境确认 | R: 运维 / A: 你（PM） / C: — / I: 全 | `dq_report_before.json` 零严重问题 |
| W1~W2 P0 | 统一模型 + 协议抽象 + JsonLegacyImpl + 接入 consumer | R: 开发 / A: 你 / C: 代码评审 / I: 全 | TDD 100%；2 处 import 接入零异常 |
| W3~W5 P1 | Schema init + SqliteImpl + 三批 import + DualWrite 上线 | R: 开发 / A: 你 / C: 运维 / I: 全 | 对账 100% 匹配；DualWrite 0 DB locked |
| W6~W7 P2 | 72h 门禁观察 + 5 项 Checklist 签批 + 切读/断旧写 + Alembic | R: 开发+运维双人 / A: 你（签字） / C: — / I: 全 | Checklist 存档；Alembic head = v1.0 |
| W8~W9 P3 | Cron 三件套接入 + 7 天观测 + 历史归档 + 工程索引更新 | R: 运维 / A: 你 / C: 开发 / I: 全 | `data/archive/*.tar.gz.enc` + SHA256 归档 |
| W10+ P4（待触发） | PG 实现 + pgloader 迁移 + 双写 + 切读 | R: 全栈 / A: 你 / C: DBA / I: 全 | PG 5 触发条件成立时才启动 |

---

> **文档版本规则**：每阶段（P0/P1/P2/P3）完成后，在本文件 `CHANGELOG` 附录追加阶段完成记录（人/日期/问题数/回滚次数）。严禁在执行过程中擅自跳步骤或修改 CheckList 阈值。
