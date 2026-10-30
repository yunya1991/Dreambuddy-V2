# L0 底层通用能力底座 — 深度调研报告

> 日期：2026-10-30
> 来源：本地架构审计 + 4 维多源调研（传统金融 / 代码工程 / AI 训练 / GitHub 量化项目）+ 交叉验证
> 5 维评分：8.2 / 10（完整性 8、可落地性 8.5、工程适配性 9、风险识别 8、创新性 7.5）
> 上游：开工SKILL 阶段 1 问题定义包（v3，用户已确认）

## 一、命题与约束

**命题**：梳理 L0 底座（认知五类四层 + 18/20/19/21/38/41/33）完整架构与数据流，从架构和数据流层面验证底座对下游的支撑能力，对标成熟实践输出优化路线。

**主要矛盾**：单模块已验证 vs 底座整体未验证；认知五系统闭环 vs 数据底座链路的衔接未系统梳理；自建底座 vs 成熟范式未对标。

**约束**：单人维护、FAIL-OPEN、云端 4C8G、禁止 MLflow/K8s 等重型工具、评审只读。

## 二、本地架构审计结论（现状）

### 2.1 L0 数据流主链路契约（已实证）

```
18 采集 (scheduler.py: collect_once → dc.fetch → sink_postgres 落 PG data_center.records)
  → 20 清洗 (dispatcher.py L260-326: EN_SILVER 开关 → DataCleaningPipeline.clean → QualityGate 拦截，失败丢弃+审计留痕)
  → PG data_center.records (id/dedupe_key/source/category/timestamp/metrics/events/timeseries/raw)
  → 19-DAL 回填 (scheduler._run_backfill 周期执行 → backfill_18_records.py L81-132 提取数值指标 → dreambuddy_core.db mm_metrics, 71k+ 行)
  → 21 特征 (feature_hub/h3_wrapper.py L74-143: FeaturePipeline.run，异常 FAIL-OPEN 回退原始特征)
  → 7 个下游消费方
```

**下游消费方（代码实证 7 个）**：12-ML `ml_strategy.py`、9-基本面 `dal_snapshot_provider.py`、10-经典指标 `Bot2StrategyTrend.py`、4-MEMORY `seed_genes.py`、40-周期神经网络 `p6_e0_token_sequence.py`、11-易经 `feature_registry.py` + `bcrm2_adapter.py`。

### 2.2 认知五系统衔接点（35-SPEC §0.1/§4 已定义）

认知系统(4-MEMORY) ↔ 知识库(2-KNOWLEDGE) ↔ SKILL管理(registry) ↔ 文档管理(0-) ↔ 索引系统：突触为 `record_hook/verify_hook`、record→RAG、auto_register_skill→doc-sync、doc-sync→verify（P0-P3 24/24 已验收）。**认知↔数据链衔接点**：seed_genes 消费 21 特征、recall 注入 L3 即时记忆、D4 评审复用 data-troubleshoot。

### 2.3 本地审计发现的架构 gap（按严重度）

| # | gap | 证据 |
|---|---|---|
| G1 | 18 采集层无统一 DataSource 窄接口抽象，collector 按 category/source 字符串路由，契约靠约定 | data_center/core/dispatcher.py L178-190 |
| G2 | 特征无 point-in-time 语义，7 个下游各自取数，存在"看到未来"口径风险 | h3_wrapper.py 无 as_of 参数 |
| G3 | 特征定义散落代码中，无注册表（名称+表达式+依赖+新鲜度声明） | feature_hub 目录 |
| G4 | 33-REA 架构健康只出报告，未形成 CI 门禁（分层违规不会失败） | 33-REA逆向解析工程/ |
| G5 | 41-文件索引基于规则/正则，缺 AST 级符号/引用图 | 41-文件索引系统/core |
| G6 | 无 symbol_map（同一资产多源多码），下游口径靠各自处理 | 18 records 表无 canonical_id |
| G7 | 数据血缘靠人工记忆，无任务运行表（job/inputs/outputs/ts） | 全链路 |
| G8 | 38 冷热分层 SPEC 已定稿（2026-10-17）但未全部实施；scripts/ 下仅 sync_intent_registry.py | 38-数据库管理系统/ |

## 三、4 维调研结论

### 3.1 传统金融数据平台底座

**关键范式**：①Security Master/统一符号体系（OpenFIGI，内部 ID↔多外部符号映射表）；②DAMA 六维数据质量（完整/准确/一致/时效/有效/唯一），每维阈值即门禁；③数据契约左移（契约即代码、Git 版本化、进 CI）；④血缘轻量路径——OpenLineage 价值依赖 Airflow/dbt 生态，纯手写管道拿不到免费血缘；⑤时序冷热分层三件套（TimescaleDB hypertable 分区+压缩 90%+retention policy 声明式下沉 Parquet）。

**可借鉴**：G6→建 `symbol_map`（exchange_symbol↔canonical_id，最便宜最防坑）；20 清洗按 DAMA 六维设阈值断言（不引 GE 全家桶）；G8→K 线大表用 TimescaleDB 扩展替代手工归档；G7→用"任务运行表"轻量实现血缘（每次任务写一行）。

