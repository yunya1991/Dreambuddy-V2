# SPEC-C — L0 三层目标架构：互联层（L0-I）/ 调度层（L0-S）/ 封装层（L0-P）

> **版本**: v0.4
> **更新日期**: 2026-11-01（C11/C12/C13 落地 + §9 全量验收回写；v0.3 = 2026-10-30 新增 §5.1 G0 前置门禁）
> **状态**: 本地评审已闭环，**待用户确认后进入阶段 4 云端评审（D1-D8）**
> **本地评审报告**: [l0-three-layer-review-round1.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/.trae/documents/l0-three-layer-review-round1.md)
> **调研对象**: **云端 `43.160.201.117`（Ubuntu 24.04.5，4C16G/180G）为交付目标**；本地 macOS 仅作代理证据与训练端，一致性核对见 §1.1
> **依据**: [l0-foundation-research-report.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/.trae/documents/l0-foundation-research-report.md) 第八章（三层目标专项审计与对标）
> **上游**: SPEC-A（五能力现状与断点 S1-S7）、SPEC-B（协同化路线图 B1-B9）
> **关系**: 本 SPEC **吸收并重排** SPEC-B —— SPEC-B 的 B1/B3/B4 归入 L0-I，B2/B5/B6/B7 归入 L0-P，B8 归入 L0-P，B9 归入 L0-S（见 §7）
> **约束**: 单人维护、FAIL-OPEN、云端 4C16G、禁止 MLflow/K8s/Kafka/DataHub/Backstage 运行时、零回归（HC-1a 开关回落）、评审只读、本 SPEC 不改任何代码

---

## 1. 命题

> L0 五能力（认知 / 采集 / 检索 / PG 数据存储管理 / REA 逆向解析）当前"各自能跑、整体不协同、底层不防震"。本章把用户提出的三个目标固化为 L0 内部的三层结构：**打通（L0-I 互联层）→ 灵活调度与管理（L0-S 调度层）→ 封装统一底层能力（L0-P 封装层）**，并明确三层的职责边界、契约与落地顺序。

## 1.1 调研对象与证据口径（云端为目标，本地为代理）— 硬约束

> **口径（用户确认）**：本 SPEC 的**目标运行环境是云端**（`43.160.201.117`，Ubuntu 24.04.5 LTS，4C16G/180G）。**本地不是交付对象**，本地审计只是"服务云端"的代理证据；**所有结论必须能说明"云端成立与否"**，凡本地与云端不一致处，一律以**云端实测**为准并显式标注。

### 1.1.1 一致性核对矩阵（2026-10-30 实测）

| 核对项 | 本地（macOS，代理侧） | 云端（Ubuntu，权威侧） | 一致性结论 |
|---|---|---|---|
| 代码版本 | **`4d6837f880`（= origin/main = 云端，0/0）** | `4d6837f880`（main，已含 `event_emitter`、SACG 埋点、运行态同步） | ✅ **一致**（2026-10-30 12:26 本地 fast-forward 后对齐） |
| 代码级直连审计 | `sqlite3.connect` **179 处 / 85 文件**（另有 gitignored `.cognitive/vm_fixed_backup.py` 2 处，非仓内代码）；PG 直连 14 处/11 文件；`job_runs/task_registry` 0 命中 | `sqlite3.connect` **179 处/85 文件**；PG 直连 **14 处/11 文件**；`job_runs/task_registry` **0 命中** | ✅ **一致**（文件集合 diff 仅多 1 个本地备份文件） |
| 工作区洁净度 | 15 项 tracked dirty（13 运行态 backtest_cache + 2 部署文档本地未提交）+ 2 untracked | 1 项 tracked dirty（`pool.json`）+ 3 untracked（REA 新样本） | ✅ **`.py` 改动两端均为 0**；差异全为运行数据/文档 |
| 调度载体 | launchd **25** 个 plist（9 KeepAlive / 10 StartInterval / 6 其它） | systemd **74** 个单元（19 个 running）+ **26** 个 timer | ❌ **载体与规模均不同**（云端是本地 3 倍） |
| 系统 cron | 0 条 | **1 条**（`41-文件索引系统/scripts/reconcile_cron.py`，每小时，写 PG `fis` 库） | ❌ 不一致（"cron=0"仅对本地成立） |
| 应用内调度器 | ≥5 套 | 同代码 → ≥5 套，并与 26 个 systemd timer **叠加** | ✅ 代码一致；❌ 运行时调度源更多 |
| 主存储 | SQLite 为主：`18/data_center.db`、`4-MEMORY/data/cognitive_memory.db`、`3.1-FRONTEND/dev.db`、`7-产物中台/business.db`、`2-KNOWLEDGE/9-RAG-INFRA/chroma_db/chroma.sqlite3` | **PG 16.15（postgres:16-alpine）**：`dreambuddy` 36 表 / `data_center` 5 表 / `fis` 5 表；**仍并存** SQLite `data_center.db`、`cognitive_memory.db`、`chroma.sqlite3`；**`dev.db`/`business.db` 已不存在**（Prisma 已切 PG） | ⚠️ **部分不一致**：云端"PG 主 + SQLite 遗留"，本地"SQLite 主" |
| PG 扩展 | — | 仅 `plpgsql`（**无 `pg_trgm` / `vector` / `pg_stat_statements`**） | ⚠️ 影响 C7 检索选址（PG 侧暂无全文/相似检索能力） |
| DSH bridge `:3847` / 产物中台 HUB `:8787` | **未监听** | **未监听** | ✅ 两环境同为空——配置项指向死连接，被 FAIL-OPEN 掩盖（S1 实证） |
| 趋势面板 `:8765` | 未监听 | 监听（`yijing-data-server`） | ⚠️ 云端独活 |
| 事件链 | 代码已同步（`34/core/event_emitter.py` 存在） | `event_emitter` → `events/dreamos/*.jsonl` → `etl-worker.service`（60s）→ PG `observability` 三表 | ✅ 代码一致（见 §3.2 组件②） |
| 时区/编码 | Asia/Shanghai | 同（脚本统一 `+0800`） | ✅ |
| 运行时 | Python 3.x（本机 venv 分散） | Python **3.12.3**，系统级 | — |

### 1.1.2 对结论的适用范围（读本 SPEC 必须先读）

1. **代码级断点（S1-S7、C1-C13）在云端成立**：云端复跑审计得到与本地完全相同的 179/85、14、0 命中，说明"没缝/无人走/无注册表"不是本地假象。
2. **调度层（§3.3）的载体描述必须双写**：本地 `launchd` ↔ 云端 `systemd service + timer`；本 SPEC 的规则一律写成"**OS 调度器（launchd 或 systemd）只负责拉起**"，禁止把 launchd 当作唯一事实。
3. **"系统 cron = 0"只对本地成立**：云端有 1 条 cron（41 索引对账），C9 纳管时必须把它并入任务注册表，否则"统一调度"会有暗渠。
4. **C7 检索入口的落地形态以云端为准**：云端 41 已 PG 化（`fis` 库 5 表）+ Chroma 在 `2-KNOWLEDGE/9-RAG-INFRA/chroma_db`，但 PG **无 `pg_trgm`/`vector` 扩展** → 统一检索只能"路由既有窄接口"，不得在 PG 侧新造全文检索。
5. **代码已两端对齐（`4d6837f880`）**：云端先行合入的 `event_emitter`（JSONL → ETL → observability）本地已具备，§3.2 组件②按"链路已存在、只补认知回写"处理，避免重复建设；剩余差异仅运行数据与本地未提交文档，不影响任何架构结论。

### 1.1.3 云端尚待验证项（本轮未能取证，需在阶段 4 云端评审补齐）

| # | 待验证 | 取证方式 |
|---|---|---|
| V1 | 云端 `dreambuddy` 库 36 表与 19-DAL 仓储的实际覆盖关系（哪些表真有读写） | `pg_stat_user_tables` 的 `n_tup_ins/upd` + DAL 仓储清单比对 |
| V2 | 26 个 timer 的真实触发成功率与滞留（无 `job_runs` 时的替代口径） | `journalctl -u <unit> --since` 计数 |
| V3 | 云端 18 采集是否已双写到 PG `data_center`，SQLite `data_center.db` 是否仍为事实源 | 表行数对照 + `sink_sqlite/sink_postgres` 开关取值 |
| V4 | 云端 KB 容量余量（4C16G/180G 下新增 `job_runs` + 事件表的余量） | `df -h` + PG 库大小 |

