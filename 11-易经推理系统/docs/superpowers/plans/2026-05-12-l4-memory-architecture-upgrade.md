# L4 记忆系统架构升级方案 v2.1

> 状态: Draft | 日期: 2026-05-12 | 作者: 系统架构
> 本文档定义记忆系统的完整升级蓝图，作为重要地基文档供进一步调研和实现参考。
> v2.1 吸收了治理层设计（状态机、失败语义、索引分层、DoD 等），与实现层合并为完整方案。

---

## 一、设计原则

1. **Constraints 是唯一规则源（SSOT）**：Memory 不直接改写约束，记忆沉淀到约束必须经过 `memory → evolution → constraints` 唯一通道。
2. **入口层保持薄封装**：L1~L4 入口脚本只做薄封装，复杂能力下沉到 MemoryEngine 和 `scripts/memory_l4/`。
3. **全链路可追溯**：所有关键产物必须携带 `trace_id`、`evidence_refs`、`stage_id`、`constraint_version`。
4. **Fail-Closed 策略**：任何自动化升级失败即停止推进，产出结构化审计（含 stage + reason_code + evidence_refs），不允许无证据强制通过。
5. **向后兼容**：Schema 升级不破坏 v0.1 读取器，新字段全为 optional 或提供默认值。

---

## 二、现状盘点

### 2.1 当前 L4 系统已有能力

| 模块 | 文件 | 功能 |
|---|---|---|
| 路径配置 | `paths.py` | 统一目录配置 |
| Agent 权限 | `agent_acl.py` | ACL 访问控制 |
| 案例注册 | `case_registry.py` | Episode → TradeCase 注册 |
| 象限迁移 | `quadrant_migrator.py` | x/y 坐标计算与更新 |
| 失败分析 | `failure_analyzer.py` | 亏损案例聚类 → 风险信号 |
| 蒸馏模板 | `distill_template.py` | 创建 Distill 骨架 |
| 索引构建 | `index_builder.py` | 搜索特征提取 |
| 相似查询 | `query_similar.py` | 三维相似度匹配 |
| 统计构建 | `stats_builder.py` | 聚合快照 |
| 仪表盘 | `dashboard_renderer.py` | Plotly HTML 渲染 |
| 内存总线 | `shared_memory_bus.py` | JSONL 事件通信 |
| 记忆图谱 | `memory_graph.py` | Agent-记忆关系图 |
| 元学习 | `meta_learning_tasks.py` | 假设验证/回测任务调度 |
| 迁移映射 | `migration_mapper.py` | 跨市场风险映射 |

### 2.2 当前数据模型

- **TradeCase** (`.workbuddy/memory_l4/schemas/trade_case.schema.json`): 交易案例，包含 intent/investigation/plan/execution/review/quadrant
- **Distill** (`.workbuddy/memory_l4/schemas/distill.schema.json`): 蒸馏教训，包含 kind/claim/supporting_case_ids/actionable_rules/quadrant
- **Stats** (`.workbuddy/memory_l4/schemas/stats.schema.json`): 聚合统计快照

### 2.3 当前象限体系

- **X 轴 (-1 → +1)**: 伤害 → 受益，从 PnL 推导（5% = 1.0）
- **Y 轴 (0 → 1)**: 确定性强度 = 0.4×perf + 0.4×consistency + 0.2×human
- **一致性阶梯**: 1→0.2, 2→0.35, 3→0.5, 5→0.65, 8→0.75, 13→0.85, 21→0.95, 21+→1.0

### 2.4 当前缺口

| 缺口 | 说明 | 优先级 |
|---|---|---|
| A0-A9 思维链缺失 | TradeCase.plan.steps 只是字符串数组，无法承载完整决策证据链 | P0 |
| 实时检索缺失 | L1 仅有文件存储，无实时检索接口 | P0 |
| 复盘仅分析失败 | failure_analyzer 只处理 pnl<0 案例，缺少成功分析 | P0 |
| 蒸馏过于简单 | distill_template 只生成骨架，无 what/why/how 三层逻辑 | P0 |
| L4 状态机缺失 | 无内部状态流转与失败语义定义 | P0 |
| 索引分层缺失 | 只有结构化索引，无语义索引与一致性要求 | P1 |
| A7/A8 无桥接 | 理论与实践 SKILL 输出未接入 L4 消费管道 | P1 |

---

## 三、L4 在整体中的定位

### 3.1 分层职责声明

| 层级 | 职责 | 延迟要求 |
|---|---|---|
| **L1** | 检索与相关性排序，实时支持 A0-A9 各阶段决策 | 毫秒~秒级 |
| **L2** | 短期反馈与健康检查（Bandit + 一致性） | 秒~分钟级 |
| **L3** | 长期索引维护与质量巡检（向量文档与索引资产） | 分钟级 |
| **L4** | **归档层分析与进化输入**：失败/成功分析、迁移映射、共享图谱、元学习任务 | 分钟~小时级 |

