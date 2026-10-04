# 24-图结构上下文压缩 — 工程索引

> **版本**: v1.0  
> **更新日期**: 2026-09-30  
> **模块状态**: 🧪 实验状态（L3）  
> **语言**: TypeScript

---

## 1. 模块定位表

| 维度 | 内容 |
|------|------|
| 模块名称 | 24-图结构上下文压缩（Graph Context Compressor） |
| 模块定位 | DreamBuddy-V2 上下文管理实验模块，通过 B/A/C 三层图结构对对话/执行上下文进行压缩与检索 |
| 所属层级 | L3 实验模块（待主线集成） |
| 核心能力 | 三层图构建、价值评分压缩、语义感知压缩、分片压缩、增量压缩、意图路由、可视化输出、执行引擎（状态/检查点/HITL/并行） |
| 对外入口 | `index.ts` → `createCompressor()` |
| 协议版本 | `PROTOCOL_VERSION = '1'` |
| 代码版本 | `VERSION = '0.1.0'` |
| 关键模块 | `contract.ts` / `compressor.ts` / `semantic-compressor.ts` / `sharded-compressor.ts` / `incremental-compressor.ts` / `graph-state.ts` / `graph-checkpointer.ts` / `graph-hitl.ts` / `graph-parallel.ts` / `graph-executor.ts` / `planner/` |

---

## 2. 目录地图

```
24-图结构上下文压缩/
├── index.ts                       # 对外公共入口（createCompressor / blueprintRegistry / 算法导出）
├── contract.ts                    # 稳定接口契约 + Compressor 工厂实现
├── types.ts                       # 基础类型（NodeType / EdgeType / GraphData / InferenceResult 等）
├── models.ts                      # B/A/C 三层图核心模型（BNode/ANode/CNode/ArchitectureGraph 等）
├── blueprint.ts                   # B 层蓝图构建（createBlueprint / findComponent / getChildren）
├── architecture.ts                # A 层架构图展开（expandToArchitecture / getDependencies / getPathTo）
├── chronicle.ts                   # C 层执行记录展开（expandToChronicle / calculateSize）
├── blueprint-registry.ts          # 跨 session 架构模板注册表 + 意图路由
├── visualization.ts               # 压缩前后三层图对比 + 时间线 + 统计
│
├── compressor.ts                  # 基础压缩算法（C→A→B 回溯压缩，价值评分）
├── semantic-compressor.ts         # 语义感知压缩（TF-IDF + 关键词命中 + 信息熵）
├── sharded-compressor.ts          # 分片压缩（长对话优化，按时间切片）
├── incremental-compressor.ts      # 增量压缩（版本链，append/rollback/getDiff）
│
├── graph-state.ts                 # 图执行状态管理（运行时状态 + 快照）
├── graph-checkpointer.ts          # 检查点持久化（磁盘 JSON 存储 + 回滚）
├── graph-hitl.ts                  # 人机协作 HITL（中断/approve/reject/edit）
├── graph-parallel.ts              # 并行节点调度器（parallelGroup + all/any 汇总）
├── graph-executor.ts              # 统一执行引擎（组合 State + Checkpoint + HITL）
├── graph-parallel-executor.ts     # 并行执行器
├── intent-gateway.ts              # 意图网关（confirmed/clarifying 两态）
│
├── planner/                       # 双维度编排架构（S/C/F 链 + 技能注册 + 交叉验证）
│   ├── planner.ts
│   ├── chain-planner.ts
│   ├── chains-registry.ts
│   ├── skills-registry.ts
│   ├── module-registry.ts
│   ├── cross-validator.ts
│   ├── confidence-evaluator.ts
│   ├── skill-selector.ts
│   ├── intent-clarification-engine.ts
│   └── index.ts
│
├── skills/graph-compressor/       # graph-compressor SKILL
│   ├── SKILL.md
│   └── core/
│       ├── graph-compress.ts
│       ├── build_and_compress.ts
│       ├── semantic-compressor-advanced.ts
│       ├── graph-inference-engine.ts
│       ├── graph-persistence.ts
│       └── auto-graph-generator.ts
│
├── *.test.ts                      # 单元/集成测试（graph-state / graph-parallel / graph-hitl 等）
└── docs/                          # 标准文档目录
    ├── ENGINEERING_INDEX.md       # 本文件
    ├── TECHNICAL_DESIGN.md
    ├── API_SPEC.md
    └── CHANGELOG.md
```

