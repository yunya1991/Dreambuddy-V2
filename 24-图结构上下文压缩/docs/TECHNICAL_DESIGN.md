# 24-图结构上下文压缩 — 技术设计

> **版本**: v1.0  
> **更新日期**: 2026-09-30

---

## 1. 概述

图结构上下文压缩引擎（Graph Context Compressor）是 DreamBuddy-V2 的上下文管理实验模块。核心思路是将对话/执行过程抽象为 **B/A/C 三层图结构**：

- **B 层 Blueprint（蓝图）**：顶层意图与组件，2-6 个节点
- **A 层 Architecture（架构）**：执行步骤 DAG，3-10 个节点
- **C 层 Chronicle（编年）**：逐条执行记录时间线，10-N 个节点

通过对 C 层节点进行多维度价值评分，压缩低价值节点，在保留决策路径的同时显著降低上下文 Token 消耗。模块同时提供完整的**执行引擎**能力：状态管理、检查点持久化、人机协作（HITL）、并行调度。

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                      调用方 (Frontend / Gateway)         │
└───────────────────────┬─────────────────────────────────┘
                        │
            ┌───────────▼────────────┐
            │      index.ts          │  公共入口
            │  createCompressor()    │
            └───────────┬────────────┘
                        │
            ┌───────────▼────────────┐
            │     contract.ts        │  Compressor 工厂 + 意图识别
            └───────────┬────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
  ┌─────▼─────┐  ┌──────▼──────┐  ┌────▼───────┐
  │ 基础压缩   │  │ 语义压缩     │  │ 分片压缩    │
  │compressor  │  │semantic-     │  │sharded-    │
  │  .ts       │  │compressor.ts │  │compressor  │
  └─────┬─────┘  └──────┬──────┘  └────┬───────┘
        │               │               │
        └───────────────┼───────────────┘
                        │
            ┌───────────▼────────────┐
            │   B/A/C 三层图模型      │
            │ blueprint/architecture │
            │ /chronicle/models      │
            └────────────────────────┘
```

### 2.2 执行引擎架构（Phase 1-3）

```
GraphExecutor (graph-executor.ts)
    │
    ├── GraphStateManager (graph-state.ts)   ← 运行时状态
    ├── GraphCheckpointer (graph-checkpointer.ts) ← 检查点持久化
    ├── HITLManager (graph-hitl.ts)          ← 人机协作
    └── ParallelScheduler (graph-parallel.ts) ← 并行调度
```

`GraphExecutor` 通过**组合模式**整合上述组件，不修改各自实现，提供统一执行接口。

---

## 3. 核心算法

### 3.1 基础压缩算法（compressor.ts）

**C→A→B 回溯压缩**，基于四维度价值评分：

```
score(node) = w_token * tokenScore
            + w_latency * latencyScore
            + w_struct * structuralScore
            + w_semantic * semanticScore
```

| 维度 | 权重 | 计算方式 |
|------|------|---------|
| Token 消耗 | 0.4 | 节点 tokenCost / 全局最大 tokenCost |
| 执行耗时 | 0.3 | 节点 latencyMs / 全局最大 latencyMs |
| 结构位置 | 0.2 | 入口节点 0.9 / 分支节点 0.7 / 被依赖节点 0.2+0.1*依赖数 |
| 语义重要性 | 0.1 | min(1, (outputCount+inputCount)/4) |

**压缩步骤**：
1. 对所有 C 层节点评分
2. 按评分降序排序，保留前 `ceil(total * (1 - targetRatio))` 个
3. 保留节点：摘要化输入输出（`summary` 字段），截断日志
4. 压缩节点：保留引用关系，清空 inputs/outputs/logs，状态置为 `compressed`
5. 同步裁剪 A 层架构图（只保留对应架构节点）
6. 计算压缩率 = newSize / originalSize

### 3.2 语义感知压缩（semantic-compressor.ts）

在基础评分上叠加语义评分，解决"内容稀疏但决策关键"和"文本冗余"的识别问题。

**语义评分三维度**：

| 维度 | 说明 |
|------|------|
| TF-IDF | 全局词汇表的逆文档频率，识别独特信息 |
| 关键词命中 | 6 个领域关键词桶（strategy/risk/analysis/decision/data/introspect） |
| 信息熵 | 词汇多样性，归一化到 0-1 |

```
semanticScore = keywordBias * keywordScore
              + (1-keywordBias) * 0.5 * tfidfScore
              + (1-keywordBias) * 0.5 * entropyScore