## 2. 命名与坐标系（避免与既有编号冲突）

| 体系 | 含义 | 层级数 | 与本 SPEC 的关系 |
|---|---|---|---|
| **L0 / L1 / L2** | 按"是否依赖生成式 LLM 推理"分层（SPEC-v1.3 §1） | 3 层（纵向） | 本 SPEC 讨论的是 **L0 内部**的组织，不改变该纵向定义 |
| **C1-C4** | 认知系统内部四层闭环 | 4 层 | L0-I 的"认知"能力内部结构，不下沉到本 SPEC |
| **SACG** | 意图→图编排→资源→治理的执行范式 | 4 阶段 | 属 L1/L2 执行侧，不是 L0 内部结构 |
| **L0-P / L0-I / L0-S** | 本 SPEC：封装层 / 互联层 / 调度层 | 3 层（L0 内部，横向） | ✅ 本文使用；层内顺序为 **P 在最底** |

> **硬约束**：文档与代码命名一律用 `L0-P / L0-I / L0-S`，禁止再用"L0 三层"泛指，避免与 L0/L1/L2 混淆。

## 3. 三层职责与契约

### 3.1 L0-P 封装层（最底，防震层）

**职责**：把"资源访问"（PG / SQLite / Chroma / 文件 / 外部 HTTP）收进唯一出口，向上只暴露领域语义。

| 项 | 规定 |
|---|---|
| 对外契约 | 统一门面 `fetch(scope, params) -> {ok, data, source, timestamp, degraded, meta}` + 统一动作 `settle(result, context)`（沿用 34 `L0Foundation` 信封，不另造）。**信封必含 4 个新增字段**（评审 P0-3）：`version`（契约版本）、`trace_id`（与 `event_emitter` 打通）、`idempotency_key`（幂等）、`error_code`（枚举，不允许自由文本 reason 直出） |
| port 数量 | **上限 6 个**：`Memory`（recall/record/verify）、`Collector`（collect/status）、`Search`（search/index）、`Store`（read/write/query/health）、`Analysis`（analyze/report）、`Event`（publish/consume）。**`Facade` 是门面本体、不计为 port**（评审 P1-1：原"第 7 个 Facade"违反硬规则2"每个 port 需第二实现"）；调度器写 `job_runs`、dispatcher 消费事件一律走 `Store`/`Event`，`Event` 只保留"跨能力通知"语义 |
| 每个 port 必带的 4 类语义 | ①**事务边界**（是否支持 `txn`、跨 port 是否同一事务）；②**分页**（`cursor/limit`，禁止返回全量）；③**身份与权限**（如 41 的 `user_id/token` 必须作为入参显式化，不得藏在 adapter 全局态）；④**错误枚举**（`not_found / unavailable / conflict / invalid / timeout / degraded`） |
| adapter | PG / SQLite（旧）/ Chroma / 文件系统 / HTTP，**所有方言细节（`ON CONFLICT`、`INSERT OR REPLACE`、`PRAGMA`、表名、字段名）只能出现在 adapter 内**；Store adapter 声明**方言能力集，分两层**：**操作符**（`skip_locked / upsert / returning / txn / jsonb_filter`）+ **类型与语义映射**（`datetime→timestamptz 或 text`、`json→jsonb 或 text`、`numeric→decimal 或 float`、隔离级别、连接/并发上限、游标分页、全文/部分索引）。**禁止跨方言声明等价**——调用方必须显式降级（如无 `skip_locked` 时用单线程轮询）。**DDL 归属**：schema 定义与迁移只允许唯一 owner（见 §5.1 G0-6），业务层禁止建表（现状 `19-数据访问层/dreambuddy_dal/di.py:78` 的 `init_db_schema` 在 DI 内，属待迁移项） |
| 禁止 | ①业务层出现 `sqlite3.connect` / `psycopg2.connect` / `create_engine`；②port 返回 cursor/row/Connection；③新建第 7 个 port；④模块级 `sys.path.insert` + 直接 import 民间封装（`l0_foundation.py:41-42` 为现存反例，须在 G0 清理） |

### 3.2 L0-I 互联层（与 L0-S 并列）

**职责**：让五个能力"知道彼此存在、能互相触发、能被一个入口检索"。

| 项 | 规定 |
|---|---|
| 组件①能力声明 | `capabilities.yaml`（**Schema 复用 DreamOS `CapabilitySpec`** 的字段名：`capability_id/category/name/provides/requirements/status/degraded_reason/version` + 本 SPEC 增补 `health_cmd`、`port`）；**只做"文件 + CI 校验"这一事实源，不加载进运行时 `CapabilityRegistry`**（理由：DreamOS 注册表是进程内存态，五能力分散在 5+ 个进程，加载需额外常驻进程，与 4C16G 约束冲突）；health 由外部 runner 按 `health_cmd` 探活 |
| 组件②事件 | **默认不建跨库 outbox**。P2 用"`job_runs` 状态转移 → 认知 record"同进程回调（一次写，以 `external_id = run_id` 幂等，无跨库重复写）；**前置硬条件（评审 P0-7）**：认知表必须先有 `external_id` 唯一索引，且 `record()` 必须接受幂等入参——现状 `record()` 无幂等键、记忆 ID 含毫秒，同一 run 会写多条并触发 verify 反复升级置信度，未补齐前 C8 不得开工。另外，`record()` 现状会 `Popen` 触发 41 索引重建（`cognitive_loop_entry.py:1062`），**必须改为批量/去抖**，否则每次调度完成都抢 CPU 拖慢实盘（评审 P0-11）。仅当出现**非调度来源的生产者**（如 REA 分析完成、检索命中）需要通知认知时，才在 P3 评估单表事件，且**表必须与认知库同库、dispatcher 置于认知进程内**；若坚持用 PG，则表为 `domain_events`（`id/aggregate_id/type/payload/status/attempts/next_attempt_at/created_at/published_at`）+ 单进程 `FOR UPDATE SKIP LOCKED`，`aggregate_id` 内串行，消费方以 event id 幂等。**现状（云端实测，不重建）**：云端已有单向链路 `34/core/event_emitter.py` → `events/dreamos/*.jsonl` → `etl-worker.service`（60s）→ PG `observability` 三表；本 SPEC 只在链路末尾补"→ 认知 record"一段，**不新造第二个事件生产者** |
| 组件③检索入口 | 单一 MCP 工具 `unified_search(query, sources, top_k)` **必须经 `Search` port 分发**（不得直连三后端，评审 P0-1），port 内实现 41 / Chroma / 认知 recall 三个 backend adapter。**41 是外部部署**（云端 `/home/ubuntu/fis-p0` 独立 venv + `FIS_AGENT_TOKEN` 权限 + 每小时 cron 刷新索引），不是"零依赖切片"：必须做探活，**全后端不可用时显式返回"全降级"错误码**，禁止用 FAIL-OPEN 把故障伪装成"无结果"。排序策略：各后端分数 min-max 归一化后按 `source` 分层返回（不做跨源硬比）；去重键=规范化路径（文档）或记忆 ID（认知）；`top_k` 上限 50，默认 10 |
| 禁止 | ①自建消息总线/Kafka/CDC；②让事件直接读写某能力的私有表（必须经 L0-P）；③检索入口内同步执行业务任务（触发一律走 outbox） |

### 3.3 L0-S 调度层（与 L0-I 并列）

**职责**：让"何时跑、跑没跑、跑成没有"变成可查询的事实。

| 项 | 规定 |
|---|---|
| 控制面 | 声明式任务清单（`task_key / schedule / timeout / max_concurrency / retry / enabled / fallback`）+ `job_runs` 表（`run_id/task_key/logical_window/state/attempts/started_at/heartbeat_at/finished_at/error`） |
| 数据面 | 执行器（线程池/子进程）**只认 `task_key` + 输入契约**，不得 import 业务函数；控制面与执行面仅经 `job_runs` 通信 |
| 八要素 | **`logical_window` 统一为 UTC 门控时刻**（host `+0800` 与 PG 容器 UTC 不得混用，评审 P0-10）；幂等 run key（`task_key + logical_window`，unique）／状态机 `pending→claimed→running→success/failed/timeout/dead`／指数退避+抖动／按 task_key 并发限流／超时回收／心跳／运行记录与日志引用／开关。**补三条**：①迟到容忍窗（默认 5min，超窗记 `missed_run` 并跳过，不补发）；②长任务跨窗拆成多个 run，不延长单窗；③**连续 N 窗（默认 3）无 run 必须告警**——这是"回收后被 unique 拒导致静默停摆"的唯一兜底（评审 P0-10） |
| 保留与归档 | `job_runs` 默认保留 90 天，之后归档到 `38-` 冷热分层；**禁止无界增长**（云端 180G 磁盘，评审 P1-4） |
| 与 OS 层边界 | **OS 调度器只负责"拉起常驻进程 + 看门狗"**：本地为 `launchd`（25 plist），云端为 `systemd service/timer`（74 单元 + 26 timer）——两者是**同一职责的两种载体**，规则不得只写 launchd；凡是需要业务上下文（DB 状态/开关/依赖其他能力）的定时逻辑，收进 L0-S；**不得改变实盘进程的生命周期管理方式** |
| 禁止 | ①调度层持有业务知识；②为调度引入 Prefect/Dagster/Celery/Temporal；③一次性移除 OS 调度器（launchd 或 systemd）；④在新任务注册表之外继续新增裸 `crontab`（云端现有 1 条须先纳管） |