---

## 3. 文件清单与职责

| 文件 | 职责 | 关键导出 |
|------|------|---------|
| `index.ts` | 公共入口，统一导出契约、算法、planner | `createCompressor`, `blueprintRegistry`, `VERSION`, `compress`, `semanticCompress`, `shardedCompress`, `buildVisualization` |
| `contract.ts` | 稳定接口契约 + `Compressor` 工厂 | `Compressor` 接口, `CompressInput`, `CompressResult`, `createCompressor`, `IntentRecognitionResult` |
| `types.ts` | 基础类型定义 | `NodeType`, `EdgeType`, `SerializedNode`, `SerializedEdge`, `GraphData`, `InferenceResult` |
| `compressor.ts` | 基础回溯压缩算法 | `compress()`, `scoreNode()`, `generateCompressionReport()` |
| `semantic-compressor.ts` | 语义感知压缩 | `semanticCompress()`, `dumpSemanticScores()` |
| `sharded-compressor.ts` | 分片压缩 | `shardedCompress()`, `describeShards()` |
| `incremental-compressor.ts` | 增量压缩（版本链） | `IncrementalCompressor`, `createIncrementalCompressor()` |
| `graph-state.ts` | 运行时状态管理 | `GraphStateManager`, `NodeResult`, `GraphStateSnapshot` |
| `graph-checkpointer.ts` | 检查点持久化 | `GraphCheckpointer`, `createCheckpointer()`, `listCheckpointFiles()` |
| `graph-hitl.ts` | 人机协作 | `HITLManager`, `HITLNode`, `InterruptContext`, `InterruptDecisionResult` |
| `graph-parallel.ts` | 并行调度 | `ParallelScheduler`, `ParallelNode`, `createParallelNode()`, `extractParallelGroups()` |
| `graph-executor.ts` | 统一执行引擎 | `GraphExecutor`, `createGraphExecutor()`, `NodeHandler` |
| `intent-gateway.ts` | 意图识别网关 | `getIntentGateway()`, `IntentGatewayResult` |
| `blueprint-registry.ts` | 架构模板注册表 | `blueprintRegistry`, `routeByIntent()` |
| `visualization.ts` | 可视化数据构建 | `buildVisualization()`, `VisualizationData` |
| `planner/` | 双维度编排架构 | `ExecutionPlanner`, `orchestrate()`, `ensureRegistryInitialized()` |

---

## 4. 核心流程索引

### 4.1 上下文压缩主流程
1. **入口**：`Compressor.compress(input)` — [`contract.ts`](../contract.ts)
2. **意图路由**：`blueprintRegistry.routeByIntent(intentText)` 匹配 Blueprint 模板
3. **三层图展开**：
   - B 层：`createBlueprint()` — [`blueprint.ts`](../blueprint.ts)
   - A 层：`expandToArchitecture(blueprint)` — [`architecture.ts`](../architecture.ts)
   - C 层：`expandToChronicle(architecture, sessionId)` — [`chronicle.ts`](../chronicle.ts)
4. **模式选择**（`resolveMode`）：
   - 节点数 ≤ 10 → `basic`（`compress()`）
   - 10 < 节点数 ≤ 100 → `semantic`（`semanticCompress()`）
   - 节点数 > 100 → `sharded`（`shardedCompress()`）
5. **输出**：`CompressResult`（graph + stats + report）

