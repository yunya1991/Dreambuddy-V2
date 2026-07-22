# Dream OS 技术设计文档 v2.1

> **文档层级**: L1 — 系统级技术设计
> **版本**: v2.4.0
> **更新日期**: 2026-07-21
> **维护者**: Dream OS Core Team
> **关联文档**: [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | [SYSTEM_ARCHITECTURE_OVERVIEW.md](../SYSTEM_ARCHITECTURE_OVERVIEW.md)

---

## 0. 文档说明

### 0.1 文档范围

本文档是 Dream OS 操作系统内核的技术设计文档，涵盖：
- 系统架构设计与核心理念
- SACG 四层架构的深度技术细节
- 节点体系与适配器框架
- 自我进化与预算管控机制
- 应用层设计与扩展机制
- 数据流与状态管理

### 0.2 目标读者

| 角色 | 关注章节 |
|------|----------|
| 架构师 | §1-§3 架构设计 |
| 内核开发者 | §4-§6 核心层技术深度 |
| 应用开发者 | §7 应用层 + §8 扩展指南 |
| 运维工程师 | §9 部署架构 + §10 可观测性 |

---

## 1. 系统概述

### 1.1 设计哲学

Dream OS 是一个**意图驱动的 AI 操作系统内核**，核心设计哲学是：

> **纯编排层，不重复建设能力**

OS 内核只负责"调度"——理解意图、编排执行、管理状态、治理进化。所有具体业务能力通过适配器接入，不改核心代码。

这种设计的核心理念是：
- **内核稳定**：SACG 四层是稳定的骨架，不随业务变化而改动
- **能力可插拔**：新增业务能力只需实现节点或适配器，注册即可用
- **演进可控**：能力层迭代不影响内核，内核升级不破坏能力层
- **统一抽象**：所有能力统一为 Node 抽象，统一调度、统一治理

#### 1.1.1 系统定位：操作系统 vs 交易系统

Dream OS 具有**双重身份**，需要明确区分：

| 维度 | Dream OS 操作系统内核 | Dream OS 交易系统 |
|------|----------------------|------------------|
| **定位** | 通用意图驱动编排框架 | 意图明确的交易能力实现 |
| **核心职责** | 理解意图 → 编排节点 → 执行 → 存储 | 通过交易赚钱（S-A-C-G 交易全链路） |
| **通用性** | 完全通用，可编排任意领域节点 | 专用，聚焦交易决策与执行 |
| **当前节点** | 适配器可接入任意节点 | 22个内置交易节点（A/C/F/G系列） |
| **用户意图** | 多样化（分析/交易/研究/管理） | 单一明确（通过交易获利） |
| **关系** | **底座** | **核心能力域** |

**关键认知**：交易系统不是 Dream OS 的"外部应用"，而是当前最成熟、最核心的**内建能力域**。操作系统内核提供编排骨架，交易节点填充血肉，两者共同构成当前可用的交易系统。

未来随着能力扩展，Dream OS 可接入非交易节点（知识管理、数据分析、内容生成等），形成多能力域的通用操作系统。但在当前阶段，交易能力是 Dream OS 的旗舰能力实现。

### 1.2 核心目标

| 目标 | 描述 |
|------|------|
| **意图驱动** | 从自然语言到结构化意图再到执行，三层递进，降低使用门槛 |
| **图编排执行** | 所有执行以图结构组织，支持条件跳转、反思、动态调整 |
| **节点即能力** | 统一的 Node 抽象，支持多来源能力接入（内置/SKILL/API/函数） |
| **状态可追溯** | G 层作为操作系统原生文件系统，提供检查点、历史、压缩能力 |
| **自我进化** | 从执行历史中学习，持续优化节点选择、参数、链路 |
| **预算可控** | 三级 Token 预算 + 四级降级策略，确保成本可控 |

### 1.3 关键设计原则

| 原则 | 说明 | 实现方式 |
|------|------|----------|
| **单一职责** | 每层每个组件只做一件事 | SACG 四层严格分层，节点独立实现 |
| **依赖倒置** | 内核依赖抽象，不依赖具体实现 | Node/Adapter/Registry 接口 + 依赖注入 |
| **开闭原则** | 对扩展开放，对修改关闭 | 新增节点/适配器无需改内核代码 |
| **接口隔离** | 客户端只依赖需要的接口 | 每层对外暴露最小必要接口 |
| **可观测性** | 所有执行过程可追踪可回放 | G 层检查点 + 历史记录 + 上下文压缩 |

---

## 2. 系统架构

### 2.1 顶层架构范式

Dream OS 采用**"OS内核 + 能力层 + 应用层"**的三层操作系统级架构：

```
┌──────────────────────────────────────────────────────────────┐
│                     应用层 (Applications)                     │
│   TradingAgent / API Server / CLI / ...                       │
│   （每个应用都是 OS 内核的一个使用者，组合内核能力）             │
├──────────────────────────────────────────────────────────────┤
│                     能力层 (Capabilities)                      │
│   内置节点 / SKILLs / 经典指标 / 基本面 / ...                  │
│   （通过适配器接入 OS，不改核心代码）                           │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│                  Dreambuddy OS 内核                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  S层 Sense 感知层                                     │    │
│  │  IntentEngine + Recognizers + TokenBudget           │    │
│  │  输入: 用户/市场/信号/记忆 → 输出: IntentResult      │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  A层 Arrange 编排层                                   │    │
│  │  GraphPlanner + NodeSelector + BudgetAllocator       │    │
│  │  输入: IntentResult → 输出: ExecutionPlan + Graph    │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  C层 Compute 执行层                                   │    │
│  │  GraphExecutor + NodeRunner + Reflector + Aggregator │    │
│  │  输入: Graph + State → 输出: ExecutionReport         │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  G层 GraphStore 存储层                                │    │
│  │  Checkpointer + Compressor + HistoryReplay           │    │
│  │  持久化检查点、上下文压缩、历史回放                    │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Registry     │  │ Evolution    │  │ Budget       │      │
│  │ 节点注册表    │  │ 自我进化      │  │ 预算管理      │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  适配器框架 (Adapters)                                │    │
│  │  FunctionAdapter / SkillAdapter / APIAdapter         │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 四层功能架构详解

| 层级 | 类比 | 核心组件 | 输入 | 输出 | 核心职责 |
|------|------|---------|------|------|----------|
| **S层 (感知层)** | OS用户态 / Shell | IntentEngine, Recognizers, TokenBudget | 用户输入 + 市场数据 + 信号 + 记忆 | IntentResult | 理解意图，产出结构化意图 |
| **A层 (编排层)** | OS调度器 / 进程调度 | GraphPlanner, NodeSelector, BudgetAllocator | IntentResult + Registry | ExecutionPlan + ExecutionGraph | 根据意图动态编排执行图，分配预算 |
| **C层 (执行层)** | OS内核态 / CPU | GraphExecutor, NodeRunner, Reflector, Aggregator | Graph + State | ExecutionReport | 执行节点、反射决策、结果聚合 |
| **G层 (存储层)** | OS文件系统 / 内存 | GraphStore, Checkpointer, Compressor, History | State + Report | 检查点 + 历史 + 压缩状态 | 状态检查点、上下文压缩、历史回放 |

### 2.3 横切关注点

| 横切组件 | 类比 | 核心职责 |
|----------|------|----------|
| **Registry** | 设备管理器 / 服务注册 | 节点注册、发现、版本管理，节点的唯一真相源 |
| **Adapters** | 设备驱动 | 将外部能力（SKILL/API/Function）统一包装为 Node |
| **Evolution** | 自动更新 / 自我优化 | 从历史中学习，提炼教训，优化节点和链路 |
| **Budget** | 资源配额 / cgroup | 全局 Token 预算管控，分级降级策略 |

### 2.4 通信与调用结构

```
应用层
  │
  ▼  (调用 run/execute)
S层 ────► A层 ────► C层 ────► G层
 │         │         │         │
 │         ▼         │         │
 │     Registry ─────┘         │
 │         │                   │
 │         ▼                   │
 │     Adapters                │
 │                             │
 └────── Evolution ◄───────────┘
            │
            ▼
       Registry (更新)
```

**调用约定**：
- 每层只调用下一层，不跨层调用（S → A → C → G）
- 横切关注点通过依赖注入方式接入各层
- 所有层共享 State 对象，但每层只读写自己负责的部分
- 错误通过 OSError + ErrorCode 统一抛出，向上层传递

---

## 3. 核心引擎架构

### 3.1 三引擎协同架构

Dream OS 的核心是 SACG 四层内核，其中 S/A/C 三层构成了"感知-编排-执行"三引擎协同：

| 引擎 | 层级 | 决策内容 | 依据 |
|------|------|----------|------|
| **意图引擎** | S层 | "做什么"——识别用户/市场意图 | 输入数据 + 规则 + LLM + 历史反馈 |
| **编排引擎** | A层 | "怎么做"——选择节点、分配预算、构建图 | 意图 + 注册表 + 预算模式 |
| **执行引擎** | C层 | "做对了吗"——执行、反思、调整、聚合 | 执行图 + 节点结果 + 反思逻辑 |

三引擎之间通过**结构化数据**传递信息，实现解耦：
- S → A: `IntentResult`（意图类型 + 置信度 + 推荐链路 + 优先级）
- A → C: `ExecutionPlan` + `ExecutionGraph`（节点列表 + 预算分配 + 图结构）
- C → S: 执行反馈（通过 Evolution 间接优化意图识别）

### 3.2 S 层 — 感知引擎深度

#### 3.2.1 混合识别架构

S 层采用**"规则 + LLM + 动态"**的混合识别架构，兼顾效率和准确性：

```
多源输入（用户文本/市场数据/交易信号/记忆）
                │
                ▼
┌───────────────────────────────────┐
│  RuleBasedRecognizer (零Token)    │
│  关键词匹配 + 正则 + 特征规则       │
└───────────────┬───────────────────┘
                │ 置信度
                ▼
        置信度 >= threshold ?
        ┌───────┴───────┐
        是               否
        │               │
        ▼               ▼
   直接返回      Token预算充足 ?
                ┌───────┴───────┐
                是               否
                │               │
                ▼               ▼
        ┌──────────────┐  降级返回
        │ LLMBased     │  (低置信度UNKNOW)
        │ Recognizer   │
        └──────┬───────┘
               │
               ▼
        ┌──────────────┐
        │ Dynamic      │  ← 历史反馈优化
        │ Recognizer   │
        └──────┬───────┘
               │
               ▼
          结果融合
          (加权投票)
               │
               ▼
         IntentResult
```

#### 3.2.2 识别器设计

每个识别器实现 `BaseRecognizer` 接口：

```python
class BaseRecognizer:
    recognizer_id: str
    name: str
    priority: int  # 融合时的权重

    def recognize(self, input_data: IntentInput) -> RecognizerResult:
        """识别意图，返回置信度和类型"""
        ...

    def supports(self, input_data: IntentInput) -> bool:
        """判断是否支持该输入"""
        ...
```

三种识别器的特点对比：

| 识别器 | Token消耗 | 速度 | 准确率 | 适用场景 |
|--------|-----------|------|--------|----------|
| RuleBased | 0 | 极快 (<1ms) | 中 (60-70%) | 常见意图、关键词明确 |
| LLMBased | 高 (500-2000) | 慢 (1-10s) | 高 (85-95%) | 复杂意图、模糊表达 |
| Dynamic | 低 (状态查询) | 快 (<10ms) | 渐进提升 | 有历史反馈的场景 |

#### 3.2.3 结果融合策略

多识别器结果采用**加权投票 + 置信度校准**的融合策略：

1. 每个识别器输出 `(intent_type, confidence)`
2. 按识别器 priority 加权
3. 同一意图类型的置信度累加
4. 取最高置信度的意图类型作为结果
5. 应用置信度校准（基于历史准确率）

#### 3.2.4 Token 预算门控

S 层内置 `TokenBudgetManager`，管理单周期内的 Token 消耗：

- **预算检查点**：每次 LLM 调用前检查预算
- **预算分配**：S 层占总预算的 10-15%
- **预算耗尽**：自动降级为纯规则模式，返回 UNCERTIAN + 低置信度

#### 3.2.5 36 场景分类系统

`ScenarioClassifier` 是 S 层的核心组件之一，将市场状态划分为 **3 × 4 × 3 = 36 种标准场景**，为编排选择和进化优化提供细粒度的场景索引。

**三维分类体系**：

| 维度 | 取值 | 说明 |
|------|------|------|
| **趋势方向** | BULL / BEAR / NEUTRAL | 基于均线排列和涨跌幅的趋势判定 |
| **波动率等级** | LOW / NORMAL / HIGH / EXTREME | 基于 ATR% 的波动率分级 |
| **动量加速度** | ACCELERATING / DECELERATING / EXHAUSTION | 动量速度 + 加速度 + 衰竭检测 |

**趋势判定规则**：
- **BULL**：price > ema20 > ema50 > ema200 且 trend_score ≥ 0.6
- **BEAR**：price < ema20 < ema50 < ema200 且 trend_score ≥ 0.6
- **NEUTRAL**：其他情况

**波动率阈值**（ATR%）：
- **EXTREME**：≥ 4%
- **HIGH**：≥ 2%
- **NORMAL**：≥ 1%
- **LOW**：< 1%

**动量加速度判定**：
- **ACCELERATING**：动量速度 > 50 且加速度 > 0（趋势在加速）
- **DECELERATING**：动量速度 > 30 且加速度 < 0（趋势仍在但减速）
- **EXHAUSTION**：衰竭信号（加速度转负 + 短期与中期动量背离 + RSI 超买/超卖回落）

**场景 ID 命名规范**：`{TREND}_{VOLATILITY}_{MOMENTUM}`，例如 `BULL_NORMAL_ACCELERATING`

**输入数据要求**（market_data 字段）：
```
price, ema20, ema50, ema200,
change_1h, change_4h, change_24h,
atr_pct, rsi14
```

### 3.3 A 层 — 编排引擎深度

#### 3.3.1 图规划流程

A 层的核心是 `GraphPlanner`，将意图转化为可执行的图：

```
IntentResult
    │
    ▼
┌─────────────┐
│ 链路选择器   │  → 选择主链路（A/C/F）+ 辅助链路
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ NodeSelector│  → 从 Registry 中筛选节点
│             │    - 按意图类型匹配
│             │    - 按链路筛选
│             │    - 按优先级排序
│             │    - 去重和依赖检查
└──────┬──────┘
       │
       ▼
┌─────────────┐
│BudgetAlloc. │  → 给每个节点分配 Token 预算
│             │    - 按重要性分配
│             │    - 关键节点保底
│             │    - 可选节点弹性
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 图构建器     │  → 构建 ExecutionGraph
│             │    - 顺序图（默认）
│             │    - 条件图（高级）
│             │    - 依赖边 + 数据流边
└──────┬──────┘
       │
       ▼
ExecutionPlan + ExecutionGraph
```

#### 3.3.2 标准链路配置

系统预定义三条标准链路，覆盖主要交易场景：

| 链路 | 节点序列 | 适用意图 | 预期深度 |
|------|----------|----------|----------|
| **A链（决策链）** | A0→A1→A2→A3→A4→A5→A6→A7→A8→A9 | 趋势跟随/均值回归/突破 | 深度分析，辩证决策 |
| **C链（技术链）** | C1→C2→C3→C5 | 技术面为主的快速决策 | 技术指标聚焦 |
| **F链（基本面链）** | F1→F2→F3→F4→F5 | 基本面驱动 | 基本面深度研究 |

**链路组合策略**：
- **主链路**：根据意图类型选择（如 TREND_FOLLOWING → A链为主）
- **辅助链路**：根据置信度动态添加（如置信度低 → 增加 C链验证）
- **治理节点**：G1/G2 可插入任意链路关键节点后

#### 3.3.3 节点选择算法

NodeSelector 采用**"意图匹配 + 链路约束 + 优先级排序"**的三层选择：

1. **意图匹配**：节点 tags 与意图关键词的匹配度
2. **链路过滤**：只选属于指定链路的节点
3. **优先级排序**：按节点 priority 排序
4. **依赖检查**：确保前置节点已选中
5. **预算裁剪**：从低优先级节点开始裁剪，直到符合预算

#### 3.3.4 预算分配策略

BudgetAllocator 采用**"关键节点保底 + 可选节点弹性"**的分配策略：

- **关键节点**（A0/A3/A4/A9 等）：分配保底预算，确保必须执行
- **重要节点**（A1/A2/A5/A6 等）：分配标准预算
- **可选节点**（C 系列、F 系列）：弹性预算，预算充足时执行
- **反思/聚合**：预留 10% 预算用于反思和聚合

#### 3.3.5 编排记忆与三级降级

`OrchestrationMemory`（编排记忆表）是 A 层的核心组件，存储每种市场场景的最优编排模式，支持**四级降级查询**，确保在任何数据条件下都能给出合理的编排建议。

**5 种标准编排模式**：

| 模式名称 | 节点序列 | 适用场景 |
|----------|----------|----------|
| **c_chain** | C1 → C2 → C3 | 纯技术面快速决策（默认 fallback） |
| **c_f_chain** | C1 → C2 → F1 → F3 | 技术面 + 基本面验证 |
| **full_chain** | C1 → C2 → F2 → G1 | 全链路 + 风控（高置信度场景） |
| **f_chain** | F1 → F2 → F3 → F4 | 纯基本面驱动 |
| **c_g_chain** | C1 → C3 → G1 | 技术面 + 风控（保守模式） |

**四级降级查询策略**：

```
L0: 精确匹配全维度 (36场景)
    ↓ 未命中
L1: 降维 趋势×波动率 (12场景)
    ↓ 未命中
L2: 降维 仅趋势 (3场景)
    ↓ 未命中
L3: 默认 c_chain (C1→C2→C3)
```

**记忆表数据结构**：
```json
{
  "version": "1.0.0",
  "scenarios": {
    "BULL_NORMAL_ACCELERATING": {
      "best_pattern": "c_f_chain",
      "nodes": ["C1", "C2", "F1", "F3"],
      "metrics": {"sharpe": 1.85, "win_rate": 0.62},
      "sample_count": 120,
      "confidence": "high"
    }
  },
  "fallback_chain": ["L0_exact", "L1_trend_vol", "L2_trend", "L3_default"]
}
```

**编排选择输出**（`OrchestrationChoice`）：
- `pattern`：选中的编排模式名称
- `nodes`：节点序列
- `score`：历史得分（夏普比率估计）
- `confidence`：置信度（high/medium/low/default）
- `fallback_level`：命中的降级层级（L0/L1/L2/L3）
- `source_scenario`：实际命中的场景 ID

### 3.4 C 层 — 执行引擎深度

#### 3.4.1 图执行循环

C 层的核心是 `GraphExecutor`，采用**"执行-反思-决策"**的循环模式：

```
current_node = graph.get_entry()
while current_node is not None:
    # 1. 执行节点
    result = NodeRunner.run(current_node, state)
    state.update(current_node.node_id, result)

    # 2. 反思决策
    decision = Reflector.decide(result, state)

    # 3. 动作路由
    if decision.action == CONTINUE:
        current_node = graph.next()
    elif decision.action == REDO:
        pass  # 重试当前节点
    elif decision.action == INSERT:
        graph.insert_before(decision.node_id, current_node)
    elif decision.action == JUMP:
        current_node = graph.get(decision.target_id)
    elif decision.action == TERMINATE:
        break

    step_count += 1
    if step_count > max_steps:
        break

# 4. 结果聚合
final_report = Aggregator.aggregate(state)
```

#### 3.4.2 节点执行器（NodeRunner）

NodeRunner 负责单个节点的执行，包含：

| 功能 | 说明 |
|------|------|
| **前置检查** | 检查节点依赖是否满足、预算是否充足 |
| **执行封装** | 调用 node.execute_core()，捕获异常 |
| **重试机制** | 失败自动重试（max_retries 次，指数退避） |
| **超时控制** | 执行超时自动终止 |
| **结果标准化** | 将节点输出统一为 NodeResult |
| **成本统计** | 统计本次执行的 Token 消耗和耗时 |

#### 3.4.3 反射决策器（Reflector）

Reflector 是 C 层的"智能调度器"，每步执行后决定下一步动作：

**反射维度**：
- **置信度检查**：节点结果置信度是否达标？不达标→REDO 或 JUMP
- **一致性检查**：当前节点结果与前序节点是否矛盾？矛盾→INSERT（补充节点）
- **进度评估**：整体进度如何？是否需要提前终止？
- **预算检查**：剩余预算是否支撑后续执行？不足→SKIP 可选节点

**反射决策的启发式规则**：
```python
if result.confidence < 0.3:
    return REDO  # 置信度太低，重做
elif conflict_with_previous(result, state):
    return INSERT("C1")  # 矛盾，插入技术验证
elif result.confidence > 0.9 and is_late_stage():
    return TERMINATE  # 高置信度，提前结束
elif budget_remaining < 0.2:
    return JUMP("A9")  # 预算不足，跳转到结尾
else:
    return CONTINUE
```

#### 3.4.4 结果聚合器（Aggregator）

Aggregator 负责将多节点结果聚合成最终结论：

**聚合策略**：
- **方向聚合**：加权投票（按节点重要性和置信度）
- **置信度聚合**：D-S 证据理论或加权平均
- **理由聚合**：提取关键节点的核心论据
- **风险聚合**：汇总所有风险提示

### 3.5 G 层 — 存储引擎深度

#### 3.5.1 G 层定位

G 层是 Dream OS 的**原生文件系统**，提供三个核心能力：

| 能力 | 组件 | 类比 | 用途 |
|------|------|------|------|
| **检查点** | Checkpointer | 内存快照 / core dump | 执行中保存状态，支持回滚 |
| **上下文压缩** | ContextCompressor | 内存压缩 / 虚拟内存 | State 过大时自动压缩，节省 Token |
| **历史记录** | HistoryReplay | 文件系统 / 版本控制 | 记录完整执行历史，支持回放和模式挖掘 |

#### 3.5.2 检查点机制

**触发时机**：
- 每个节点执行完成后自动保存
- 反射决策前保存（便于回滚）
- 关键节点（A4/A7门禁）前后强制保存

**检查点数据结构**：
```python
@dataclass
class Checkpoint:
    cp_id: str              # 检查点ID
    cycle_id: str           # 周期ID
    node_id: str            # 触发节点
    timestamp: float        # 时间戳
    state_snapshot: dict    # 状态快照
    step: int               # 执行步数
    token_used: int         # 已用Token
```

**回滚支持**：
- 支持回滚到任意检查点
- 回滚后可从指定节点重新执行
- 回滚历史保留在 G 层

#### 3.5.3 上下文压缩

**压缩触发条件**：
- State 大小超过阈值（默认 10000 tokens）
- 节点数超过阈值（默认 20 个节点结果）
- 新节点执行前主动检查

**压缩策略**：
- **摘要压缩**：将多个节点结果摘要为一段话
- **关键信息保留**：保留方向、置信度、关键论据
- **分层压缩**：旧节点压缩程度更高，新节点保留完整
- **可还原**：压缩过程可逆（通过 G 层历史）

#### 3.5.4 历史回放

**历史记录内容**：
- 每个周期的完整执行轨迹
- 每个节点的输入输出
- 反思决策过程
- 最终结果和实际反馈

**历史查询能力**：
- 按意图类型查询
- 按结果查询（正确/错误）
- 按时间范围查询
- 模式匹配（相似执行路径）

**回放能力**：
- 重放某个周期的执行过程
- 从任意检查点开始重新执行
- 对比多次执行的差异

---

## 4. 节点体系

### 4.1 Node 抽象

Node 是 Dream OS 中**能力的统一抽象**，所有具体能力都实现为 Node。

```python
class Node(ABC):
    """节点接口 — 所有能力的统一抽象"""

    node_id: str              # 唯一标识
    name: str                 # 名称
    chain: str                # 所属链路 (A/C/F/G)
    tags: List[str]           # 标签（用于意图匹配）
    version: str              # 版本号
    priority: int             # 优先级
    required_tokens: int      # 预估Token消耗
    dependencies: List[str]   # 依赖的前置节点

    @abstractmethod
    def execute(self, state: State) -> NodeResult:
        """执行节点逻辑"""
        ...

    def can_execute(self, state: State) -> bool:
        """判断是否可以执行（前置检查）"""
        return True
```

### 4.2 BaseNode 基类

`BaseNode` 提供了 Node 的标准实现，所有内置节点继承自它：

**BaseNode 提供的默认实现**：
- 执行计时和统计
- 异常捕获和标准化
- Token 消耗追踪
- 状态读写辅助方法
- 依赖检查

**子类只需实现**：
```python
def execute_core(self, state: State) -> NodeResult:
    """核心业务逻辑，子类实现"""
    ...
```

### 4.3 节点分类体系

#### 4.3.1 A系列 — 决策链（辩证分析）

A 系列节点基于**唯物辩证法**和**矛盾论**，实现从感性到理性、从理论到实践的完整认知闭环：

| 节点 | 名称 | 辩证阶段 | 核心输出 |
|------|------|----------|----------|
| A0 | 矛盾论分析 | 感性具体 | 主要矛盾 + 次要矛盾 |
| A1 | 深度调研 | 感性材料收集 | 多维度调研数据 |
| A2 | 综合分析 | 思维抽象 → 思维具体 | 综合判断 + 多视角分析 |
| A3 | 策略制定 | 理性具体 | 交易策略 + 仓位建议 |
| A4 | 决策门禁 | 第一次飞跃检验 | 风险收益评估 + GO/NO-GO |
| A5 | 执行规划 | 实践方案 | 入场计划 + 止盈止损 |
| A6 | 市态监控 | 实践中观察 | 市场状态变化监测 |
| A7 | 实践门禁 | 第二次飞跃检验 | 实践验证 + 调整决策 |
| A8 | 统一升华 | 理论实践统一 | 经验总结 + 规律提炼 |
| A9 | 离场策略 | 实践闭环 | 离场策略 + 复盘建议 |

#### 4.3.2 C系列 — 技术分析链

C 系列节点聚焦**技术面分析**，提供量化的技术视角：

| 节点 | 名称 | 分析维度 | 核心指标 |
|------|------|----------|----------|
| C1 | 技术扫描 | 多周期技术面 | MA/EMA/趋势线/支撑阻力 |
| C2 | 动量分析 | 动量指标 | RSI/MACD/KDJ/RSI背离 |
| C3 | 波动率分析 | 波动率 | ATR/Bollinger/IV |
| C5 | 离场系统 | 技术离场 | 止盈止损/移动止损/超买超卖 |

#### 4.3.3 F系列 — 基本面链

F 系列节点聚焦**基本面分析**，提供价值和宏观视角：

| 节点 | 名称 | 分析维度 | 数据来源 |
|------|------|----------|----------|
| F1 | 新闻分析 | 新闻情绪 | 新闻API/社交媒体 |
| F2 | 资金流分析 | 资金流向 | 交易所数据/链上数据 |
| F3 | 估值分析 | 估值模型 | 梅特卡夫定律/NVT/PU |
| F4 | 链上数据 | 链上指标 | Glassnode/Nansen |
| F5 | 宏观分析 | 宏观经济 | 利率/美元指数/股市 |

#### 4.3.4 G系列 — 治理链

G 系列节点提供**横切治理能力**，可插入任意链路：

| 节点 | 名称 | 治理维度 | 插入位置 |
|------|------|----------|----------|
| G1 | 风控 | 风险控制 | A4门禁后、A5执行前 |
| G2 | 治理 | 合规审查 | 关键决策点 |

### 4.4 节点注册与发现

#### 4.4.1 注册方式

节点有三种注册方式：

| 方式 | 适用场景 | 示例 |
|------|----------|------|
| **手动注册** | 动态注册、测试 | `registry.register(MyNode())` |
| **装饰器注册** | 代码内定义 | `@register_node("A0")` |
| **自动发现** | 批量加载 | `NodeLoader.load_from_dir("nodes/")` |

#### 4.4.2 NodeRegistry 设计

NodeRegistry 是节点的**唯一真相源**，采用线程安全设计：

```python
class NodeRegistry(Registry):
    _nodes: Dict[str, Node]    # node_id -> Node
    _lock: RLock               # 重入锁

    def register(node) -> None
    def unregister(node_id) -> bool
    def get(node_id) -> Optional[Node]
    def list_nodes(chain=None, tag=None) -> List[Node]
    def summary() -> dict      # 注册表概览
```

**设计原则**：
- 单一真相源：一个 node_id 只能注册一次
- 线程安全：所有操作加锁
- 可观测：支持列表查询和统计
- 动态可扩展：支持运行时增删节点

---

## 5. 适配器框架

### 5.1 设计理念

适配器框架是 Dream OS **"不重复建设能力"** 理念的核心实现。它将各种外部来源的能力统一包装为 Node，使 OS 内核无需关心能力的具体实现方式。

```
外部能力（Function / SKILL / API）
        │
        ▼
   适配器 (Adapter)
        │  包装为
        ▼
      Node  ←  OS 内核统一调度
```

### 5.2 适配器类型

#### 5.2.1 FunctionAdapter — 函数适配器

将**本地 Python 函数**包装为 FunctionNode：

```python
# 原始函数
def my_analysis(data: dict) -> dict:
    # 业务逻辑
    return {"direction": "LONG", "confidence": 0.7}

# 适配
adapter = FunctionAdapter()
node = adapter.to_node({
    "type": "function",
    "handler": my_analysis,
    "node_id": "MY_FUNC",
    "name": "我的分析函数",
    "chain": "C",
})

# 使用（和内置节点完全一样）
result = node.execute(state)
```

**适用场景**：
- 已有 Python 函数快速接入
- 简单的工具函数
- 测试和原型开发

#### 5.2.2 SkillAdapter — SKILL适配器

将 **SKILL.md 技能描述**包装为 SkillNode：

```python
adapter = SkillAdapter()
node = adapter.to_node({
    "type": "skill",
    "skill_path": "path/to/skill/SKILL.md",
    "node_id": "MY_SKILL",
})
```

**SkillAdapter 的工作原理**：
1. 解析 SKILL.md，提取元数据（名称、描述、输入输出）
2. 根据 SKILL 描述生成 Prompt
3. 调用 LLM 执行 SKILL 逻辑
4. 解析 LLM 输出为 NodeResult

**适用场景**：
- 复杂的、需要 LLM 推理的能力
- 已有 SKILL 体系的能力复用
- 业务逻辑变化频繁的场景

#### 5.2.3 APIAdapter — API适配器

将 **HTTP API** 包装为 APINode：

```python
adapter = APIAdapter()
node = adapter.to_node({
    "type": "api",
    "url": "https://api.example.com/analyze",
    "method": "POST",
    "node_id": "MY_API",
    "name": "外部分析API",
    "input_mapping": {"symbol": "state.market.symbol"},
    "output_mapping": {"direction": "result.direction"},
})
```

**适用场景**：
- 外部服务接入
- 微服务架构下的能力复用
- 跨语言/跨系统集成

### 5.3 AdapterRegistry — 适配器管理器

AdapterRegistry 管理多个适配器，根据配置自动分发：

```python
reg = AdapterRegistry()
reg.register(FunctionAdapter())
reg.register(SkillAdapter())
reg.register(APIAdapter())

# 自动选择合适的适配器
node = reg.to_node(config)
```

**适配流程**：
1. 遍历所有注册的适配器
2. 调用 `adapter.can_handle(config)` 判断
3. 找到第一个能处理的适配器
4. 调用 `adapter.to_node(config)` 生成 Node
5. 返回 Node

---

## 6. 自我进化系统

### 6.1 进化架构

Dream OS 的自我进化是一个**三层反思闭环**：

```
┌─────────────────────────────────────────────────────────┐
│                     G 层历史数据                          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 1: 经验提炼 (LessonDistiller)                    │
│  从历史执行中提取可复用的经验教训                          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 2: 差距分析 (GapAnalyzer)                        │
│  分析预期与实际的差距，定位问题根源                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 3: 优化建议 (NodeOptimizer)                      │
│  生成具体的节点/链路/参数优化建议                          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
              EvolutionReport
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
   人工审核确认           自动应用（低风险）
         │                       │
         ▼                       ▼
   Registry 更新          DynamicRecognizer 更新
```

### 6.2 LessonDistiller — 经验提炼

**核心功能**：从历史执行数据中提炼可复用的经验教训。

**提炼维度**：
- **成功模式**：高胜率的执行路径和节点组合
- **失败模式**：常见的错误模式和陷阱
- **边界条件**：策略有效的适用范围
- **时机特征**：最佳入场/离场的市场特征

**算法**：
- 模式匹配：相似执行路径的聚类
- 相关性分析：节点特征与最终结果的相关性
- 统计检验：胜率/赔率的显著性检验

### 6.3 GapAnalyzer — 差距分析

**核心功能**：分析"预期"与"实际"的差距，定位问题根源。

**分析维度**：

| 差距类型 | 描述 | 定位方法 |
|----------|------|----------|
| **意图偏差** | 识别的意图与实际需要不符 | 对比用户反馈与意图识别结果 |
| **节点偏差** | 节点输出与预期不符 | 对比节点预测与实际结果 |
| **链路偏差** | 链路选择错误 | 对比不同链路的成功率 |
| **时序偏差** | 时机判断错误 | 分析入场/离场时机的准确性 |

### 6.4 NodeOptimizer — 节点优化器

**核心功能**：基于差距分析，生成具体的优化建议。

**优化方向**：

| 优化对象 | 优化内容 | 风险等级 |
|----------|----------|----------|
| **节点参数** | 调整节点的阈值、权重等参数 | 低（可自动应用） |
| **节点优先级** | 调整节点在选择时的优先级 | 中（需审核） |
| **链路配置** | 调整标准链路的节点组成 | 高（需人工确认） |
| **新增节点** | 建议新增节点填补能力空白 | 高（需开发实现） |
| **废弃节点** | 建议移除效果差的节点 | 高（需人工确认） |

### 6.5 进化闭环

完整的进化闭环：

```
1. 执行 → G层记录历史
2. 收集反馈 → 实际结果与预测对比
3. 进化引擎运行 → LessonDistiller → GapAnalyzer → NodeOptimizer
4. 生成 EvolutionReport
5. 低风险优化 → 自动应用（参数调整、权重调整）
6. 高风险优化 → 人工审核 → 应用到 Registry
7. 下次执行 → 应用优化后的配置
8. 验证效果 → G层继续记录 → 循环
```

### 6.6 执行反馈收集器（ExecutionFeedbackCollector）

`ExecutionFeedbackCollector` 是进化引擎的核心数据来源，负责记录每笔交易的实际结果，并计算与回测预期的偏差，当偏差超过阈值时触发编排优化。

**触发进化的阈值条件**：

| 触发条件 | 阈值 | 说明 |
|----------|------|------|
| **方向准确率** | < 50% | 连续 3 笔方向准确率低于 50% |
| **夏普偏差** | > 30% | \|actual_sharpe - expected_sharpe\| / \|expected\| > 30% |
| **最小样本** | 3 笔 | 至少 3 笔交易才触发评估 |

**反馈记录数据结构**：
```python
@dataclass
class ExecutionFeedback:
    scenario_id: str           # 场景ID（36种场景之一）
    pattern_used: str          # 使用的编排模式
    timestamp: str             # ISO格式时间
    trades: List[Dict]         # 交易明细
    actual_sharpe: float       # 实际夏普比率
    expected_sharpe: float     # 预期夏普比率
    deviation: float           # 偏差率
    direction_accuracy: float  # 方向准确率
    trigger_evolution: bool    # 是否触发进化
```

**反馈收集流程**：
1. 交易执行后，AutoTrader 调用 `record_trade_feedback()`
2. 收集器将交易结果按场景 ID 分组存储
3. 调用 `evaluate(scenario_id)` 计算该场景的执行指标
4. 若触发条件满足，设置 `trigger_evolution = True`
5. 进化引擎通过 `_check_orchestration_optimization()` 批量检查所有场景

### 6.7 编排优化机制

`EvolutionEngine._check_orchestration_optimization()` 实现了**基于执行反馈的编排动态优化**，是进化引擎的核心触发源之一。

**优化流程**：

```
收集所有场景的执行反馈
    ↓
遍历每个场景
    ↓
feedback.trigger_evolution == True ?
    ├─ 是 → 生成编排调整提案
    │         ↓
    │       沙箱验证（_sandbox_validate）
    │         ↓
    │       通过 → 更新 OrchestrationMemory
    │         ↓
    │       记录优化日志
    └─ 否 → 跳过
```

**编排调整策略**：
- 当前模式不含风控（非 `c_g_chain`）→ 切换到 `c_g_chain`（增加 G1 风控节点）
- 后续可扩展：多模式竞争、次优模式切换、节点增删等

**沙箱验证规则**：
- 新提案的预估得分 > 现有得分 × 1.1
- 简化版：有合理理由即通过（待接入 ScenarioBacktester 做回测验证）

---

## 7. 应用层与能力域设计

### 7.1 三层架构定位与能力域路由

Dream OS 采用**内核层 → 能力域层 → 应用层**的三层架构：

```
应用层 (Applications)
    ├─ TradingAgent      → 面向交互的交易分析
    ├─ AutoTrader        → 面向实盘的自动化交易
    ├─ API Server        → 面向远程调用的服务接口
    └─ CLI               → 面向开发者的命令行工具

能力域层 (Capability Domains)
    ├─ 交易能力域         → A0-A9/C1-C5/F1-F5/G1-G2 节点 + 回测 + 实盘执行
    ├─ [知识管理能力域]   → [未来扩展]
    └─ [数据分析能力域]   → [未来扩展]
    ↑
    CapabilityRegistry / CapabilityRouter

操作系统内核层 (OS Kernel)
    └─ S-A-C-G 四层 + Registry + Adapters + Budget + Evolution
```

**设计原则**：
- **内核提供骨架**：SACG 四层是通用编排框架，与业务无关
- **能力域填充血肉**：交易节点实现交易逻辑，未来可扩展其他领域
- **应用面向场景**：应用是能力域的封装，面向具体使用场景
- **各层独立演进**：内核升级不破坏能力域，能力域扩展不修改内核
- **物理分离，逻辑集成**：能力域代码独立目录，内核通过标准接口调用

#### 7.1.1 能力域注册与路由机制

能力域是 Dream OS 内核与业务能力之间的标准接口层。内核通过 `CapabilityRegistry` 管理多个能力域，通过 `CapabilityRouter` 将意图路由到最优能力域。

**CapabilityRegistry — 能力域注册表**

类比操作系统中的设备管理器，CapabilityRegistry 管理所有已接入的能力域：

| 功能 | 说明 |
|------|------|
| **注册** | `register(capability)` — 注册能力域实例 |
| **发现** | `discover_and_register(package_path)` — 自动扫描包路径下能力域 |
| **查询** | `get(capability_id)` / `list_capabilities()` |
| **意图匹配** | `find_by_intent(intent_type)` — 按意图查找匹配的能力域 |
| **节点关联** | `attach_node_registry()` — 关联内核 NodeRegistry |

**CapabilityRouter — 意图路由器**

S 层意图识别后，CapabilityRouter 根据 IntentResult 选择最优能力域：

```
IntentResult (intent_type="TREND_FOLLOWING")
    │
    ▼
┌─────────────────────────────────────┐
│ CapabilityRouter.route(intent)      │
│   1. 精确匹配: intent_type ∈ supported_intents ?
│   2. 关键词匹配: 意图关键词 ∩ 能力域 tags
│   3. 默认回退: default_capability_id
│   4. 失败: 无匹配
└──────────────┬──────────────────────┘
               │ RoutingResult
               │ (capability_id, score, config)
               ▼
        A 层 GraphPlanner
        （使用选中能力域的节点和配置编排执行图）
```

**路由策略优先级**：

| 优先级 | 匹配类型 | 说明 | 示例 |
|--------|----------|------|------|
| 1 | exact | 意图类型在能力域 supported_intents 中 | TREND_FOLLOWING → trading |
| 2 | fuzzy | 关键词与能力域 tags 匹配 | "总结文档" → knowledge |
| 3 | fallback | 回退到默认能力域 | 未识别 → trading（交易场景）|
| 4 | none | 无匹配，返回失败 | 需要澄清或扩展能力域 |

**TradingAgent 集成路由后的流程**：

```python
def run(self, user_input, market_data):
    # S 层：识别意图
    intent = self.intent_engine.recognize(user_input, market_data)

    # 新增: 能力域路由
    routing = self.capability_router.route(intent)
    if not routing.success:
        return {"error": "无匹配能力域", "candidates": routing.candidates}

    # A 层：编排（使用选中能力域的节点和配置）
    plan = self.graph_planner.plan(state, capability_config=routing.capability_config)

    # C 层：执行
    report = self.graph_executor.execute(graph, state, plan=plan)
    ...
```

### 7.2 能力域：交易能力域（旗舰内建能力）

交易能力域是 Dream OS **当前唯一的内建能力域**，也是整个系统**意图实现最核心的能力**。它的意图极其纯粹和明确：**通过交易赚钱**。

**核心设计理念：交易分析评估器驱动的质量提升闭环**

**Dream OS 交易系统的核心不是"自身交易"，而是"分析评估 → 模块能力回测 → 节点编排推荐"的质量提升闭环。**

```
交易执行 → 亏损原因分析 → 模块能力评估 → 模块回测验证 → 编排推荐 → 节点编排调整 → 交易执行
     ↑                                                                                 │
     └─────────────────────────────────────────────────────────────────────────────────┘
```

**TradingAnalysisEvaluator — 交易分析评估器（核心组件）**

交易分析评估器是交易能力域的核心，负责：

| 阶段 | 职责 | 方法 | 输出 |
|------|------|------|------|
| 1. 亏损原因分析 | 分析交易失败的根本原因 | `analyze_loss_reasons()` | 亏损原因分类（入场信号/离场信号/趋势过滤等） |
| 2. 模块能力评估 | 评估每个节点在不同场景下的表现 | `evaluate_module_capabilities()` | 模块能力评分（准确率/胜率/盈亏比/稳定性/时效性） |
| 3. 模块回测 | 对模块组合进行回测验证 | `backtest_modules()` | 回测结果（收益/回撤/夏普/胜率） |
| 4. 编排推荐 | 基于分析结果推荐最优节点编排 | `recommend_orchestration()` | 场景→节点编排映射 |

**亏损原因分类（10类）**：

| 原因 | 代码 | 检测规则 | 权重 |
|------|------|----------|------|
| 入场信号质量问题 | ENTRY_SIGNAL | entry_confidence < 0.6 | 0.25 |
| 离场信号质量问题 | EXIT_SIGNAL | exit_reason in ("forced", "timed_out") | 0.20 |
| 趋势过滤失效 | TREND_FILTER | NEUTRAL场景且亏损>2% | 0.15 |
| 信号质量评估不足 | SIGNAL_QUALITY | signal_strength < 0.5 | 0.15 |
| 市场状态识别错误 | MARKET_RECOGNITION | scenario_mismatch == True | 0.12 |
| 止损设置不合理 | STOP_LOSS | 亏损>3%且触发止损 | 0.10 |
| 止盈设置不合理 | TAKE_PROFIT | 盈利<1%且触发止盈 | 0.08 |
| 波动率估计偏差 | VOLATILITY | 实际与估计波动率差异>50% | 0.08 |
| 动量判断错误 | MOMENTUM | momentum_confidence < 0.4 | 0.07 |
| 多资产相关性未考虑 | CORRELATION | correlation_conflict == True | 0.05 |

**模块能力维度（5维）**：

| 维度 | 指标 | 含义 | 权重 |
|------|------|------|------|
| 准确率 | accuracy | 方向判断准确率 | 0.30 |
| 成功率 | success_rate | 交易胜率 | 0.25 |
| 效益 | profit_factor | 盈亏比 | 0.20 |
| 稳定性 | stability_score | 连续盈利/亏损次数 | 0.15 |
| 时效性 | timeliness_score | 信号提前/延迟程度 | 0.10 |

**为什么是旗舰能力？**

| 维度 | 说明 |
|------|------|
| **意图明确性** | 交易意图无需复杂识别——"赚钱"是唯一目标 |
| **闭环完整性** | 从分析 → 决策 → 执行 → 监控 → 进化，形成完整闭环 |
| **自动化程度** | AutoTrader + AutoScheduler 实现 7×24 全自动交易 |
| **落地验证** | 经过多轮回测和实盘验证，是最成熟的能力域 |
| **系统核心** | Dream OS 的其他能力（知识管理/数据分析）最终也服务于更好地交易 |

**代码组织（物理分离）**：

交易能力域的代码完全独立于内核，位于 `dreamos/capabilities/trading/`：

```
dreamos/capabilities/trading/
├── __init__.py              # TradingCapability 能力域定义
├── nodes/                   # 22 个交易节点（A/C/F/G 系列）
│   ├── a0_contradiction.py
│   ├── a1_deep_research.py
│   ├── ...
│   └── g2_governance.py
├── strategies/              # 策略配置（链路、阈值）
│   ├── default_chain.py
│   └── thresholds.py
├── execution/               # 实盘执行层
│   └── auto_trader.py       # AutoTrader 自动化交易
└── backtest/                # 回测引擎
    └── engine.py            # DreamOSBacktester
```

**关键设计：交易系统不独立为单独项目**

虽然交易能力域在代码上物理分离，但它**不独立为单独的仓库/项目**。原因：
1. **内核需要旗舰能力**：没有交易能力，Dream OS 就失去了最成熟的落地场景
2. **共享基础设施**：交易能力直接使用内核的 SACG 四层、Budget、Evolution 等基础设施
3. **协同进化**：交易反馈直接驱动内核的 EvolutionEngine 优化
4. **统一品牌**：Dream OS 交易系统的口碑反哺操作系统本身的认知

**节点分类**：

| 链路 | 节点 | 职责 | 对应交易环节 |
|------|------|------|-------------|
| A链 | A0-A2 | 矛盾分析 → 深度调研 → 综合分析 | 研究分析 |
| A链 | A3-A5 | 策略制定 → 决策门禁 → 执行规划 | 决策执行 |
| A链 | A6-A9 | 市态监控 → 实践门禁 → 统一升华 → 离场策略 | 监控优化 |
| C链 | C1-C3 | 技术扫描 → 动量分析 → 波动率分析 | 技术分析 |
| C链 | C5 | 离场系统 | 技术面离场 |
| F链 | F1-F5 | 新闻/资金流/估值/链上/宏观 | 基本面分析 |
| G链 | G1-G2 | 风控/治理 | 风险控制 |

**交易能力域的特点**：
- **意图单一明确**：通过交易赚钱，无需复杂意图识别
- **链路高度成熟**：A0-A9 决策流水线经过多轮优化
- **闭环完整**：从分析 → 决策 → 执行 → 监控 → 进化，形成完整闭环
- **自动化程度高**：AutoTrader + AutoScheduler 实现全自动交易

### 7.2 TradingAgent — 交易智能体

TradingAgent 是 Dream OS 的**旗舰应用**，将 S-A-C-G 四层内核串联为完整的交易决策智能体。

#### 7.2.1 架构设计

```
TradingAgent
    │
    ├─ IntentEngine (S层) ── 识别交易意图
    │
    ├─ GraphPlanner (A层) ── 编排执行图
    │
    ├─ GraphExecutor (C层) ── 执行节点
    │
    ├─ GraphStore (G层) ──── 状态持久化
    │
    ├─ NodeRegistry ──────── 节点管理
    │     └─ 22个内置交易节点
    │
    ├─ GlobalBudgetManager ─ 全局预算
    │
    └─ EvolutionEngine ───── 自我进化
```

#### 7.2.2 核心流程

```python
def run(self, user_input: str, market_data: dict) -> dict:
    # 1. 创建/重置状态
    state = new_state(cycle_id=gen_cycle_id())

    # 2. S层：识别意图
    intent_result = self.intent_engine.recognize(
        user_message=user_input,
        market=market_data,
    )
    state.set_intent(intent_result)

    # 3. A层：编排执行图
    plan = self.graph_planner.plan(state)
    graph = self.graph_planner.build_graph(plan)

    # 4. C层：执行
    report = self.graph_executor.execute(graph, state, plan=plan)

    # 5. G层：记录历史
    self.graph_store.checkpoint(state, node_id="FINAL")
    self.graph_store.record(state, report.to_dict())

    # 6. 返回结果
    return {
        "action": report.final_action,
        "confidence": report.final_confidence,
        "reasoning": report.reasoning,
        "cycle_id": state.cycle_id,
        "nodes_executed": report.nodes_executed,
        "tokens_used": report.tokens_used,
    }
```

#### 7.2.3 特性

| 特性 | 说明 |
|------|------|
| **节点可插拔** | 通过 Registry 管理，新增节点不影响 Agent |
| **预算全局管控** | GlobalBudgetManager 统一分配和监控 |
| **状态可追溯** | GraphStore 保存每个周期的完整快照 |
| **自我进化** | 历史数据驱动 Evolution 持续优化 |
| **多预算模式** | lean/standard/full 三档可切换 |

### 7.3 API Server

API Server 提供 HTTP 接口，支持远程调用 Dream OS 能力：

- `POST /api/v1/run` — 执行一次完整推理
- `POST /api/v1/intent` — 只做意图识别
- `GET /api/v1/nodes` — 列出可用节点
- `GET /api/v1/history` — 查询历史记录
- `GET /api/v1/health` — 健康检查

### 7.4 CLI

CLI 提供命令行交互，支持：

- **REPL 模式**：交互式对话
- **单条命令**：一次性执行
- **调度器**：定时任务管理
- **自动化命令**：自动交易、自动调度
- **分析命令**：历史数据分析、进化报告

### 7.5 自动交易系统（AutoTrader）

AutoTrader 是**交易能力域的自动化封装**，将 S-A-C-G 四层内核 + 交易节点 + 进化引擎串联为完整的**自动化交易闭环**。它既是应用层组件，也是交易能力域的旗舰实现。

**与 TradingAgent 的区别**：

| 维度 | TradingAgent | AutoTrader |
|------|-------------|------------|
| **定位** | 交互式交易分析 | 自动化实盘交易 |
| **触发方式** | 用户主动调用 | 定时调度触发 |
| **交互模式** | 有用户输入 | 无用户输入，全自动化 |
| **决策链路** | 完整 A0-A9 + 意图识别 | 精简链路，意图固定为交易 |
| **输出** | 分析结果 + 建议 | 直接下单或 HOLD |
| **使用场景** | 人工决策辅助 | 全自动量化交易 |

#### 7.5.1 完整自动化链路

```
定时触发（Scheduler）
    ↓
市场扫描（Market Scan）
    ↓  获取 K线 + 计算技术指标
36 场景分类（ScenarioClassifier）
    ↓
编排选择（OrchestrationMemory）
    ↓  四级降级查询
A1-A5 分析（GraphExecutor）
    ↓
G1 风控检查（Risk Control）
    ↓  GO/NO-GO 决策
A5 执行决策（Execution Planning）
    ↓
交易所下单（OKX / Hyperliquid）
    ↓
A9 离场监控（Exit Strategy）
    ↓
反馈回写（ExecutionFeedbackCollector）
    ↓
进化优化（EvolutionEngine）
```

#### 7.5.2 核心组件

| 组件 | 位置 | 职责 |
|------|------|------|
| **AutoTrader** | `cli/auto_trader.py` | 自动交易主类，编排全流程 |
| **ScenarioClassifier** | `core/sense/scenario_classifier.py` | 36 场景分类 |
| **OrchestrationMemory** | `core/memory/orchestration_memory.py` | 编排记忆与降级查询 |
| **ExecutionFeedbackCollector** | `core/memory/execution_feedback.py` | 执行反馈收集 |
| **EvolutionEngine** | `evolution/engine.py` | 自我进化引擎 |
| **DreamOSScheduler** | `cli/scheduler.py` | 定时任务调度器 |

#### 7.5.3 市场数据获取

AutoTrader 通过动态导入 `aster_spot.py` 获取实时市场数据，支持以下指标计算：

**技术指标集**（场景分类必需字段）：
- 价格：`price`
- 均线：`ema20`, `ema50`, `ema200`
- 涨跌幅：`change_1h`, `change_4h`, `change_24h`
- 波动率：`atr_pct`
- 动量：`rsi14`

**数据来源**：
- Hyperliquid：通过 `aster_spot.py` 获取 K 线和 MID 价格
- OKX：通过 OKX API 获取行情数据

#### 7.5.4 交易执行

**支持的交易动作**：
- `LONG`：开多仓
- `SHORT`：开空仓
- `HOLD`：持有/不操作
- `EXIT`：平仓离场
- `REDUCE`：减仓
- `RAISE_TP`：提高止盈

**交易所支持**：
- **Hyperliquid**：通过 `aster_spot.HyperliquidClient`
- **OKX**：通过 OKX API 客户端
- 支持 dry_run 模拟交易模式

**风控保护**：
- 最小交易间隔：30 分钟（防止频繁交易）
- G1 风控门禁（A4 决策门禁后强制检查）
- 预算管控（Token 消耗上限）

#### 7.5.5 反馈与进化

**交易后自动触发进化检查**：
1. 交易执行完成后，调用 `record_trade_feedback()` 记录反馈
2. 调用 `_try_trigger_evolution()` 触发进化引擎检查
3. 进化引擎扫描所有场景，对满足触发条件的场景执行编排优化
4. 优化结果写入 `OrchestrationMemory`，下次交易自动应用

#### 7.5.6 调度器（DreamOSScheduler）

**调度器特性**：
- Cron 表达式配置定时任务
- 多币种批量扫描
- 任务状态管理（running/paused/stopped/error）
- 执行历史记录
- 线程安全设计

**默认调度配置**（`scheduler_jobs.json`）：
```json
[
  {
    "name": "scan_main",
    "cron_expr": "*/5 * * * *",
    "enabled": true,
    "symbols": ["BTC", "ETH", "SOL", "AVAX", "LINK", "ARB", "OP", "MATIC"]
  }
]
```

**调度器数据文件**：
- `scheduler_jobs.json`：调度任务配置
- `scheduler_history.json`：执行历史记录

---

## 8. 扩展指南

### 8.1 新增节点

**步骤**：

1. 继承 `BaseNode`
2. 实现 `execute_core()` 方法
3. 设置元数据（node_id/name/chain/tags 等）
4. 注册到 Registry

**示例**：
```python
from dreamos import BaseNode, NodeResult, State, register_node

@register_node
class MyNode(BaseNode):
    node_id = "MY_NODE"
    name = "我的自定义节点"
    chain = "C"
    tags = ["custom", "example"]
    priority = 50
    required_tokens = 1000

    def execute_core(self, state: State) -> NodeResult:
        # 你的业务逻辑
        data = state.get_market_data()
        result = do_analysis(data)
        return NodeResult(
            node_id=self.node_id,
            confidence=result["confidence"],
            direction=result["direction"],
            reasoning=result.get("reasoning", ""),
        )
```

### 8.2 新增适配器

**步骤**：

1. 继承 `BaseAdapter`
2. 实现 `can_handle(config)` 方法
3. 实现 `to_node(config)` 方法
4. 注册到 AdapterRegistry

### 8.3 新增应用

**步骤**：

1. 确定应用场景和目标用户
2. 选择需要的节点集（可复用内置节点）
3. 组合 SACG 四层，设计应用主流程
4. 配置预算模式和降级策略
5. 接入数据源和输出渠道

---

## 9. 数据流设计

### 9.1 主执行数据流

```
用户输入 + 市场数据
    │
    ▼
┌─────────────────────────────────┐
│ S层：IntentEngine               │
│  - 规则识别 → LLM识别 → 融合      │
│  - Token预算门控                 │
└───────────────┬─────────────────┘
                │ IntentResult
                │  (intent_type, confidence,
                │   recommended_chain, priority)
                ▼
┌─────────────────────────────────┐
│ A层：GraphPlanner               │
│  - 链路选择 → 节点选择            │
│  - 预算分配 → 构建执行图          │
└───────────────┬─────────────────┘
                │ ExecutionPlan + ExecutionGraph
                │  (nodes, budget_allocation, graph)
                ▼
┌─────────────────────────────────┐
│ C层：GraphExecutor              │
│  - 逐节点执行 → 每步反思           │
│  - 动态调整 → 结果聚合            │
└───────────────┬─────────────────┘
                │ ExecutionReport
                │  (final_action, confidence,
                │   reasoning, nodes_executed)
                ▼
┌─────────────────────────────────┐
│ G层：GraphStore                 │
│  - 检查点保存 → 上下文压缩        │
│  - 历史记录 → 模式索引            │
└───────────────┬─────────────────┘
                │
                ▼
           最终结果
```

### 9.2 状态数据结构

State 是贯穿整个执行过程的**全局状态容器**：

```python
@dataclass
class State:
    cycle_id: str                    # 周期ID
    session_id: str                  # 会话ID

    # S层输出
    intent: Optional[IntentResult]   # 意图识别结果

    # A层输出
    plan: Optional[ExecutionPlan]    # 执行计划

    # C层输出
    results: Dict[str, NodeResult]   # 各节点结果
    trace: List[str]                 # 执行轨迹
    step: int                        # 当前步数

    # 元数据
    metadata: Dict[str, Any]         # 自定义元数据

    # 方法
    def update(node_id: str, result: NodeResult)
    def get_result(node_id: str) -> Optional[NodeResult]
    def get_confidence(node_id: str) -> float
    def get_direction(node_id: str) -> str
    def has_node(node_id: str) -> bool
```

### 9.3 数据契约

各层之间传递的数据结构都有明确的契约：

| 数据结构 | 产生层 | 消费层 | 核心字段 |
|----------|--------|--------|----------|
| IntentResult | S | A | intent_type, confidence, recommended_chain, priority, keywords |
| ExecutionPlan | A | C | selected_nodes, budget_allocation, total_budget, plan_id |
| NodeResult | 节点 | C/State | node_id, status, confidence, direction, data, reasoning |
| ExecutionReport | C | G/调用方 | final_action, final_confidence, reasoning, nodes_executed, tokens_used |

---

## 10. 配置与部署

### 10.1 配置架构

```
优先级（高 → 低）：
代码传入参数  ────────────────  运行时最高优先级
    ↑
环境变量 (.env / export)  ───  部署环境配置
    ↑
YAML 配置文件  ──────────────  系统级配置
    ↑
代码默认值  ─────────────────  兜底
```

### 10.2 主要配置项

| 配置项 | 默认值 | 说明 | 影响范围 |
|--------|--------|------|----------|
| budget_mode | standard | 预算模式 | 全局 Token 预算 |
| llm_trigger_threshold | 0.55 | LLM触发阈值 | S层识别策略 |
| max_checkpoints | 50 | 最大检查点数 | G层存储大小 |
| max_history | 200 | 最大历史记录数 | G层历史存储 |
| max_retries | 2 | 节点最大重试次数 | C层执行鲁棒性 |
| max_steps | 20 | 最大执行步数 | C层执行深度 |
| auto_compress | True | 自动压缩开关 | G层压缩策略 |

### 10.3 部署模式

| 模式 | 适用场景 | 特点 |
|------|----------|------|
| **库模式** | 嵌入其他Python应用 | 最轻量，直接 import |
| **CLI模式** | 本地开发/测试 | 交互式，便于调试 |
| **API模式** | 远程调用/服务化 | 网络API，多语言接入 |
| **后台服务** | 生产环境持续运行 | launchd/systemd 管理 |

---

## 11. 可观测性

### 11.1 可观测性体系

| 维度 | 数据来源 | 工具/方法 |
|------|----------|-----------|
| **执行追踪** | G层历史 + 执行轨迹 | 周期ID追踪、节点级追踪 |
| **性能监控** | 每步耗时 + Token消耗 | 耗时统计、Token使用率 |
| **成功率** | 节点执行状态 + 最终结果 | 成功率统计、失败分析 |
| **预算监控** | GlobalBudgetManager | 预算使用率、预警、降级 |
| **进化追踪** | EvolutionEngine | 优化建议、效果对比 |

### 11.2 日志体系

| 日志类型 | 级别 | 内容 |
|----------|------|------|
| DEBUG | 调试 | 详细执行过程、每个节点的输入输出 |
| INFO | 信息 | 关键节点完成、意图识别结果、最终决策 |
| WARN | 警告 | 重试、预算预警、置信度低 |
| ERROR | 错误 | 节点执行失败、系统异常 |

---

## 12. 技术栈

| 层次 | 技术选择 | 说明 |
|------|----------|------|
| **语言** | Python 3.10+ | 数据科学生态丰富，LLM集成成熟 |
| **核心架构** | 自研 SACG 四层架构 | 意图驱动的图编排执行 |
| **节点抽象** | 自研 BaseNode + Registry | 统一能力抽象，动态注册发现 |
| **适配器** | 自研 Adapter 框架 | Function/SKILL/API 三种适配器 |
| **LLM接入** | 统一 LLMClient 抽象 | 支持多后端切换（OpenAI/Anthropic/本地） |
| **状态管理** | dataclass + 字典 | 轻量、可序列化、可压缩 |
| **配置管理** | YAML + 环境变量 + 代码参数 | 多层级配置，灵活覆盖 |
| **测试框架** | pytest | 标准Python测试框架 |
| **打包** | Python 包（dreamos） | 标准包结构，pip 可安装 |
| **部署** | launchd / systemd / 直接运行 | 多种部署方式 |

---

## 13. 系统边界

### 13.1 三层边界模型

Dream OS 采用**三层边界模型**，从内到外依次为：操作系统内核层 → 能力域层 → 应用层。

```
┌─────────────────────────────────────────────────────────────┐
│  应用层 (Applications)                                       │
│  TradingAgent / AutoTrader / API Server / CLI               │
│  （应用是能力域的封装，面向具体使用场景）                      │
├─────────────────────────────────────────────────────────────┤
│  能力域层 (Capability Domains)                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ 交易能力域   │  │ [未来扩展]   │  │ [未来扩展]   │         │
│  │ A0-A9/C/F/G │  │ 知识管理     │  │ 数据分析     │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│  （当前仅交易能力域已实现，未来可横向扩展）                    │
├─────────────────────────────────────────────────────────────┤
│  操作系统内核层 (OS Kernel)                                  │
│  S层 → A层 → C层 → G层                                      │
│  Registry / Adapters / Budget / Evolution                    │
│  （完全通用，与业务领域无关）                                  │
└─────────────────────────────────────────────────────────────┘
```

### 13.2 操作系统内核层边界

**内核层做什么**（通用编排能力）：
- ✅ 意图识别与理解（IntentEngine）
- ✅ 执行图编排与调度（GraphPlanner + NodeSelector）
- ✅ 节点执行与反思（GraphExecutor + Reflector）
- ✅ 状态管理与持久化（GraphStore + Checkpointer）
- ✅ 上下文压缩与历史回放（Compressor + HistoryReplay）
- ✅ 节点注册与发现（NodeRegistry）
- ✅ 外部能力适配（AdapterRegistry）
- ✅ Token 预算管控（GlobalBudgetManager）
- ✅ 自我进化优化（EvolutionEngine）

**内核层不做什么**（业务领域逻辑）：
- ❌ 具体业务逻辑（由能力域节点实现）
- ❌ 数据采集与清洗（由数据源系统负责）
- ❌ 前端界面展示（由前端项目负责）
- ❌ 用户认证与权限（由接入方负责）
- ❌ 数据库管理（由各系统自行选择）

### 13.3 交易能力域边界

**交易能力域做什么**（交易专用能力）：
- ✅ 市场矛盾分析（A0）
- ✅ 深度调研与信息收集（A1）
- ✅ 技术分析与指标计算（C1-C3）
- ✅ 策略制定与决策（A3-A5）
- ✅ 风控检查与治理（G1-G2）
- ✅ 离场策略与监控（A9, C5）
- ✅ 实盘交易执行（AutoTrader）
- ✅ 自动化调度与扫描（AutoScheduler）

**交易能力域不做什么**（非交易职责）：
- ❌ 通用意图识别（由内核 S 层负责）
- ❌ 节点编排调度（由内核 A 层负责）
- ❌ 状态持久化（由内核 G 层负责）
- ❌ 非交易类业务（如知识管理、内容生成）

### 13.4 关键边界原则

1. **内核无业务**：操作系统内核不包含任何交易业务逻辑，只提供编排框架
2. **能力域无编排**：交易节点只实现交易逻辑，不干预执行流程（由内核 C 层调度）
3. **应用无节点**：应用层只组合能力，不直接实现节点逻辑
4. **未来扩展性**：新增能力域（如知识管理）只需实现新节点，无需修改内核
5. **物理分离，逻辑集成**：能力域代码独立目录（`capabilities/<domain>/`），但逻辑上与内核紧密集成，不独立为单独项目

### 13.5 物理分离 vs 逻辑集成

**物理分离的原因**：
- **代码清晰**：交易逻辑与内核编排框架物理隔离，降低认知负担
- **独立演进**：交易策略、参数、阈值可独立迭代，不影响 OS 内核
- **多能力域共存**：未来知识管理/数据分析能力域可按相同模式并排存在
- **测试隔离**：能力域可独立测试，不依赖完整内核启动

**逻辑集成的原因**：
- **内核需要旗舰能力**：交易是 Dream OS 最核心的意图实现，脱离交易能力，内核失去最成熟的落地场景
- **共享基础设施**：交易能力直接使用内核的 SACG、Budget、Evolution、Registry 等基础设施，独立项目会导致重复建设
- **协同进化**：交易执行反馈直接驱动内核 EvolutionEngine 优化编排策略
- **统一品牌**：Dream OS 交易系统与操作系统共享品牌认知，互相背书

**不独立为单独项目的决策**：

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 独立项目 | 完全解耦，可独立发布 | 重复建设基础设施，失去协同进化，品牌割裂 | ❌ 否决 |
| 物理分离+逻辑集成（当前方案） | 代码清晰，共享内核，协同进化 | 需要维护清晰的边界契约 | ✅ 采用 |
| 完全混在一起 | 简单，无迁移成本 | 内核与业务耦合，无法扩展多能力域 | ❌ 否决 |

---

## 14. 未来优化方向

### 14.1 内核层优化

| 方向 | 优先级 | 描述 |
|------|--------|------|
| **G层持久化** | P1 | 实现磁盘持久化，支持跨会话历史 |
| **多会话隔离** | P2 | 支持多用户、多会话的状态隔离 |
| **分布式执行** | P3 | 支持节点分布式执行，提升吞吐 |
| **API Server 完善** | P2 | 完善 HTTP API，支持更多管理功能 |
| **监控告警** | P2 | 生产级监控和告警体系 |
| **性能优化** | P3 | 图执行性能、压缩算法优化 |
| **更多适配器** | P2 | Database Adapter、Message Queue Adapter 等 |

### 14.2 交易能力域优化

| 方向 | 优先级 | 描述 |
|------|--------|------|
| **节点实现完善** | P0 | 填充 22 个内置节点的完整业务逻辑 |
| **进化闭环打通** | P1 | 打通执行反馈 → 进化 → 自动优化的完整闭环 |
| **回测系统增强** | P1 | 支持更多币种、更多周期、更精细的模拟 |
| **风控体系升级** | P2 | 增加更多风控维度和动态风控策略 |
| **多交易所支持** | P2 | 支持更多交易所接入 |

### 14.3 能力域扩展（长期）

| 方向 | 优先级 | 描述 |
|------|--------|------|
| **知识管理能力域** | P3 | 基于 S-A-C-G 框架的知识管理、文档分析、信息检索 |
| **数据分析能力域** | P3 | 通用数据分析、报表生成、趋势预测 |
| **内容生成能力域** | P3 | 基于意图的内容生成、报告撰写、文案创作 |
| **跨能力域编排** | P3 | 支持一次意图触发多个能力域的协同执行 |

---

## 15. 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v2.4 | 2026-07-21 | **交易分析评估器（核心新增）**：新增 `TradingAnalysisEvaluator` 交易分析评估器，实现亏损原因分析（10类）、模块能力评估（5维）、模块回测、编排推荐的完整闭环；更新 EvolutionEngine 整合评估器，新增 `analyze_trades()` / `evaluate_module_capabilities()` / `recommend_orchestration()` 等方法；更新 §7.2 明确"分析评估 → 模块能力回测 → 节点编排推荐"的核心设计理念 |
| v2.3 | 2026-07-21 | **物理分离，逻辑集成**：交易节点从 `dreamos/nodes/` 迁移到 `dreamos/capabilities/trading/nodes/`，实现操作系统内核与交易能力域的物理分离；新增 CapabilityRegistry 和 CapabilityRouter 内核组件，实现意图驱动的能力域路由；新增 §7.1.1 能力域注册与路由机制、§7.2 交易能力域旗舰地位阐述、§13.5 物理分离 vs 逻辑集成决策；AutoTrader 和回测引擎迁移到交易能力域子目录；旧 `dreamos/nodes/` 保留为向后兼容层 |
| v2.2 | 2026-07-21 | 新增系统定位章节：明确操作系统内核 vs 交易系统的双重身份；引入能力域层（Capability Domains）概念；重构系统边界为三层边界模型（内核层/能力域层/应用层）；更新应用层设计，明确交易能力域是内建核心能力；优化未来优化方向，分内核层/交易能力域/能力域扩展三个维度 |
| v2.1 | 2026-07-15 | 新增 36 场景分类系统、编排记忆与四级降级、执行反馈收集器、编排优化机制、自动交易全链路（AutoTrader）、调度器与默认配置 |
| v2.0 | 2026-07-14 | 新建完整系统级技术设计文档，覆盖 SACG 四层深度设计、节点体系、适配器框架、自我进化、应用层、数据流、部署运维 |