## 4. 现状基线（引用第八章审计，均为只读事实）

> **基线口径**：以**云端**（`4d6837f880` @ Ubuntu 24.04.5）为准，本地值仅作对照；一致性核对见 §1.1。

| 项 | 云端基线（权威） | 本地基线（代理） | 目标 |
|---|---|---|---|
| `sqlite3.connect` 直连 | 179 处 / 85 文件，约 92% 在存储层之外 | 179 处 / 85 文件（同构） | adapter 之外 = 0（新增禁直连，存量分批收编） |
| PG 直连 | 14 处 / 11 文件（含 39 `dc_pg.py` 民间封装） | 14 处 / 12 文件 | 统一收编进 19-DAL |
| OS 调度器 | systemd 74 单元（19 running）+ 26 timer | launchd 25 plist（9 常驻 / 10 周期 / 6 其它） | 不减少，仅把内部定时逻辑接入 `job_runs` |
| 系统 cron | **1 条**（41 索引对账，每小时） | 0 条 | 纳管进任务注册表（非"保持 0"） |
| 应用内调度器 | ≥5 套，且与 26 timer 叠加 | ≥5 套 | 统一任务注册表 1 份 + `job_runs` 1 张 |
| 任务注册表 / 运行记录 | 0（Grep 零命中） | 0 | 1 份声明 + 1 张运行表 |
| 统一 L0 门面 | 1 个原型（34 `L0Foundation`，11 scope）；**已被 3.1-FRONTEND 三个脚本与 39 跨子系统调用**（非"仅本子系统"） | 同（同一文件） | 全 L0 公共门面 + 唯一入口声明 |
| 能力注册 | DreamOS `CapabilityRegistry` 运行时内存态，不覆盖 L0 五能力 | 同 | 五能力全覆盖 + 声明文件 |
| 事件链 | JSONL → `etl-worker` → PG `observability` 三表（**单向、无认知回写**） | 同（代码已同步） | 补"→ 认知 record"一段，不重建 |
| 数据库 | PG 16.15：`dreambuddy` 36 表 / `data_center` 5 / `fis` 5；扩展仅 `plpgsql`；SQLite `data_center.db`、`cognitive_memory.db`、`chroma.sqlite3` 并存 | SQLite 为主 + 本地 PG 实例；`dev.db`/`business.db` 仍在 | 统一走 `Store` port，方言差异收进 adapter |

## 5. 六条架构硬规则（评审基线）

1. **直连禁令**：`sqlite3.*` / `psycopg*` / `create_engine` 仅允许出现在 adapter 目录；CI 用 import-linter + grep 断言（承接 SPEC-B B5）。
2. **port 上限 7**：新增 port 须给出"第二实现（真实 + 内存 fake）"举证，否则不建。
3. **信封透传**：跨层调用一律使用 `{ok,data,source,timestamp,degraded,meta}`；禁止抛异常穿透到 L1/L2。
4. **调度只认 task_key**：控制面不得 import 业务模块；业务侧通过注册函数名/命令声明接入。
5. **OS 层只拉起**：本地 `launchd` KeepAlive / 云端 `systemd` Restart 只保证进程活着；"跑什么（周期、重试、超时）"由任务注册表决定，**两份载体的规则等价，不得只针对其中一端设计**。
6. **封装先行原则（不是"一律先做封装再谈打通"）**：新代码必须建在门面之上（否则事件/调度将直接耦合私有表，换库需重写）；但**存量 179 处直连的收编不与"打通"绑定**——它单开轨道、不进关键路径。**"打通"的可见成果由前置切片 C7（统一检索入口）承担**，其后才轮到门面公共化与存量收编。

> **关于落地顺序的修订（评审后）**：价值顺序是"打通 → 调度 → 封装"，依赖顺序是"封装先行（仅约束新代码）→ 互联 → 调度"。**"打通"不再等待封装全部完成**：C7 统一检索入口前置到 P0，作为"打通"的第一个可见成果；但它**必须经 C2 的 `Search` port 分发**（不得直连三后端），且 41 属外部部署需探活（见 §3.2 组件③）。存量直连收编单开轨道、不阻塞任何后续步骤。

### 5.1 G0 开工前置门禁（本地三方评审 P0，未关闭不得进入 P0）

| # | 门禁项 | 为什么必须先做 | 验收 |
|---|---|---|---|
| G0-1 | **密钥治理**：移除 `l0_foundation.py:165` 的 `FIS_PG_PASSWORD` 明文默认值，改为环境/密钥文件注入；**已入库口令必须轮换**（git 历史已泄露） | 明文口令在仓库里，任何 clone 者都能连生产 PG | 全仓 `grep` 无明文口令；旧口令失效；新口令只在云端 env |
| G0-2 | **配置与路径外置**：门面内 `_PROJECT_ROOT`+相对路径＋`/home/ubuntu/fis-p0` 绝对路径改为 adapter 配置；本地/云端差异只允许出现在配置 | 现在改一个路径要改代码，且两环境路径不同 | 同一代码两环境零改动启动 |
| G0-3 | **禁用模块级 `sys.path.insert`**：`l0_foundation.py:41-42` 为反例，`import dc_pg` 必须下沉到 adapter | 逐文件 hack 会让适配层从第一天就破 | 新代码 0 处；存量单开轨道 |
| G0-4 | **CI 阻断 job**：新增独立 job `l0-contracts`（跑新契约测试），**不动既有 `continue-on-error` job** | 现状所有 pytest 都 `continue-on-error`，测试红了流水线也是绿的 | 故意让一条契约测试失败时 CI 变红 |
| G0-5 | **健康检查与回滚**：部署末尾改 `health-check.sh --record-good`；回滚需人工确认，禁止连续 3 次失败即 `git reset --hard` | 失败计数不清零会误回滚新代码 | 一次正常部署后 `health-state` 归零；回滚需显式操作 |
| G0-6 | **DDL / schema 唯一 owner**：`init_db_schema` 从 `di.py:78` 移到独立迁移模块，业务层禁止建表 | 谁都能建表就永远换不掉库 | 全仓建表语句只在迁移模块 |
| G0-7 | **磁盘与日志上限**：`events/*.jsonl` 加 logrotate；磁盘水位 >85% 告警 | 180G 写满会直接打断实盘写仓 | logrotate 生效；水位告警可触发 |
| G0-8 | **认知幂等字段**：认知表加 `external_id` 唯一索引 + `record(idempotency_key=)` | C8 的"run_id 幂等"在当前实现上不成立 | 同一 key 重复 record 只产生 1 条记忆 | **✅ 2026-11-01 已关闭**：`memories.external_id` + 部分唯一索引（`WHERE external_id IS NOT NULL`；`7b0917f87c`）+ `record(idempotency_key=)` 契约入口 + 存量库已迁移；P0-11 索引重建改为 `index_rebuild_trigger` 去抖（默认 60s 窗，路径经 `FIS_P0_HOME` 外置）；9 条契约测试入阻断 job |

## 5.2 六条硬规则与本节的优先级

G0 是**开工前置**，六条硬规则是**全程约束**；G0 未关闭时，C1 及之后的所有项只能做只读设计与测试编写，不得改生产路径。

## 6. 分期路线（P0-P3）

### P0 — P0-A 门面立起来（L0-P 起手）