### 4.2 执行引擎流程
1. **入口**：`GraphExecutor.execute()` — [`graph-executor.ts`](../graph-executor.ts)
2. **状态推进**：`GraphStateManager.getNextExecutableNodes()` 基于依赖关系获取可执行节点
3. **HITL 检查**：`HITLManager.shouldInterrupt()` 决定是否中断等待人工决策
4. **节点执行**：`NodeHandler(node, context)` 返回 `NodeHandlerResult`
5. **状态记录**：`recordNodeStart` / `recordNodeComplete` / `recordNodeFailure`
6. **检查点保存**：`GraphCheckpointer.saveCheckpoint(snapshot)`
7. **预算检查**：`isOverBudget()` 超限则中止

### 4.3 并行执行流程
1. **分组识别**：`ParallelScheduler.identifyParallelGroups()` 按 `parallelGroup` 分组
2. **条件检查**：`canExecuteGroup()` 检查组外依赖是否完成
3. **分批执行**：按 `maxConcurrency`（默认 10）分批 `Promise.all`
4. **结果合并**：`mergeResults()` 按 `mergeStrategy`（all/any）合并输出

---

## 5. 配置参数索引

### 5.1 `CompressorOptions`（contract.ts）
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `mode` | `'basic' \| 'semantic' \| 'sharded' \| 'auto'` | `'auto'` | 压缩模式 |
| `defaultTargetRatio` | `number` | `0.5` | 默认目标压缩率 |
| `maxConcurrency` | `number` | - | 最大并发数 |
| `shardSize` | `number` | `50` | 分片大小（sharded 模式） |
| `semanticWeight` | `number` | `0.4` | 语义评分权重（semantic 模式） |
| `onError` | `(err: Error) => void` | - | 错误回调 |
| `onCompressed` | `(result: CompressResult) => void` | - | 压缩完成回调 |

### 5.2 `CompressionOptions`（compressor.ts）
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `targetRatio` | `number` | `0.5` | 目标压缩率 |
| `minNodes` | `number` | `1` | 最小保留节点数 |
| `keepAllEdges` | `boolean` | `false` | 是否保留所有边 |
| `weights.tokenCost` | `number` | `0.4` | Token 消耗权重 |
| `weights.latency` | `number` | `0.3` | 耗时权重 |
| `weights.structuralPosition` | `number` | `0.2` | 结构位置权重 |
| `weights.semanticImportance` | `number` | `0.1` | 语义重要性权重 |

### 5.3 `SemanticCompressionOptions`
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `semanticWeight` | `number` | `0.4` | 语义权重占比 |
| `keywordBias` | `number` | `0.5` | 关键词/TF-IDF 比例 |

### 5.4 `ShardOptions`
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `shardSize` | `number` | `50` | 每片最大节点数 |
| `targetRatio` | `number` | `0.6` | 每片目标压缩比 |
| `useSemantic` | `boolean` | `true` | 是否使用语义评分 |
| `anchorNodes` | `number` | `2` | 每片强制保留锚点数 |

### 5.5 `GraphExecutorConfig`
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `hitlEnabled` | `boolean` | `false` | 是否启用 HITL |
| `maxTokenBudget` | `number` | `8000` | 最大 Token 预算 |
| `confidenceThreshold` | `number` | `0.6` | 置信度阈值 |
| `checkpointConfig.storageDir` | `string` | `./graph-checkpoints` | 检查点存储目录 |
| `checkpointConfig.autoSave` | `boolean` | `true` | 是否自动保存 |
| `checkpointConfig.maxCheckpoints` | `number` | `50` | 最大检查点数 |

### 5.6 `ParallelSchedulerConfig`
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `maxConcurrency` | `number` | `10` | 最大并行数 |
| `defaultMergeStrategy` | `'all' \| 'any'` | `'all'` | 默认汇总策略 |

