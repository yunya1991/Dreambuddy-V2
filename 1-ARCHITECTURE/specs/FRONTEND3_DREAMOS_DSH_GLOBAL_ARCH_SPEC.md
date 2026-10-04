# 全局架构现状与 11 缺口 SPEC (SPEC-A)

> **版本**: v1.2
> **日期**: 2026-09-29
> **状态**: ✅ 用户已批准 + Muse 缺口 #11 已澄清 + P2 五缺口代码证据复核修正
> **作者**: dreambuddy-v2 架构盘点（基于两轮深度探索）
> **定位**: 前端3.1 + DreamOS SACG + DSH Subagent + 中台三大组件 的**架构层面**现状与缺口
> **调研方法**: recall 认知记忆 + Explore agent 代码审计 + 文档比对 + 行业对标
>
> **与既有文档关系**:
> | 既有文档 | 维度 | 关系 |
> |----------|------|------|
> | [WORKBUDDY_OS_GAP_ANALYSIS.md](../WORKBUDDY_OS_GAP_ANALYSIS.md) (v1.0, 2026-06-30) | **模块层面**：A/C/F/G/T 五域功能模块"文档定义 vs 代码实现"清单 | **互补**：前者聚焦模块清单，本 SPEC 聚焦跨层架构协同 |
> | [WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md](../WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md) (v1.0, 2026-07-01) | UFO²/Skill Compose/Nacos/LangGraph/AutoGen/CrewAI 行业对标 | **增量更新**：覆盖 2025-2026 最新趋势由 SPEC-B 接续 |
> | [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md) (v0.2, 2026-09-24) | DSH 9 Subagent 详设 | **本 SPEC §四 引用并审计现状** |
> | [SYSTEM_ARCHITECTURE_OVERVIEW.md](../SYSTEM_ARCHITECTURE_OVERVIEW.md) (v2.3, 2026-07-03) | DreamOS 三层+SACG 四层职责表 | **本 SPEC §三 引用** |
> | [v3-frontend-architecture.md](../../3.1-FRONTEND/docs/v3-frontend-architecture.md) (1751行) | 前端3.1 综合技术文档 | **本 SPEC §二 引用并对比文档/实现差距** |
>
> **后续**: SPEC-B（行业对标+架构优化方案）由并行调研 Agent 输出后形成

---

## 一、三层 OS 架构总览

```
┌────────────────────────────────────────────────────────────────────┐
│  应用层 — 前端3.1 (Next.js, port 3001)                              │
│  • 41 路由 / 62 组件 / 12 Store                                     │
│  • Agent B (基本面研究) + Agent A (技术分析)                        │
│  • 三屏交易 + 研究助手                                              │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ 92 API 端点 / IPC NDJSON
┌──────────────────────────────┴─────────────────────────────────────┐
│  OS 内核 — DreamOS SACG 四层 (Orchestrator, 编排规划)               │
│  S: IntentEngine 识别意图                                           │
│  A: GraphPlanner 编排执行图（选 A/C/F 链, 纯编排不执行业务）        │
│  C: GraphExecutor + Reflector + Aggregator ← C-Drive-Agent 驱动   │
│  G: GraphStore + Checkpointer                                      │
│  横切: Registry / Evolution / Budget                                │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ IPC NDJSON
┌──────────────────────────────┴─────────────────────────────────────┐
│  驱动力层 — DSH Subagent 架构 (隔离执行, 独立上下文)                 │
│  C-Drive-Agent 4 步循环：recall → 反思(含 Bull/Bear) → jeval → 路由│
│  ┌────────────┬────────────┬────────────┬────────────┬──────────┐ │
│  │technical   │sentiment   │macro       │flow        │onchain   │ │
│  │(C1+C2+C3)  │(F1)        │(F5)        │(F2)        │(F4)      │ │
│  └────────────┴────────────┴────────────┴────────────┴──────────┘ │
│  ┌────────────┬────────────┐                                       │
│  │valuation   │risk        │  portfolio (P2, 节点全缺)             │
│  │(F3)        │(P2, 无节点)│                                       │
│  └────────────┴────────────┘                                       │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│  中台三大组件（横切支撑）                                            │
│  ① 产物中台 Artifact Hub      ② 网关中台 Gateway Hub    ③ 百炼集成  │
│  AI 产物投递+归档+邮件路由   认证+API配置+交易参数+积分  API+KB+RAG │
│  ✅ 新路径已落地(v1.2)       ✅ 3-FRONTEND/ 已实施      ✅ 已闭环   │
│  ⚠️ 遗留代码待废弃声明                                           │
└────────────────────────────────────────────────────────────────────┘
```