**不引入**：Marquez/DataHub、Refinitiv 级 security master、GE 完整套件。

### 3.2 代码工程底座

**关键范式**：①Bazel/Pants 核心价值是依赖图+affected 分析，但 setup 成本对单人极高；②架构守护=Fitness Function（架构约束变成 CI 自动失败的测试）；③Python 原生架构守护成熟——import-linter（YAML 声明 layers/forbidden 契约，CI 执行）；④代码索引现代底座是 tree-sitter（GitHub/Sourcegraph 均从 ctags 迁移），SCIP 把定义/引用落盘为可查询结构。

**可借鉴**：G4→33-REA 引入 **import-linter**（pip 级零基础设施），把 L0→DAL→特征→交易分层写成 layers 契约进 CI，架构健康从"报告"升级为"门禁"——性价比最高；G5→41 索引用 tree-sitter Python 绑定重建符号图，SQLite 存储与现有栈一致；受影响面分析用 `pytest --lf`+自维护 import 图。

**不引入**：Bazel/Nx/Turborepo、Sourcegraph 自部署、ArchUnit（借思想）。

### 3.3 AI 训练基础设施（轻量）

**关键范式**：①Feature Store 最小三件套=离线存储+在线存储+**point-in-time join**（防数据泄漏）；Feast quickstart 即 Parquet+SQLite 本地组合；②Pandera 单 pip、schema 即 Python 类、pytest 原生集成，小团队首选；③轻量模型注册=DVC（Git 指针+对象存储）；**我们 registry.json（versions/state/promote）正是 MLflow 状态机的文件式类比，属行业认可的合理取舍**；④持续训练成熟模式=定时重训+walk-forward+challenger-champion 门控。

**可借鉴**：G2→feature_hub 引入 `as_of` 时间戳语义，7 个下游统一禁止看到未来（Feast 最值得抄的一条）；G3→特征定义注册表化（配置驱动）；20 清洗用 Pandera schema 补强手写校验；训练后验证门控（不优于现役不 promote，registry.json 已能承载）。

**不引入**：Feast/Hopsworks 完整框架、TFDV、GE 全量、MLflow、漂移触发重训。

### 3.4 GitHub 成熟量化项目数据层

**关键范式**：①qlib 三层（raw→.bin 缓存→表达式引擎+三级缓存）——表达式懒计算+缓存命中值得抄，.bin 私有格式不抄；②Lean 统一事件流（Slice 视图，Time Frontier 天然防未来函数）；③vnpy 双层抽象——`BaseDatafeed`+`BaseDatabase` 窄接口多后端适配器；④zipline bundle 全量快照笨重。

**可借鉴**：G1→18 采集层定义统一 DataSource 窄接口（load_bars/save_bars/load_snapshot），DAL 只面向抽象（vnpy 模式）；qlib 式日历/instrument 注册表（交易日历一等公民）；G3→经典指标类特征用"声明式表达式+计算结果缓存"（Redis 已在栈内，注意锁残留）；下游统一"某一时刻全量可见数据"切片接口（Slice 思想）。

**不引入**：.bin 私有格式、zipline bundle、Lean 全事件驱动引擎（与 timer 轮询架构冲突）、backtrader feed 体系。

## 四、交叉验证

### 4.1 矛盾项清单

| 冲突 | 各维立场 | 倾向结论 |
|---|---|---|
| 特征计算引擎 | qlib 表达式引擎 vs 现有硬编码 h3_wrapper | 借"声明式表达式+缓存"思想渐进改造，不重写 |
| 数据架构范式 | Lean 事件驱动 vs 现有 timer 轮询 | 保留轮询，仅借 Slice 统一视图思想 |
| 质量框架 | GE/Soda 契约 vs 现有手写 QualityGate | 用 Pandera 补强（pytest 原生），不引 GE |
| 血缘 | OpenLineage vs 任务运行表 | 任务运行表（轻量、无新服务） |

### 5 维评分：8.2/10，无阻断项，进入报告合成（本报告）。

## 五、可落地结论（SPEC-B 输入候选，按优先级）

| 优先级 | 项 | 借鉴来源 | 解决 gap |
|---|---|---|---|
| P0 | feature_hub 加 `as_of` point-in-time 语义 | Feast | G2 |
| P0 | import-linter 分层契约进 CI（REA 升级为门禁） | Fitness Function | G4 |
| P1 | `symbol_map` 统一符号映射表 | Security Master | G6 |
| P1 | 18 采集层统一 DataSource 窄接口 | vnpy | G1 |
| P1 | 特征定义注册表（名称+表达式+依赖+新鲜度） | Feast/qlib | G3 |
| P2 | 任务运行表轻量血缘 | OpenLineage 思想 | G7 |
| P2 | 20 清洗 Pandera schema 补强 | Pandera | — |
| P2 | 41 索引 tree-sitter 化 | SCIP/tree-sitter | G5 |
| P2 | K 线大表 TimescaleDB 分区+压缩 | TimescaleDB | G8 |
| P3 | qlib 式日历/instrument 注册表、表达式缓存 | qlib | G3 |

