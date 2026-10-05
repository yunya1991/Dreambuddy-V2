---
name: "dream-arch-collaboration-workflow"
description: "三层架构能力协同调用规范+认知系统协作流程。Invoke for 主骨架调用链编排、跨子系统协同、LLM四阶段协作、认知recall命中架构记忆、或需调用DreamOS/DSH/子域能力时。"
---

## Autonomy Boundary

可自主执行：
- 治理规则检查与合规报告
- SKILL 索引与生命周期管理
- 架构同步校验
- 代码审查与合并建议

需用户确认：
- 执行代码合并（merge 到主分支）
- 修改治理规则本身
- 执行系统级重启或部署

禁止：
- 未经审查直接合并到主分支
- 修改核心治理规则而不经过审批


# Dream Architecture Collaboration Workflow — 三层架构协同调用规范 SKILL

> 定位：DreamBuddy-v2 三层协同架构的**能力调用规范层**。本 SKILL 是纯编排指引，不重复建设任何能力，通过调用已有 SKILL 和子系统实现完整协作。
>
> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-arch-collaboration-workflow/SKILL.md`（TRAE 调用入口，本文件）
> - `1-ARCHITECTURE/skills/dream-arch-collaboration-workflow/SKILL.md`（项目级索引发现）
>
> **事实源（SSoT）**：架构争议以 `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` v3.0 §1.8 为准。
> **来源**：2026-09-30 双维度验证（26/26代码✅）+ 7场景模拟测试（全✅）+ 传统金融/AI多agent调研。

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **跨子系统协同**：需要编排主骨架调用链（前端→DreamOS→DSH→子域→产物中台）
   - 触发词：「调用链」「能力协同」「三层架构」「主骨架编排」
2. **LLM 四阶段协作**：需要按"熟悉架构→能力调用→内容整合→探索补充"四阶段工作
   - 触发词：「LLM协作」「四阶段」「能力调用规范」
3. **认知 recall 命中架构记忆**：recall 返回 tags 含 `架构三层协同域`/`主骨架`/`基础底层能力`/`子模块化系统能力` 的记忆
4. **子系统调度**：需要调用 BCRM/BDSM/经典指标/自进化/数据采集等子域能力
5. **新场景探索**：骨架完善后探索新能力组合（LLM 定位第四阶段）

**不触发的场景**：
- 单子系统内部开发（走子系统自身 SKILL）
- 纯文档同步（走 `dream-doc-sync-workflow`）
- 纯 TDD 开发（走 `dream-tdd-dev-workflow`）

---

## 二、三层协同架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  1. 主骨架（纵向调用链）                                      │
│  前端3.1 → DreamOS SACG → DSH多子agent → 子域能力 → 产物中台  │
│  每层职责单一边界清晰，前端默认不直连 DSH/DreamOS 8000         │
└─────────────────────────────────────────────────────────────┘
        │  │  │  │
        ▼  ▼  ▼  ▼
┌─────────────────────────────────────────────────────────────┐
│  2. 基础底层能力（横切支撑，跨主骨架各层）                     │
│  知识库·认知系统·数据采集四中心·文档管理·LLM wiki·Jev评估·     │
│  产物中台·监控告警·治理                                       │
└─────────────────────────────────────────────────────────────┘
        │  │  │  │
        ▼  ▼  ▼  ▼
┌─────────────────────────────────────────────────────────────┐
│  3. 子模块化系统能力（被主骨架 DSH/DreamOS 调度的领域算法）     │
│  经典指标·基本面·AI skill·Superpower·易经推理(BCRM/BDSM/宏观)· │
│  自进化·三屏趋势·V15马丁·V4波浪                               │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 主骨架五层职责

| 层 | 职责 | 关键文件 | 端口/协议 |
|----|------|---------|----------|
| 前端 3.1 | 意图识别/交互/本地 DAG | `task-manager.ts` executeWithPlanner | HTTP 3001 |
| DreamOS SACG | 编排/调度/蓝图规划 | `dreamos/apps/api_server.py` | HTTP 8000-8002 |
| DSH 多子agent | Agent 执行层 | `python-server/server.py` 14个_handle_* | stdin NDJSON IPC |
| 子域能力 | 领域算法 | 10/11/12/14/17/23 子系统 | Python import / HTTP 8092 |
| 产物中台 | 归档/查询/索引 | 7-产物中台 | — |

### 2.2 基础底层能力清单（9项）

| 能力 | 位置 | 说明 |
|------|------|------|
| 知识库 | `2-KNOWLEDGE/` + `9-RAG-INFRA/` | 交易/技术/理论/运营/AI认知 5域 + RAG 三层融合 |
| 认知系统 | `4-MEMORY/9-工具与接口/` | recall/record/verify + rumination/prediction/evaluation 三引擎 |
| 数据采集 | `18→19→20→21` 四中心 | 获取/访问层/清洗/特征工程 |
| 文档管理 | `0-系统文档管理/` | INDEX 导航 + doc_lint/coverage/link_checker |
| LLM wiki | DSH `cordis-plugin-knowledge-wiki` | 知识编译与检索 |
| Jev 评估 | DSH `python-server/jev_judge.py` | 质量评估 |
| 产物中台 | `7-产物中台/` | 不可变归档 + 索引查询 |
| 监控告警 | `15-监控告警系统/` | 5文档齐全 |
| 治理 | `2-GOVERNANCE/` | 宪法级章程 + 合规规则 |

### 2.3 子模块化能力清单（12项）

| 能力 | 位置 | 关键文件 |
|------|------|---------|
| 经典指标 | `10-经典指标系统` | `classic_system_server.py`(8092) |
| 基本面分析 | `9-基本面分析` | `data_collector.py`(废弃→data_center.compat) + `tavily_fundamental_generator.py` |
| AI skill | `skills/` + `1-ARCHITECTURE/skills/` | 154+ A/C/F/G/T |
| Superpower | `4-MEMORY/9-工具与接口/cognitive_superpowers.py` | 认知治理 |
| BCRM2.0 | `11-易经推理系统/scripts/memory_l4/bcrm2_adapter.py` | 技术分析 |
| BDSM | `11-易经推理系统/scripts/memory_l4/force_vector/bdsm_*.py` | 基本面(5文件: phase3_backtest/diagnose/shadow_audit/snapshot_writer/tactical_position) |
| 宏观算法 | `11-易经推理系统/scripts/memory_l4/tavily_macro.py` | 宏观面 |
| 自进化 | `23-四层闭环自进化交易架构/dreambuddy_evolution/` | evolution_pipeline + adapters/三bridge |
| 三屏趋势 | `12-三屏趋势系统` | — |
| V15马丁 | `14-V15经典马丁策略` | 标杆策略 |
| V4波浪 | `17-v4-wave-strategy` | ewave_strategy_adapter |
| 调控系统 | `16-调控系统` | 离场决策 |

---

## 三、主骨架调用流程（7步标准编排）

```
用户意图
  ↓