### 5.7 `IncrementalCompressorOptions`
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `targetRatio` | `number` | `0.5` | 目标压缩率 |
| `minKeepThreshold` | `number` | `0.4` | 最低保留评分 |
| `autoIncrementThreshold` | `number` | `5` | 自动压缩触发消息数 |
| `maxVersions` | `number` | `50` | 最大版本数量 |

---

## 6. 测试体系

| 测试文件 | 覆盖范围 |
|---------|---------|
| `graph-state.test.ts` | `GraphStateManager` 状态管理、节点记录、快照恢复 |
| `graph-hitl.test.ts` | `HITLManager` 中断/决策/超时 |
| `graph-hitl-integration.test.ts` | HITL 与执行引擎集成 |
| `graph-parallel.test.ts` | `ParallelScheduler` 并行分组/执行/合并 |
| `graph-parallel-integration.test.ts` | 并行执行集成 |
| `graph-integration.test.ts` | 执行引擎端到端集成 |
| `planner/chain-planner.test.ts` | 链规划器 |

---

## 7. 技术债务

| 编号 | 描述 | 影响 | 建议 |
|------|------|------|------|
| TD-1 | `contract.ts` 中 `expand()` 方法返回空 `{ edges: [] }`，未实现层级展开 | 功能缺失 | 实现 B/A/C 层级按需展开 |
| TD-2 | `incremental-compressor.ts` 依赖 `./skills/graph-compressor/core/graph-compress.ts`，存在跨目录耦合 | 维护性 | 抽取共享压缩核心到顶层 |
| TD-3 | `graph-state.ts` 的 `shouldInterrupt` 使用 `(node as any).interruptBefore`，类型不安全 | 类型安全 | 引入 `HITLNode` 类型断言 |
| TD-4 | `semantic-compressor.ts` 中文分词采用 n-gram 简易方案，精度有限 | 压缩质量 | 接入专业中文分词库 |
| TD-5 | `graph-checkpointer.ts` 使用同步 `fs` 写入，大检查点可能阻塞 | 性能 | 改为异步写入 |
| TD-6 | `contract.ts` 模块级 `intentBlueprintItems` / `notebookNotes` Map 无清理机制，长生命周期可能内存泄漏 | 内存 | 增加 session 级 TTL 清理 |
| TD-7 | 多个 `CompressResult` 类型定义（`contract.ts` / `types.ts` / `compressor.ts`）存在差异 | 一致性 | 统一类型定义来源 |

---

## 8. 快速导航

- **接口契约**：[`contract.ts`](../contract.ts)
- **入口 API**：[`index.ts`](../index.ts)
- **基础压缩算法**：[`compressor.ts`](../compressor.ts)
- **语义压缩**：[`semantic-compressor.ts`](../semantic-compressor.ts)
- **分片压缩**：[`sharded-compressor.ts`](../sharded-compressor.ts)
- **增量压缩**：[`incremental-compressor.ts`](../incremental-compressor.ts)
- **执行引擎**：[`graph-executor.ts`](../graph-executor.ts)
- **状态管理**：[`graph-state.ts`](../graph-state.ts)
- **检查点**：[`graph-checkpointer.ts`](../graph-checkpointer.ts)
- **HITL**：[`graph-hitl.ts`](../graph-hitl.ts)
- **并行调度**：[`graph-parallel.ts`](../graph-parallel.ts)
- **意图网关**：[`intent-gateway.ts`](../intent-gateway.ts)
- **可视化**：[`visualization.ts`](../visualization.ts)
- **Planner**：[`planner/index.ts`](../planner/index.ts)
- **SKILL 文档**：[`skills/graph-compressor/SKILL.md`](../skills/graph-compressor/SKILL.md)
- **已有文档**：[`SPEC.md`](../SPEC.md) / [`TECHNICAL-DOC.md`](../TECHNICAL-DOC.md) / [`IMPLEMENTATION.md`](../IMPLEMENTATION.md) / [`THEORY-AND-PRACTICE.md`](../THEORY-AND-PRACTICE.md)
