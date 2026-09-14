# SPEC: 底层基建 × DreamOS × Harness 深度集成

> **版本**: v1.0 | **日期**: 2026-09-14 | **状态**: Draft
> **依据**: SYSTEM_ARCHITECTURE_OVERVIEW.md v3.0 + RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md

## 1. 背景与目标

### 1.1 问题定义

当前三大基建（数据采集-清洗-特征提取、认知系统、知识库）与 DreamOS 操作系统、DeepSeek Harness 之间存在 **5 个断裂点**，导致系统无法形成完整闭环。

### 1.2 设计原则

- **DreamOS 不被 Harness 反向定义**：Harness 是通用 agent runtime，DreamOS 是交易领域操作系统
- **Plugin 只透传不决策**（HC-9）：领域代码零 Harness 依赖（HC-10）
- **IPC 失败即 FAIL-OPEN**（HC-7）：绝不返回缓存
- **C 层不包含业务节点**：C 层通过 GraphExecutor 调度，业务节点来自 Registry

## 2. 现状调研

### 2.1 三大基建现状

| 基建 | 路径 | 核心组件 | 成熟度 |
|------|------|---------|--------|
| 数据管道 | `18-/20-/21-` | 8+采集器→4清洗器→6特征模块，DataRecord契约，Bronze→Silver→Gold | ★★★☆☆ |
| 认知系统 | `4-MEMORY/` | 5个MCP工具+贝叶斯蒸馏+反刍/预测/巩固引擎 | ★★★★☆ |
| 知识库 | `2-KNOWLEDGE/` | 8域50+文件+ChromaDB RAG+知识锚点 | ★★★★☆ |

### 2.2 DreamOS OS 内核现状

| 层 | 组件 | 状态 |
|----|------|------|
| S 层 | IntentEngine | ✅ 已通过 IPC 暴露 |
| A 层 | GraphPlanner | ✅ 已通过 IPC 暴露 |
| C 层 | GraphExecutor | ✅ 已通过 IPC 暴露（execute_c_chain） |
| G 层 | SessionConsumer | ✅ 投影到 g_layer_events.jsonl |
| Reflector | Reflector.decide() | ✅ 已通过 IPC 暴露（mode=decide） |
| A7 | A7PracticeGateNode | ✅ 代码存在，未接入 RAG |
| A8 | A8UnityNode | ✅ 代码存在，未接入 RAG |

### 2.3 Harness 集成现状

| 组件 | 状态 |
|------|------|
| Cordis plugins (7个) | ✅ 已注册到 headless profile |
| Python IPC server | ✅ 8个方法暴露 |
| Session Log | ✅ 事件流写入 session.jsonl |
| Profile 打包 | ✅ headless + web 两个 profile |

### 2.4 五个断裂点

| # | 断裂点 | 现状 | 影响 |
|---|--------|------|------|
| G1 | 数据管道 Gold 层 → OS C 层 | C1/C2/C3 不消费 Gold 层 FeatureVector，内部自算指标 + 默认值兜底 | 所有 symbol 分析结果相同 |
| G2 | G 层事件 → 认知系统 | cognitive_daemon 监听代码文件，**明确排除** graph_store/l4_events/a7_gate_logs | 认知系统不知道 OS 运行情况 |
| G3 | A7/A8 → RAG 检索 | A7/A8 代码存在但未调用 RAG hybrid_retriever | 知识库不参与决策 |
| G4 | 认知蒸馏 → 知识库沉淀 | bayesian_memories.json 未自动沉淀到 2-KNOWLEDGE | 知识库不更新 |
| G5 | Harness Session Log → 认知系统 | Harness 事件流未作为认知系统结构化输入 | 认知输入靠文件轮询 |

### 2.5 接口差异分析

#### G1: 数据管道 FeatureVector vs C 层 state.market

```
数据管道产出:
  FeatureVector(df=DataFrame, meta=meta)
  DataRecord(source, category, sub_category, timestamp, metrics{...}, ...)

C 层节点期望:
  state.market = {
    "price": float,
    "change_1h": float, "change_4h": float, "change_24h": float,
    "rsi14": float, "macd": float, "macd_signal": float, "macd_hist": float,
    "ema20": float, "ema50": float, "ema200": float,
    "atr": float, "atr_pct": float,
    "bb_upper": float, "bb_middle": float, "bb_lower": float, "bb_width": float,
    "vol_ratio": float, "atr_change": float
  }

差异: FeatureVector 是 DataFrame（时间序列），C 层需要单点快照（最新值）
适配: 从 FeatureVector.df 取最后一行 → 映射为 dict → state.market
```