Step 1: recall 检索（硬约束，免费只读，min_quality="C"）
  ↓
Step 2: SACG 规划蓝图（Supervisor 中心化路由，记 routing 日志）
  ↓
Step 3: DSH 子 agent 执行（isolated 默认 / fork 继承 supervisor 上下文）
  ↓
Step 4: 风控 sidecar 拦截（veto 或放行，不可改策略）
  ↓
Step 5: 产物中台归档（immutable + doc-sync 索引同步）
  ↓
Step 6: record + verify 闭环（贝叶斯升级 + 动态蒸馏）
  ↓
Step 7: wiki 编译（tags 含 wiki-compile 触发 wiki-ingest-trigger）
```

### Step 1: recall 检索（硬约束，不可跳过）

```
recall(context="当前任务描述或问题关键词", top_k=5, min_quality="C")
```

- 检索是免费的（只读不写），避免重复踩坑
- `min_quality="C"` 确保返回最多结果（98%记忆为C级）
- 即使无结果也表明已检查记忆库——闭环起点

### Step 2: SACG 规划蓝图

DreamOS SACG（Scheduler-Architect-Coordinator-Gateway）四层编排：
- **Scheduler**：意图识别（零Token本地计算，6类意图）
- **Architect**：构建蓝图/执行图/时间线/图存储
- **Coordinator**：NodeRegistry（35模块配置+11本地实现）调度
- **Gateway**：DSH 子 agent 路由

路由决策日志化（借鉴 LangChain Supervisor 模式）：每次路由记 `routing_decision → worker → result`。

### Step 3: DSH 子 agent 执行

DSH（dream-harness-bridge）= Agent 执行层（非通信桥）。

**上下文双模**（借鉴 LangChain）：
- `isolated`（默认）：子 agent 从空白上下文启动，不污染 supervisor
- `fork`：继承 supervisor 全状态，复用 prompt cache，省去重复 file-read

**DSH 8子agent**：technical/sentiment/macro/flow/valuation/onchain/risk/portfolio

**DSH 13业务method路由**（server.py dispatch）：
c1_scan / c2_momentum / c3_volatility / execute_c_chain / intent_gateway / technical_indicators / fundamental_analysis / artifact_index / trade_index / build_vector_index / session_consumer / graph_planner / reflection

**硬约束**：
- HC-9: Plugin 只透传不决策，交易判断在 DreamOS Python 侧
- HC-10: 领域代码零 Harness 依赖，`dreamos/` 禁止 import Harness/Cordis
- HC-7: 跨语言边界 FAIL-OPEN 默认中性兜底

### Step 4: 风控 sidecar 拦截

借鉴传统金融 Risk Sidecar 独立 veto 模式：
- Risk 作为独立 sidecar（不属任何子域）
- Strategy → Risk → Execution 链路
- Risk 可否决不可改策略
- 事前（限额/敞口）/事中（kill-switch）/事后（归因）三层

### Step 5: 产物中台归档

- 交易记录、绩效归因、审计日志写入 immutable store
- 产物中台统一查询入口
- doc-sync 自动同步索引防断链（调用 `dream-doc-sync-workflow`）

### Step 6: record + verify 闭环

```
record(content="经验内容", quality_level="B", tags="标签1,标签2")
verify(memory_id="VM-xxx", success=true)
```

- verify 触发贝叶斯置信度更新与动态蒸馏
- 失败路径同样 record（反模式），verify(success=false) 降低置信度

### Step 7: wiki 编译

record tags 含 `wiki-compile` 时，TAG_HOOKS 触发 `wiki-ingest-trigger` skill，LLM wiki 自动编译。

---

## 四、LLM 四阶段定位（硬约束）

> LLM 不直接推理解决交易问题。四阶段：

| 阶段 | 职责 | 禁止 |
|------|------|------|
| ① 熟悉架构 | 文档管理系统索引定位（0-系统文档管理/INDEX.md） | 禁止跳过文档直接编码 |
| ② 能力调用 | DSH/DreamOS 编排子系统 | 禁止 LLM 直接做交易判断（HC-9） |
| ③ 内容整合 | summary/图表/辩论论据 | 禁止生成原始数据 |
| ④ 探索补充 | 骨架完善后探索新组合 | 禁止绕过硬约束（HC-1~HC-11） |

---

## 五、规范流程十条（调研结论，结合传统金融+AI实践+DreamBuddy实际）

1. **数据分层采集**：Hot（Redis k线/盘口）→ Warm（Parquet 历史回测，bitemporal 双时间戳）→ Cold（归档）。回测走 Warm 层 point-in-time 数据，禁 look-ahead bias。
2. **风控横切独立 veto**：Risk 作为独立 sidecar，可否决不可改策略；事前限额/事中 kill-switch/事后归因三层。
3. **Supervisor 显式路由日志**：DreamOS SACG 每次路由记 `routing_decision → worker → result`，接入全链路 trace。
4. **上下文双模管理**：worker 默认 isolated；需继承 supervisor 决策上下文用 fork；长链路自动 compaction。
5. **记忆三层闭环**：session 级（对话历史）+ durable 级（4-MEMORY 认知 recall→record→verify）+ wiki 级（LLM wiki 编译）。三者索引统一同步。
6. **FAIL-OPEN 与人机协作**：敏感操作（下单/调仓）走 human-in-the-loop；告警走飞书 IM；LLM 降级链不阻塞热路径。
7. **Skill 分布式 over MCP**：子域能力以 Skill 注册到 MCP，DSH/DreamOS 按需调用，避免每领域起独立 agent（成本 3-10x）。
8. **产物不可变归档**：交易记录/绩效归因/审计日志写入 immutable store；产物中台统一查询；doc-sync 自动同步索引。
9. **Security Master 主数据**：建立币种/标的持久内部 ID 映射，处理 splits/renaming，保证多源数据对齐。
10. **回测验证闭环**：dream-backtest-verify 5步（load trades→fetch klines→detector gate→rebound attribution→value report），Deflated Sharpe Ratio 防 p-hacking。

---

## 六、FAIL-OPEN 与异常处理

| 异常场景 | 处理策略 |
|----------|---------|
| 前端 8095 bridge 不可用 | 回退 8092 Classic System，再回退 task_poller |
| DreamOS 8000 不可用 | 前端默认不接 DreamOS（需 DREAMOS_BRIDGE_ENABLED 灰度开启） |
| DSH 子 agent 执行失败 | FAIL-OPEN 默认中性兜底 + 6层堆栈日志 |
| 重原生库 import 失败 | lazy_import_heavy 降级，不崩溃（F-06） |
| 认知 record 失败 | 不阻塞主流程，仅本地日志 |
| 文档同步失败 | 永不阻塞交易热路径，降级为告警 |

**核心原则**：所有异常降级为告警，不阻塞交易热路径。

---

## 七、认知闭环（recall + record + verify）

**任务开始前**（硬约束，不可跳过）：

```
recall(context="三层架构 能力协同 主骨架 子域能力 <关键词>", top_k=5, min_quality="C")
```

**任务完成后**：

```
record(content="[架构协同] <编排摘要> | 调用链: <层列表> | 子域: <列表> | 结果: <成功/失败>",
       quality_level="B",
       tags="架构三层协同域,主骨架,能力调用,<域标签>")
```

**硬约束记忆闸门**（P0级）：任何用户已确认的项目决策，正文含"必须/禁止/默认/下限/上限/阈值"关键词之一，必须在用户确认后30秒内 record，质量 ≥B 级，tags 标"硬约束"+域标签。

---

## 八、相关 SKILL 与工具

| 类型 | 名称 | 用途 |
|------|------|------|
| 同构 | `dreambuddy-os` | DreamOS 调度层（本 SKILL 的上层入口） |
| 同构 | `dream-doc-sync-workflow` | 文档索引同步（Step 5 产物归档后调用） |
| 工作流 | `dream-tdd-dev-workflow` | TDD 开发周期 |
| 工作流 | `dream-backtest-verify` | 回测验证 5步 |
| 工作流 | `dream-feature-landing-workflow` | DreamOS 功能落地 |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |
| 调研 | `dream-research-workflow` | 深度调研 |

---

## 九、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-30 | 初始版本：三层架构总览+7步调用流程+10条规范流程+LLM四阶段+FAIL-OPEN+认知闭环。来源：双维度验证(26/26)+7场景测试(全✅)+传统金融/AI多agent调研 |
