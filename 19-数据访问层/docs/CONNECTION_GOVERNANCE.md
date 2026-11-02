# DAL 连接上限与方言能力集声明（M2④）

> **版本**: v1.0 ｜ **日期**: 2026-11-02 ｜ **状态**: 生效
> **依据**: SPEC-L0-MCP-PACKAGING §3.1（stdio 进程模型：1 宿主 = 1 壳进程 = 1×DB 连接；连接治理下沉 19-DAL 层，壳内禁止自建连接池）+ PLAN-L0-MCP-P0-P3 M2④
> **定位**: 本文件是 19-DAL 对 MCP 壳层的连接治理声明（SSoT）。壳层（mcp_shells/*）不感知本文件中的具体数值，只依赖本声明承诺的行为契约。

## 1. 连接模型（现状声明）

- **连接工厂**: `get_sqlite_connection(db_path)` 上下文管理器——每次 with 新建一个连接，__exit__ 自动 commit+close，**无连接池、无跨调用复用**
- **进程模型**: stdio 壳为 1 宿主 = 1 壳进程；N 个 Worker 并发 = N 个壳进程 = N 个独立连接（WAL 模式下并发读不阻塞）
- **事务边界**: isolation_level=None（自动提交关闭），业务层显式 BEGIN/COMMIT；异常自动 rollback

## 2. 连接上限治理

| 治理项 | 数值/规则 | 实现位置 |
|---|---|---|
| busy_timeout | 5000ms（critical PRAGMA，断言校验） | connection.py _apply_pragmas |
| 锁冲突重试 | 最多 3 次重试，退避 100/300/900ms | connection.py auto_retry_locked |
| journal_mode | WAL（并发读不阻塞写） | 同上 |
| 单连接内存预算 | cache 20MB + mmap 256MB + soft_heap_limit 128MB | 同上 |
| 并发连接上限 | **不设硬性数值上限**：WAL + busy_timeout + 重试退避构成软治理；云端 4C16G 单机场景下，壳进程数由宿主 mcp.json 条目数决定（当前 3 存量壳），实际并发连接数为个位数，远低于 SQLite WAL 单写多读的安全水位 | 本声明（治理决策） |

**治理决策说明**: 不引入连接池（与壳内禁止自建连接池一致）；若未来 Worker 并发规模增长导致锁冲突率上升，优先调整 busy_timeout/重试参数，其次才评估连接池——届时本声明升版。

## 3. 方言能力集声明

| 后端 | 环境变量值 | 状态 | 说明 |
|---|---|---|---|
| json_legacy | DB_BACKEND=json_legacy（默认） | 可用 | 遗留 JSON 存储 |
| dual_write | DB_BACKEND=dual_write | 可用 | 双写迁移期 |
| sqlite_unified | DB_BACKEND=sqlite_unified | 可用 | SQLite WAL 统一库（目标态） |

- **后端选择规则**: 仅由宿主环境变量 DB_BACKEND 决定（di.py），非法值直接抛错（不静默回退）
- **壳层约束（对 mcp_shells 的契约）**: 壳默认继承宿主 env，壳内禁止改写 DB_BACKEND；后端选择不暴露为工具入参；多后端验证走独立 profile（宿主层切换）——即 SPEC §3.5 环境继承规约

## 4. 壳层依赖契约（mcp_shells 视角）

壳层只依赖以下行为承诺，不感知具体数值：
1. 数据访问一律经 DAL（get_sqlite_connection / Repository 协议），壳内禁止直连 SQLite 文件
2. 锁冲突由 DAL 自动重试（auto_retry_locked），壳层无需自行处理 SQLITE_BUSY
3. 连接生命周期由上下文管理器保证（无泄漏），壳层无需管理连接关闭
4. 后端由宿主 env 决定，壳层透传不解释

## 5. 变更流程

- 本声明数值调整（busy_timeout/重试参数/内存预算）需升版并在 47-MCP管理系统 CHANGELOG 登记
- 新增后端（第 4 种 DB_BACKEND）需同步更新 §3 方言能力集表
