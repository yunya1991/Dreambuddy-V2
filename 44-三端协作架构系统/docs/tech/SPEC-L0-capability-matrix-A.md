# SPEC-A — L0 五能力能力矩阵：现状与协同 Gap 清单

> **版本**: v0.1 (2026-10-30)
> **状态**: 待评审（开工SKILL 阶段 3 产出，用户确认门后进入阶段 4 评审）
> **上游**: [l0-foundation-research-report.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/.trae/documents/l0-foundation-research-report.md) 第七章（能力矩阵与协同主线专项调研）
> **命名口径（硬约束）**: 五能力 = ①广义认知系统（五类四层 C1-C4）②数据采集系统 ③检索系统 ④PostgreSQL 数据存储管理 ⑤REA 逆向解析能力；协同主线 = 认知-数据-工程解析-数据存储-检索入口。C1-C4 ≠ L0/L1/L2 ≠ SACG ≠ 矛盾维度 C1-C8；④不得笼统称"数据库管理"。
> **下游**: SPEC-B（协同化路线图）

---

## 1. 命题

> 五大能力组各自可独立运行，但**能力矩阵化与协同化不足**：无机器可读的能力声明、能力间事件不互通、检索入口分裂、REA 产出无消费者。本 SPEC-A 固化能力矩阵现状与断点清单，作为 SPEC-B 协同化路线图的输入基线。

## 2. 能力矩阵（代码实证基线）

### 2.1 矩阵总表

| 能力组 | 对外接口 | 核心存储 | 协同状态 |
|---|---|---|---|
| ①广义认知 | MCP recall/record/verify/stats/health | cognitive_memory.db(SQLite) + ChromaDB + JSON 蒸馏产物 | ✅接口面完整 / ❌与数据链·REA 无事件互通 |
| ②数据采集 | BaseCollector.fetch + Registry + dispatcher 路由 + scheduler | PG data_center.records | ✅注册机制 / ⚠️无统一 DataSource 窄接口 / ❌事件不入认知 |
| ③检索系统 | 41-SearchAPI.search / ChromaDB RAG / 认知 recall | SQLite 索引 + ChromaDB | ❌三入口分裂，无统一路由 |
| ④PG数据存储管理 | sink_postgres write/read_all/query_records/latest_records + migrate_to_postgres | PG16 三库 + Redis7 + MinIO | ✅读写接口 / ⚠️迁移进行中 / ❌无元数据目录·血缘 |
| ⑤REA逆向解析 | PythonAnalyzer.analyze → AnalyzeResult+Evidence | 文件（报告/JSON） | ✅单机能力 / ❌产出无消费者（不入认知·不进CI） |

### 2.2 接口明细（证据锚点）

| 能力组 | 接口项 | 证据（文件:行） |
|---|---|---|
| ① | MCP 五工具契约 | 4-MEMORY/9-工具与接口/cognitive_mcp_server.py:5-17, 58-170 |
| ① | record 接线 TAG_HOOKS+record_hook+knowledge-ingest | cognitive_mcp_server.py:393-474 |
| ① | verify 接线 verify_hook+skill_hooks | cognitive_mcp_server.py:477-515 |
| ① | IntentRouter 聚合记忆+SKILL+知识RAG 三检索源 | cognitive_loop_entry.py:312-347 |
| ① | recall hot/cold path（cache + SQLite archival） | cognitive_loop_entry.py:355-420 |
| ①→③ | RAG→认知写入桥（memory_id↔source 映射） | 2-KNOWLEDGE/9-RAG-INFRA/bridge/memory_bridge.py:161-218 |
| ② | 采集器抽象 BaseCollector.fetch | 18-数据获取中心/data_center/collectors/_base.py:13-28 |
| ② | Registry (category,source)→collector 工厂 | 18-数据获取中心/data_center/core/registry.py:11-31 |
| ② | dispatcher 路由与注册 | 18-数据获取中心/data_center/core/dispatcher.py:37-149 |
| ② | 采集入口 collect_once + 主循环+backfill | 18-数据获取中心/data_center/scheduler.py:80-129, 149-203 |
| ②→④ | records 表结构 + ON CONFLICT 落库 | 18-数据获取中心/data_center/storage/sink_postgres.py:54-100 |
| ④ | PG 读写接口 write/read_all/query_records/latest_records | sink_postgres.py:166-238 |
| ④ | 后端切换 get_sink()（DATA_CENTER_BACKEND） | sink_postgres.py:412-418 |
| ④ | SQLite→PG 迁移（四表+行数校验） | 38-数据库管理系统/migrate_to_postgres.py:44-87 |
| ④ | 冷热分层/归档/dal-backup 设计 | 38-数据库管理系统/SPEC-方案4-SQLite迁移PostgreSQL.md:17-37 |
| ③ | SearchAPI 统一检索（权限过滤+增量更新） | 41-文件索引系统/api/search_api.py:36-49, 77-108 |
| ③ | L1文件名+L2倒排+L3向量合并去重 | 41-文件索引系统/core/searcher.py:81-117 |
| ⑤ | PythonAnalyzer.analyze(path) API | 33-REA逆向解析工程/README.md:17-27 |
| ⑤ | Evidence/AnalyzeResult 产出结构 | 33-REA逆向解析工程/SPEC.md:145-200 |
| ⑤ | Evidence-First 四层事实分级哲学 | 33-REA逆向解析工程/SPEC.md:45-78 |
| 数据链→特征 | 19-DAL→21 特征管道衔接 | 9-基本面分析/dal_snapshot_provider.py:40-89, 711-872 |