| # | 项 | 落点 | 验收 |
|---|---|---|---|
| C1 | **L0 公共门面（缩小版）**：把 `L0Foundation` 的**统一信封 + scope 注册机制**抽为独立可导入包（`dreambuddy_l0/`，禁止中文目录当模块路径），供新代码使用；**不一次性迁移 34 的 11 个 scope**。**必须先出调用方清单**（评审 P0-2 已核实 4 处：`3.1-FRONTEND/scripts/data_query_executor.py:26`、`l1_route_signal.py:41`、`l2_cognitive_settle.py:42`、`39-金融语义蒸馏系统/scripts/gen_spacetime_events.py:58`），并声明**唯一入口**；`_load_cle` 私有方法转公有 `load_cle()` 并给弃用期，禁止 L2 继续依赖私有方法 | 顶层包 `dreambuddy_l0/`（原 34 文件保留为薄壳 re-export） | 包可被导入；4 处调用方行为零变化；**至少 1 个真实消费者**（如 18 scheduler）改用新入口 |
| C2 | **六能力 port 定义**：Memory/Collector/Search/Store/Analysis/Event 各 1 个 Protocol（方法数 ≤7，签名不出现 Connection/row/SQL，且带 §3.1 的 4 类语义）+ 内存 fake + Store 方言能力集（操作符+类型映射）。**契约测试必须进 G0-4 的阻断 job**，并加"fake vs 真 adapter 差分比对" | 包内 `ports/` | 6 个 Protocol + 6 个 fake；契约测试在 CI 阻断；差分比对无未解释差异 |
| C3 | **直连基线仪表**：把"adapter 之外的 DB 直连文件数"做成可执行检查脚本，先 report-only 输出名单与趋势。**评审 P0-6：仓库非包化 + 大量 `sys.path`/importlib，import-linter 分层契约不可用 → C3/C10 一律降级为 grep 门禁 + 白名单**，包化完成后再评估 import-linter | `scripts/check_db_direct_imports.py`（report-only） | 报告可产出且可复现；CI 不阻断 |
| C7 | **统一检索入口（前置切片，"打通"第一成果）**：MCP `unified_search` **经 C2 的 `Search` port 分发**，port 内实现 41 / Chroma / recall 三个 backend adapter（评审 P0-1：不得直连窄接口，否则换实现必重写）。**41 是外部部署**（`/home/ubuntu/fis-p0` 独立 venv + token + 每小时 cron），必须探活；**全后端不可用要显式报"全降级"错误码**。分数 min-max 归一化 + 按 `source` 分层；去重键=规范化路径/记忆 ID。**云端约束**：PG 仅 `plpgsql`（无 `pg_trgm`/`vector`）→ 禁止在 PG 侧新造全文/向量检索 | 4-MEMORY/9-工具与接口 + 包内 `search/` | 三后端合并结果可用；断任一后端不报错；**断全部后端必须返回 `error_code=all_sources_unavailable` 而不是空结果** |

### P1 — P1-A 存储真正走缝 + 能力可声明

| # | 项 | 落点 | 验收 |
|---|---|---|---|
| C4a | **19-DAL 补 PG adapter（新增前置，评审 P0-8）**：现状后端只有 `json_legacy / dual_write / sqlite_unified`（`di.py:15-17`），**没有 PG 实现**，C4 原"收编进 DAL"无从落地。先实现 `Postgres*Repository` + 契约测试（含类型映射、事务、分页） | 19-DAL | PG 后端可读写；与 json_legacy 字段级一致 |
| C4b | **`dc_pg` 收编**：39 `scripts/dc_pg.py` 的能力搬到 19-DAL PG adapter，保留旧名薄壳（保返回结构 + 保 FAIL-OPEN，调用方零改动）；比对口径=字段级 + 样本量 + 阈值，禁止只比条数 | 19-DAL + 39 薄壳 | 调用方零改动；抽样比对达阈值 |
| C5 | **热点目录收编（独立轨道，第一批）**：11-易经推理系统 的 61 处直连按模块分批改走 `Store` port（每批一个模块，开关按**文件/进程**粒度）。**前置**：DualWrite 现状新库写失败仅 `warning`、影子比对只比 `len()`（`di.py:177`）→ 必须先补**字段级 diff + diff 率门槛 + per-repo 读开关**（现 `READ_SOURCE` 是全局 env），否则切读会假 MATCH。**且 11 是实盘宿主（`yijing_trading`），只读查询先行、写路径暂缓**，改后需重启实盘的批次单列窗口 | 11 系统 + 19-DAL | 每批回归通过；开关关闭回到旧路径；shadow diff 率低于阈值才允许切读 | **进行中 2026-11-01**：前置加固 `0b1e73c020`；`force_vector` 两批共 8 文件读路径收编（`41a70b35f8` + `db2799982e`）；第三批 `five_domain_sqlite_reader` 2 处读路径收编（直连集中到 `_five_domain_store_port.py`，开关 `FD_STORE_PORT`，10 条契约测试含 legacy/port 逐字段等价）；**第四批 `bcrm2` 只读收编 `0ec862f923`**（`macro_data_fetcher` 2 处 records 只读 + `incremental_learner` 2 处学习库只读 → `bcrm2/_store_port.py`，开关 `BCRM_MACRO_STORE_PORT` / `BCRM_LEARNER_STORE_PORT`，11 条契约测试；**写路径 6 处 + 聚合读 1 处按"只读先行"暂缓**）；**第五批 `4e95b844b8`**（`five_domain_ic_analysis` 5 处 + `backtest_five_domain_v2` 3 处只读直连收编 → `_five_domain_store_port.py` 新增 5 helper，开关 `FD_IC_STORE_PORT` / `FD_BT5_STORE_PORT`，14 条契约测试，真实库 1395 日期开关关/开全等）；**第六批 `634a6f6af2`**（`_probe_sqlite_records` 1 处 mode=ro 探针收编 → 新增 `fetch_all_rows_id_desc`，开关 `FD_PROBE_STORE_PORT`，5 条契约测试，真实库 33244 行输出逐字节一致）；其余 14 个 legacy 条目分类：写路径 5 文件 12 处暂缓、`daily_report_system` 4 处读项目外 WorkBuddy automations.db 不属 records port 语义、8 个测试/验证文件 11 处为种子脚手架登记保留；白名单中 11 系统共 17 个条目（14 个 legacy + 3 个收编集中点）；**第七批 `ed222cb966`**：`bcrm2` 写路径 9 处收编（`incremental_learner` 4 写方法 + `macro_data_fetcher` 缓存读写 2 + `backfill_fma_shadow` 3）→ `_store_port.py` 新增 `_connect_rw/_connect_ro` + 6 写助手 + 4 读助手（connect 3→15），新增开关 `BCRM_BACKFILL_STORE_PORT`，port 分支异常回退 legacy 直写（fail-safe、全幂等、回退重放安全），13 条契约测试，真实数据等价（evolution 2000/29325 行、learner 49→51、macro 100 行开关关/开双跑全等）；剩余 3 处暂缓（learner 聚合读 AVG/SUM port 不可表达、`storage.py`/`kg_store.py` 连接持有型需 port 句柄抽象单独立项）；白名单 11 系统剩 15 个条目（12 legacy + 3 收编集中点）；**开关默认关=合并零风险，实盘切流（开开关）需单列重启窗口**；**第八批 `7e5d455809`**：剩余 3 处全收编——learner 聚合读（`fetch_recent_performance` AVG/SUM 专用 SQL 助手，复用 `BCRM_LEARNER_STORE_PORT`，connect 1→0、删 `import sqlite3`）+ `storage.py`/`kg_store.py` 连接持有型（`connect_persistent`/`connect_autocommit` 纯透传工厂，参数逐字节等价故无开关，connect 各 1→0）；`_store_port.py` 15→18，白名单 11 系统剩 12 个条目（9 legacy + 3 收编集中点）；契约 +6 共 31 条（本地+云端全绿）；pyproject 存量风格豁免（同第五批先例）；真实库双模式全等 + evolution 2000 行/kg 93 triples 副本验证；**11 系统 bcrm2 业务代码直连清零，legacy 仅剩 daily_report（项目外 DB）+ 测试脚手架** |
| C6 | **能力声明**：`capabilities.yaml` 覆盖五能力（provides/requirements/health_cmd/port），**文件 + CI 校验为唯一事实源**（不加载运行时注册表） | `0-系统文档管理/capabilities.yaml` + 校验脚本 | 五能力声明完整；校验可拦截漂移 | **✅ 2026-11-01 已落地**：`capabilities.yaml`（五能力/15 条 provides）+ `scripts/validate_capabilities.py`（port/impl 漂移检测）+ 9 条契约测试 + `l0-contracts` CI 阻断步骤 |

