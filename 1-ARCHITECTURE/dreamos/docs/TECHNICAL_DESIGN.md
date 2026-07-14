# Dream OS 技术设计文档 v2.0

> **文档层级**: L1 — 系统级技术设计
> **版本**: v2.0.0
> **更新日期**: 2026-07-14
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

---

## 7. 应用层设计

### 7.1 应用层定位

应用层是 Dream OS 内核的**使用者和组合者**，它不修改内核代码，而是通过组合内核的 SACG 四层能力 + 特定节点集，构建面向具体场景的应用。

**设计原则**：
- 内核提供骨架，应用填充血肉
- 应用之间共享内核，但各自独立配置
- 应用可以有自己的节点集、配置、调度策略

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

### 13.1 Dream OS 做什么

- ✅ 意图识别与理解
- ✅ 执行图编排与调度
- ✅ 节点执行与反思
- ✅ 状态管理与持久化
- ✅ 上下文压缩与历史回放
- ✅ 节点注册与发现
- ✅ 外部能力适配
- ✅ Token 预算管控
- ✅ 自我进化优化
- ✅ 应用框架与脚手架

### 13.2 Dream OS 不做什么

- ❌ 具体业务逻辑（由节点/适配器实现）
- ❌ 数据采集与清洗（由各系统负责）
- ❌ 交易执行与下单（由交易系统负责）
- ❌ 前端界面展示（由前端项目负责）
- ❌ 用户认证与权限（由接入方负责）
- ❌ 数据库管理（由各系统自行选择）

---

## 14. 未来优化方向

| 方向 | 优先级 | 描述 |
|------|--------|------|
| **节点实现完善** | P0 | 填充 22 个内置节点的完整业务逻辑 |
| **G层持久化** | P1 | 实现磁盘持久化，支持跨会话历史 |
| **进化闭环打通** | P1 | 打通执行反馈 → 进化 → 自动优化的完整闭环 |
| **多会话隔离** | P2 | 支持多用户、多会话的状态隔离 |
| **分布式执行** | P3 | 支持节点分布式执行，提升吞吐 |
| **API Server 完善** | P2 | 完善 HTTP API，支持更多管理功能 |
| **监控告警** | P2 | 生产级监控和告警体系 |
| **性能优化** | P3 | 图执行性能、压缩算法优化 |
| **更多适配器** | P2 | Database Adapter、Message Queue Adapter 等 |

---

## 15. 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v2.0 | 2026-07-14 | 新建完整系统级技术设计文档，覆盖 SACG 四层深度设计、节点体系、适配器框架、自我进化、应用层、数据流、部署运维 |