> **L4 不是"另一个检索层"，而是经验升格与跨周期进化的中台输入层。**

### 3.2 总体架构分层

```
┌─────────────────────────────────────────────────────────────────┐
│                        A0-A9 交易系统                          │
│  A0矛盾 A1调研 A2第一性 A3模拟 A4验证 A5执行                    │
│  A6监控 A7实践理论 A8理论验证 A9离场                            │
│         │                                      ▲               │
│         │ 调用记忆                             │ 反馈结果       │
├─────────┼──────────────────────────────────────┼───────────────┤
│         ▼                                      │               │
│  ┌──────────────┐    ┌──────────────────┐      │               │
│  │  L1 实时检索  │───→│  L4 记忆引擎     │──────┘               │
│  │  (毫秒~秒级)  │    │  (分钟~小时级)   │                      │
│  └──────┬───────┘    └──────┬───────────┘                      │
│         │                   │                                   │
│         │  共享 TradeCase 格式，L1 侧重实时查询，L4 侧重深度加工 │
└─────────┼───────────────────┼───────────────────────────────────┘
          │                   │
          ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                      记忆数据层 (统一存储)                       │
│                                                                 │
│  .workbuddy/memory_l4/                                         │
│  ├── cases/          ← TradeCase JSON (L1/L4 共享)             │
│  ├── distills/       ← Distill JSON                            │
│  ├── reviews/        ← ReviewRecord JSON (新增)                │
│  ├── episodes/       ← Episode 原始数据                        │
│  ├── indexes/        ← 索引文件                                │
│  └── stats/          ← 聚合统计                                │
│                                                                 │
│  artifacts/memory_l4/                                          │
│  ├── shared_bus/     ← 事件总线 JSONL                          │
│  ├── graph/          ← 记忆图谱                                │
│  ├── failure_analysis/ ← 分析产物                              │
│  └── dashboard/      ← HTML 仪表盘                             │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 完整数据流

```
                    ┌─────────────────────────────────────────────┐
                    │            交易事件闭环 (A0-A9)              │
                    │  矛盾识别→调研→第一性→模拟→验证→执行→监控→离场│
                    └─────────────────────┬───────────────────────┘
                                          │
                            Episode 数据落地
                                          │
                                          ▼
                    ┌──────────────────────────────────┐
                    │  L1: case_registry (注册 TradeCase)│
                    │  - 创建完整 TradeCase JSON        │
                    │  - 包含 thinking_chain (A0-A9)    │
                    │  - 包含 evidence_chain (证据链)   │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────┴───────────────┐
                    │                              │
                    ▼                              ▼
        ┌───────────────────────┐    ┌────────────────────────┐
        │  L1 实时检索服务       │    │  L4 记忆引擎 (批量)     │
        │  - 索引构建            │    │                        │
        │  - 相似案例查询        │    │  ┌──────────────────┐  │
        │  - 条件过滤查询        │    │  │ review_engine    │  │
        │  - A0-A9 阶段调用     │    │  │ (对错双向分析)    │  │
        └───────────────────────┘    │  └────────┬─────────┘  │
                    ▲               │           ▼             │
                    │               │  ┌──────────────────┐  │
                    │               │  │ distill_engine   │  │
                    │ 查询参考       │  │ (11步+三问)      │  │
                    │               │  └────────┬─────────┘  │
                    │               │           ▼             │
                    │               │  ┌──────────────────┐  │
                    │               │  │ quadrant_migrator│  │
                    │               │  │ (四象限量化)     │  │
                    │               │  └────────┬─────────┘  │
                    │               │           ▼             │
                    │               │  ┌──────────────────┐  │
                    │               │  │ migration_mapper │  │
                    │               │  │ (跨市场迁移)     │  │
                    │               │  └────────┬─────────┘  │
                    │               │           ▼             │
                    │               │  ┌──────────────────┐  │
                    │               │  │ meta_learning    │  │
                    │               │  │ (元学习任务调度)  │  │
                    │               │  └──────────────────┘  │
                    │               └────────────────────────┘
                    └──────────────────────────────────────────┘
