# 知识与数据存储边界图 — KNOWLEDGE_STORAGE_BOUNDARY_MAP

> **版本**: v1.0 | **更新日期**: 2026-09-10
> **定位**: 明确四套存储系统的职责边界、存储内容、调用关系与数据流，消除系统间认知混淆
> **关联**: [TRADING_CAPITAL_FLOW_MAP.md](./TRADING_CAPITAL_FLOW_MAP.md) · [SYSTEM_MAP.md](./SYSTEM_MAP.md) · [ARCHITECTURE_MAP.md](./ARCHITECTURE_MAP.md)
> **排查快照**: 2026-09-10 00:30 项目代码 + 文件 + 数据库实证

---

## 1. 核心结论

1. **项目存在四套独立的存储系统**，各司其职，但边界未文档化导致认知混淆
2. **交易记录归档从未进入 2-KNOWLEDGE 知识库** — 交易流水存在 `data/polling_trader/`，策略知识存在 `2-KNOWLEDGE/`，两者独立
3. **2-KNOWLEDGE 存的是"策略知识文档"（md），不是"交易案例数据"（jsonl）** — RAG 检索的是规则约束，CBR 检索的是历史交易案例，两套检索互补但不交叉
4. **4-MEMORY 认知库存"经验记忆"（VM-xxx），不存"交易流水"** — trade_settlement_bridge 把交易 outcome 蒸馏为经验后写入认知库，但不存原始 TradeRecord
5. **四套系统之间存在三个断层**（见 §5），阻碍闭环形成

---

## 2. 四套存储系统总表

| 系统 | 路径 | 存什么 | 不存什么 | 谁写入 | 谁消费 | 体量 |
|:---|:---|:---|:---|:---|:---|:---|
| **A. 策略知识库** | `2-KNOWLEDGE/` | 策略规则、架构文档、风控约束、外部调研（md 文件） | 交易记录、行情数据、模型参数 | 手动编写 + archiver.py 归档调研 | RAG 检索 → 交易决策热路径（2026-09-10 接入） | ~50 md，骨架级 |
| **B. 认知记忆系统** | `4-MEMORY/` | 经验记忆（VM-xxx）、贝叶斯策略参数记忆 | 交易流水、原始 TradeRecord | CLAUDE.md 硬约束闸门、memory_bridge.py（RAG→认知桥，流量待通） | mcp_cognitive recall/record/verify | cognitive_memory.db（SQLite 2.1MB）+ bayesian_memories.json |
| **C. 交易运行数据** | `11-易经推理系统/data/polling_trader/` | 交易决策日志、已平仓记录、CBR案例库、持仓JSON | 策略知识、经验记忆 | polling_trader 实时写入 | learning_scheduler 训练、CBR KNN 检索 | trader_*.jsonl + all_trades.jsonl + cbr_cases_v03.jsonl |
| **D. 自进化基因库** | `23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data/` | ESS策略基因、开仓前快照 | 交易流水本身 | trade_settlement_bridge.on_trade_settled() | ReflectionEngine 反思 → ESS 权重更新 | evolution_snapshots.json + strategy_genes/gene_index.json |

---

## 3. 系统间数据流图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         交易决策热路径                                    │
│                                                                         │
│  OKX行情 → BCRM2.0推理 → _open_position() ────────────────────────┐     │
│                               │                                     │     │
│                               ├─→ PositionTracker（持仓内存+JSON） │     │
│                               ├─→ evolution_snapshots.json（系统D） │     │
│                               │                                     │     │
│                          平仓触发                                    │     │
│                               │                                     │     │
│                    _handle_close_position() [L7865]                  │     │
│                               │                                     │     │
│                    ├─→ all_trades.jsonl          （系统C·交易流水）  │     │
│                    ├─→ cbr_cases_v03.jsonl       （系统C·CBR案例库） │     │
│                    └─→ TradeSettlementBridge     （系统D·反思闭环）  │     │
│                               │                                     │     │
│                    ┌──────────┘                                     │     │
│                    ↓                                                 │     │
│            ReflectionEngine.calculate_cs()                            │     │
│                    ↓                                                 │     │
│            ESSProvider.update_ess() → 基因库更新 ✅                   │     │
│                                                                      │     │
│  ══════════════════════════════════════════════════════════════════  │     │
│                         RAG 知识检索流（2026-09-10 接入）              │     │
│                                                                      │     │
│  2-KNOWLEDGE md → ChromaDB 向量化 → hybrid_search                   │     │
│                               ↓                                       │     │
│                    _rag_hotpath_lookup() [FAIL-OPEN 只读]            │     │
│                               ↓                                       │     │
│            ├─→ _open_position L12839      [RAG-PRE-OPEN]              │     │
│            ├─→ _evolution_build_position L8603 [RAG-PRE-EVO-OPEN]    │     │
│            └─→ _evolution_check_exit L9187   [RAG-PRE-EXIT]          │     │
│                               ↓                                       │     │
│                    注入 inference["rag_context"]                      │     │
│                    注入 context["rag_context"]                       │     │
│  ══════════════════════════════════════════════════════════════════  │     │
│                         认知记忆流                                      │     │
│                                                                      │     │
│  CLAUDE.md 硬约束闸门 → record() → 4-MEMORY cognitive_memory.db    │     │
│  RAG 检索结果 → memory_bridge.py → record() [桥已建，流量待通]      │     │
│  交易 outcome → trade_settlement_bridge → record() [经验蒸馏]       │     │
│                                                                      │     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 各系统详细说明

