# 图文笔记压缩模型（Graph-Based Context Compression）

## 1. 问题定义

### 1.1 背景

传统大模型应用中，上下文压缩依赖文本摘要技术，存在以下核心问题：

| 问题类别 | 具体表现 | 影响 |
|---------|---------|------|
| 信息损失 | 丢弃细节时丢失上下文关系 | 无法追溯决策依据 |
| 语义漂移 | 多次压缩后语义偏离原始意图 | 长期对话质量下降 |
| 不可恢复 | 压缩后无法还原原始逻辑 | 无法深度复盘 |
| 无限增长 | 上下文随对话轮次线性增长 | Token 成本失控 |

### 1.2 核心假设

> **假设**：上下文关系可以通过图结构（节点+边）来表达，而非仅依赖文本描述。

**推理**：
- 执行步骤是节点（Node）
- 步骤间的依赖和数据流转是边（Edge）
- 压缩 = 保留高价值节点 + 合并低价值路径
- 展开 = 从图结构重新生成详细执行链

### 1.3 目标

- 解决无限上下文难题：通过层级压缩实现无限对话轮次
- 保留上下文关系：节点和边不丢失，可追溯、可复盘
- 支持增量扩展：每次新执行只更新增量部分
- 支持语义检索：基于图结构的语义查询和推理

---

## 2. 三层模型架构

### 2.1 模型总览

```
┌─────────────────────────────────────────────────────────────┐
│                      正向展开 (B → A → C)                    │
│                                                             │
│  🏗️ Blueprint ──展开──→ 🔀 Architecture ──展开──→ ⏱️ Chronicle │
│      (顶层架构)             (DAG依赖)              (执行记录)    │
│                                                             │
│                      回溯压缩 (C → A → B)                    │
│                                                             │
│  ⏱️ Chronicle ──压缩──→ 🔀 Architecture ──压缩──→ 🏗️ Blueprint │
│      (完整记录)             (保留依赖)              (架构级摘要)  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 层级定义

| 层级 | 名称 | 类型 | 核心作用 | 粒度 |
|-----|------|------|---------|------|
| **B** | Blueprint | 架构图 | 定义系统组件和数据流向 | 模块级 |
| **A** | Architecture | DAG图 | 定义执行步骤和依赖关系 | 步骤级 |
| **C** | Chronicle | 时间线 | 记录实际执行过程 | 执行级 |

#### 2.2.1 Blueprint（蓝图）

**定义**：顶层架构图，描述系统的宏观组件和数据流向。

**组成**：
- **节点（BNode）**：组件、模块、服务
- **边（BEdge）**：数据流向、控制流
- **根节点**：系统入口

**数据结构**（见 `models.ts`）：
```typescript
interface BNode {
  id: NodeId;
  type: 'component' | 'module' | 'service';
  name: string;
  description: string;
  metadata: NodeMetadata;
  children?: NodeId[];
}

interface BEdge {
  source: NodeId;
  target: NodeId;
  dataFlow: DataFlow;
  label?: string;
}
```

**示例结构**：
```
bp_root (量化分析系统)
├── intent_engine (意图识别引擎)
├── knowledge_base (知识库检索)
├── market_data (行情数据服务)
├── analysis_chain (分析链)
├── strategy_engine (策略引擎)
└── report_generator (报告生成器)

数据流向:
  intent_engine → knowledge_base [query]
  intent_engine → market_data [query]
  intent_engine → analysis_chain [control]
  knowledge_base → analysis_chain [knowledge]
  market_data → analysis_chain [market]
```

#### 2.2.2 Architecture（架构图）

**定义**：DAG（有向无环图），描述具体执行步骤和依赖关系。

**组成**：
- **节点（ANode）**：步骤、决策点、并行分支
- **边（AEdge）**：数据依赖、条件分支
- **入口点**：执行起点

**数据结构**（见 `models.ts`）：
```typescript
interface ANode {
  id: NodeId;
  type: 'step' | 'decision' | 'parallel';
  name: string;
  parentNodeId: NodeId;
  metadata: NodeMetadata;
  requires?: NodeId[];
  branches?: { condition: string; target: NodeId }[];
}
```

**示例结构**：
```
start
  └── S1_RESEARCH (依赖: start)
        └── S2_ANALYSIS (依赖: S1_RESEARCH)
              └── S3_DESIGN (依赖: S2_ANALYSIS)
                    └── S4_VALIDATE (依赖: S3_DESIGN)
                          ├── [回测通过] → S5_EXECUTE
                          └── [回测失败] → S3_DESIGN (循环)