## 六、风险与待验证

- point-in-time 改造触及 7 个下游消费方，需逐个 FAIL-OPEN 灰度（HC-1a/零回归）
- TimescaleDB 扩展引入需云端 PG 实例支持验证（4C8G 资源评估）
- import-linter 契约初版会暴露存量违规，需先 report-only 再转 enforce
- 待验证：21 特征当前是否有隐式时间对齐；38 归档方案4迁移完成度

---

## 七、能力矩阵与协同主线专项调研（2026-10-30 补充，用户确认口径）

> 用户口径：五大能力组 = **①广义认知系统 ②数据采集系统 ③检索系统 ④PostgreSQL 数据存储管理 ⑤REA 逆向解析能力**；协同主线 = **认知-数据-工程解析-数据存储-检索入口**。目标从「五个能跑的能力」升级为「一个协同的能力矩阵」。

### 7.1 五能力能力矩阵（代码实证）

| 能力组 | 对外接口（文件:行） | 核心存储 | 协同状态 |
|---|---|---|---|
| ①广义认知 | MCP: recall/record/verify/stats/health（4-MEMORY/9-工具与接口/cognitive_mcp_server.py:5-17, 58-170）；record 已接线 TAG_HOOKS+record_hook+knowledge-ingest 标记（L393-474）；verify 已接线 verify_hook+skill_hooks（L477-515）；IntentRouter 聚合记忆+SKILL+知识RAG三检索源（cognitive_loop_entry.py:312-347） | cognitive_memory.db(SQLite) + ChromaDB + bayesian_memories.json | MCP 面完整✅；与数据链/REA 无事件互通❌ |
| ②数据采集 | BaseCollector.fetch（18-数据获取中心/data_center/collectors/_base.py:13-28）；Registry 注册表（core/registry.py:11-31）；dispatcher(category,source) 路由（core/dispatcher.py:37-149）；scheduler.collect_once（scheduler.py:80-129） | PG data_center.records（sink_postgres.py:54-100）+ get_sink() 后端切换（L412-418） | 注册机制✅；无统一 DataSource 窄接口（G1）⚠️；采集/清洗/回填事件不入认知❌ |
| ③检索系统 | **三入口分裂**：41-SearchAPI.search()（41-文件索引系统/api/search_api.py:77-108；L1文件名+L2倒排+L3向量合并 core/searcher.py:81-117）；ChromaDB RAG（2-KNOWLEDGE）；认知 recall（MCP） | SQLite 索引 + ChromaDB | 各自为政❌；RAG 不索引 PG 数据；41 只索引文件 |
| ④PG数据存储管理 | sink_postgres write/read_all/query_records/latest_records（L166-238）；migrate_to_postgres.py:44-87（records/metrics/quality_issues/alerts 四表迁移+行数校验）；冷热分层/归档/dal-backup（38-数据库管理系统/SPEC-方案4 L17-37） | PG16 三库(dreambuddy/data_center/fis) + Redis7 + MinIO | 读写接口完整✅；SQLite→PG 迁移进行中⚠️；无统一元数据目录/血缘（G7）❌ |
| ⑤REA逆向解析 | PythonAnalyzer.analyze(path) → AnalyzeResult+Evidence（33-REA逆向解析工程/README.md:17-27；SPEC.md:145-200）；Evidence-First 四层事实分级（SPEC.md:45-78） | 文件（报告/JSON） | 单机能力完整✅；产出无消费者（不入认知、不进 CI 门禁 G4）❌；与 41 索引不互通 |

**衔接亮点（已通）**：RAG→认知写入桥 memory_bridge.py:161-218（检索结果 record 为 C 级记忆并持久化 memory_id↔source 映射）；dal_snapshot_provider.py:711-872 连接 19-DAL 与 21 特征管道。

### 7.2 协同主线断点清单（认知-数据-工程解析-存储-检索）

| # | 断点 | 证据 |
|---|---|---|
| S1 | 数据链事件对认知不可见：采集/清洗/回填全程无 record 调用 | scheduler.py:80-203 审计未发现认知调用 |
| S2 | REA 产出（报告/Evidence）不入认知库，架构知识无法被 recall | 33-REA 内未发现 record 调用 |
| S3 | 检索入口三分裂（41索引/Chroma/recall），无统一路由 | search_api.py vs memory_bridge vs cognitive recall 各自独立 |
| S4 | PG 存储无检索暴露：RAG 不索引 PG、41 只索引文件，存储数据只能 SQL 直达 | 2-KNOWLEDGE 仅文件源 |
| S5 | 认知库与主存储分裂：cognitive_memory.db 为 SQLite，与 PG 主存储无双写/一致性机制 | 4-MEMORY/data/ |
| S6 | 五能力无机器可读能力声明（无 provides/consumes/health 注册表），能力地图靠文档记忆 | 全仓库无 capabilities 描述文件 |
| S7 | REA 架构健康只是报告不是 CI 门禁（= 原 G4） | 33-REA 只出报告 |