```

---

## 四、核心对象模型

### 4.1 TradeCase v0.2 — 完整交易闭环事件

每笔交易必须沉淀为完整闭环事件，包含：**结果链**（收益率、回撤、离场原因、是否达成目标）、**证据链**（引用的行情、策略、报告、episode 文件）、**思维链**（A0-A9 全链路决策轨迹与阶段结论）。

核心要求：
- 必须可定位到 `case_id` 与 `trace_id`
- 必须包含 `execution.episode_refs[]` 和 `evidence_refs[]`
- 必须可被后续索引、复盘、蒸馏、统计复用

```
TradeCase (v0.2)
├── case_id, version, ts_start, ts_end, inst_id, tags  [不变]
├── intent                                              [不变]
├── investigation                                       [不变]
├── theory_refs                                         [不变]
├── environment_snapshot                                [不变]
│
├── thinking_chain        ←──────── 新增，A0-A9 完整思维链
│   └── [{
│         stage,            // "A0" ~ "A9"，实际执行过的阶段
│         ts,               // 该阶段时间戳
│         decision,         // 该阶段做出的决策
│         rationale,        // 决策理由
│         contradiction,    // A0 专用：识别到的矛盾
│         contradiction_analysis,  // A0/A8 专用：矛盾分析
│         hypothesis,       // A3/A4 专用：假设
│         test_result,      // A4/A8 专用：测试结果
│         exit_logic,       // A9 专用：离场逻辑
│         evidence_refs,    // 该阶段证据引用
│         stage_output_ref  // 该阶段产出文件引用
│       }]
│
├── evidence_chain          ←──────── 新增，完整决策证据链
│   ├── market_data_refs    // 市场数据引用
│   ├── signal_refs         // 信号/指标引用
│   ├── strategy_refs       // 策略文档引用
│   ├── historical_refs     // 历史案例引用 (指向其他 TradeCase)
│   └── constraint_refs     // 约束/规则引用
│
├── decision_outcome        ←──────── 新增，交易评估结论
│   ├── pnl_pct             // 收益率
│   ├── drawdown            // 回撤
│   ├── exit_reason         // 离场原因
│   └── goal_achieved       // 是否达成目标 (bool)
│
├── l4_status               ←──────── 新增，L4 内部状态 (见第 10 节状态机)
│
├── plan                    [不变]
├── execution               [不变]
├── online_pressure_test    [不变]
├── rollout_monitoring      [不变]
├── backtest                [不变]
├── review                  [扩展]
│   ├── summary             [不变]
│   ├── theory_practice_consistency  [不变]
│   ├── lessons             [不变]
│   ├── mistakes            ← 新增: [{what, why, severity, stage_ref}]
│   ├── successes           ← 新增: [{what, where_right, stage_ref}]
│   └── review_record_id    ← 新增: 指向 ReviewRecord 的引用
│
├── dream_reflection        [不变]
└── quadrant                [不变]
```

### 4.2 ReviewRecord v0.1 — 复盘记录

围绕 TradeCase 的理论-实践复盘对象。必须回答：**做错了什么，为什么错（根因、误判信号、约束缺口）**；**做对了什么，哪里对（有效信号、正确机制、可复用动作）**。

输出要求：
- 理论修订建议（Theory）
- 实践动作建议（Practice）
- 理论与实践一致性评分（用于蒸馏优先级）

```
ReviewRecord (v0.1)
├── review_id             // "REV_{timestamp}_{case_id}"
├── version               // "v0.1"
├── snapshot_ts           // 复盘时间戳
├── case_id               // 关联的 TradeCase
├── direction             // "success" | "failure" | "mixed"
│
├── mistakes              // [{
│     what,               // 做错了什么
│     why,                // 为什么错 (根因)
│     severity,           // 严重程度 0-1
│     stage_ref,          // 关联 A0-A9 阶段
│     theory_gap          // 理论与实践的差距
│   }]
│
├── successes             // [{
│     what,               // 做对了什么
│     where_right,        // 哪里对 (理论依据)
│     stage_ref,          // 关联 A0-A9 阶段
│     reproducible        // 是否可复现
│   }]
│
├── theory_practice_analysis  // A7/A8 交叉验证后的差距结论
│   ├── consistency_score     // 一致性评分 0-1
│   ├── confirmed_theories    // 被实践证实的理论
│   ├── contradicted_theories // 被实践证伪的理论
│   └── gap_analysis          // 差距分析
│
├── distill_proposals     // 蒸馏建议: [{distill_kind, claim, confidence}]
├── quadrant              // 复盘记录的象限坐标
├── a7_report_ref         // A7 实践理论报告引用
└── a8_report_ref         // A8 理论验证报告引用
```

### 4.3 DistillRecord v0.2 — 逻辑蒸馏记录

围绕事件闭环与复盘结果的抽象对象，必须覆盖固定链路：**意图 → 调研 → 理论 → 假设 → 测试观测 → 结论 → 落地 → 监控 → 复盘 → 做梦 → 更新优化**。

每次蒸馏必须回答三问：
- **是什么**（定义与边界）
- **为什么**（证据与因果）
- **怎么做**（可执行规则与触发条件）

```
Distill (v0.2)
├── distill_id, version  [不变]
│
├── kind                  [扩展枚举]
│   └── "benefit_experience" | "risk_signal" | "decision_heuristic"
│       | "contradiction_pattern" | "exit_logic" | "theory_update"
│
├── what_is_it            ←──────── "是什么"
│   ├── claim             // 核心主张 (兼容顶层 claim)
│   ├── definition        // 定义
│   └── classification    // 分类标签
│
├── why_it_works          ←──────── "为什么"
│   ├── causal_analysis   // 因果分析
│   ├── theory_basis      // 理论基础
│   ├── evidence_chain    // 证据链
│   └── contradiction_resolved  // 矛盾解法
│
├── how_to_apply          ←──────── "怎么做"
│   ├── actionable_rules  // 可执行规则 (兼容顶层 actionable_rules)
│   ├── trigger_conditions  // 触发条件
│   ├── step_by_step      // 逐步操作指南
│   └── risk_warnings     // 风险警戒
│
├── supporting_case_ids   [不变]
├── claim                 [保留，兼容旧版]
├── actionable_rules      [保留，兼容旧版]
│
├── process_trace         ←──────── 11步蒸馏流程追溯
│   ├── intent, investigation, theory_refs, hypothesis,
│   │   test_results, conclusion, implementation,
│   │   monitoring, review_result, reflection, optimization
│
├── quadrant              [不变]
└── migration_history     [不变]
```

### 4.4 StatsSnapshot — 四象限统计快照

统计驱动对象，用于：
- **静态库**：形成四象限分类与程度分层，支持 A0-A9 检索参考
- **动态演化**：通过量变与迁移趋势发现可验证进化候选

四象限坐标体系保持不变（x/y 不改），增加过滤维度用于精细检索：
- `regime`：市场状态（如 bull/bear/range）
- `category`：交易类型（如 trend/reversal/arbitrage）
- `severity`：影响程度（由 PnL 与风险暴露推导）

关键统计指标（最小集）：
- **事件分布**：市场、策略、情景、象限密度
- **绩效结构**：收益、回撤、胜率、尾部风险暴露
- **一致性结构**：理论-实践一致性、复盘有效率
- **迁移结构**：象限迁移率、迁移后表现稳定性

### 4.5 版本兼容性策略

- TradeCase `v0.1` 文件可被 v0.2 读取器处理（新字段缺失时使用默认值）
- TradeCase `v0.2` 写入器在保存 v0.1 文件时，新字段写入默认空值
- `thinking_chain`、`evidence_chain`、`decision_outcome`、`l4_status` 均为可选字段
- Distill 保留顶层 `claim` 和 `actionable_rules` 作为兼容层

---

## 五、索引底座设计

### 5.1 索引目标

- 支持"结构化相似 + 语义相似"的统一检索
- 支持按 case、distill、阶段、市场、风险标签的组合检索
- 支持同类历史事件快速引用，服务 A0-A9 当前决策
- 支持思维链特征检索（按 A0-A9 阶段与矛盾类型定位历史案例）

### 5.2 索引分层

| 层级 | 类型 | 匹配方式 | 用途 |
|---|---|---|---|
| **结构化索引** | case_features / distill_features | 字段匹配、规则可解释 | 阶段、regime、决策精确匹配 |
| **语义索引** | 向量文档（P3 扩展） | 案例文本、蒸馏结论、可执行规则的 embedding | 语义相似案例发现 |
| **过滤索引** | regime/category/severity/stage_id | 组合过滤 | A0-A9 精细调用 |
| **统一融合** | 实体 ID 排序 | 多索引结果融合 | 输出统一排名 |

### 5.3 索引一致性要求

| 规则 | 说明 |
|---|---|
| **CASE_NOT_INDEXED** | 案例存在但未索引视为问题，索引构建必须覆盖全部 case |
| **INDEX_CASE_NOT_FOUND** | 索引引用不得悬空，索引中的 case_id 必须对应实际文件 |
| **版本化 metadata** | 索引构建必须产出 `snapshot_ts`、`feature_version`、`weights` |

### 5.4 索引升级设计

- 文件: `scripts/memory_l4/index_builder.py`
- 改动:
  - 新增提取 thinking_chain 特征：各阶段 stage、decision、contradiction
  - 新增提取 evidence_chain 特征：引用类型分布
  - 新增 A0-A9 阶段覆盖度统计（哪些阶段有数据，哪些缺失）
  - 新增 `thinking_features` 和 `evidence_features` 字段
  - 新增索引一致性校验（悬空引用检测）

### 5.5 L1 实时检索接口

- 文件: `scripts/memory_l4/query_similar.py` (扩展)
- 新增接口:
  - `query_by_stage(stage_id, top_k)`: 按 A0-A9 阶段检索案例
  - `query_by_regime_and_outcome(regime, outcome_direction, top_k)`: 按市场状态+结果方向检索
  - `query_by_tags(tags, top_k)`: 按标签检索
  - `query_library(regime, category, min_x, min_y)`: 四象限事件库查询
  - `get_evidence_chain(case_id)`: 获取完整证据链
  - `get_thinking_chain(case_id)`: 获取完整思维链

---

## 六、复盘与蒸馏标准化工作流

### 6.1 复盘（Review）标准流程

- **输入**：完整 TradeCase + episode + evidence
- **分析**：理论与实践双维度交叉分析（失败与成功双向）
- **输出**：错因、对因、改进行动、理论实践一致性评分
- **产物**：结构化 ReviewRecord（可审计，可被蒸馏消费）

补充：
- 失败分析能力保留为子模块（兼容现有 failure_analyzer）
- Review 引擎作为上层编排，统一输出 mistakes/successes/theory_practice_gap

### 6.2 蒸馏（Distill）标准流程

- **输入**：ReviewRecord + 历史同类 case + 理论知识源
- **处理**：11 步固定链路与三问校验
- **输出**：DistillRecord（三层结构 what/why/how + process_trace）
- **校验**：必须可解释、可执行、可回测、可失败归因

### 6.3 主流程

```
A0-A9 决策执行
  -> 生成 episode 与证据
  -> 注册 TradeCase（完整闭环）
  -> L4 失败分析/成功分析（review 引擎）
  -> A7/A8 结果适配并汇入 review_record
  -> 迁移分析/共享图构建/元任务入队
  -> 复盘（理论-实践）
  -> 蒸馏（三问闭环）
  -> 四象限统计聚合
  -> 输出 evolution 候选（非直接发布）