```

#### 2.2.3 Chronicle（时间线）

**定义**：实际执行记录，包含时间、Token 消耗、输入输出等详细信息。

**组成**：
- **节点（CNode）**：每步执行的具体记录
- **边（CEdge）**：数据传递的时间戳和摘要

**数据结构**（见 `models.ts`）：
```typescript
interface CNode {
  id: NodeId;
  architectureNodeId: NodeId;
  executionId: string;
  startTime: number;
  endTime?: number;
  metadata: NodeMetadata;
  inputs: Record<string, any>;
  outputs: Record<string, any>;
  logs: string[];
}
```

**示例结构**：
```
时间线 exec_xxx:
  start: 10ms | 0 tokens | status: completed
  S1_RESEARCH: 149ms | 1268 tokens | status: completed
  S2_ANALYSIS: 277ms | 977 tokens | status: completed
  S3_DESIGN: 220ms | 600 tokens | status: completed
  S4_VALIDATE: 221ms | 709 tokens | status: completed
  S5_EXECUTE: 234ms | 707 tokens | status: completed
```

---

## 3. 核心算法

### 3.1 正向展开算法（B → A → C）

**流程**：
```
1. 从 Blueprint 创建 Architecture
   - 将每个模块展开为具体步骤
   - 建立步骤间的依赖关系
   - 添加条件分支逻辑

2. 从 Architecture 创建 Chronicle
   - 按拓扑顺序执行每个步骤
   - 记录执行时间、Token 消耗
   - 记录输入输出数据
   - 记录执行日志
```

**关键实现**（见 `compressor.ts`）：

```typescript
// B → A: 将蓝图展开为架构图
expandToArchitecture(blueprintId: string): ArchitectureGraph {
  // 1. 创建入口节点
  // 2. 展开分析链为 S1-S5 步骤
  // 3. 建立步骤间的依赖边
  // 4. 添加条件分支
}

// A → C: 将架构图展开为时间线
expandToChronicle(architectureId: string, executionId: string): ChronicleGraph {
  // 1. 按拓扑顺序遍历架构节点
  // 2. 为每个节点创建执行记录
  // 3. 记录时间、Token、输入输出
  // 4. 创建数据传递边
}
```

### 3.2 回溯压缩算法（C → A → B）

**核心思想**：根据节点的价值权重，保留高价值节点，压缩低价值节点。

**价值评估指标**：
| 指标 | 权重 | 说明 |
|-----|------|------|
| Token 消耗 | 0.4 | 消耗越高，价值越高 |
| 执行耗时 | 0.3 | 耗时越长，复杂度越高 |
| 输出重要性 | 0.2 | 是否产生关键输出 |
| 位置重要性 | 0.1 | 入口/出口节点优先保留 |

**压缩流程**：
```
1. 计算每个节点的价值评分
2. 按评分排序，保留 top-K 节点
3. 对保留节点：保留摘要信息，压缩详细内容
4. 对压缩节点：标记为 compressed，保留引用
5. 更新边：只保留与保留节点相关的边
6. 生成压缩报告：记录丢弃的详情和原因
```

**关键实现**（见 `compressor.ts`）：

```typescript
compress(chronicleId: string, targetRatio: number = 0.5): CompressionResult {
  // 1. 计算原始大小
  const originalSize = this.calculateGraphSize(chronicle);
  
  // 2. 创建压缩后的 Chronicle
  const compressedChronicle = this.createCompressedChronicle(chronicle, targetRatio);
  
  // 3. 创建压缩后的 Architecture
  const compressedArchitecture = this.createCompressedArchitecture(arch, chronicle);
  
  // 4. 计算压缩率和丢弃详情
  const discardedDetails = this.findDiscardedDetails(chronicle, compressedChronicle);
  
  return { compressedChronicle, compressedArchitecture, compressionRatio, discardedDetails };
}
```

### 3.3 压缩策略

| 策略 | 适用场景 | 实现方式 |
|-----|---------|---------|
| **价值优先** | 通用场景 | 按 Token+耗时排序保留 |
| **路径保留** | 调试场景 | 保留完整执行路径 |
| **关键节点** | 生产场景 | 仅保留入口和出口 |
| **语义感知** | 高级场景 | 基于语义重要性评估（待实现） |

---

## 4. 技术特性

### 4.1 上下文保留

**传统文本压缩 vs 图结构压缩**：

| 维度 | 文本压缩 | 图结构压缩 |
|-----|---------|-----------|
| 关系保留 | ❌ 丢失 | ✅ 完整保留 |
| 可追溯性 | ❌ 不可追溯 | ✅ 可追溯到任意层级 |
| 可恢复性 | ❌ 不可恢复 | ✅ 可重新展开 |
| 语义漂移 | ✅ 可能发生 | ❌ 结构保证语义稳定 |
| 增量更新 | ❌ 需重新压缩 | ✅ 仅更新增量 |

### 4.2 无限上下文解决方案

**原理**：通过层级压缩，将详细执行记录（C）压缩为架构级摘要（A），再压缩为蓝图级摘要（B）。

**无限循环模型**：
```
对话轮次 1: C1 → A1 → B1
对话轮次 2: C2 → A2 → B2 (基于 B1 展开)
对话轮次 3: C3 → A3 → B3 (基于 B2 展开)
...
对话轮次 N: CN → AN → BN
```

**存储增长模式**：
- 传统：O(N)，线性增长
- 图结构：O(log N)，对数增长（每次压缩约 50%）

### 4.3 与调度器的协同

**调度器（Hermes-Planner）** 的 Skip Gate 决策可以记录到图结构中：

```
执行记录:
  S1_RESEARCH: completed | token: 800 | latency: 150ms
  S2_ANALYSIS: completed | token: 600 | latency: 200ms
  S3_DESIGN: skipped | reason: "用户意图为概念解释，无需设计"
  S4_VALIDATE: skipped | reason: "S3未执行"
  S5_EXECUTE: completed | token: 400 | latency: 100ms