与原 G1-G8 映射：S7=G4；S1 扩展 G7（血缘→事件流）；S3/S4 为新增检索维度断点；S6 为新增能力矩阵元层断点。

### 7.3 外部对标：能力矩阵与协同闭环范式（2024-2026）

**能力矩阵范式**：Backstage catalog-info.yaml（每组件一个 YAML 描述符，kind/metadata/spec/relations 声明 dependsOn/providesApi，**文件即能力地图，无需运行 Backstage 本体**）✅直接借鉴；Open Data Mesh DPDS 用五类 port（input/output/discovery/observability/control）显式声明协同契约 ✅借鉴 port 概念；Gartner Data Fabric（主动元数据+知识图谱）与 Palantir Foundry Ontology（object/link+action+OSDK）思想借鉴、平台不引入。

**认知-数据-检索闭环共性**（Mem0 / Zep / Letta / Cognee）：写入管线（Mem0 两阶段 LLM 抽取+ADD/UPDATE/DELETE/NOOP 对账）→ 图/向量双存 → 多模式检索（Cognee 14 种检索模式自动路由）→ MCP/SDK 注入上下文。Zep 卖点是**多端读写同一张图**；Letta 上下文每轮从 DB「编译」。

**轻量协同机制（开源佐证）**：PG 单表 outbox 代 Kafka（业务写与事件写同事务，worker 轮询发布，零新设施）✅最契合现状；MCP 聚合网关（IBM ContextForge / AWS MCP Gateway & Registry）思想借鉴、自建 thin proxy。

**不引入**：DataHub / OpenMetadata / Kafka / Backstage 运行时（运维过重）。

### 7.4 能力矩阵化落地建议（SPEC-B 输入，按优先级）

| 优先级 | 项 | 借鉴来源 | 解决断点 |
|---|---|---|---|
| P0 | capabilities.yaml 能力注册表（五能力声明 provides/consumes/health/port） | Backstage/DPDS | S6 |
| P0 | 统一检索 facade：单 MCP 工具路由 41/Chroma/recall 三后端 | Cognee 多模式路由/Zep 单图多端 | S3 |
| P0 | REA 产出标准化入认知（Evidence 摘要→record） | Mem0 写入管线 | S2 |
| P1 | PG domain_events outbox 表 + 轻量 dispatcher：数据链事件（采集/清洗/回填）发布→认知 record | PG outbox 模式 | S1 |
| P1 | import-linter CI 门禁（承接原 G4，REA 从报告升级为门禁） | Fitness Function | S7 |
| P2 | RAG 索引 PG 数据快照（存储→检索暴露） | Cognee ECL 管线 | S4 |
| P2 | 认知库 PG 镜像/迁移评估（对齐 38 方案4） | — | S5 |
| P2 | REA 符号图与 41 索引互通（tree-sitter，承接 G5） | SCIP | — |
| P3 | 能力健康聚合端点（五能力 health 聚合进 cognitive health） | IDP 成熟度模型 | S6 |

**原调研第五章 P0-P3 清单的归属**：as_of point-in-time、symbol_map、DataSource 窄接口、特征注册表、任务运行表、Pandera、TimescaleDB 属数据链内功轨道，与协同化轨道并行；import-linter 并入 P1-S7；tree-sitter 并入 P2。

---

## 八、L0 三层目标架构：互联层—调度层—封装层（2026-10-30 补充）

> **用户口径（原文要点）**：①底层核心能力第一目标是**打通**——沿主线打通、互联互通；②第二目标是**灵活调度**——检索系统可作入口，但灵活调度与管理同样重要；③第三目标是**封装统一底层能力**——底层改动不波及上层（痛点：数据库系统更换时多次出问题，大量细枝末节仍依赖老数据库）。
>
> **命名澄清**：本章讨论的是 **L0 内部的组织方式**。现有 L0/L1/L2 定义见 [SPEC-v1.3-L0L1L2-architecture.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/SPEC-v1.3-L0L1L2-architecture.md) §1（按"是否依赖生成式 LLM 推理"分层：L0 基础能力层 / L1 基础智能层 / L2 大模型驱动层）。两者**正交**：L0/L1/L2 回答"谁依赖大模型"，本章回答"L0 内部怎么组织"。为避免与 C1-C4 认知四层再混淆，本章三层命名为 **L0-P 封装层（Ports）/ L0-I 互联层（Interconnect）/ L0-S 调度层（Schedule）**。

### 8.0 调研口径：云端为目标，本地为代理（2026-10-30 实测补正）

> **用户口径**：调研目标必须是云端，本地与云端要完全一致；调查本地是为服务云端。本节把 8.1-8.7 的证据按"云端权威 / 本地代理"重新定标。