```

---

## 七、核心模块升级设计

### 7.1 Phase 1: 记忆底层 — TradeCase + 索引升级

#### 7.1.1 TradeCase Schema 扩展

- 文件: `.workbuddy/memory_l4/schemas/trade_case.schema.json` → v0.2
- 新增 `thinking_chain` 数组字段、`evidence_chain` 对象、`decision_outcome` 对象、`l4_status` 字段
- `review` 对象新增 `mistakes[]`、`successes[]`、`review_record_id`

#### 7.1.2 case_registry 增强

- 文件: `scripts/memory_l4/case_registry.py`
- 改动:
  - `create_case_from_episode_data()`: 新增 thinking_chain/evidence_chain/decision_outcome 初始化
  - 新增 `populate_thinking_chain(case, stage_records)`: 将 A0-A9 各阶段产出填充到 thinking_chain
  - 新增 `populate_evidence_chain(case, evidence_refs)`: 将各类证据引用填充到 evidence_chain
  - 新增 `populate_decision_outcome(case, episode)`: 从 episode 提取交易评估结论
  - 版本标识从 `v0.1` 升级到 `v0.2`

#### 7.1.3 索引升级 + L1 实时检索

- 见第 5.4、5.5 节

#### 7.1.4 A0-A9 → L1 数据通道

- 文件: 新建 `scripts/memory_l4/a0a9_bridge.py`
- 功能:
  - `collect_stage_outputs(trace_id)`: 从 artifacts/trading/ 收集 A0-A9 各阶段产出
  - `build_thinking_chain_from_stages(stage_outputs)`: 将阶段产出转换为 thinking_chain 格式
  - `enrich_case_with_stages(case_id, stage_outputs)`: 将阶段数据填充到已存在的 TradeCase
  - `query_memory_for_stage(stage_id, context)`: A0-A9 阶段调用 L1 检索历史参考

### 7.2 Phase 2: 复盘引擎 — 对错双向分析

#### 7.2.1 ReviewRecord Schema

- 文件: 新建 `.workbuddy/memory_l4/schemas/review.schema.json`
- 定义如 4.2 节所示

#### 7.2.2 Review Engine

- 文件: 新建 `scripts/memory_l4/review_engine.py`
- 功能:
  - `analyze_success(case, episode)`: 成功案例分析 → 成功经验信号
  - `analyze_failure(case, episode)`: 失败案例分析 (复用 failure_analyzer 逻辑)
  - `build_review_record(case, analysis, a7_report, a8_report)`: 构建 ReviewRecord
  - `run_review(snapshot_ts, cases, episodes_by_case_id)`: 批量复盘
- 保留 `failure_analyzer.py` 作为 review_engine 的子模块导入

#### 7.2.3 A7/A8 报告桥接

- 文件: 新建 `scripts/memory_l4/a7a8_bridge.py`
- 功能:
  - `parse_a7_report(report_path)`: 解析 A7 实践理论报告 → 标准化格式
  - `parse_a8_report(report_path)`: 解析 A8 理论验证报告 → 标准化格式
  - `merge_into_review(review_record, a7_parsed, a8_parsed)`: 合并到 ReviewRecord

### 7.3 Phase 3: 蒸馏升级 — 11步流程 + 三问逻辑

#### 7.3.1 Distill Schema 扩展

- 文件: `.workbuddy/memory_l4/schemas/distill.schema.json` → v0.2
- 新增 `what_is_it`、`why_it_works`、`how_to_apply`、`process_trace`
- `kind` 枚举扩展

#### 7.3.2 Distill Engine

- 文件: 新建 `scripts/memory_l4/distill_engine.py`
- 功能:
  - `init_distill(review_record)`: 从 ReviewRecord 启动蒸馏
  - `step_intent` → `step_investigation` → `step_theory` → `step_hypothesis` → `step_test` → `step_conclusion` → `step_implementation` → `step_monitoring` → `step_review` → `step_reflection` → `step_optimization`: 11 步流程
  - `answer_what_is_it` / `answer_why_it_works` / `answer_how_to_apply`: 三问逻辑
  - `complete_distill(distill)`: 完成蒸馏，计算象限坐标

#### 7.3.3 distill_template 兼容

- 文件: `scripts/memory_l4/distill_template.py`
- 改动: 保留原有 CLI 接口，内部调用 distill_engine 的完整流程

### 7.4 Phase 4: 统计驱动闭环

#### 7.4.1 四象限静态事件库

- 按 (regime, category, x_range, y_range) 四维索引
- 构建 `event_library_index` 支持 A0-A9 快速查询

#### 7.4.2 动态演化趋势

- 扩展 `stats_builder.py`:
  - 新增 `compute_evolution_metrics()`: 蒸馏记录的 y 轴演化速率、稳定性
  - 新增 `identify_emerging_patterns()`: 识别正在形成的新模式
  - 新增 `pattern_maturity_score()`: 模式成熟度评分（案例数 × 一致性 × 时间跨度）

#### 7.4.3 象限体系增强

- 保持 x/y 核心不变
- 新增第三维标签过滤: regime / category / severity

---

## 八、文件变更清单

### 8.1 Schema 文件

| 文件 | 操作 | 说明 |
|---|---|---|
| `trade_case.schema.json` | 修改 → v0.2 | 新增 thinking_chain, evidence_chain, decision_outcome, l4_status, review 扩展 |
| `distill.schema.json` | 修改 → v0.2 | 新增 what/why/how, process_trace, kind 扩展 |
| `review.schema.json` | 新建 | ReviewRecord 完整定义 |
| `stats.schema.json` | 修改 | 新增 event_library, category, severity |

### 8.2 Python 模块

| 文件 | 操作 | Phase | 说明 |
|---|---|---|---|
| `case_registry.py` | 修改 | P1 | thinking_chain/evidence_chain/decision_outcome 初始化 |
| `index_builder.py` | 修改 | P1 | 思维链特征提取 + 一致性校验 |
| `query_similar.py` | 修改 | P1 | 新增 L1 实时检索接口 |
| `a0a9_bridge.py` | 新建 | P1 | A0-A9 数据通道 |
| `review_engine.py` | 新建 | P2 | 对错双向复盘 |
| `a7a8_bridge.py` | 新建 | P2 | A7/A8 报告桥接 |
| `distill_engine.py` | 新建 | P3 | 11步流程 + 三问蒸馏 |
| `failure_analyzer.py` | 保留 | P2 | 作为 review_engine 子模块 |
| `quadrant_migrator.py` | 修改 | P4 | 支持新字段 |
| `stats_builder.py` | 修改 | P4 | 演化指标 + 事件库 |
| `distill_template.py` | 修改 | P3 | 兼容层调用 distill_engine |

### 8.3 目录结构变更

```
.workbuddy/memory_l4/schemas/
├── trade_case.schema.json        (修改 → v0.2)
├── distill.schema.json           (修改 → v0.2)
├── stats.schema.json             (修改)
└── review.schema.json            (新建)

