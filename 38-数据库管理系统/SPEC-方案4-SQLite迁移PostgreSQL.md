# 方案 4 SPEC：SQLite 迁移 PostgreSQL

- 版本：v1.0
- 日期：2026-10-17
- 状态：待实施
- 负责推进目录：38-数据库管理系统

## 1. 背景与目标

实例已完成扩容（内存 7.5G → 15G，磁盘 118G → 178G），且数据采集中心新增了功能。SQLite 单文件数据库在多进程并发写入场景下存在锁竞争瓶颈，且无法支撑后续按月分区、时序聚合等需求。本方案将数据采集中心主库从 SQLite 迁移到已有的 PostgreSQL 16（Docker 容器 dreambuddy-pg），目标：

1. 消除多进程并发写入的锁竞争
2. 为按月分区与时序查询打好结构基础
3. 保持现有代码接口不变，通过配置切换存储后端
4. 全程可回滚（SQLite 原库保留为回滚路径）

## 2. 现状调查结论（2026-10-17 实测）

| 项目 | 现状 |
|---|---|
| 实例资源 | 4 核 / 15G 内存 / 178G 磁盘（已扩容，磁盘用 18%） |
| SQLite 主库 | 31M，7,306 条 records（冷数据归档后），另有 metrics / quality_issues / alerts 表 |
| PostgreSQL | Docker 容器 dreambuddy-pg（postgres:16-alpine），127.0.0.1:5432，现有 dreambuddy 库仅 9.7M，基本空闲 |
| 统一存储模块 | data_center/storage/sink_sqlite.py，被 12 个文件引用，接口清晰：records/metrics/quality_issues/alerts 四表 + query_records / latest_records / source_health 等查询函数 |
| 直连 SQLite 的边缘脚本 | 5 个：collect_yahoo_direct.py、collect_missing_data.py、fed_event_collector.py、social_volume_collector.py、utxo_age_collector.py |

## 3. 方案设计

### 阶段 1：建库建表
- 在 dreambuddy-pg 容器中创建 data_center 数据库
- 表结构对齐 SQLite 现有 schema：records（dedupe_key 唯一约束 + ON CONFLICT 去重）、metrics、quality_issues、alerts
- timestamp 字段建索引；表结构预留按月分区能力（当前数据量小，先不启用分区，量大后用 pg_partman 或原生分区升级）

### 阶段 2：编写 sink_postgres.py
- 接口与 sink_sqlite.py 完全对齐（写入函数、查询函数、source_health 等）
- 通过环境变量或配置项切换存储后端（如 DATA_CENTER_BACKEND=postgres|sqlite）
- SQLite 路径完整保留，作为回滚通道

### 阶段 3：数据迁移与校验
- 迁移现有 7,306 条 records 及 metrics / quality_issues / alerts 表数据
- 逐表校验行数一致；records 抽样校验 dedupe_key 与内容一致
- 校验不通过则中止切换

### 阶段 4：切换与验证
- 数据采集调度器（datacenter-scheduler.service）切换到 PostgreSQL 后端并重启
- 验证：新数据正常写入 PostgreSQL、查询函数正常、SQLite 不再增长
- 观察期（建议 3 天）：期间 SQLite 原库保留，随时可切回

### 阶段 5：收尾
- 观察期结束后 SQLite 原库转为备份保留
- 5 个直连 SQLite 的边缘脚本逐步改造为统一存储模块接口（列入后续清单，不阻塞本方案）
- 每日 4:30 自动归档脚本同步适配 PostgreSQL（冷数据归档 SQL 语法调整）

## 4. 风险与约束

- 切换前必须完成数据迁移校验，校验不通过不切换
- 采集服务重启会短暂中断采集（分钟级），安排在低峰执行
- 回滚方式：配置切回 sqlite 后端并重启服务，数据无损
- 暂不引入 TimescaleDB 扩展：当前数据量 PostgreSQL 原生能力足够，未来量大再升级
- 边缘脚本改造不阻塞主链路切换

## 5. 验收标准

- PostgreSQL 中四张表数据与迁移前 SQLite 一致
- 采集调度器运行正常，新数据持续写入 PostgreSQL
- 查询接口（query_records / latest_records / source_health）返回正确
- 自动归档任务在新后端正常工作
- 回滚演练通过（配置切回 sqlite 可正常启动）