### 1.1 职责分层原则（硬约束）

| 层 | 职责 | 类比 | 关键约束 |
|----|------|------|---------|
| 前端3.1 | 用户交互+可视化 | UX 层 | 不做业务决策 |
| DreamOS SACG | 编排规划——"做什么" | OS 内核调度器 | **纯编排不执行业务**（A 层硬约束） |
| DSH Subagent | 驱动力——"怎么做" | OS 驱动程序 | 隔离执行，subagent 间不通信（HC-7） |
| 中台 | 横切支撑 | 共享底座 | 跨层共享，避免重复 |

### 1.2 数据驱动避幻觉（硬约束）

- DSH Subagent 的**输入数据**必须来自 DreamOS 编排节点（F1-F5 + C1-C3）的**已验证输出**
- LLM **只做提炼和图表生成**，不生成原始数据
- 节点能力经过回测验证和实盘检验，规避大模型幻觉

---

## 二、前端3.1 现状

### 2.1 实现盘点

| 维度 | 文档规划 | 实际实现 | 完成率 |
|------|---------|---------|--------|
| 路由 | 40 子页面 | 4 子页面 | **10%** |
| 子页面 classic (9) | 9 | 0 | 0% |
| 子页面 fundamental (11) | 11 | 0 | 0% |
| 子页面 monitor (4) | 4 | 0 | 0% |
| 子页面 settings (4) | 4 | 0 | 0% |
| 子页面 memory (2) | 2 | 0 | 0% |
| 子页面 trade (2) | 2 | 0 | 0% |
| governance | 3 子页面 | /board/* 已替代 | 部分 |
| 路由前缀 | /v3/dashboard/* | /dashboard/*（无 v3 前缀） | **偏离** |
| API Client | 19 域拆分 (src/lib/v3/api/{task,chat,market,...}.ts) | api-client.ts 单文件 | **5%** |
| 组件分层 | src/components/v3/{layout,screens,features,primitives,hooks}/ | src/components/{V3*.tsx, features/} 平铺 | **偏离** |

### 2.2 已实现核心能力

- **41 路由 / 62 组件 / 12 Store**：核心交易工作流可用
- **Agent B**（基本面研究）：F1-F5 数据接入与展示
- **Agent A**（技术分析）：C1-C3 技术指标与 K 线
- **三屏交易**：周线/日线/实时 三屏协同
- **研究助手**：T 域搜索+产物记忆

### 2.3 README.md 与实现的矛盾（需修复）

- README.md 称"代码在 3-FRONTEND/"，实际 `3.1-FRONTEND/` 本身已是完整 Next.js 项目
- 文档规划 40 子页面，实际仅实现 4（**完成率 10%**）
- API Client 文档要求 19 域拆分，实际仅 `api-client.ts` 单文件
- 组件分层文档要求 5 层（layout/screens/features/primitives/hooks），实际只有平铺

---

## 三、DreamOS SACG 四层现状

### 3.1 S 层（Sense 感知）

- **IntentEngine**：6 类意图识别（execute_trade / market_query / analysis / strategy / risk / dialog）
- **前端规则引擎 + 内核分类器双层**：前端 confidence>=0.9 跳过 LLM，节省 10-30s 延迟
- **意图权重**：trade(3.0) > analysis(2.5) > strategy/risk(2.0) > query(1.0) > dialog(0.5)
- **现状**：✅ 已运行（VM-1789577077862 验证：'分析比特币价格走势' 修正为 analysis/technical_analysis）

### 3.2 A 层（Arrange 编排）

- **GraphPlanner**：纯编排层，选 A/C/F 链生成执行图
- **硬约束**：A 层不执行业务逻辑，只规划
- **三链派发**：A 链（AI 决策）/ C 链（经典量化）/ F 链（基本面）
- **现状**：✅ 已运行（参考 [THREE_CHAIN_DISPATCH_CHECKLIST.md](../THREE_CHAIN_DISPATCH_CHECKLIST.md)）

### 3.3 C 层（Compute 执行）⚠️ 关键缺口

| C 层组件 | 现状 | 目标 | 差距 |
|---------|------|------|------|
| `GraphExecutor.execute()` | 内部调度 C1→C2→C3，返回 ExecutionReport | DSH subagent 驱动执行 | ❌ 无 DSH 接入 |
| `Reflector.decide()` | 低置信度返回 REDO（重做当前节点） | 1.调认知 2.反思 3.jeval 4.补资料 | ❌ **只有 REDO** |
| `Aggregator.aggregate()` | 按节点结果算方向/置信度 | 聚合 subagent 输出+图表配置 | ❌ 无图表 |
| 认知系统 | `cognitive_loop_adapter.py` L62-85 已封装 recall/record/verify | C 层直接调用 | ⚠️ 适配器存在但未接入 C 层 |
| jev-judge | 通过 Python IPC 接入 harness（3 个 Harness 事件） | C 层 Aggregator 聚合后调用 | ⚠️ 在 harness 层未进 C 层 |

**关键证据**：
- [graph_executor.py](../../dreamos/) L100-106：`execute()` 签名无认知/jeval/subagent 接口
- [reflector.py](../../dreamos/) L127-140：当前只有 REDO 逻辑，无认知查询
- `cognitive_loop_adapter.py` L62-85：recall 封装已存在，MCP 不可用时返回 `[]`（FAIL-OPEN）
- recall 记忆 VM-1786324739691：Reflector REDO 机制已验证运行（95 次/日，max_retries=2）

### 3.4 G 层（Graph 存储）

- **GraphStore + Checkpointer**：执行图状态持久化
- **现状**：✅ 基础运行，但 Checkpoint 机制未达到 LangGraph 级别（中断恢复/回溯弱）
- **参考**：[WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md](../WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md) §2.4 LangGraph 对比

### 3.5 横切组件

| 横切 | 职责 | 现状 |
|------|------|------|
| Registry | 35 个模块配置 + 11 个本地实现 | ✅ 已运行 |
| Evolution | 自进化系统（CBR/KNN 案例库 + 贝叶斯参数优化） | ⚠️ 部分实施，未与 DSH 闭环 |
| Budget | Tavily 预算/成本控制 | ⚠️ 进行中 |

---

## 四、DSH Subagent 架构现状

### 4.1 9 个 Subagent 清单（来自 [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md) v0.2）

| Subagent | 对应节点 | 数据源 | 图表类型 | 优先级 |
|----------|---------|--------|---------|--------|
| `C-Drive-Agent` | C 层本身 | 认知库 + jeval | — | P0 |
| `technical-agent` | C1+C2+C3 | OKX K线 | K线+指标叠加 | P0 |
| `sentiment-agent` | F1 | 贪婪恐惧/期权 PCR | 仪表盘+折线 | P0 |
| `macro-agent` | F5 | GDP/CPI/利率/流动性 | 柱状+趋势线 | P1 |
| `flow-agent` | F2 | ETF/杠杆/稳定币 | Sankey+柱状 | P1 |
| `onchain-agent` | F4 | 活跃地址/算力/MVRV | 折线+热力图 | P1 |
| `valuation-agent` | F3 | NVT/StockFlow | 散点+回归线 | P1 |
| `risk-agent` | 无 | 需新建 VaR/相关性/压力 | 热力图+矩阵 | P2 |
| `portfolio-agent` | 无 | 需新建 仓位/再平衡 | 饼图+柱状 | P2 |

### 4.2 现状审计（关键发现）

- DSH 当前**没有 subagent 概念**，是"Cordis 插件 + 节点链路"架构
- `cordis-plugin-fundamental` 把 F1-F5 **全混在一个 tool** 里返回（违反单一职责）
- **图表能力完全缺失**：所有插件输出都是 JSON 文本或文本卡片
- 前端 `src/app/fundamental/` 下有 12 个基本面页面，但 DSH **无对应 subagent 输出结构化数据**

### 4.3 Subagent 输出契约（v0.2 设计，待实施）

```typescript
interface SubagentOutput {
  module: string;           // "macro" | "flow" | "onchain" | ...
  summary: string;          // LLM 提炼的 1-2 句人读结论
  signals: Signal[];        // 标准化信号 [{name, value, direction, confidence}]
  charts: ChartSpec[];      // 图表配置 [{type, title, data, config}]
  raw_data?: any;           // 原始数据（可选，供下钻）
}

interface Signal {
  name: string;
  value: number | string;
  direction: "long" | "short" | "neutral";
  confidence: number;       // 0.0-1.0
}

interface ChartSpec {
  type: "candlestick" | "line" | "bar" | "sankey" | "gauge" | "scatter" | "heatmap" | "pie";
  title: string;
  data: any;
  config?: any;
}
```

### 4.4 C-Drive-Agent 四步循环详设（v0.2，待实施）

```
C 层每个节点执行后：
  Step 1: recall(context, top_k=5, min_quality="C") → 历史相似场景经验
  Step 2: Reflector 扩展（含 Bull/Bear 辩论，置信度<0.65 时触发）
  Step 3: jeval 判断（仅 Step 2 返回 CONTINUE 时）→ noul>=0.85 放行 / noul<0.50 阻止
  Step 4: subagent 补充（仅 Step 2 返回 SUPPLEMENT 时）→ 路由到对应 subagent
```

**分级触发机制**（避免延迟累积）：

| 置信度 | 触发动作 | 预估延迟 |
|--------|---------|---------|
| > 0.75 | 跳过四步循环，直接下一节点 | 0ms |
| 0.65-0.75 | 只 Step 1 recall + Step 2 反思 | ~50ms |
| 0.50-0.65 | recall + 反思 + Bull/Bear 辩论 | ~200-300ms |
| < 0.50 | 全链路四步循环（含辩论 + subagent 补充） | ~500ms-1s |

### 4.5 实现形态决策

- **采用**：Cordis 插件 + Python server IPC（与现有架构一致，不引入新框架）
- **不采用**：Claude Managed Agent（外部依赖）/ LangGraph 节点（引入新框架）

---

## 五、中台三大组件

### 5.1 产物中台 Artifact Hub ✅ 新路径已落地（v1.2 修正）

- **核心功能**：AI 产物投递 + 归档 + 邮件路由 + 跨部门交付流转
- **现状（代码证据复核后）**：
  - ✅ 新路径 `dreamos/core/artifact/store.py` 已落地（save/list/get/delete/search/stats 全实现，M1+M2+M3 完成）
  - ✅ 前端 `/api/artifacts/route.ts` + `ArtifactGallery.tsx` 已落地（集成到 `/dashboard/notebook`）
  - ⚠️ `7-ARTIFACT_HUB/` 目录已不存在（v1.1 SPEC 描述路径错误）
  - ⚠️ 遗留代码在 `11-易经推理系统/skills/0-CORE/artifact-alignment-manager/`，需废弃声明
- **存储**：`scheduler_data/artifacts/{type}/{id}.json`（6 类产物：insight_card/mood_board/bull_bear_debate/briefing/report/chart）
- **参考**：[COMPANY_CENTRAL_HUB.md](../中台设计/COMPANY_CENTRAL_HUB.md)（公司中枢设计）

### 5.2 网关中台 Gateway Hub ✅ 已实施

- **核心功能**：用户认证 + API 配置管理 + 交易参数 + 积分系统
- **现状**：`3-FRONTEND/dream-universal-gateway/` Next.js 项目运行
- **状态管理**：`src/stores/`
- **核心库**：`src/lib/`

### 5.3 百炼集成中心 ✅ 已基本完成闭环（v1.2 修正）

- **核心功能**：统一 API 调用管理 + 知识库 + RAG 配置 + Function Calling
- **现状（代码证据复核后）**：
  - ✅ `11-易经推理系统/skills/2-INTELLIGENCE/dream-bailian-integration/` SKILL 完整存在
  - ✅ `bailian_client.py`（API 调用管理，含重试/错误处理）
  - ✅ `rag_engine`（RAG 检索）、`function_caller`（Function Calling）、`workflow_engine`（工作流编排）四能力全 ✅
  - ✅ DSH 接入路径已实现：`subagent_registry.py` `set_llm_fn_provider` + `make_bailian_llm_fn` + `register_subagents_with_bailian`（FAIL-OPEN 容错）
- **缺口**：SPEC 状态描述过时（v1.1 说"接入路径未明确"，实际已闭环）

---

## 六、11 个缺口详表（按优先级）

### 6.1 P0 缺口（影响核心决策闭环，2 个）

| # | 缺口 | 现状 | 目标 | 影响范围 |
|---|------|------|------|---------|
| 1 | **DSH 图表能力完全缺失** | 输出仅 JSON/文本，无 charts 字段 | SubagentOutput.charts[] 完整支持 8 类图表 | DSH 全栈 + 前端3.1 12 个基本面页面 + 三屏交易可视化 |
| 2 | **Reflector 仅 REDO 未接入认知/jeval/subagent** | L127-140 只有 REDO 逻辑 | 4 步循环（recall → 反思 → jeval → 路由） | C 层全部 + C-Drive-Agent + A0 矛盾论输入 |

### 6.2 P1 缺口（影响前端3.1 完整性，3 个）

| # | 缺口 | 现状 | 目标 | 影响范围 |
|---|------|------|------|---------|
| 3 | **前端3.1 缺 C-Drive-Agent 4 步循环可视化** | 无 SACG C 层执行步骤的可视化 | 实时显示 recall/反思/jeval/路由 4 步进度 | 前端3.1 /dashboard/monitor/* + Agent A |
| 4 | **缺 Bull/Bear 辩论 UI** | 无多空对抗可视化 | 显示 bull_confidence vs bear_confidence + 关键论据列表 | 前端3.1 /dashboard/analysis/* |
| 5 | **缺 SubagentOutput charts 字段消费组件** | 无统一图表渲染组件 | ECharts 集成，支持 8 类图表类型 | 前端3.1 全栈（fundamental/technical/monitor） |

### 6.3 P2 缺口（影响治理与功能完整性，5 个）

> **v1.2 修正（2026-09-29）**：基于代码证据复核，5 项描述与实际代码存在偏差，已对齐。修正率 4/5（80%），印证记忆 VM-1790639109113。

| # | 缺口 | 现状（代码证据复核后） | 真实剩余工作量 | 影响范围 |
|---|------|------|------|---------|
| 6 | **前端3.1 SACG 监控缺 sense/compute 子页** | ✅ `/dashboard/monitor/page.tsx` 父页面已存在，含 4 tabs（SACGOverview/DAGGraphView/BACTimeline/HistoryPlayer），arrange/graph 功能通过 tabs 部分覆盖；❌ 缺 sense 子页对应 `SenseConfidenceGauge` 组件；❌ 缺 compute 子页对应 `ReflectorPanel` + `CrossValidationPanel` 组件；❌ 缺 4 子目录路由（v3-frontend-architecture.md §C 规划 `/v3/dashboard/monitor/{sense\|arrange\|compute\|graph}`） | 补 sense/compute 两个子页组件 + 4 子目录路由（可选，tabs 已部分覆盖 arrange/graph） | 前端3.1 monitor/ |
| 7 | **Meta-Labeling 前后端割裂** | ✅ 前端 `/dashboard/meta-labeling/page.tsx` 已存在 228 行完整实现（含 L1Signal/MetaLabelResult 接口、computeMetaLabel 函数、决策矩阵、统计卡片、过滤器）；✅ 后端 `11-易经推理系统/scripts/memory_l4/bcrm2/meta_labeling_features_v2.py` `MetaLabelingFeaturesV2` 类 11 方法（含 Kelly 公式、概率校准）；❌ 前端使用 MOCK_SIGNALS 硬编码数据，无 API 端点桥接 | 补 1 个 API 端点（`/api/meta-labeling`）桥接前后端 | 前端3.1 + 11-易经推理系统 |
| 8 | **DreamOS 节点层缺 risk/portfolio 桥接** | ✅ DSH Subagent 层已完整实现：`dream-harness-bridge/packages/python-server/risk_agent.py` L16-L325（VaR95/99、相关性、压力测试 ML 三管线 PCA/AE/VAE、compute_portfolio_heat）；`portfolio_agent.py` L16-L293（compute_allowed_actions、漂移度、再平衡、饼图+柱状）；✅ `subagent_registry.py` 已注册 DSH_RISK + DSH_PORTFOLIO；❌ DreamOS `nodes.yaml` 缺 risk/portfolio 对应节点（只有 G1_risk_control 是 G 链风控，非 risk-agent 的 VaR/压力/相关性） | 在 nodes.yaml 新增 2 个 DreamOS 节点映射（risk/portfolio → DSH subagent） | DreamOS nodes.yaml + DSH |
| 9 | **百炼集成已基本完成闭环**（SPEC 过时修正） | ✅ `11-易经推理系统/skills/2-INTELLIGENCE/dream-bailian-integration/` SKILL 完整存在：`bailian_client.py`（API 调用管理）、`rag_engine`（RAG）、`function_caller`（Function Calling）、`workflow_engine`（工作流编排），四能力全 ✅；✅ DSH 接入路径已实现：`subagent_registry.py` `set_llm_fn_provider` + `make_bailian_llm_fn` + `register_subagents_with_bailian`（FAIL-OPEN 容错，无 API key 走规则降级） | 仅需更新 SPEC 状态描述（代码已闭环） | 中台百炼 |
| 10 | **产物路径新路径已落地，遗留代码待废弃声明** | ✅ `7-ARTIFACT_HUB/` 目录已不存在（SPEC 原描述路径错误）；✅ 新路径 `dreamos/core/artifact/store.py` 已落地（save/list/get/delete/search/stats 全实现）；✅ 前端 `/api/artifacts/route.ts` + `ArtifactGallery.tsx` 已落地；⚠️ 遗留代码在 `11-易经推理系统/skills/0-CORE/artifact-alignment-manager/`（非 SPEC 所述路径），需废弃声明 | 在遗留路径加废弃声明（参考 P1#1 experiments/ 模式） | 产物中台 |

### 6.4 已澄清缺口（1 个）

| # | 缺口 | 现状 | 澄清结论 |
|---|------|------|---------|
| 11 | **Muse 在仓库内无文档** | 用户曾提到"引入 muse 一些功能(meta新产品)"未明确 | ✅ **已澄清（2026-09-28）**：Muse = Meta 公司 2026-07 推出的消费级 AI 智能体（**Muse Spark 1.1**），由 Meta Superintelligence Labs 开发，定位为"个人超级智能"产品体验优化。**核心体验能力**：(1) 主动执行任务（不只被动答疑，可打电话/取消订阅/找折扣）；(2) 实时干预（用户在生成过程中可 steer 方向/语气/裁剪章节）；(3) 产物归一存储（mood boards/训练计划/slides 全部一处可回看可分享）；(4) Daily Briefing（每日简报+日历+趋势）；(5) Research Deep Dives（多源综合）；(6) 多 subagent 并行编排（main agent 委托 execution across parallel subagents）；(7) 1M token 上下文 + active context compaction；(8) Computer Use 跨多应用工作流。**已有 Muse 启发实现**：3.1-FRONTEND `InsightCard.tsx`/`RecommendationCard.tsx`/`SynthesisChart.tsx`(sankey/heatmap/gauge/line/bar)/`ReportExport.tsx`(MD+PDF 导出) + dream-harness-bridge `synthesized_cards` 字段。**3-FRONTEND 缺口**：dream-universal-gateway 仅有 `TaskCard.tsx`+`MessageItem.tsx` 基础渲染，**未移植** InsightCard/SynthesisChart/ReportExport 等 Muse 启发组件 → 移植 + 升级为 SPEC-B F7 优化项 |

---

## 七、关键术语澄清（避免概念混淆）

### 7.1 "C" 系列的三层抽象

| 术语 | 抽象层 | 含义 |
|------|--------|------|
| **前端 C 系列 (C0-C8)** | 前端组件层 | 前端 classic 模式本地思维链步骤（9 步） |
| **SACG C 层 (Compute)** | OS 内核层 | DreamOS 执行层（GraphExecutor + Reflector + Aggregator） |
| **DreamOS C 链 (技术链)** | 业务编排层 | A/C/F 三链之一，对应经典量化（C1-C5） |

> 三者是**不同抽象层**的概念，避免在跨层文档中混用。

### 7.2 Meta = Meta-Labeling（非 Meta 公司）

- **位置**：[meta_labeling_features_v2.py](../../11-易经推理系统/scripts/memory_l4/bcrm2/meta_labeling_features_v2.py)
- **定义**：量化术语，L1→L2→L3 决策链的 **L2 时机判断模块**
- **技术**：LightGBM/XGBoost 二分类器，预测 L1 信号是否盈利（不是元数据产品）
- **参考**：[TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) L1→L2 Meta-Labeling→L3 辩证裁决

### 7.3 Subagent 输出契约（v0.2 spec，待实施）

- `SubagentOutput.charts` 字段**前端无消费组件** → 缺口 #5
- `SubagentOutput.signals` 已被 Aggregator 部分消费
- `SubagentOutput.raw_data` 用于下钻（前端无 UI） → 缺口 #6

---

## 八、与 WORKBUDDY_OS_GAP_ANALYSIS 的关系

| 维度 | WORKBUDDY_OS_GAP_ANALYSIS (v1.0, 6-30) | 本 SPEC (v1.0, 9-28) |
|------|---------------------------------------|---------------------|
| 盘点层面 | **模块层面**：A/C/F/G/T 五域功能模块"文档定义 vs 代码实现" | **架构层面**：跨层（前端3.1 + SACG + DSH + 中台）协同 |
| 缺口示例 | A5 战术执行 / A6 情报监控 / A7 实践门禁 / C2 Regime | DSH 图表缺失 / Reflector 仅 REDO / SubagentOutput charts 前端无消费 |
| 互补点 | 模块清单已实现/未注册/缺失分类 | 跨层架构协同缺口 + 行业对标 |
| 共同覆盖 | 都识别 risk/portfolio 全缺（§六 #8 与 GAP §六 G 域） | 一致 |

> 两份文档**互补**：GAP_ANALYSIS 解决"哪些模块没实现"，本 SPEC 解决"已实现的模块如何跨层协同+对齐行业最佳实践"。

---

## 九、引用前置文档清单

| 类别 | 文档路径 | 用途 |
|------|---------|------|
| DreamOS | [SYSTEM_ARCHITECTURE_OVERVIEW.md](../SYSTEM_ARCHITECTURE_OVERVIEW.md) (v2.3) | 三层+SACG 四层职责表 |
| DreamOS | [WORKBUDDY_OS_MODULAR_ARCHITECTURE.md](../WORKBUDDY_OS_MODULAR_ARCHITECTURE.md) | 52 模块注册表 + A/C/F/G/T 域 |
| DreamOS | [RESEARCH_SACG_HARNESS_MAPPING.md](../RESEARCH_SACG_HARNESS_MAPPING.md) | SACG→Harness 工程映射 |
| DreamOS | [THREE_CHAIN_DISPATCH_CHECKLIST.md](../THREE_CHAIN_DISPATCH_CHECKLIST.md) | 三链派发清单 |
| DreamOS | [WORKBUDDY_OS_GAP_ANALYSIS.md](../WORKBUDDY_OS_GAP_ANALYSIS.md) (v1.0) | 模块层面缺口（互补） |
| 行业对标 | [WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md](../WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md) (v1.0) | UFO²/Skill Compose/Nacos/LangGraph 调研 |
| DSH | [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md) (v0.2) | 9 Subagent 详设 |
| DSH | [CHAIN_INTEGRATION_SPEC.md](../dream-harness-bridge/docs/CHAIN_INTEGRATION_SPEC.md) | 端口统一方案 A（已实施） |
| 中台 | [中台设计/README.md](../中台设计/README.md) | 三大中台索引 |
| 中台 | [COMPANY_CENTRAL_HUB.md](../中台设计/COMPANY_CENTRAL_HUB.md) | 公司中枢设计 |
| DSH 配置 | [cordis.yml](../dream-harness-bridge/.dsh-home/profiles/web/cordis.yml) | DSH/Cordis 插件配置 |
| 前端3.1 | [v3-frontend-architecture.md](../../3.1-FRONTEND/docs/v3-frontend-architecture.md) (1751行) | 综合技术文档 + P0-P3 路线图 + 92 API 端点 |
| 前端3.1 | [3.1-FRONTEND/README.md](../../3.1-FRONTEND/README.md) | 索引（已过时） |
| Meta-Labeling | [TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) | L1→L2→L3 决策链 |
| Meta-Labeling | [meta_labeling_features_v2.py](../../11-易经推理系统/scripts/memory_l4/bcrm2/meta_labeling_features_v2.py) | V2 实现 |

---

## 十、下一步行动

| 阶段 | 行动 | 状态 |
|------|------|------|
| ✅ 完成 | recall 检索相关经验（硬约束） | 已完成 |
| ✅ 完成 | 两轮深度盘点（前端3.1 + DreamOS + DSH + 中台） | 已完成 |
| ✅ 完成 | 本 SPEC-A 形成 | 本文档 |
| 🔄 进行中 | 并行启动 3 维度行业对标调研（金融产品 / AI multi-agent / GitHub 开源） | 3 个 Agent 后台运行 |
| ⏳ 待启动 | SPEC-B：行业对标调研结论与架构优化方案 | 等 3 个 Agent 调研结果 |
| ⏳ 待启动 | NotifyUser 提交两份 SPEC 供 review | SPEC-B 完成后 |
| ⏳ 待启动 | hermes 反思：是否形成新 SKILL（如 dream-arch-gap-analysis-workflow） | 任务结束 |

---

## 十一、本 SPEC 不覆盖项（明确边界）

为避免 SPEC 范围蔓延，以下项**不在本 SPEC 覆盖范围**，由对应专项文档处理：

| 不覆盖项 | 责任文档 |
|---------|---------|
| A/C/F/G/T 模块清单级缺口（A5/A6/A7 等） | [WORKBUDDY_OS_GAP_ANALYSIS.md](../WORKBUDDY_OS_GAP_ANALYSIS.md) |
| DSH Subagent v0.2 完整 spec（9 个 subagent 详设） | [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md) |
| 前端3.1 完整技术文档（1751 行） | [v3-frontend-architecture.md](../../3.1-FRONTEND/docs/v3-frontend-architecture.md) |
| DreamOS 完整架构（v2.3, 148K） | [SYSTEM_ARCHITECTURE_OVERVIEW.md](../SYSTEM_ARCHITECTURE_OVERVIEW.md) |
| 2025-2026 行业对标优化方案 | **SPEC-B**（待形成） |

---

*SPEC-A 版本: v1.0 | 日期: 2026-09-28 | 范围: 前端3.1 + DreamOS SACG + DSH Subagent + 中台三大组件 + 11 缺口 | 状态: 待用户 review*