```

**价值**：
- 记录决策依据，可复盘
- 基于历史跳过记录优化 Skip Gate 规则
- 可视化展示调度器的决策效果

---

## 5. 已实现功能

### 5.1 核心模块

| 文件 | 功能 | 状态 |
|-----|------|------|
| `models.ts` | 三层图模型定义 | ✅ 完成 |
| `compressor.ts` | 压缩/展开核心算法 | ✅ 完成 |
| `demo.ts` | 演示脚本 | ✅ 完成 |

### 5.2 API 接口

| 方法 | 功能 | 说明 |
|-----|------|------|
| `createBlueprint(name)` | 创建蓝图 | 顶层架构 |
| `expandToArchitecture(id)` | B→A 展开 | 生成 DAG |
| `expandToChronicle(id, execId)` | A→C 展开 | 生成执行记录 |
| `compress(id, ratio)` | C→A→B 压缩 | 回溯压缩 |
| `getBlueprint(id)` | 获取蓝图 | 查询 |
| `getArchitecture(id)` | 获取架构图 | 查询 |
| `getChronicle(id)` | 获取时间线 | 查询 |

### 5.3 演示验证结果

**单轮压缩**（目标 50%）：
```
原始时间线: 6 节点 | 1481 bytes
压缩后: 6 节点(3个保留, 3个压缩) | 1222 bytes
压缩率: 82.5%
保留上下文: 12.4%
```

**多轮压缩**（3 轮）：
```
第1轮: 压缩率 95.7%
第2轮: 压缩率 88.9%  
第3轮: 压缩率 88.9%
```

---

## 6. 后续研究方向

### 6.1 短期（1-2 周）

#### 6.1.1 增量压缩算法

**目标**：每次新执行只压缩新增部分，保留历史压缩结果。

**实现思路**：
```
1. 维护压缩版本链：C1 → C2 → C3 → ... → Cn
2. 增量压缩：只对 Cn - Cn-1 进行压缩
3. 合并压缩结果：将增量压缩合并到历史压缩版本
4. 支持版本回溯：可回溯到任意历史版本
```

**预期收益**：
- 压缩效率提升 50%+
- 支持增量查询和分析

#### 6.1.2 可视化渲染

**目标**：将三层图渲染为交互式思维导图/架构图。

**技术方案**：
```
1. 使用 D3.js 或 React Flow 进行渲染
2. 支持缩放、拖拽、展开/折叠
3. 点击节点显示详细信息（Token、耗时、输入输出）
4. 支持跨层级导航（点击 B 节点展开到 A，点击 A 节点展开到 C）
```

**预期收益**：
- 直观展示上下文关系
- 支持交互式复盘和调试

#### 6.1.3 与调度器深度集成

**目标**：将调度器的决策记录到图结构中。

**实现思路**：
```
1. 在 Skip Gate 决策时记录 reason 和 confidence
2. 将调度器的路由决策作为边属性记录
3. 基于历史记录优化 Skip Gate 规则
4. 生成调度器决策图谱
```

**预期收益**：
- 可追溯调度器决策过程
- 基于数据优化 Skip Gate 规则

### 6.2 中期（1-2 月）

#### 6.2.1 语义感知压缩

**目标**：基于节点的语义重要性决定保留策略，而非仅依赖 Token 成本。

**技术方案**：
```
1. 使用 Embedding 模型对节点内容进行向量化
2. 计算节点间的语义相似度
3. 基于语义重要性和唯一性评估节点价值
4. 保留语义独特性高的节点，合并语义重复的节点
```

**预期收益**：
- 压缩质量提升 30%+
- 避免丢失语义关键节点

#### 6.2.2 持久化存储

**目标**：将压缩后的图结构存储到数据库，支持长期累积和检索。

**技术方案**：
```
1. 使用图数据库（Neo4j）或向量数据库存储
2. 支持按节点类型、状态、时间范围查询
3. 支持语义检索（基于 Embedding）
4. 支持版本管理和增量更新
```

**预期收益**：
- 支持无限对话轮次
- 支持跨会话上下文复用

#### 6.2.3 自动图生成

**目标**：从自然语言描述自动生成蓝图和架构图。

**技术方案**：
```
1. 使用 LLM 解析用户意图和需求
2. 生成对应的 Blueprint 结构
3. 自动展开为 Architecture DAG
4. 生成执行计划
```

**预期收益**：
- 降低图结构维护成本
- 支持动态生成执行链

### 6.3 长期（3-6 月）

#### 6.3.1 图结构推理引擎

**目标**：基于图结构进行推理和决策，替代部分 LLM 推理。

**技术方案**：
```
1. 构建图结构知识库
2. 基于图结构进行路径搜索和规划
3. 支持因果推理和关系推理
4. 与 LLM 协同工作
```

**预期收益**：
- 降低 Token 消耗
- 提升决策准确性和可解释性

#### 6.3.2 多模态图结构

**目标**：支持图像、语音等多模态内容的图结构压缩。

**技术方案**：
```
1. 将图像/语音转换为结构化节点
2. 建立多模态节点间的关系
3. 支持跨模态检索和推理
```

**预期收益**：
- 支持多模态上下文压缩
- 扩展应用场景

#### 6.3.3 分布式图压缩

**目标**：支持大规模图结构的分布式压缩和处理。

**技术方案**：
```
1. 使用分布式图计算框架（Spark GraphX）
2. 支持水平扩展
3. 支持实时压缩和查询
```

**预期收益**：
- 支持大规模应用场景
- 支持实时压缩和分析

---

## 7. 技术选型

### 7.1 现有技术栈

| 组件 | 技术 | 版本 |
|-----|------|------|
| 语言 | TypeScript | 5.x |
| 运行时 | Node.js | 20.x |
| 构建工具 | pnpm | 8.x |

### 7.2 推荐技术栈（后续扩展）

| 组件 | 推荐技术 | 理由 |
|-----|---------|------|
| 图数据库 | Neo4j | 成熟的图存储和查询能力 |
| 向量数据库 | Milvus | 高性能向量检索 |
| 可视化 | React Flow | 交互式图可视化 |
| 分布式计算 | Spark GraphX | 大规模图处理 |
| Embedding | DeepSeek Embeddings | 已在项目中使用 |

---

## 8. 风险与挑战

### 8.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|-----|------|------|---------|
| 压缩过度导致信息丢失 | 中 | 高 | 设置最小保留比例，支持手动调整 |
| 图结构复杂度爆炸 | 低 | 高 | 定期压缩，限制最大节点数 |
| 语义漂移 | 中 | 中 | 结构保证语义稳定，定期验证 |

### 8.2 工程挑战

| 挑战 | 描述 | 解决思路 |
|-----|------|---------|
| 实时压缩性能 | 大规模图压缩耗时 | 异步压缩、增量压缩 |
| 可视化性能 | 大规模图渲染卡顿 | 分级渲染、按需加载 |
| 数据一致性 | 多版本同步 | 版本控制、事务处理 |

---

## 9. 参考资源

### 9.1 相关项目

| 项目 | 链接 | 参考点 |
|-----|------|--------|
| LangGraph | https://github.com/langchain-ai/langgraph | 图结构执行框架 |
| Neo4j | https://neo4j.com/ | 图数据库 |
| React Flow | https://reactflow.dev/ | 交互式图可视化 |
| Milvus | https://milvus.io/ | 向量数据库 |

### 9.2 理论基础

| 理论 | 应用 |
|-----|------|
| DAG 压缩 | 架构图压缩 |
| 图论 | 节点重要性评估 |
| 信息论 | 压缩率评估 |
| 知识图谱 | 语义关系建模 |

---

## 10. 版本记录

| 版本 | 日期 | 变更 | 作者 |
|-----|------|------|------|
| v0.1.0 | 2026-06-18 | 初始版本，实现三层模型和压缩算法 | - |

---

*文档结束*