| 核对项 | 本地（macOS，代理） | 云端 `43.160.201.117`（Ubuntu 24.04.5，权威） | 结论 |
|---|---|---|---|
| 代码版本 | **`4d6837f880`（= origin/main = 云端，0/0）** | `4d6837f880`（main；含 `event_emitter`、SACG 埋点、运行态同步） | ✅ 一致（2026-10-30 12:26 本地 fast-forward） |
| `sqlite3.connect(` | 179 处 / 85 文件（另 gitignored `.cognitive/vm_fixed_backup.py` 2 处不属仓内代码） | **179 处 / 85 文件**（同命令同口径） | ✅ 一致（文件集合仅多 1 个本地备份） |
| PG 直连 | 14 处 / 11 文件 | **14 处 / 11 文件** | ✅ 一致 |
| `job_runs/task_registry` | 0 命中 | **0 命中** | ✅ 一致 |
| 调度载体 | launchd 25 plist | **systemd 74 单元（19 running）+ 26 timer** | ❌ 载体与规模不同 |
| 系统 cron | 0 条 | **1 条**（41 索引对账，每小时） | ❌ 不一致 |
| 存储 | SQLite 主（`data_center.db`/`cognitive_memory.db`/`dev.db`/`business.db`/`chroma.sqlite3`） | **PG 16.15** `dreambuddy` 36 表 / `data_center` 5 / `fis` 5；并存 SQLite `data_center.db`/`cognitive_memory.db`/`chroma.sqlite3`；`dev.db`/`business.db` **已不存在** | ⚠️ 部分不一致 |
| PG 扩展 | — | 仅 `plpgsql`（无 `pg_trgm`/`vector`/`pg_stat_statements`） | ⚠️ 约束 C7 选址 |
| DSH `:3847` / HUB `:8787` | 未监听 | **未监听** | ✅ 两端同为空（配置指向死连接） |
| 事件链 | 代码已同步（`event_emitter` 存在） | JSONL `event_emitter` → `etl-worker`(60s) → PG `observability` 三表 | ✅ 代码一致 |
| 工作区 | 15 tracked dirty（13 backtest_cache + 2 未提交文档）+ 2 untracked | 1 tracked dirty（`pool.json`）+ 3 untracked（REA 样本） | `.py` 两端均 0；仅运行数据漂移 |

**对 8.1-8.7 的适用范围**：①代码级结论（179/85、14、0 命中）**在云端成立**，不是本地假象；②调度类结论（8.2 的"launchd 25 / cron 0 条"）**仅对本地成立**，云端须改为"systemd 74 单元 + 26 timer + 1 条 cron"；③C7 检索入口在云端只能路由 41（已 PG 化 `fis` 库）/ Chroma / recall 的既有 API，**不得在 PG 侧新造全文/向量检索**（无 `pg_trgm`/`vector`）。

### 8.1 审计 A：封装缺失的量化（"换库多次出问题"的根因）

| 直连模式 | 命中数 | 涉及文件 | 分布特征 |
|---|---|---|---|
| `sqlite3.connect(` | **179 处** | **85 个 py 文件** | 横跨约 20 个子系统；存储层内仅约 15 处（18 `sink_sqlite.py` 11 处、19-DAL `connection.py` 1 处、迁移脚本 3 处）→ **约 92% 发生在存储层之外** |
| `psycopg/psycopg2.connect` / `create_engine` | 14 处 | 12 个文件 | 多为脚本/工具（38 迁移、39 `dc_pg.py`、34 语料处理、43 情绪通道），无统一 PG 封装入口 |
| 事实上的"民间封装" | — | — | 39-金融语义蒸馏系统 `/scripts/dc_pg.py` 被 34 `core/l0_foundation.py:L40-42` 直接 import，成为跨模块 PG 助手；但它不在 19-DAL 内，也不受 DAL 契约约束 |

**直连热点分布（top 5）**：11-易经推理系统 61 处/27 文件（含 bcrm2/incremental_learner 7 处、coin_fundamental_crypto 5 处）；1-ARCHITECTURE 31 处/6 文件（含 dreamos/cli/bcrm2_scheduler 11 处、dreamos_full_scheduler 5 处）；23-四层闭环自进化 22 处/8 文件；4-MEMORY 13 处/10 文件；18-数据获取中心 12 处/2 文件。

