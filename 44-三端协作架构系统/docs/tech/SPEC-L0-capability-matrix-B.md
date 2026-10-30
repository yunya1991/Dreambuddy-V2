# SPEC-B — L0 五能力协同化路线图

> **版本**: v0.1 (2026-10-30)
> **状态**: 待评审（开工SKILL 阶段 3 产出，用户确认门后进入阶段 4 评审）
> **上游**: [l0-capability-matrix-SPEC-A.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/.trae/documents/l0-capability-matrix-SPEC-A.md)（能力矩阵现状+断点 S1-S7）
> **约束**: 单人维护、FAIL-OPEN、云端 4C16G、禁止 MLflow/K8s/Kafka/DataHub 等重型工具、评审只读、零回归
> **目标**: 从「五个能跑的能力」→「一个协同的能力矩阵」：能力可声明、事件可互通、检索可统一、知识可闭环
> **与 SPEC-C 的关系（2026-10-30）**: [l0-three-layer-SPEC-C.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/.trae/documents/l0-three-layer-SPEC-C.md) 已接管并重排本 SPEC 的协同化项（B1/B3/B4/B9 → C6/C7/C8/C12），本 SPEC 保留 B6/B7/B8 作为封装层后续批次。**评审以 SPEC-C 为主干，本 SPEC 作为子项清单。**

---

## 1. 目标架构：能力矩阵三件套协同机制

```
┌────────────────────────────────────────────────────────────┐
│  capabilities.yaml（能力注册表，文件即能力地图）              │
│  五能力各自声明 provides / consumes / health / port         │
└────────────────────────────────────────────────────────────┘
        ▲ 声明                ▲ 发布事件            ▲ 统一检索
        │                     │                     │
┌───────┴──────┐   ┌─────────┴────────┐   ┌────────┴───────┐
│ ①广义认知     │   │ PG domain_events │   │ 统一检索 facade │
│ (MCP 五工具)  │◄──┤ outbox 表+轮询    │   │ (MCP 单工具     │
│              │   │ dispatcher       │   │  路由三后端)    │
└──────────────┘   └──────────────────┘   └────────────────┘
```

三件套均为**文件/PG 表/单 MCP 工具**级轻量实现，零新基础设施。

## 2. 分期路线

### P0 — 能力可声明 + 检索统一 + REA 入认知（解决 S6/S3/S2）

| # | 项 | 落点 | 验收 |
|---|---|---|---|
| B1 | **capabilities.yaml 能力注册表**：五能力组各声明 name/domain/provides(API列表)/consumes/health(检查命令)/port；**Schema 复用 DreamOS `CapabilitySpec` 字段名**（`capability_id/category/requirements/status/degraded_reason`），**但不加载运行时 `CapabilityRegistry`**（跨进程不可行），文件 + CI 校验为唯一事实源；附校验脚本（schema 断言+实现一致性） | `0-系统文档管理/capabilities.yaml` + `scripts/validate_capabilities.py` | 校验脚本通过；五能力声明完整；声明与实现无漂移 |
| B2 | **REA 产出标准化入认知**：PythonAnalyzer.analyze 完成后，将 AnalyzeResult 摘要+Evidence 计数 record 入认知库（tags 含 `rea,evidence`，FAIL-OPEN：认知不可用时仅告警） | 33-REA逆向解析工程 应用编排层 | 跑一次 REA 后 recall 可命中该架构知识 |
| B3 | **统一检索 facade**：新 MCP 工具 `unified_search(query, sources, top_k)`，路由三后端（41-SearchAPI / ChromaDB RAG / 认知 recall），结果按归一化得分合并去重；单后端失败自动降级其余（FAIL-OPEN） | 4-MEMORY/9-工具与接口/ 新增 facade 模块，注册进 cognitive_mcp_server.py | 单工具返回三后端合并结果；断任一后端不报错 |

### P1 — 事件互通 + REA 门禁（解决 S1/S7）

