# C3 直连基线报告（report-only）

> **日期**: 2026-10-30 21:11 (UTC+8)
> **扫描对象**: 云端 /home/luke/dreambuddy（HEAD 7b0917f8）
> **口径**: 排除 venv-trading / node_modules / .venv / .git / tests；仅 *.py
> **用途**: L0-P 封装层存量收编的量化锚点（179→0 进度仪表的基线）

## 一、SQLite 直连（sqlite3.connect）

**总量: 151 处**（SPEC 调研时点 179 处，本轮口径排除 tests 后为 151 处）

### 按系统分布（top 12）

| 系统 | 处数 |
|---|---|
| 11-易经推理系统 | 19 |
| 4-MEMORY | 7 |
| 23-四层闭环自进化交易架构 | 7 |
| 40-周期神经网络系统 | 6 |
| 1-ARCHITECTURE | 6 |
| 3.1-FRONTEND | 4 |
| 19-数据访问层 | 4 |
| 43-战略承接推演层 | 2 |
| 18-数据获取中心 | 2 |
| 10-经典指标系统 | 2 |
| scripts | 1 |
| 根目录散落脚本 | 1+ |

### 按文件热点（top 10）

| 文件 | 处数 |
|---|---|
| 1-ARCHITECTURE/dreamos/cli/bcrm2_scheduler.py | 11 |
| 18-数据获取中心/data_center/storage/sink_sqlite.py | 11 |
| 11-易经推理系统/scripts/memory_l4/bcrm2/incremental_learner.py | 7 |
| 23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/data_center.py | 6 |
| 1-ARCHITECTURE/dream-harness-bridge/packages/python-server/artifact_store.py | 6 |
| 1-ARCHITECTURE/dreamos/cli/dreamos_full_scheduler.py | 5 |
| 11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_crypto.py | 5 |
| 11-易经推理系统/scripts/memory_l4/five_domain_ic_analysis.py | 5 |
| run_hourly_sacg_execution.py（根目录） | 4 |
| 1-ARCHITECTURE/dreamos/cli/auto_scheduler.py | 4 |

## 二、PG 直连（psycopg2.connect / psycopg.connect）

**总量: 12 处 / 10 文件**

| 文件 | 处数 |
|---|---|
| 39-金融语义蒸馏系统/scripts/dc_pg.py | 1（统一辅助模块，C4b 收编对象） |
| 18-数据获取中心/data_center/storage/sink_postgres.py | 1 |
| 34-前端应用训练系统/scripts/unified_corpus_processor.py | 1 |
| 38-数据库管理系统/migrate_to_postgres.py | 1 |
| 38-数据库管理系统/scripts/sync_intent_registry.py | 2 |
| 7-产物中台/系统研究索引体系/prisma/scripts/etl_worker.py | 1 |
| 19-数据访问层/scripts/backfill_chart_to_mm_metrics.py | 1 |
| 19-数据访问层/scripts/backfill_18_records.py | 1 |
| 1-ARCHITECTURE/dreamos/shared/event_writer.py | 1 |
| 43-战略承接推演层/strategic_extension/sentiment_channel.py | 2 |

## 三、收编优先级建议（与 SPEC-C 热点顺序一致）

1. **第一优先（11-易经，19 处）**: bcrm2/incremental_learner、force_vector、five_domain_ic_analysis 等高频交易链路文件
2. **第二优先（1-ARCHITECTURE，6 处）**: dreamos/cli 调度器族（bcrm2_scheduler 11 处为单文件最大热点）
3. **第三优先（23-四层闭环，7 处）**: adapters/data_center.py 等
4. **PG 侧（12 处）**: dc_pg.py 为统一辅助模块，C4b 收编后其余调用方自然收敛

## 四、基线仪表

| 指标 | 基线值 | 目标 |
|---|---|---|
| sqlite3.connect 直连 | 151 | 0（新代码禁直连，存量按热点批次收编） |
| PG 直连 | 12 | 0（经 dc_pg / DAL adapter 收口） |

> 本报告为 report-only 基线，不阻断任何流程；后续每批收编后重新扫描更新仪表。