finalScore = semanticWeight * semanticScore + (1-semanticWeight) * metaScore
```

中文分词采用 **2-gram 子串** 方案（无外部依赖），配合简化停用词表过滤。

### 3.3 分片压缩（sharded-compressor.ts）

针对长对话（> 50 节点）的性能优化：

1. 按 `startTime` 排序保持执行顺序
2. 按 `shardSize`（默认 50）切片
3. 每片独立调用 `semanticCompress` 或 `compress`
4. **锚点节点**：每片首尾 `anchorNodes`（默认 2）个节点强制保留，维护跨片连续性
5. 合并所有分片结果，保持原顺序

当节点数 ≤ `shardSize * 1.5` 时不分片，直接走对应算法。

### 3.4 增量压缩（incremental-compressor.ts）

**版本链数据结构**：`version_1 → version_2 → ... → version_n`

每个版本包含：`timestamp / parentId / messageIds / keptNodeIds / compressedNodeIds / compressionRatio / avgKeptScore / avgCompressedScore / totalTokens / metadata`。

**核心操作**：
- `append(messages)`：追加消息，达到 `autoIncrementThreshold`（默认 5）触发压缩
- `compress()`：对 buffer 中消息增量压缩，创建新版本
- `fullCompress()`：基于所有历史消息全量重压缩
- `rollback(versionId)`：回滚到指定版本（删除其后所有版本）
- `getDiff(a, b)`：对比两版本差异
- `getContextForLLM()`：输出最新版本的保留消息 + 压缩摘要

---

## 4. 数据流

### 4.1 压缩数据流

```
CompressInput
    │
    ▼
mapPayloadToChronicleNodes()  ──┐
    │                           │
    ▼                           │
blueprintRegistry.routeByIntent │  意图路由
    │                           │
    ▼                           ▼
createBlueprint() ──► expandToArchitecture() ──► expandToChronicle()
                                                       │
                                                       ▼
                                            [mode 选择]
                                            basic / semantic / sharded
                                                       │
                                                       ▼
                                              CompressionResult
                                                       │
                                    ┌──────────────────┼──────────────────┐
                                    ▼                  ▼                  ▼
                              CompressResult     VisualizationData     CompressionReport
```

### 4.2 执行引擎数据流

```
ArchitectureGraph
    │
    ▼
GraphExecutor.execute()
    │
    ├─► getNextExecutableNodes()  （依赖满足的节点）
    │
    ├─► HITLManager.shouldInterrupt()?
    │     ├─ yes → createInterrupt() → waitForResolution()
    │     │           ├─ approve → 继续
    │     │           └─ reject → recordNodeSkip()
    │     └─ no → 继续
    │
    ├─► NodeHandler(node, context) → NodeHandlerResult
    │
    ├─► recordNodeComplete() / recordNodeFailure()
    │
    ├─► saveCheckpoint(snapshot)
    │
    └─► isOverBudget()? → 中止
```

---

## 5. 接口设计

### 5.1 `Compressor` 接口（contract.ts）

```typescript
interface Compressor {
  compress(input: CompressInput): Promise<CompressResult>;
  expand(graphId: string, level: 'A' | 'B' | 'C'): Promise<GraphData>;
  health(): Promise<HealthStatus>;
  getStats(): CompressorStats;
  getVisualizationData(input: CompressInput): Promise<VisualizationData>;
  getMode(): 'basic' | 'semantic' | 'sharded' | 'auto';
  recognizeIntent(userMessage, sessionId, previousMessages?): IntentRecognitionResult;
  clarifyIntent(answer, sessionId, selectedIntentId?): IntentRecognitionResult;
  getNotebookView(sessionId: string): NotebookView;
  addNote(sessionId: string, note): NoteEntry;
}
```

### 5.2 `GraphExecutor` 接口（graph-executor.ts）

```typescript
class GraphExecutor {
  constructor(config: GraphExecutorConfig);
  registerNodeHandler(nodeId, handler): void;
  setDefaultHandler(handler): void;
  getStateManager(): GraphStateManager;
  getCheckpointer(): GraphCheckpointer;
  getHITLManager(): HITLManager;
  getExecutionId(): string;
  execute(): Promise<ExecutionResult>;
  resumeFromCheckpoint(nodeId): Promise<void>;
  pause(): void;
  getIsRunning(): boolean;
  getExecutionSummary(): ExecutionSummary;
}
```

### 5.3 `NodeHandler` 签名

```typescript
type NodeHandler = (node: ANode, context: ExecutionContext) => Promise<NodeHandlerResult> | NodeHandlerResult;

interface NodeHandlerResult {
  outputSummary?: string;
  tokenCost: number;
  latencyMs: number;
  confidence: number;
  outputs: Record<string, unknown>;
  shouldInterrupt?: boolean;
}
```

---

## 6. 状态管理

### 6.1 `GraphState` 结构（graph-state.ts）

```typescript
interface GraphState {
  currentNodeId: NodeId;
  nodeResults: Map<NodeId, NodeResult>;
  confidence: number;
  tokenUsed: number;
  contextSummary: string;
  metadata: GraphStateMetadata;
}
```

### 6.2 节点状态机

```
pending ──► running ──► completed
                │
                ├────► skipped  （人工拒绝 / 条件跳过）
                └────► failed   （执行异常）