### P2 — P2-A 事件互通 + 调度可见

| # | 项 | 落点 | 验收 |
|---|---|---|---|
| C8 | **事件互通（默认回调，不建跨库 outbox）**：`job_runs` 状态转移后同进程回调 → 认知 record（以 `external_id=run_id` 幂等）。**开工前置 = G0-8**（认知表 `external_id` 唯一索引 + `record(idempotency_key)`），并先把 `record()` 触发 41 重建改为批量/去抖（评审 P0-7/P0-11）；REA/检索等非调度来源在 P3 再评估单表事件（与认知同库、dispatcher 在认知进程内） | 18 scheduler + 认知 MCP | 一次采集可 recall 到事件；重复执行不产生重复记忆；消费失败不阻断主流程；record 不触发实时重建 | **✅ 2026-11-01 已落地（本地 + 云端）**：`dreambuddy_l0/scheduling/event_bridge.py`（终态 `succeeded/failed/timeout/dead` → `Memory` port record，正文 `[L0调度][job_runs] task_key=… run_id=… window=… state=… duration=…`，`external_id=run_id`）；`JobRunRecorder` 注入可选 `memory` port，`finish` 落库后再回调，无 memory 时零行为变化；`dreambuddy_l0/adapters/cognitive.py`（`MemoryPort` → `CognitiveLoopEntry` 同进程委托，认知目录经 `DREAMBUDDY_MEMORY_DIR` 外置、函数内 import）；18 采集按 `memory_enabled()` 注入（云端 PG 后端默认开 / 本地默认关，避免直写只读镜像）。**三层证据**：16 条契约测试（真实认知库 run_id 去重）→ 全量 66 passed/6 skipped（本地与云端一致）；云端 `CognitiveLoopEntry.recall()` 对该 run 事件命中 top-1（score 0.3676）；同一 `dc.collect.cloud@5978430` 两次 `record_run` 返回**同一** memory_id（`VM-1793529157478-44ffc691`），`memories` 表按 external_id 计数=1；重启 `datacenter-scheduler.service` 后真实窗口 `dc.collect.cloud@5978431` 自动产出记忆 `VM-1793529335073-82d43af0`。**降级**：record 失败只发 `scheduling.memory_record_failed` 且 run 不回滚；回调路径无 `Popen`/实时重建（沿用 G0-8 去抖） |
| C9 | **任务注册表 + `job_runs`**：声明式任务清单，**先纳管云端三条真实链路**——`datacenter-scheduler.service`（18 采集）、`datacenter-backfill.timer`（每小时 :15）、41 索引 `crontab`（每小时对账）；本地对应 `datacenter`/`dc-scheduler`。**窗口统一 UTC**、迟到容忍 5min、跨窗拆 run、`missed_run` 记录、**连续 3 窗无 run 告警**（评审 P0-10） | 18 + 公共调度模块 | 任务可在注册表查询；每次执行有 run 记录；幂等 run key 生效；**云端裸 crontab 归零**；模拟时钟跳变/重启后无重复 run | **✅ 2026-11-01 已落地（本地 + 云端）**：`0-系统文档管理/job_registry.yaml`（四任务/UTC/5min/90d）+ `dreambuddy_l0/scheduling/`（registry/windows/job_runs/cli）+ `dreambuddy_l0/adapters/jsonl.py`；18 `dc-scheduler` 每窗口幂等心跳记账；20 条契约测试入阻断 job。**云端复核通过**：`/var/lib/dreambuddy/job_runs.jsonl` 三段真实 run（`dc.collect.cloud@5978425/5978426/5978427`、`dc.backfill.cloud@498202`、`index.reconcile.cloud@498202`，均 succeeded）；41 裸 crontab 行已删除（`sudo -u ubuntu crontab -l` 为空），改由 `index-reconcile.timer`（`*:00`）承载；新增 `job-runs-audit.timer`（`*:05`，`audit --host cloud` + `prune`）承载 missed_run 审计与 90 天保留。**密码来源修正**：`dreambuddy-pg` 的 `POSTGRES_PASSWORD` 与库内真实口令不一致，41 改用 `EnvironmentFile=/etc/dreambuddy-pg.env` |
| C10 | **直连门禁 enforce**（承接 SPEC-B B5，先 report-only 2 周再切 enforce）。**降级说明**（评审 P0-6）：包化前用 grep 门禁 + 白名单，import-linter 待 `dreambuddy_l0/` 包化完成后再启用 | CI | report-only 报告产出；enforce 后白名单外新增直连 CI 失败 | **✅ 2026-11-01 已落地（本地 + 云端）**：`scripts/check_db_direct_imports.py --ratchet`（白名单 ratchet，只减不增）接入 `l0-contracts` CI 阻断步骤，白名单外新增直连即红；契约测试 `test_c10_direct_gate.py` 入阻断 job；本地与云端复核 ratchet exit=0（d17abcb854） |

### P3 — P3-A 联调与可视

| # | 项 | 落点 | 验收 |
|---|---|---|---|
| C11 | **检索触发任务**：检索命中 → 按 task_key 排 job（去重窗口 + 并发上限 + FAIL-OPEN）；跨界通知仅在 P3 事件表通过评审后启用 | L0-I × L0-S | 一次检索命中可产出 1 个可追踪 job；重复检索不风暴 | **✅ 2026-11-01 已落地（本地 + 云端）**：`job_registry.yaml` 新增 `search_triggers` 映射节（`load_registry` 校验引用已注册 task_key）；`dreambuddy_l0/scheduling/trigger.py`（`SearchJobTrigger.on_search`：ref 前缀匹配 → `enqueue` 排 pending job，去重键 `task_key:sha1(ref)[:12]@window` 落 `search_triggers` 表，开放态计入 `max_concurrency`，失败信封不排 job，FAIL-OPEN）；`JobRunRecorder.enqueue()`（state=pending 不冒充 running）；11 条契约测试入阻断 job。**云端实证**：命中 `41-文件索引系统/docs/x.md` → `index.reconcile.cloud@498204` pending 落盘，30s 内重复命中判 `duplicate` |
| C12 | **调度/能力健康聚合**：`job_runs` 与五能力 health 聚合进 cognitive `health`（跑没跑/成功率/最老滞留/降级原因分布）；云端 health 探测以 `capabilities.yaml` 的 `health_cmd` 为准，**不依赖 systemd/launchd 内部状态** | MCP health | health 返回五能力 + 调度分项；两端同口径 | **✅ 2026-11-01 已落地（本地 + 云端）**：`dreambuddy_l0/scheduling/health.py`（`collect_l0_health`：每 task 跑没跑/终态成功率/最老开放态滞留/missed streak 告警 + 降级原因分布；五能力按 `capabilities.yaml` 的 `health_cmd` subprocess 探活（cwd=repo_root + timeout，源码扫描无 systemctl/launchctl）；host 自动识别过滤任务归属；store/registry/声明文件单项故障只降级不拖垮）；`cognitive_mcp_server.py::_handle_health` 挂接 `result["l0"]`（try/except FAIL-OPEN，基础健康载荷零回归）；16 条契约测试入阻断 job。**两端冒烟**：本地 host=local 五能力全 ok；云端 host=cloud 五能力全 ok、tasks 恰为 4 个云端任务（`dc.collect.cloud/dc.backfill.cloud/index.reconcile.cloud/os.memory-cleanup.cloud`） |
| C13 | **OS 层定时逻辑接入（零侵入，双载体等价）**：仅限 **每端各 1 个非实盘周期任务**（本地 `dbsync` 经 launchd、云端 `memory-cleanup` 经 systemd timer），通过**只读旁路**（不改 `ExecStart`）解析日志/心跳记账；**实盘进程（dreamos / yijing_trading / v15 / trailing-stop-runner / yijing_live_300s 等）不内嵌记账**，只保留 OS 层生命周期管理。先在这 2 个任务演练 2 周再推广 | OS 层旁路 collector（launchd 与 systemd 各一份，只读） | 两端各有 1 个任务在 `job_runs` 可见；实盘进程零改动；改 `ExecStart` = 违规 | **✅ 2026-11-01 已落地（本地 + 云端）**：`dreambuddy_l0/scheduling/sidecar.py`（launchd：`print gui/<uid>/<label>` 优先 + legacy `list` 回落 + plistlib 读 plist 日志 mtime；systemd：`systemctl show` 的 `LastTriggerUSec` + `ExecMainStatus/Result`，兼容新版格式化时间戳按本机本地时间解析；审计先行的 `missed_run` 行被旁路后到证据升级为真实终态；红线扫描禁写 OS 单元入契约；FAIL-OPEN + `task_key@window` 幂等）；注册表新增 `os.dbsync.local`（600s 窗口对齐 StartInterval）+ `os.memory-cleanup.cloud`（6h 窗口）；cli 增 `sidecar` 子命令；17 条契约测试。**两端实证**：本地 `os.dbsync.local@2986511` succeeded（二次扫描 `duplicate`）；云端 `os.memory-cleanup.cloud@83031` succeeded（started/finished 对齐 systemd 真实触发 02:00–02:05:01，二次扫描 `duplicate`）；实盘进程零改动 |