### 系统 A：策略知识库 `2-KNOWLEDGE/`

**定位**：从 Skills 蒸馏的跨领域系统知识，三层分层存储。

**存储内容**（按子域）：
- `0-SCHEMA/`：元知识层，说明"如何读懂和使用知识库"
- `1-TRADING/`：交易策略知识（V9基线、三屏架构、风控体系、参数速查）— **不是交易记录**
- `2-TECHNICAL/`：技术运维知识（架构、调度、部署）
- `3-THEORY/`：哲学/理论（第一性原理、矛盾分析法）
- `4-OPERATIONS/`：运营治理（门禁、审批、OKR）
- `5-CHAIN-DEVELOPMENT/`：三链开发方法论（D/Z/E 链）
- `6-PRODUCT-BUSINESS/`：产品业务与系统工作流程
- `7-EXTERNAL-RESEARCH/`：外部调研归档（finance/github/technical）
- `8-AI-COGNITION/`：AI 沉淀资料库索引
- `9-RAG-INFRA/`：RAG 检索基础设施（ChromaDB + 向量索引 + 混合检索）

**明确不存**：
- ❌ 交易流水记录（TradeRecord jsonl）
- ❌ 行情数据（K线、tick）
- ❌ 模型参数（LightGBM 模型文件）
- ❌ 持仓状态（open_positions JSON）

**关键文件**：
- [INDEX.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/INDEX.md) — 根索引
- [9-RAG-INFRA/rag_engine/hybrid_retriever.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/9-RAG-INFRA/rag_engine/hybrid_retriever.py) — RAG 检索入口
- [9-RAG-INFRA/bridge/memory_bridge.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/9-RAG-INFRA/bridge/memory_bridge.py) — RAG → 认知库桥接（已建未通）
- [9-RAG-INFRA/integration/archiver.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/9-RAG-INFRA/integration/archiver.py) — 外部调研归档

**消费方**：`_rag_hotpath_lookup()`（polling_trader.py L12839/L8603/L9187，2026-09-10 接入）

### 系统 B：认知记忆系统 `4-MEMORY/`

**定位**：AI 认知记忆系统，存"经验"而非"流水"。

**存储内容**：
- `4-MEMORY/data/cognitive_memory.db`（SQLite）：memories 表存经验记忆（VM-xxx），每条有 content/quality_level/confidence/tags
- `4-MEMORY/2-交易记忆单元/bayesian_memories.json`：贝叶斯后验更新的策略参数记忆
- `4-MEMORY/0-元记忆/`：记忆元数据与架构文档
- `4-MEMORY/9-工具与接口/`：认知 MCP 工具（recall/record/verify）
- `.cognitive/sessions/`：会话行动链（action_chain.jsonl）

**明确不存**：
- ❌ 原始 TradeRecord 交易流水
- ❌ 策略知识文档（那是 2-KNOWLEDGE 的职责）

**写入路径**：
- CLAUDE.md 硬约束闸门：用户确认的硬约束 30 秒内 `record(content, quality_level="B")`
- trade_settlement_bridge：交易 outcome 蒸馏为经验后 `record()`
- memory_bridge.py：RAG 检索结果 → `record()`（桥已建，流量待通）

**消费方**：`mcp_cognitive recall`（任务开始前检索经验，CLAUDE.md 硬约束）

### 系统 C：交易运行数据 `data/polling_trader/`

**定位**：交易系统运行时产生的实时数据和归档数据。