```

`NodeResult.status` 取值：`'pending' | 'running' | 'completed' | 'skipped' | 'failed' | 'cancelled'`

### 6.3 状态操作

| 方法 | 说明 |
|------|------|
| `recordNodeStart(nodeId)` | 标记节点为 running，记录开始时间 |
| `recordNodeComplete(nodeId, result)` | 标记 completed，累加 tokenUsed，更新 confidence |
| `recordNodeFailure(nodeId, error)` | 标记 failed |
| `recordNodeSkip(nodeId, reason)` | 标记 skipped |
| `advanceTo(nodeId)` | 推进当前节点指针 |
| `getNextExecutableNodes()` | 返回依赖已满足的待执行节点 |
| `isComplete()` | 检查所有节点是否 completed/skipped |
| `isOverBudget()` | 检查 tokenUsed ≥ maxTokenBudget |
| `createSnapshot(nodeId)` | 创建可序列化快照 |
| `restoreFromSnapshot()` | 从快照恢复 |

### 6.4 检查点持久化

- 存储格式：JSON 文件，路径 `${storageDir}/${executionId}.json`
- 默认目录：`process.cwd()/graph-checkpoints`
- 自动保存：每个节点完成后 `saveCheckpoint()`
- 最大保留：`maxCheckpoints`（默认 50），超出删除最旧
- 回滚：`revertToNode(nodeId)` 优先返回该节点自身快照，否则返回之前最新快照

---

## 7. 配置管理

配置通过构造函数参数注入，均提供默认值。详见 [`ENGINEERING_INDEX.md`](./ENGINEERING_INDEX.md#5-配置参数索引) 第 5 节。

关键设计：
- `CompressorOptions.mode = 'auto'`：根据 payload 规模自动选择算法
  - 节点数 ≤ 10 → `basic`
  - 10 < 节点数 ≤ 100 → `semantic`
  - 节点数 > 100 → `sharded`
- `GraphExecutorConfig` 组合了 HITL / Checkpoint / Token / 置信度四类配置

---

## 8. 错误处理

### 8.1 压缩错误

`contract.ts` 的 `compress()` 使用 try-catch，失败时返回 **fallback 结果**：

```typescript
{
  graph: { edges: [] },
  originalTokens: fallbackTokens,
  compressedTokens: fallbackTokens,
  compressionRatio: 1,  // 无压缩
  stats: { totalNodes: 0, ... },
  report: { strategy: 'error-fallback', ... }
}
```

同时通过 `onError` 回调通知调用方。

### 8.2 执行引擎错误

`GraphExecutor.execute()` 捕获节点执行异常，返回：

```typescript
{
  success: false,
  completedNodes,
  totalNodes,
  tokenUsed,
  finalConfidence,
  interrupts,
  error: error.message
}
```

`finally` 块确保 `isRunning` 标志复位，避免死锁。

### 8.3 并行执行错误

`ParallelScheduler.executeParallelGroup()` 中单个节点失败不中断整组：
- 失败节点结果：`{ outputSummary: '执行失败: ...', tokenCost: 0, confidence: 0, outputs: { error } }`
- 统计 `successCount` / `failedCount`，合并输出包含 `nodeResults`

---

## 9. 扩展性设计

### 9.1 压缩算法扩展

新增压缩算法只需实现与 `compress()` 相同的签名：

```typescript
(chronicle, architecture, blueprint, options) => CompressionResult
```

然后在 `contract.ts` 的 `resolveMode` / 算法分发处注册新模式。

### 9.2 意图路由扩展

`blueprint-registry.ts` 提供 `routeByIntent(intentText)`，新增意图模板只需注册到注册表。

### 9.3 并行扩展

节点通过 `parallelGroup` 字段标记并行组，`mergeStrategy` 控制汇总策略。`ParallelScheduler` 不修改 `models.ts`，通过类型扩展 `ParallelNode = ANode & { parallelGroup?, mergeStrategy? }` 实现。

### 9.4 HITL 扩展

`HITLNode = ANode & { interruptBefore?, interruptLabel?, riskLevel?, approvalFields? }`，支持低风险自动通过、高风险强制人工确认。

---

## 10. 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-09-30 | 标准化 TECHNICAL_DESIGN 文档，整合 B/A/C 三层压缩、执行引擎、并行、HITL 设计 |

> 更早版本历史见 [`CHANGELOG.md`](./CHANGELOG.md)。