## 7. 与 SPEC-A / SPEC-B 的关系

| SPEC-B 原项 | 本 SPEC 归属 | 处理 |
|---|---|---|
| B1 capabilities.yaml | C6（L0-I） | **修订**：Schema 复用 `CapabilitySpec` 字段，但**不加载运行时注册表**，只做文件 + CI 校验 |
| B2 REA 产出入认知 | C8（L0-I） | 修订：不作为事件类型，改为 REA 完成后直接 record（`run_id`/报告 hash 幂等） |
| B3 统一检索 facade | C7（L0-I） | 继承并**前置到 P0**；修订为**必须经 `Search` port 分发**，41 视为外部依赖需探活 |
| B4 PG domain_events outbox | C8（L0-I） | **修订**：默认改为 `job_runs` 状态回调；PG outbox 降级为 P3 备选（仅非调度来源） |
| B5 import-linter 门禁 | C3 + C10（横切） | 拆成"先报告基线、后 enforce" |
| B6 RAG 索引 PG 快照 | 保留在 SPEC-B（L0-P 扩展） | 依赖 C1 门面先行 |
| B7 认知库 PG 镜像评估 | 保留在 SPEC-B（L0-P 扩展） | 依赖 C4/C5 收编经验 |
| B8 REA 符号图与 41 互通 | 保留在 SPEC-B（L0-P 扩展） | 依赖 C2 port 定义 |
| B9 能力健康聚合 | C12（L0-S 可视） | 继承并扩展到调度 |

**合并结论**：SPEC-B 的协同化项（B1/B3/B4/B9）由本 SPEC 接管并重排；SPEC-B 保留存储/索引扩展项（B6/B7/B8）作为 L0-P 的后续批次，且**必须排在 C1/C2 之后**。数据链内功轨道（as_of / symbol_map / DataSource 窄接口 / 特征注册表 / Pandera / TimescaleDB）与本 SPEC 并行，不受影响。

## 8. FAIL-OPEN 与零回归

| 项 | 降级策略 |
|---|---|
| C1 门面公共化 | 仅新代码接入；34 原调用路径不动；门面异常返回 `degraded` 信封不抛错 |
| C2 port | adapter 缺失 → 返回 `degraded`（`upstream_unavailable`），上层按现有逻辑兜底 |
| C5 直连收编 | 按模块开关；任一批异常可单独回退，不影响其他批次 |
| C6 能力声明 | 声明文件缺失/损坏 → 校验降级为告警，不阻断构建 |
| C7 统一检索 | 单后端超时/异常 → 剔除该后端，返回其余并标 `degraded`；**全部后端不可用 → `ok=false, error_code=all_sources_unavailable`**（禁止伪装成"无结果"） |
| C8 事件互通 | record 失败仅日志+告警，任务本身已成功；`external_id=run_id` 唯一约束防止重复记忆；record 触发索引重建改为批量/去抖 |
| C9 调度 | `job_runs` 不可写 → 仅执行不记账（降级）**但必须打 ERROR 并计入"连续 3 窗无 run"告警**，不允许静默 |
| C10 门禁 | report-only 期不阻断；enforce 需存量清零评审（包化前用 grep 白名单，不启用 import-linter） |

## 9. 验收标准（SPEC-C 整体）