scripts/memory_l4/
├── __init__.py
├── paths.py                      (修改: 新增 reviews_dir)
├── agent_acl.py                  (不变)
├── case_registry.py              (修改)
├── index_builder.py              (修改)
├── query_similar.py              (修改)
├── a0a9_bridge.py                (新建)
├── review_engine.py              (新建)
├── a7a8_bridge.py                (新建)
├── distill_engine.py             (新建)
├── failure_analyzer.py           (保留，作为子模块)
├── distill_template.py           (修改)
├── quadrant_migrator.py          (修改)
├── stats_builder.py              (修改)
├── dashboard_renderer.py         (不变)
├── shared_memory_bus.py          (不变)
├── memory_graph.py               (不变)
├── meta_learning_tasks.py        (不变)
└── migration_mapper.py           (不变)
```

---

## 九、L4 运行状态机与失败语义

### 9.1 L4 内部状态机

```
M0_CASE_REGISTERED
    ↓
M1_REVIEW_COMPLETED
    ↓
M2_DISTILL_COMPLETED
    ↓
M3_STATS_UPDATED
    ↓
M4_CANDIDATE_EMITTED
    ↓ (进入 evolution 通道 memory → evolution → constraints)
```

**任一环节失败 → M_FAIL**（附 reason_code + evidence_refs），停止后续自动推进。

### 9.2 失败语义字典

| reason_code | 触发条件 | 说明 |
|---|---|---|
| `CASE_INCOMPLETE` | TradeCase 缺少必要字段 | 思维链、证据链、episode_refs 不完整 |
| `EVIDENCE_MISSING` | 证据引用指向不存在的文件 | episode_ref 或 evidence_ref 无法解析 |
| `REVIEW_INCONSISTENT` | A7/A8 理论验证未通过 | 理论-实践一致性评分低于阈值 |
| `DISTILL_INVALID` | 蒸馏三问未完成 | what/why/how 任一层面产出为空 |
| `STATS_INTEGRITY_FAILED` | 统计聚合数据异常 | 象限坐标超出范围或聚合结果不一致 |
| `CANDIDATE_EMIT_BLOCKED` | 进化候选不满足发布条件 | 样本量不足或置信度过低 |

### 9.3 失败处置规则

1. 任一步失败立即停止后续自动推进
2. 必须写入结构化审计产物（含 stage + reason_code + evidence_refs）
3. 允许人工修复后重试，不允许无证据强制通过
4. 所有状态变更必须记录到 `l4_status` 字段并写入 `migration_history`

### 9.4 与现有代码的映射关系

当前目录职责保持：

| 目录/文件 | 职责 |
|---|---|
| `workflows/memory/L1~L4_archive/entrypoint.py` | 入口薄封装 |
| `workflows/memory/memory_engine/engine.py` | 核心编排与组合逻辑 |
| `scripts/memory_l4/case_registry.py` | TradeCase 注册 |
| `scripts/memory_l4/index_builder.py` / `query_similar.py` | 索引构建与检索 |
| `scripts/memory_l4/failure_analyzer.py` | 失败分析 |
| `scripts/memory_l4/migration_mapper.py` | 跨市场迁移分析 |
| `scripts/memory_l4/memory_graph.py` | 共享记忆图构建 |
| `scripts/memory_l4/meta_learning_tasks.py` | 元学习任务入队 |
| `scripts/memory_l4/stats_builder.py` | 统计快照与聚合 |

目标新增组件（当前阶段仅文档定义）：

| 组件 | 职责 |
|---|---|
| `review_engine.py` | 对错双向复盘编排 |
| `a7a8_bridge.py` | A7/A8 到 L4 结构化适配 |
| `thinking_chain_index_extension` | 思维链特征提取与索引扩展 |

---

## 十、冲突与兼容策略

| 冲突点 | 严重度 | 吸收策略 |
|---|---|---|
| plan.steps 无法承载 A0-A9 思维链 | 高 | 新增 `thinking_chain[]`，保留 `plan.steps` 兼容旧数据 |
| 失败分析单向，缺少成功经验复盘 | 中 | 设定 `review_engine` 目标模型，`failure_analyzer` 作为子模块 |
| A7/A8 与 L4 数据不兼容 | 中 | 新增适配层契约，定义字段映射与最小输入输出 |
| Distill 结构过扁平 | 高 | 升级到 what/why/how + process_trace，保留旧字段映射 |
| 四象限检索粒度不足 | 低 | x/y 不改，补 regime/category/severity 过滤维度 |
| 索引不支持思维链检索 | 中 | 先定义扩展字段与检索契约，后续再实施 |

---

## 十一、实施优先级

### P0 — 规范固化 (必须先行)

1. **TradeCase Schema v0.2**: thinking_chain + evidence_chain + decision_outcome + l4_status + review 扩展
2. **case_registry 增强**: 初始化新字段
3. **L4 状态机固化**: M0-M4 + 失败语义字典写入文档
4. **索引升级**: 思维链特征提取 + 一致性要求
5. **L1 实时检索接口**: query_by_stage, query_by_regime, get_thinking_chain
6. **A0-A9 数据桥**: collect_stage_outputs → enrich TradeCase
7. **ReviewRecord Schema**: 定义复盘输出格式
8. **三问蒸馏模板与复盘模板固化**

### P1 — 链路打通

9. **review_engine.py**: 对错双向分析
10. **A7/A8 桥接**: 理论与实践报告接入
11. **failure_analyzer 重构**: 作为 review_engine 子模块
12. **打通 "事件入库 → 复盘 → 蒸馏 → 统计 → 候选" 完整链路**
13. **统一产物目录与命名规范**
14. **增加最小门禁**（字段完整性、证据完整性、可追溯性）

### P2 — 演化强化

15. **Distill Schema v0.2**: what/why/how + process_trace
16. **distill_engine.py**: 11步流程 + 三问
17. **distill_template 兼容**: 保留 CLI
18. **四象限动态演化指标接入候选生成**
19. **引入 regime/category/severity 过滤维度**
20. **候选优先级评分 + evolution 验证门禁联动**

### P3 — 认知强化 (可选)

21. **静态事件库**: 四象限分类 + A0-A9 查询接口
22. **语义索引（向量检索）接入**
23. **蒸馏知识源扩展**（知识库/历史事件/联网检索）策略文档化
24. **形成稳定的"理论-实践-约束"闭环运营节律**

---

## 十二、关键设计决策记录

### 12.1 为什么 L1 和 L4 共享 TradeCase？

- **一致性**: 避免数据格式转换的复杂度和丢失信息的风险
- **实时性**: L1 的 TradeCase 文件天然就是可检索的，通过索引加速即可实现秒级响应
- **完整性**: 一个 TradeCase 包含交易的完整闭环，L1 可以按需返回全部或子集

### 12.2 为什么 thinking_chain 是数组而不是嵌套对象？

- **灵活性**: 不同交易可能只经过部分 A0-A9 阶段，数组只记录实际执行的阶段
- **有序性**: 数组天然保持阶段执行顺序
- **可扩展**: 同一阶段可能多次执行（如 A6 多次触发），数组可以追加

### 12.3 为什么复盘独立为 ReviewRecord 而不是直接修改 TradeCase？

- **审计性**: 复盘是一个独立的时间点行为，与交易本身的时间线分开
- **多版本**: 同一 TradeCase 可能经过多次复盘，每次复盘产生独立记录
- **桥接**: ReviewRecord 天然连接 TradeCase 和 Distill，是 L4 管道的中间产物

### 12.4 为什么 Distill 保留顶层 claim 和 actionable_rules？

- **向后兼容**: 现有代码直接访问这两个字段，不需要批量迁移
- **快捷引用**: 对于不需要完整 what/why/how 的场景，顶层字段足够
- **渐进升级**: 新代码优先使用 what_is_it/how_to_apply，旧代码不受影响

### 12.5 为什么 decision_outcome 作为独立顶层字段？

- **清晰性**: 交易评估结论是闭环的核心输出，不应混在 execution.result 中
- **可检索**: 独立的 pnl/drawdown/exit_reason 字段支持按结果类型快速过滤
- **统计友好**: 四象限统计可直接引用 decision_outcome 而不需要解析 execution 内部结构

---

## 十三、风险与注意事项

| 风险 | 说明 | 缓解 |
|---|---|---|
| Schema 兼容性 | v0.2 写入器可能破坏 v0.1 读取器 | 新字段全为 optional，v0.1 读取器忽略新字段 |
| 索引性能 | thinking_chain 特征增加索引大小 | 初始阶段案例数量有限，性能可控；后续考虑向量数据库 |
| A7/A8 格式不稳定 | A7/A8 报告格式可能变化 | a7a8_bridge 使用宽松解析，缺失字段用默认值 |
| 蒸馏流程复杂度 | 11步流程可能难以自动化 | 先实现核心步骤 (intent→hypothesis→conclusion)，其余逐步迭代 |
| 四象限过度简化 | x/y 可能不足以区分复杂模式 | 增加标签过滤维度，但保持 x/y 核心不变 |
| 状态机阻塞 | M_FAIL 后修复成本高 | 提供结构化审计产物，支持修复后重试 |

---

## 十四、DoD — 核心文档完成定义

### 文档阶段 DoD

- [x] 明确 L4 系统边界、对象模型、工作流与状态机
- [x] 明确索引底座、复盘与蒸馏标准、统计驱动逻辑
- [x] 明确与现有代码目录和能力映射关系
- [x] 明确阶段升级路线与验收标准
- [x] 明确设计原则（SSOT、薄封装、可追溯、Fail-Closed）
- [x] 明确 L4 在整体中的定位（经验升格中台输入层）
- [x] 全文不要求修改现有代码即可作为后续实施依据

### 实施阶段 DoD

#### Phase 1 (P0) 验收

- [ ] TradeCase v0.2 schema 通过 JSON Schema 校验
- [ ] 新建的 TradeCase 自动初始化 thinking_chain (空数组)、evidence_chain、decision_outcome
- [ ] 索引文件包含 thinking_features 和 evidence_features
- [ ] `query_by_stage("A0")` 返回包含 A0 阶段数据的案例
- [ ] `get_thinking_chain(case_id)` 返回完整思维链
- [ ] A0-A9 阶段产出可以被收集并填充到 TradeCase
- [ ] L4 状态机 M0 标记写入 TradeCase

#### Phase 2 (P1) 验收

- [ ] review_engine 对成功和失败案例都能生成 ReviewRecord
- [ ] ReviewRecord 包含 mistakes[] 和 successes[]
- [ ] A7/A8 报告可以被解析并合并到 ReviewRecord
- [ ] ReviewRecord 通过 JSON Schema 校验
- [ ] 至少 1 条样本能闭环跑通 "事件入库 → 复盘" 并完整产出 artifacts

#### Phase 3 (P2) 验收

- [ ] Distill v0.2 schema 通过 JSON Schema 校验
- [ ] distill_engine 可以完成完整的 11 步流程
- [ ] 每个蒸馏记录回答"是什么"、"为什么"、"怎么做"
- [ ] 旧版 Distill 文件可以被 v0.2 读取器处理
- [ ] 候选可批量入队、可验证、可拒绝、可回滚

#### Phase 4 (P3) 验收

- [ ] 四象限静态事件库可被 A0-A9 查询
- [ ] 演化指标计算正确
- [ ] 新模式识别功能可以检测到新聚集的象限区域
- [ ] 仪表盘展示新字段
- [ ] A0-A9 可按阶段与矛盾类型检索高相关历史链路

---

## 十五、非目标（本阶段不做）

- 不在本阶段新增或修改业务代码（仅产出架构文档 + Schema + 模块 stub）
- 不在本阶段变更主链交易协议
- 不在本阶段上线自动约束升级执行器
- 不在本阶段实现语义索引（向量检索），作为 P3 扩展