| # | 项 | 落点 | 验收 |
|---|---|---|---|
| B4 | **PG domain_events outbox**：data_center 库建 `domain_events` 表（id/event_type/payload/created_at/consumed_at）；scheduler 在采集/清洗/回填完成点同事务写事件；轻量 dispatcher（scheduler 内嵌协程）轮询消费→调认知 record | sink_postgres.py 同目录 + scheduler.py | 采集一轮后认知库可 recall 到采集事件；事件表行数与任务次数一致 |
| B5 | **import-linter CI 门禁**（承接原 G4）：声明 L0→DAL→特征→交易分层 layers 契约 + forbidden 契约；先 report-only 跑 2 周收敛存量违规，再转 enforce | pyproject.toml/CI 配置 | report-only 报告产出；enforce 后分层违规 CI 失败 |

### P2 — 存储暴露 + 存储统一（解决 S4/S5）

| # | 项 | 落点 | 验收 |
|---|---|---|---|
| B6 | **RAG 索引 PG 数据快照**：周期性将 mm_metrics/records 的关键摘要（非全量）chunk 化入 ChromaDB，统一检索可查存储数据 | 2-KNOWLEDGE/9-RAG-INFRA/ | unified_search 可命中 PG 数据摘要 |
| B7 | **认知库 PG 镜像评估**：评估 cognitive_memory.db 迁移/镜像到 PG（对齐 38 方案4 迁移框架）；先出评估报告再决定是否迁移 | 38-数据库管理系统/ 评估文档 | 评估报告含一致性/性能/回滚方案 |
| B8 | **REA 符号图与 41 索引互通**（承接 G5）：tree-sitter 符号/引用数据双写 41 索引与 REA evidence | 41-文件索引系统/core/ | REA 分析可引用 41 索引符号数据 |

### P3 — 能力矩阵可观测（完善 S6）

| # | 项 | 落点 | 验收 |
|---|---|---|---|
| B9 | **能力健康聚合端点**：cognitive `health` 工具聚合五能力 health（各能力按 capabilities.yaml 声明的检查命令执行），输出能力矩阵健康仪表盘 | cognitive_mcp_server.py health handler | health 返回五能力分项状态 |

## 3. 与原调研 P0-P3 清单的关系（双轨制）

**协同化轨道（本 SPEC-B）**：B1-B9 解决能力间协同断点。

**数据链内功轨道（原调研第五章，并行推进、独立 SPEC）**：feature_hub `as_of` point-in-time（P0）、symbol_map（P1）、DataSource 窄接口（P1）、特征定义注册表（P1）、任务运行表血缘（P2，与 B4 outbox 表合并设计）、Pandera schema（P2）、TimescaleDB 分区（P2）。

**合并项**：原 G4 import-linter → B5；原 G5 tree-sitter → B8；原 G7 任务运行表 → 并入 B4 outbox 表设计（events 表兼作血缘记录）。

## 4. FAIL-OPEN 与零回归设计

| 项 | 降级策略 |
|---|---|
| B2 REA→认知 | 认知 MCP 不可用 → 仅写本地报告+告警，不阻断分析 |
| B3 统一检索 | 任一后端超时/异常 → 剔除该后端返回其余结果，标注 degraded |
| B4 outbox | 事件消费失败 → 事件滞留表内重试，采集主流程不受影响；dispatcher 异常仅日志 |
| B5 门禁 | report-only 期不阻断 CI；enforce 前需存量违规清零评审 |
| B6 RAG 索引 PG | 索引任务失败 → ChromaDB 保持旧快照，不影响在线检索 |

所有新代码路径默认挂开关（config flag），关闭即回到现状行为（HC-1a 零回归）。

## 5. 验收标准（SPEC-B 整体）

- [ ] P0 三项落地后：能力矩阵可机器读取（B1）、架构知识可 recall（B2）、检索单入口可用（B3）
- [ ] P1 落地后：采集事件入认知（B4）、分层违规 CI 可拦截（B5）
- [ ] 全量回归：pytest 无新增失败；tsc 0 errors；云端部署健康检查通过
- [ ] 每项落地执行 dream-acceptance-verify 五维验收（症状复测+日志证据+回归+影响面+边界）

## 6. 风险

- B3 facade 需处理三后端得分量纲不一致 → 采用归一化+来源权重，初版权重人工标定
- B4 outbox 轮询增加 scheduler 负担 → 消费协程独立节拍（默认 60s），4C16G 资源评估
- B7 认知库迁移影响面大（recall/record/verify 全链路）→ 仅评估先行，迁移决策单独评审
- B5 enforce 切换可能暴露存量违规 → report-only 收敛期不可跳过