- [x] **G0 门禁（开工前置，2026-11-01 复核）**：G0-1~G0-8 全关闭 —— G0-1/2/3 由 `test_g0_invariants.py` 守卫（无明文口令、`_FIS_P0_HOME` 外置、无模块级 `sys.path.insert`）；G0-4 `l0-contracts.yml` 阻断 job（无 `continue-on-error`，含 validate_capabilities + C10 ratchet + 契约测试）；G0-5 `health-check.sh --record-good` 已接入 `31/phase1/update.sh` 部署末尾；G0-6 `init_db_schema` 只在 `19-DAL/.../schema_init.py`；G0-7 `31/phase1/logrotate-dreambuddy.conf`；G0-8 见下方专条
- [x] **P0 已完成（2026-11-01 复核）**：C1 门面包 `dreambuddy_l0/`（W3，4b8ac0460b）；C2 六 port + 六 fake + 方言能力集 + 9 条契约测试（W4，f1f8568500）；C3 直连基线仪表 report-only（`scripts/check_db_direct_imports.py`，基线 188 处/89 文件，f1daae7790）；C7 `unified_search` 经 `Search` port 分发三后端（41/Chroma/recall，min-max 归一化 + 全降级 `all_sources_unavailable`，df1310c960）
- [x] **C4a / C4b 已完成（2026-11-01 复核）**：PG 第四后端 `PostgresTradeRepository` + 契约测试（类型映射/事务/分页/daily_stats upsert，335836e160 + c6ad3ee73a + DSN 权限修复 c50d210eae；本地无 DSN 时 6 条 skip，云端 125 passed 全跑）；`dc_pg` 收编为 39 薄壳 → `DataCenterQueries`，字段级比对 8 项全 MATCH、调用方零改动（7e46d30c07）
- [ ] **C5 进行中（独立轨道，不阻塞 C6-C13）**：前置已完成（DualWrite 字段级 diff + per-repo 读开关 + shadow diff 率门槛，0b1e73c020）；11-易经 `force_vector` 首批 4 文件收编（41a70b35f8）、第二批 4 文件收编（db2799982e）、第三批 `five_domain_sqlite_reader` 2 处收编（新增 `_five_domain_store_port.py` + 开关 `FD_STORE_PORT` + 10 条契约测试，含 legacy/port 逐字段等价 + top10 同批次 id 区间语义 + 只读红线）；**第四批 `bcrm2` 只读收编 `0ec862f923`**：新增 `bcrm2/_store_port.py`（`SqliteReadOnlyPort` + `fetch_records_by_sources(as_tuple)` + `fetch_table_rows`），`macro_data_fetcher` 2 处 records 只读（开关 `BCRM_MACRO_STORE_PORT`）与 `incremental_learner` `get_model_versions`/`get_trades_for_retraining`（开关 `BCRM_LEARNER_STORE_PORT`）改走 port；**写路径 6 处 + learner 聚合读 1 处（AVG/SUM 无法用 port 表达）按 SPEC 暂缓保留 legacy**，剩余 connect 数 macro=2 / learner=5；新增 11 条契约测试（legacy/port 逐字段等价、as_tuple 下标语义、FAIL-OPEN、write 未开放、写路径暂缓红线）；memory_l4 **1806 passed / 1 skipped**、L0 目录 **140 passed / 6 skipped** 回归通过；本地真实 `data_center.db` 上第三批 74 键、第四批 panewslab/blockbeats **263 列 + new_sources 38 列**逐字段相等（0 diff）；云端契约测试 **11 passed** + ratchet 通过；白名单 11 系统共 **20 个条目**（17 个仍含 legacy 直连、3 个为已收编集中点 `force_vector/_store_port.py` / `_five_domain_store_port.py` / `bcrm2/_store_port.py`）；因默认 legacy 行为零变化，**本批不涉及写路径，无需实盘重启窗口**（`0-系统文档管理/db_direct_whitelist.tsv`）；**第五批 `4e95b844b8`**：`_five_domain_store_port.py` 新增 5 个只读 helper（`fetch_distinct_dates` / `fetch_rows_by_sources_until`（`date(timestamp)<=?` 与 `timestamp<=?` 双形态）/ `fetch_latest_row` / `fetch_latest_rows_for_pairs` / `fetch_top10_inflow_until`），`five_domain_ic_analysis.py` 5 处（开关 `FD_IC_STORE_PORT`）与 `backtest_five_domain_v2.py` 3 处（开关 `FD_BT5_STORE_PORT`）只读直连收编，两文件 connect 归零、白名单删行（port 行 3→8）；14 条契约测试（开关关/开逐字段等价、双时间过滤形态、top10 id 区间、FAIL-OPEN、legacy 异常上抛红线）；memory_l4 全量 **0 failed**（1 网络 smoke 复测通过）、L0 shared 全绿；真实 `data_center.db`（1395 日期，2022-12-31→2026-10-29）函数级 + helper 级开关关/开全等；ratchet exit=0；backtest 为 legacy 模块级执行脚本（不可 import 回归），存量风格经 ruff per-file-ignores + black force-exclude 豁免不重排；默认 legacy 零变化，**无需实盘重启窗口**；**第六批 `634a6f6af2`**：`_probe_sqlite_records.py` 1 处 mode=ro 只读探针收编（新增 `fetch_all_rows_id_desc`，开关 `FD_PROBE_STORE_PORT`），5 条契约测试（等价/FAIL-OPEN/legacy 上抛/双模块对象打桩），真实 `data_center.db` 33244 行 probe 输出开关关/开逐字节一致，ratchet exit=0；其余 14 个 legacy 条目分类处置——写路径 5 文件 12 处（`bcrm2/incremental_learner` 5 / `macro_data_fetcher` 2 / `bcrm2/storage` 1 / `kg_store` 1 / `backfill_fma_shadow` 3）按"只读先行"暂缓、`daily_report_system` 4 处读 `~/Library/.../WorkBuddy/automations.db`（项目外 DB，不属 records port 语义）、8 个测试/验证文件 11 处为 tmp_path 种子脚手架（登记保留非收编目标）；白名单 11 系统剩 **17 个条目**（14 个 legacy + 3 个收编集中点）；**第七批 `ed222cb966`**：`bcrm2` 写路径 9 处收编——`incremental_learner` `_init_db/add_trade/add_trades_batch/save_model_version` 4 写方法（connect 5→1，仅剩聚合读 AVG/SUM 按 SPEC 暂缓）+ `macro_data_fetcher` 缓存读写 2 处（connect 2→0、删除模块级 `import sqlite3`）+ `backfill_fma_shadow` 3 处（connect 3→0，清除+插入合并为 `purge_and_insert_shadow_rows` 单事务原子调用）；`_store_port.py` 新增 `_connect_rw/_connect_ro` 工厂 + 6 写助手（`init_learner_tables/insert_trade/insert_trades_batch/upsert_model_version/save_cache_dataframe/purge_and_insert_shadow_rows`）+ 4 读助手（`load_cache_dataframe/fetch_regime_rows/fetch_shadow_stats/fetch_shadow_eval_records`），全部带 `switch` 参数、port 分支异常 `except Exception` 回退 legacy 内联实现（**fail-safe：保持久性而非 FAIL-OPEN 返回空**；全部写操作幂等——INSERT OR IGNORE/REPLACE、CREATE IF NOT EXISTS、DELETE+重插、`to_sql replace`——回退重放安全）；新增开关 `BCRM_BACKFILL_STORE_PORT`（复用 `BCRM_LEARNER_STORE_PORT`/`BCRM_MACRO_STORE_PORT`）；13 条契约测试（开关关/开全表 dump 等价、返回值一致、port broken 回退落盘、默认 legacy、HOLD 过滤、双模块对象登记红线）；memory_l4 + L0 shared 回归全绿（149 passed/6 skipped），C5 两批契约 25/25（本地+云端）；真实数据等价（`python3 -` stdin 双跑）：evolution.db 只读 3 助手开关关/开全等（regime 2000 行、shadow stats/eval 29325 行）、purge_and_insert 副本 old_count=29325 dump 全等、learner 真实库 insert=50/batch=1/upsert=True dump 全等（trades 49→51）、macro 缓存 100 行 dump 全等；ratchet 本地+云端 exit=0；白名单变化：`_store_port.py` 3→15、`incremental_learner.py` 5→1、删 `macro_data_fetcher.py`/`backfill_fma_shadow.py` 两行、新增契约测试文件 1 行，11 系统剩 **15 个条目**（12 legacy + 3 收编集中点）；剩余 3 处写路径暂缓：`incremental_learner` 聚合读（AVG/SUM port 不可表达）、`storage.py` 与 `kg_store.py`（连接持有型、25 方法共用连接、autocommit+WAL+FTS，需 port 句柄抽象单独立项）；**开关默认关=合并零风险；实盘切流（开开关）需单列重启窗口**；**第八批 `7e5d455809`**：第七批暂缓的 3 处全部收编，"port 句柄抽象"以**纯透传连接工厂**最小落地——`connect_persistent`（`check_same_thread=False` 透传，供 `EvolutionStorageSQLite` 多线程读取）与 `connect_autocommit`（`isolation_level=None` 透传，供 `KGStore` WAL+FTS），参数与原直连逐字节等价故**无开关**，`row_factory`/PRAGMA/DDL/重试逻辑留调用方；learner 聚合读新增 `fetch_recent_performance`（`_RECENT_PERF_SQL` 常量，port 分支 `_connect_ro(row=False)` 同 SQL，异常回退 legacy，复用 `BCRM_LEARNER_STORE_PORT`），`incremental_learner` connect 1→0 并删 `import sqlite3`；`storage.py`/`kg_store.py` connect 各 1→0（`import sqlite3` 保留供 `Row`/`OperationalError`）；`_store_port.py` connect 15→18，白名单删 learner/storage/kg_store 三行，11 系统剩 **12 个条目**（9 legacy = daily_report 项目外 DB 1 + 测试/验证脚手架 8；3 收编集中点）；新增 6 条契约测试（聚合读双模式等价/回退落盘/空表 `{}`、双工厂实例化验证 row_factory/isolation_level/WAL），第四批红线同步 learner 1→0，两批契约 **31/31 本地+云端全绿**；memory_l4 **1806 passed/1 skipped**、L0 shared **179 passed/6 skipped**；真实数据等价：learner 真实库（49 笔 trades）开关关/开 `get_recent_performance` 全等、evolution.db 2000 行 regime 与 kg 库 93 triples 副本工厂打开验证；ratchet 本地+云端 exit=0；pyproject 对 storage/kg_store 加存量风格豁免（同第五批先例：仅 2 行工厂改动，不重排 1400+ 行存量）；**11 系统 bcrm2 业务代码直连全部清零，C5 收编阶段收官；legacy 仅剩 daily_report（读项目外 automations.db，不属 records port 语义）与 8 个测试/验证文件（tmp_path 种子脚手架，登记保留）**
- [x] **C6 能力声明已落地（2026-11-01）**：五能力声明可机器读取；`validate_capabilities.py` 可拦截 port/impl 漂移；接入 `l0-contracts` 阻断 job
- [x] **G0-8 已关闭（2026-11-01）**：`external_id` 幂等（含存量库迁移）+ `record(idempotency_key=)` 契约入口 + P0-11 索引重建去抖；C8 开工前置解除（另有 9 条契约测试入阻断 job）
- [x] **C9 本地 + 云端已落地（2026-11-01）**：任务注册表可查询；幂等 run key / UTC 窗口 / 5min 容忍 / 跨窗拆 run / missed_run+连续 3 窗告警 / 90 天保留均有契约测试；job_runs 只经 Store/Event port 落库（JSONL adapter；PG adapter 待接入，可复用 C4a 已落地的 19-DAL PG 后端）；`audit(host=)` 限定本机任务，避免云端误判 local 任务缺失。云端三段真实 run 已复跑（见 §6 C9 行证据），41 cron→`index-reconcile.timer` 归零完成，`job-runs-audit.timer` 每小时审计+保留
- [x] **C8 本地 + 云端已落地（2026-11-01）**：`job_runs` 终态 → 认知 `record` 同进程回调（`external_id=run_id` 幂等），FAIL-OPEN（record 失败只告警+发 `scheduling.memory_record_failed`，不回滚 run）；`memory_enabled()` 云端（PG 后端）默认开、本地默认关；云端实测同一 `dc.collect.cloud@5978430` 两次写入返回同一 memory_id（`memories` 按 external_id 计数=1），重启调度器后真实窗口 `dc.collect.cloud@5978431` 自动产出记忆，且该记录可被 `recall` 命中（top-1）；16 条契约测试入 `l0-contracts` 阻断 job
- [x] **C10 本地 + 云端已落地（2026-11-01）**：`scripts/check_db_direct_imports.py --ratchet` 白名单 ratchet（只减不增）接入 `l0-contracts` CI 阻断步骤，白名单外新增直连即红；契约测试 `test_c10_direct_gate.py` 入阻断 job；本地与云端复核 ratchet exit=0（d17abcb854）
- [x] **C11 本地 + 云端已落地（2026-11-01）**：检索命中 → `SearchJobTrigger.on_search` 按 task_key `enqueue` pending job（去重键 `task_key:sha1(ref)[:12]@window`，开放态计入 `max_concurrency`，失败信封不排 job，FAIL-OPEN）；11 条契约测试入阻断 job；云端实证命中 41 文档 → `index.reconcile.cloud@498204` pending 落盘，30s 内重复命中判 `duplicate`（3e0db93c2c）
- [x] **C12 本地 + 云端已落地（2026-11-01）**：`collect_l0_health` 聚合 job_runs 分项（跑没跑/终态成功率/最老开放态滞留/missed streak 告警 + 降级原因分布）+ 五能力 `health_cmd` subprocess 探活（cwd=repo_root，不依赖 systemd/launchd 内部状态），挂接 cognitive `health` 的 `result["l0"]`（FAIL-OPEN，基础载荷零回归）；16 条契约测试入阻断 job；两端冒烟 host 自动识别、五能力全 ok、云端 tasks 恰为 4 个云端任务（bfaec659d6）
- [x] **C13 本地 + 云端已落地（2026-11-01）**：launchd/systemd 只读旁路 `sidecar.py`（不改 `ExecStart`/plist；launchd `print gui/<uid>/<label>` 优先 + plistlib 日志 mtime；systemd `LastTriggerUSec` 兼容新版格式化时间戳；审计先行的 `missed_run` 行可被旁路后到证据升级为真实终态），注册表新增 `os.dbsync.local`（600s）+ `os.memory-cleanup.cloud`（6h），cli 增 `sidecar` 子命令；17 条契约测试入阻断 job；两端实证 `os.dbsync.local@2986511`、`os.memory-cleanup.cloud@83031` succeeded 且二次扫描 `duplicate`，实盘进程零改动（760bb0377d + da5a04e425 + 02f7becf86）
- [x] P2 后：一次采集可产出可 recall 的认知记录且重复执行不重复写入（`external_id` 生效，**C8 已达成**）；三条链路有 `job_runs` 记录且幂等生效（UTC 窗口，**C9 已达成**）；grep 门禁可拦截新增直连（**C10 已达成**）
- [x] P3 后：检索可触发可追踪任务（**C11 已达成**）；health 含五能力 + 调度分项（**C12 已达成**）；**每端各 1 个**非实盘周期任务在 `job_runs` 可见（**C13 已达成**）
- [x] **全量回归（2026-11-01 复核，二次复核已更新）**：本地 `44-三端协作架构系统/shared/tests/` **140 passed / 6 skipped**（较首次复核 +21：C5 第三/四批契约测试并入；skip 均为 PG DSN 未配置的 C4a 用例）；云端同目录 **146 passed**（venv 含 numpy + PG DSN，无 skip）；`memory_l4` 全量 **0 failed / 0 error / 1 skipped**——复核发现存量 14 FAILED（`_compute_zhi/xin/ren/yan/strategy_completeness/backtest_verification/review_iteration` 已加 `cls` 必填参数、14 处测试调用未同步）+ 6 ERROR（`test_global_trade_l4.py` 手工集成脚本被 pytest 误收集），本轮以 `fbbc1a251a` 清零（测试调用补 `"crypto_usdt"`；脚本 `__test__=False` 禁收集 + sys.path 修正为 memory_l4 目录；唯一 skip 为 `/tmp/p0_trade_samples.json` 数据依赖）；`tsc --noEmit` 0 errors（3.1-FRONTEND，补齐缺失的 `minisearch` 依赖后）；云端 health 探测 `ok=true / degraded=false / 五能力全 ok`；实盘进程生命周期未改变（`systemctl show ActiveEnterTimestamp`：trailing-stop-runner 与 v15-api 自 2026-10-17 01:51、yijing-polling-trader 自 2026-10-31 08:43 持续运行，均早于本轮改动；datacenter-scheduler 的 2026-11-01 重启属 C8 落地预期；6 个实盘相关 unit 全 `active running`）
- [x] **云端一致性验收（2026-11-01 复核，二次复核已更新）**：云端 `43.160.201.117` 与本地/origin 三端对齐（存量红测修复 `fbbc1a251a` 已 ff 同步）—— validate_capabilities `OK`、C10 ratchet `exit=0`、契约测试 146 passed、`collect_l0_health(host="cloud")` 返回 `ok=true` 且 tasks 恰为 4 个云端任务（`dc.backfill.cloud/dc.collect.cloud/index.reconcile.cloud/os.memory-cleanup.cloud`）、`degraded_reasons={}`，与本 SPEC 记录基线一致
- [x] **五维验收（2026-11-01）**：C11/C12/C13 各自的症状复测、日志/落盘证据、回归、影响面、边界证据见 §6 三行证据列；影响面 = 纯新增只读模块（无实盘 unit/`ExecStart` 改动，实盘 ActiveEnterTimestamp 早于改动即证）；边界 = FAIL-OPEN（store/registry/声明文件/探针单项故障只标 `degraded`、不抛错不拖垮整体），由对应契约测试覆盖