**关键对照**：19-DAL 其实**已有可用抽象**——[di.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/dreambuddy_dal/di.py#L1-L126) 提供 `json_legacy / dual_write / sqlite_unified` 三后端选择 + `DualWrite` 读写代理 + `get_*_repo` 仓库工厂；[README.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/README.md#L68-L70) 甚至明令"严禁 18 层直连 `dreambuddy_core.db`"。**问题不是"没有缝"，而是"缝存在但无人走"**——约束写在文档里，没有机制强制。

**换库痛点的机制解释**：SQLite 与 PG 的并存不是"一套抽象两个 adapter"，而是多套并存（18 同时保留 `sink_sqlite.py` 与 `sink_postgres.py`；3.1 前端 Prisma `dev.db`；产物中台 `business.db`；认知库 `cognitive_memory.db`；38 迁移仍在进行）。[SPEC-20260928-POSTGRESQL-CENTRALIZATION.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/SPEC-20260928-POSTGRESQL-CENTRALIZATION.md#L36-L41) 记录了至少 5 个库/两套 ORM 的并存事实。**没有强制缝 → 换库的波及面 = 全部 179 个调用点**，这正是"改一处、坏一片"的算术根源。

### 8.2 审计 B：调度现状（"灵活调度"的起点）

> **口径**：本表为**本地（macOS launchd）代理口径**；**云端权威值**为 systemd **74 个单元（19 running）+ 26 个 timer + 1 条 cron**（见 §8.0）。二者是"同一职责的两种载体"，规则与结论必须双写，不得只按本地设计。

| 调度来源 | 数量 | 证据 |
|---|---|---|
| OS 服务（本地 launchd） | **25 个** `com.dreambuddy.*.plist` | 其中 9 个 `KeepAlive` 常驻（datacenter / dc-scheduler / dreamos / etl-worker / signal_scanner / yijing_data_server / trailing-stop-runner / yijing_live_300s / yijing_trading），10 个 `StartInterval` 周期（60s trend_executor、300s v15_light_poll、600s dbsync/screen_orchestrator、900s v15_orchestrator、1800s continual-training、14400s ab_monitor/ab_orchestrator/ranking-trigger/screen_monitor/yijing_monitor），其余 6 个仅 RunAtLoad/日历触发 |
| OS 服务（云端 systemd） | **74 单元 / 26 timer** | 常驻 19：v15-api、v15-capital-api、yijing-data-server、yijing-polling-trader、dreambuddy-frontend、product-hub、datacenter-scheduler、cognitive-daemon、dreamos-dynamic-evaluator、fundamental、m25/m26/m27/m28、signal-scanner、trailing-stop-runner、etl-worker、hermes-gateway、dreambuddy-continual-training |
| 系统 crontab | 本地 **0 条**；云端 **1 条** | `41-文件索引系统/scripts/reconcile_cron.py`，每小时对账并写 PG `fis`；本地另有未启用的 `experiments/ab-trading/setup_cron.sh` |
| 应用内调度器 | **≥5 套** | 18 `data_center/scheduler.py`（collect_once + backfill 主循环）；15-监控告警 `scheduler.py:L206-255`（`schedule` 库 + while True）；dreamos `cli/start_scheduler.py` → `scheduler.py` DreamOSScheduler（croniter，dreamos_full_scheduler.py 已标 DEPRECATED）；experiments/ab-trading `orchestrator.py --daemon`（10min 轮询）；11 `data_server_fixed.py:L2221-2272` 多条 `while True + sleep` 刷新线程 |

**统一性检查（全部为"无"）**：

| 检查项 | 结论 | 证据 |
|---|---|---|
| 统一任务注册表（任务清单/周期/超时/并发/重试声明） | ❌ 不存在 | Grep `task_registry|job_registry|jobs.yaml|tasks.yaml` 零命中（云端复跑同样 0） |
| 统一任务运行记录（run 历史/状态机/血缘） | ❌ 不存在 | Grep `job_runs|task_runs|run_log` 零命中；各调度器只写自己的 log 文件 |
| 幂等 run key / 错过补跑 / 超时回收 | ❌ 未见统一实现 | 各调度器各自处理或未处理 |
| 调度控制面与执行面分离 | ❌ 未分离 | dreamos `DreamOSScheduler` 直接 import 业务（AutoTrader） |

**结论**：当前调度 = **"25 个本地 launchd / 74 个云端 systemd 单元 + ≥5 套应用内调度器 + 1 条云端裸 cron + 0 条统一注册表"** 的多头治理。任何"这个任务到底跑没跑/跑了几次/失败没有"的问题，只能靠翻日志人工回答。这也解释了为什么"检索作为入口"难以落地——**入口能查到东西，但查完无法派发成一个可追踪的任务**。

### 8.3 审计 C：抽象边界（已有的缝 vs 缺的缝）

| 能力域 | 现有抽象 | 证据 | 接口宽度 | 换实现是否波及上层 |
|---|---|---|---|---|
| 存储（19-DAL） | `get_*_repo` + 三后端 DI + `DualWrite` | [di.py:L1-126](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/dreambuddy_dal/di.py#L1-L126) | 中（repo 粒度） | **部分**：走了 DAL 的不波及，不走 DAL 的（92%）全部波及 |
| 存储（39 民间） | `dc_pg` 脚本模块 | [dc_pg.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/39-金融语义蒸馏系统/scripts/dc_pg.py) | 宽（裸连接/游标） | 否（换实现要改所有 import 方） |
| 采集（18） | `BaseCollector.fetch` + `Registry` + `dispatcher(category,source)` | `collectors/_base.py:L13-28`、`core/registry.py:L11-31` | **窄**（好） | 部分：collector 契约稳定，但落库 sink 双实现并存 |
| 检索（41） | `SearchAPI.search/rebuild/update/status` + `Database`(PG pool) | `api/search_api.py:L36-108`、`core/db.py:L38-66` | **窄**（好） | 否：换索引实现只动 core |
| 认知（4-MEMORY） | MCP 五工具（recall/record/verify/stats/health） | `cognitive_mcp_server.py:L5-17,58-170` | **窄**（好） | 否：MCP 是稳定契约，但底层 SQLite 直连散落 13 处 |
| 解析（33-REA） | `PythonAnalyzer.analyze(path)` | `README.md:L17-27` | **窄**（好） | 否（单入口），但无后端抽象（换 tree-sitter 需改内部） |
| **统一 L0 门面** | `L0Foundation.fetch_context(scope,params)` + 统一信封 `{ok,data,source,timestamp,degraded,meta}` + 11 scope 注册表 | [l0_foundation.py:L91-120](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/core/l0_foundation.py#L91-L120)、[L0-接口规范-fetchContext.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/L0-接口规范-fetchContext.md#L12-L49) | **最窄**（scope 字符串） | **否**——这是全仓最接近 T3 目标的原型，但只服务 34 这一个子系统 |
| 能力注册（dreamos） | `CapabilityRegistry` + `CapabilitySpec(capability_id/category/provider_type/requirements/status/degraded_reason)` + `CapabilityMatcher` | `core/capability/registry.py:L28-105`、`shared/capability.py:L50-80` | 中 | 否：**注册表已存在**，但仅 DreamOS 运行时内存态，不覆盖 L0 五能力，无声明文件 |

**判断**：**"有零散抽象、无统一缝"**。四个能力（采集/检索/认知/解析）各自已有窄接口（这是好消息，说明不需要重建），但**五个能力之间没有同一层门面**；存储侧的缝（19-DAL）存在却只有 8% 的调用走它。**T3 的真实工作量不是"设计抽象"，而是"把已有窄接口收进同一层门面 + 让存储调用真正走 DAL"**。

### 8.4 架构判断：封装在最底，互联与调度并列其上

```
L2 大模型驱动层（LLM 推理）
L1 基础智能层（确定性算法 / 意图路由）
════════════════════ L0 边界 ════════════════════
   ┌───────────────────────┬───────────────────────┐
   │ L0-I 互联层            │ L0-S 调度层            │  ← 并列，互相消费
   │ · 能力声明（YAML+注册表）│ · 任务注册表(声明式)     │
   │ · 事件 outbox + dispatcher│ · job_runs 状态机+幂等   │
   │ · 统一检索入口(facade)  │ · 执行器+并发/超时/心跳   │
   └──────────┬────────────┴──────────┬────────────┘
              └──────────┬────────────┘
         ┌────────────────▼────────────────┐
         │ L0-P 封装层（最底）                │  ← 防震层
         │ 统一门面（L0Foundation 信封推广）    │
         │ ports: Memory/Collector/Search/Store/REA │
         │ adapters: PG / SQLite(旧) / Chroma / FS │
         └─────────────────────────────────┘
```

**三条判据**：

1. **封装层必须在最底**：它是防震层。若互联层/调度层直接连资源（outbox 写裸 PG、调度器 import 业务），换库时事件与任务代码照样重写——痛点重演。
2. **互联与调度并列、互不隶属**：调度执行完成后要发事件；事件可触发任务。把调度做成"万能编排器"（既管生命周期又管业务语义）是最常见退化路径。
3. **目标顺序 ≠ 落地顺序（评审后修订）**：价值顺序是"打通 → 调度 → 封装"，依赖顺序是"封装先行（仅约束新代码）→ 互联 → 调度"。但**"打通"不该等待封装全部完成**——统一检索入口（C7）零依赖（只需路由既有的 41/Chroma/recall 窄接口），可作为 P0 前置切片先行；存量 179 处直连的收编单开轨道，不阻塞任何后续步骤。封装先行的真实含义是：**新代码不得直连资源**，而不是"先把 179 处改完再谈打通"。

### 8.5 外部对标取舍（本轮新增）

| 技术项 | 结论 | 理由 | 最小落地形态 |
|---|---|---|---|
| PG 单表 outbox + 轮询 dispatcher | **备选（P3）** | 默认用 `job_runs` 状态回调（一次写、天然幂等），跨库 outbox 只在出现非调度来源时才评估；CDC/Debezium slot lag 会填满 4C8G 磁盘 | 若启用：`domain_events` 表 + `FOR UPDATE SKIP LOCKED` 单进程循环 |
| Kafka / Redis Stream 作事实源 | 不引入 | 多一套中间件运维面；Redis 仅作缓存/快通知 | — |
| 能力声明文件（YAML 即能力地图） | 采纳 | 机器可发现、零运行时组件；复用 DreamOS `CapabilitySpec` 的**字段名** | `capabilities.yaml` + CI 校验（不加载运行时 `CapabilityRegistry`） |
| OpenMetadata / DataHub / Backstage 运行时 | 不引入 | 重型目录服务 | YAML 即目录 |
| 自研任务注册表 + job_runs + 执行器 | 采纳 | 需求是周期+重试+可见性，不是分布式 | 注册表 + `job_runs` + 8 要素（幂等/状态机/退避/并发/超时/心跳/日志/开关） |
| Prefect / Dagster / Celery / Temporal | 不引入 | 各自需自带 UI+DB 或 broker+worker，4C8G 单机养不起 | — |
| APScheduler | 仅借语义 | 借 `max_instances=1` + `misfire_grace_time` 语义，不作 jobstore 事实源 | 触发器语义对齐 |
| Kestra 控制面/数据面分离 | 借鉴思想 | 控制面只认 task_key + 输入契约，不 import 业务函数 | 同进程线程池执行器 |
| Hexagonal Ports & Adapters | 借鉴，**限 6 个 port** | 超过即 port explosion；只在"会被替换或有第二实现"时建 port | Memory/Collector/Search/Store/REA + Facade |
| Repository + ACL（防腐层） | 采纳 | 旧库字段名/方言细节不得越界到业务层 | adapter 内做字段映射 |
| Strangler fig + 影子读切库 | 采纳 | 零回归切库的唯一稳妥路径：双写→回填→影子读 diff→按能力开关切读→停旧写 | diff 率门槛 + 连续天数门槛 |
| 统一门面信封 | 采纳（已有原型） | 故障收拢为 `degraded`，上层不感知后端 | 推广 `L0Foundation` 信封到全 L0 |

### 8.6 SPEC-C 输入：三层目标的 P0-P3（本节为 SPEC-C 的依据）

| 优先级 | 层 | 项 | 解决目标 |
|---|---|---|---|
| P0 | L0-I | **统一检索入口（前置切片）**：单 MCP `unified_search` 路由 41 / Chroma / recall，归一化合并+单后端降级——零依赖，作为"打通"第一成果 | T1（用户点名的"检索作入口"） |
| P0 | L0-P | **门面推广**：把 `L0Foundation` 的 scope 注册表+统一信封抽为 L0 公共模块（新增 scope：`storage.*` / `search.*` / `rea.*`），**只供新代码使用，存量原路径不动**；六能力 port（含 Event） | T3 起手 |
| P0 | L0-P | **存储收敛第一步**：新代码禁止直连，`dc_pg` 收编进 19-DAL；建立"直连文件数"基线仪表（179→目标 0 除 adapter） | T3 度量 |
| P1 | L0-P | **切库标准流程**：SQLite→PG 双写→回填→影子读 diff→开关切读，形成可复用 runbook（对齐 38 方案4） | T3 兑现 |
| P1 | L0-I | **能力声明**：`capabilities.yaml` 复用 `CapabilitySpec` 字段名，覆盖五能力 provides/requires/health/port；**文件 + CI 校验为唯一事实源** | T1 |
| P2 | L0-I | **事件互通**：默认 `job_runs` 状态转移 → 认知 record（同进程回调、`run_id` 幂等）；非调度来源（REA/检索）在 P3 再评估单表事件 | T1 |
| P2 | L0-S | **任务注册表 + job_runs**：声明式任务清单 + 状态机 + 幂等 run_key + 心跳/超时；先纳管 18 scheduler 与 dc-scheduler；**实盘进程不内嵌记账**，非实盘周期任务用 wrapper/旁路日志记账 | T2 |
| P3 | L0-S | **检索触发任务**：检索命中 → 按 task_key 排 job（去重窗口+并发上限+FAIL-OPEN）；跨界通知仅在事件表评审通过后启用 | T1×T2 联调 |
| P3 | L0-S | **调度可视化端点**：`job_runs` 聚合进 health（跑没跑/成功率/最老滞留） | T2 可观测 |

### 8.7 风险与边界

- **门面公共化的回归面（评审后已收缩）**：原设想把 34 的 11 个 scope 全量迁移，评审判定不可接受；现改为只抽"信封 + scope 注册机制"供新代码使用，34 原路径不动。
- **179 处直连不可能一次清零**：采用"新增禁直连 + 存量按热点目录分批收编"，热点优先级 11 → 1-ARCHITECTURE → 23；该轨道不阻塞互联与调度。
- **调度只做旁路记账（评审后收紧）**：`dreamos/v15/yijing_trading/trailing-stop-runner/yijing_live_300s` 等含交易逻辑的常驻进程**不内嵌 `job_runs`**（心跳误判会因 `logical_window` 唯一约束导致任务静默停摆）；仅用 wrapper/旁路日志解析记账，launchd 仍是唯一拉起者。
- **跨库事件默认不建**：默认用 `job_runs` 状态回调写认知（`run_id` 幂等，避免"已写认知、未提交状态"的重投污染 recall 与 verify 计数）；跨库 outbox 仅作 P3 备选。
- **能力声明与实际实现漂移**：声明文件需 CI 校验（声明的 health 命令可执行、声明的 provides 有对应 port），否则退化为第二份文档。