## 3. 协同主线断点清单（Gap）

沿「认知-数据-工程解析-数据存储-检索入口」主线：

| # | 断点 | 位置 | 证据 |
|---|---|---|---|
| S1 | 数据→认知：采集/清洗/回填事件对认知不可见 | ②→① | scheduler.py:80-203 审计未发现认知调用 |
| S2 | 工程解析→认知：REA 产出不入认知库 | ⑤→① | 33-REA 内未发现 record 调用 |
| S3 | 检索入口分裂：41索引/Chroma/recall 三路独立 | ③内部 | search_api.py vs memory_bridge vs cognitive recall |
| S4 | 存储→检索：PG 数据无检索暴露（RAG 不索引 PG、41 只索引文件） | ④→③ | 2-KNOWLEDGE 仅文件源 |
| S5 | 认知存储与主存储分裂：cognitive_memory.db(SQLite) vs PG，无双写/一致性机制 | ①↔④ | 4-MEMORY/data/ |
| S6 | 元层声明缺失：五能力无声明文件（provides/consumes/health/port）；DreamOS 已有运行时 `CapabilityRegistry` + `CapabilitySpec`，但未覆盖 L0 五能力、也无 Git 声明文件（2026-10-30 复核修正） | 全局 | `dreamos/core/capability/registry.py:L28-105`、`dreamos/shared/capability.py:L50-80`；全仓无 `capabilities.yaml` |
| S7 | 工程解析无门禁：REA 架构健康只是报告不进 CI（=原 G4） | ⑤ | 33-REA 只出报告 |

与原调研 G1-G8 映射：S7=G4；S1 扩展 G7（血缘→事件流）；S3/S4/S6 为能力矩阵维度新增断点；G1/G2/G3/G5/G6/G8 属数据链内功轨道（SPEC-B §4 归属说明）。

## 4. 外部对标结论（SPEC-B 设计依据）

| 范式 | 来源 | 取舍 |
|---|---|---|
| 文件即能力地图（catalog-info.yaml / DPDS 五类 port） | Backstage / Open Data Mesh | ✅借鉴，不运行 Backstage 本体 |
| 认知-数据-检索闭环（写入管线→双存→多模式检索→MCP 注入） | Mem0 / Zep / Letta / Cognee | ✅借鉴闭环结构 |
| PG 单表 outbox 代 Kafka | 业界轻量事件模式 | ✅借鉴，零新设施 |
| MCP 聚合网关 | IBM ContextForge / AWS MCP Gateway | 借鉴思想，自建 thin facade |
| Data Fabric / Foundry Ontology / DataHub / Kafka | Gartner / Palantir 等 | ❌不引入（太重） |

## 5. 验收标准（SPEC-A 自身）

- [x] 矩阵每个接口条目有 文件:行 代码证据（§2.2）
- [x] 断点清单与原 G1-G8 有显式映射（§3）
- [x] 命名口径符合硬约束（五能力 / C1-C4 / PG数据存储管理）
- [ ] 用户确认门通过 → 进入 SPEC-B 评审

## 6. 风险与边界

- 本 SPEC-A 为只读基线文档，不改任何代码。
- §2.2 证据基于 2026-10-30 本地审计快照；后续代码变更需同步刷新。
- S1/S2 的"未发现"结论基于静态审计，若存在动态/间接调用需在评审时举证修正。