**存储内容**：
- `trader_YYYYMMDD.jsonl`：交易决策日志（每轮 polling 的推理结果、风控检查、开仓/离场决策）
- `all_trades.jsonl`：已平仓 TradeRecord 完整 JSON（供 learning_scheduler 消费）
- `cbr_cases_v03.jsonl`：CBR 双时点案例库（开仓快照 + 平仓 outcome，KNN 检索用）
- `open_positions/*.json`：当前持仓持久化
- `s4_eval_log.jsonl`：S4 评估日志

**训练数据链路**：
- BCRM2.0 LightGBM：训练数据来自 **OKX K 线历史数据**（非 jsonl），模型缓存在 `data/bcrm2_models/`
- CBR KNN：检索 `cbr_cases_v03.jsonl`，双时点建库（[cbr_engine.py L709-L841](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/cbr_engine.py#L709-L841)）
- learning_scheduler：消费 `all_trades.jsonl` 调度训练

**关键文件**：
- [polling_trader.py L7865 _handle_close_position()](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py#L7865) — 平仓结算主入口
- [trading_utils.py L32-L82 TradeRecord](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/trading_utils.py#L32-L82) — 运行时交易 dataclass
- [trade_settlement_bridge.py L214-L285](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/trade_settlement_bridge.py#L214-L285) — outcome 标签生成

### 系统 D：自进化基因库 `23-四层闭环/gene_data/`

**定位**：自进化系统的策略基因存储与反思闭环。

**存储内容**：
- `evolution_snapshots.json`：开仓前快照（symbol 为 key，平仓时消费删除）
- ESS 策略基因库：策略基因片段 + ESS 权重
- FTC（Four-Track Consensus）轨道数据

**闭环链路**：
```
开仓 → evolution_snapshots.json（保存快照）
平仓 → retrieve_snapshot() → _extract_outcome_from_reason()（10+ 精细标签）
     → ReflectionEngine.calculate_cs() → apply_reward()
     → ess_delta → ESSProvider.update_ess() → 基因库更新 ✅
```

**关键文件**：
- [trade_settlement_bridge.py L25-L296](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/trade_settlement_bridge.py#L25-L296) — 反思回路核心

---

## 5. 三个断层与闭环机会

### 断层 1：交易记录 ↔ 知识库（系统 C → A）

**现状**：交易 outcome 存在 `all_trades.jsonl`（系统 C），但**没有蒸馏成知识文档进入 2-KNOWLEDGE**（系统 A）。RAG 检索的是策略规则，不是交易案例。

**影响**：RAG 热路径检索不到历史相似交易案例，只能检索策略文档。CBR 虽然能检索案例，但走的是独立的 KNN + jsonl 路径，不经过 RAG。

**闭环方案（第二波）**：在 `_handle_close_position` 平仓后增加蒸馏步骤，把 TradeRecord 关键字段写成 md 入 `2-KNOWLEDGE/1-TRADING/cases/`，让向量索引纳入交易案例。

### 断层 2：CBR 案例 ↔ RAG 知识库（系统 C 内部孤岛）

**现状**：[cbr_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/cbr_engine.py) 的 CBR KNN 检索 `cbr_cases_v03.jsonl`，RAG 向量检索 `2-KNOWLEDGE/*.md`，两套检索互补但不交叉。

**影响**：用户 project_memory 记录的"CBR/KNN 相似检索用于交易决策"是对的，但它的数据源是 jsonl 案例库，不是 2-KNOWLEDGE 的 md 文档。

**闭环方案（第三波）**：考虑让 CBR 案例也向量化进 ChromaDB，统一检索入口；或保持独立但让 RAG 检索结果包含 CBR 案例摘要。

### 断层 3：RAG → 认知记忆桥已建未通（系统 A → B）

**现状**：[memory_bridge.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/9-RAG-INFRA/bridge/memory_bridge.py) 写好了 RAG 检索结果 → 4-MEMORY `record()` 的桥接，但因为没有真实检索流量，权重反哺从未触发。

**影响**：RAG 检索结果不会被记录为认知记忆，无法形成"检索 → 决策 → outcome → 权重反哺"的闭环。

**闭环方案（第二波）**：第一波 RAG 热路径接入已打开流量入口，第二波接入 `search_with_feedback` 的 record/boost/annotate 链路，让检索结果自动写入认知记忆。

---

## 6. 文档更新日志

| 日期 | 版本 | 变更 |
|:---|:---|:---|
| 2026-09-10 | v1.0 | 初版：四套系统边界总表、数据流图、三断层识别 |