## 10. 风险

- **C1 曾被评为最大回归面（已收缩）**：原方案要把 34 的 11 个 scope 全量迁移，评审判定不可接受；现改为"只抽信封与注册机制供新代码用"，34 原路径不动。
- **C5 是体力活且不进关键路径**：61 处集中在 11 系统，代码形态各异（脚本/服务/测试），按"服务 → 脚本 → 测试"顺序推进，**任何时候都可暂停而不影响 C6-C13**。
- **C9 只纳管非实盘链路**：`dc-scheduler` 内嵌采集与回填，属可纳管范围；`dreamos` / `yijing_trading` / `v15` / `trailing-stop-runner` / `yijing_live_300s` 等含交易逻辑的进程**不内嵌记账**，其心跳误判会导致同一 `logical_window` 被回收后新 run 被唯一约束拒绝，任务静默停摆——这类进程只用**只读旁路**（C13），禁止改其 `ExecStart`/plist。
- **C8 无跨库事件**：默认 `job_runs` → record 同进程回调，`external_id=run_id` 幂等；避免"已写认知、未提交状态"的重投污染 recall 与 verify 计数。若后续引入 PG outbox，必须与认知同库或接受重复消费。
- **认知幂等不成立（评审 P0-7）**：现状 `record()` 无幂等入参、记忆 ID 含毫秒，同一 run 会写多条并触发 verify 反复升级置信度；G0-8 未关闭前不得开工 C8。
- **切库假 MATCH（评审 P0-9）**：`DualWrite` 新库写失败仅 `warning`、影子比对只比长度（`di.py:177`），一开读开关就可能读空/读旧；C5 前必须补字段级 diff + diff 率门槛 + per-repo 开关。
- **无 PG 后端（评审 P0-8）**：19-DAL 只有三种后端，`dc_pg` 能力无处可搬；必须先做 C4a。
- **资源争抢（评审 P0-11）**：`record()` 现状会 `Popen` 触发 41 索引重建，云端 4 核下会与止损/轮询争 CPU；必须批量/去抖，非实盘 unit 限 CPU。
- **C6 声明漂移**：声明与实际实现不一致会退化为第二份文档，CI 须校验 `health_cmd` 可执行、`provides` 有对应 port。
- **顺序风险**：若把 C7 之后立刻做 C9（调度），`job_runs` 必须经 L0-P 的 `Event` port 落库（不得直连 PG），否则换库时调度层重写。
- **本地代理失真（本轮新增）**：本地 macOS 的 launchd 25 服务、SQLite 主库、无 cron，**不能代表云端运行时**（云端 systemd 74 单元/26 timer、PG 主库+SQLite 遗留、1 条 cron）；凡只在本地验证的结论，一律标记"待云端复核"，禁止据此宣称交付完成。云端 4C16G 内存与 180G 磁盘也限制"新增常驻进程"的方案（见 §3.2 组件①）。
- **运行数据双向漂移（代码已对齐后仍存在）**：两端 HEAD 已同为 `4d6837f880`、`.py` 改动均为 0，但运行态产物各自生长（本地 13 个 `backtest_cache` json + 2 份未提交部署文档；云端 `pool.json` + 3 个 REA 新样本）。**结论只以 commit 为准**，禁止用运行数据差异推断代码差异；需要对齐运行数据时按 phase11 `11-full-migrate.sh` 走单向同步，不做双向 merge。