#### G2: cognitive_daemon 排除规则

```python
# cognitive_daemon.py 当前排除:
EXCLUDE_DIRS = {"graph_store", "l4_events", "a7_gate_logs", "episodes", ...}
# 需要新增监听: g_layer_events.jsonl
```

## 3. 实施方案

### Phase 1: 数据适配器（P0 — 解决 G1）

**目标**: C 层节点消费数据管道 Gold 层产出，不再使用默认值

**改动**:
1. `python-server/server.py` 新增 `_adapt_feature_vector_to_market(fv_dict)` 方法
2. `_get_market_data_for_chain(symbol)` 增加优先级: Gold层API → indicators API → 默认值
3. 新增 `_handle_gold_layer_query` IPC 方法，从 Gold 层查询最新特征

**验收**: 不同 symbol 产出不同分析结果

### Phase 2: 认知闭环自动消费（P0 — 解决 G2）

**目标**: cognitive_daemon 自动监听 g_layer_events.jsonl，自动 record

**改动**:
1. `cognitive_daemon.py` 的 `EXCLUDE_DIRS` 移除对 g_layer_events 的排除
2. 新增 `_process_g_layer_event(event)` 方法，将 G 层事件转化为认知 record
3. 认知 daemon 新增 `--watch-g-layer` 选项

**验收**: OS 运行后认知系统自动 record G 层事件

### Phase 3: RAG → A7/A8 集成（P1 — 解决 G3）

**目标**: A7/A8 节点调用 RAG hybrid_retriever 检索知识库

**改动**:
1. `a7_practice_gate.py` 的 `execute_core` 增加知识库检索步骤
2. `a8_unity.py` 的 `execute_core` 增加知识库检索步骤
3. 新增 `_handle_rag_query` IPC 方法，暴露 RAG 检索能力

**验收**: A7/A8 执行时从知识库检索到相关知识

### Phase 4: 认知蒸馏 → 知识库沉淀（P2 — 解决 G4）

**目标**: bayesian_memories.json 中高质量记忆自动沉淀到知识库

**改动**:
1. 认知系统蒸馏引擎触发时，将 A 级以上记忆写入知识库
2. 新增 `_handle_knowledge_deposit` IPC 方法

### Phase 5: Harness Session Log → 认知系统（P2 — 解决 G5）

**目标**: Harness 事件流作为认知系统结构化输入

**改动**:
1. cordis-plugin-session-consumer 在写入 g_layer_events.jsonl 时同步触发认知 record
2. 或通过 MCP 直接调用 record

## 4. 优先级与执行顺序

| 顺序 | Phase | 断裂点 | 价值 | 复杂度 |
|------|-------|--------|------|--------|
| 1 | Phase 1 (数据适配器) | G1 | 解决"所有symbol相同"问题 | 中 |
| 2 | Phase 2 (认知闭环) | G2 | 闭合 G层→认知 链路 | 低 |
| 3 | Phase 3 (RAG→A7/A8) | G3 | 知识库参与决策 | 中 |
| 4 | Phase 4 (蒸馏沉淀) | G4 | 知识库自动更新 | 中 |
| 5 | Phase 5 (事件流→认知) | G5 | 结构化输入 | 低 |

## 5. 硬约束清单

| HC# | 约束 | 适用 Phase |
|-----|------|-----------|
| HC-3 | 交易状态单一真相源在 DreamOS | All |
| HC-7 | IPC 失败即 FAIL-OPEN | All |
| HC-9 | Plugin 只透传不决策 | All |
| HC-10 | 领域代码零 Harness 依赖 | All |
| HC-11 | 交易领域事件过滤 | Phase 2, 5 |

## 6. 测试策略

每个 Phase 完成后:
1. 运行已有 6 套件确保无回归
2. 新增针对性测试
3. 运行 `harness_interactive_test.py --auto` 验证端到端
