# 24-图结构上下文压缩 — API 规格说明

> **版本**: v1.0  
> **更新日期**: 2026-09-30  
> **代码版本**: `0.1.0`（`VERSION`）  
> **协议版本**: `1`（`PROTOCOL_VERSION`）

---

## 1. 接口概览

本模块为 TypeScript 库，通过 `index.ts` 对外暴露。核心接口是 `Compressor`，由工厂函数 `createCompressor()` 创建。

| 接口 | 方法 | 说明 |
|------|------|------|
| `Compressor` | `compress()` | 压缩上下文，返回三层图 + 统计 |
| `Compressor` | `getVisualizationData()` | 获取压缩前后可视化对比数据 |
| `Compressor` | `recognizeIntent()` | 意图识别（confirmed/clarifying 两态） |
| `Compressor` | `clarifyIntent()` | 澄清确认意图 |
| `Compressor` | `getNotebookView()` | 获取 OKR 全景笔记本视图 |
| `Compressor` | `addNote()` | 添加短线任务便签 |
| `Compressor` | `health()` | 健康检查 |
| `Compressor` | `getStats()` | 压缩统计 |
| `Compressor` | `getMode()` | 获取压缩模式 |
| `GraphExecutor` | `execute()` | 执行图流程 |
| `ParallelScheduler` | `executeParallelGroup()` | 执行并行节点组 |
| `IncrementalCompressor` | `append() / compress() / rollback()` | 增量压缩版本链 |

---

## 2. 认证方式

本模块为内部库，无 HTTP 认证。会话通过 `sessionId` 字符串隔离上下文。

- `CompressInput.sessionId`：标识会话，用于缓存 Blueprint/Architecture
- `IncrementalCompressorOptions.sessionId`：跨 session 复用压缩版本
- `GraphExecutor` 通过 `executionId`（内部生成 `exec_${timestamp}_${random}`）区分执行实例

---

## 3. 接口详情

### 3.1 `createCompressor(options?)`

创建压缩器实例。

**签名**：
```typescript
function createCompressor(options?: CompressorOptions): Compressor
```

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `options.mode` | `'basic' \| 'semantic' \| 'sharded' \| 'auto'` | 否 | `'auto'` | 压缩模式 |
| `options.defaultTargetRatio` | `number` | 否 | `0.5` | 默认目标压缩率 |
| `options.maxConcurrency` | `number` | 否 | - | 最大并发数 |
| `options.shardSize` | `number` | 否 | `50` | 分片大小 |
| `options.semanticWeight` | `number` | 否 | `0.4` | 语义权重 |
| `options.onError` | `(err: Error) => void` | 否 | - | 错误回调 |
| `options.onCompressed` | `(result: CompressResult) => void` | 否 | - | 完成回调 |

**示例**：
```typescript
import { createCompressor } from './index';

const compressor = createCompressor({
  mode: 'auto',
  defaultTargetRatio: 0.5,
  onError: (err) => console.error('压缩失败:', err),
});
```

---

### 3.2 `Compressor.compress(input)`

压缩上下文。

**签名**：
```typescript
compress(input: CompressInput): Promise<CompressResult>
```

**`CompressInput` 参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sessionId` | `string` | 是 | 会话 ID |
| `payload` | `string \| CompressItem[]` | 是 | 待压缩内容（字符串按行切分，或结构化条目） |
| `targetRatio` | `number` | 否 | 目标压缩率，覆盖默认值 |
| `metadata` | `Record<string, unknown>` | 否 | 元数据（可含 `intent` 字段用于路由） |

**`CompressItem`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `string` | 条目 ID |
| `type` | `'message' \| 'step' \| 'tool_call' \| 'log' \| 'other'` | 条目类型 |
| `content` | `string` | 内容 |
| `tokens` | `number` | Token 数（可选，否则自动估算） |
| `timestamp` | `number` | 时间戳（可选） |
| `meta` | `Record<string, unknown>` | 扩展元数据 |

**返回 `CompressResult`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `graph` | `GraphData` | 三层图数据（blueprint / architecture / chronicle + edges） |
| `originalTokens` | `number` | 原始 Token 数 |
| `compressedTokens` | `number` | 压缩后 Token 数 |
| `compressionRatio` | `number` | 实际压缩率（后/前） |
| `stats` | `GraphStats` | 统计（节点数/边数/分层计数/保留压缩数） |
| `report` | `CompressionReport` | 压缩报告（策略/丢弃详情/耗时/算法版本） |

**示例**：
```typescript
const result = await compressor.compress({
  sessionId: 'sess_001',
  payload: [
    { id: 'm1', type: 'message', content: '帮我分析 BTC 走势', timestamp: Date.now() },
    { id: 'm2', type: 'message', content: 'BTC 价格 65200，RSI 55', timestamp: Date.now() + 1000 },
  ],
  targetRatio: 0.5,
});

console.log(`压缩率: ${(result.compressionRatio * 100).toFixed(1)}%`);
console.log(`保留节点: ${result.stats.retainedNodes}, 压缩节点: ${result.stats.compressedNodes}`);
```

---

### 3.3 `Compressor.getVisualizationData(input)`

获取压缩前后三层图对比可视化数据。若尚未压缩，内部先调用 `compress()`。

**返回 `VisualizationData`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `before` | `{ B, A, C }` | 压缩前各层节点/边 |
| `after` | `{ B, A, C }` | 压缩后各层节点/边 |
| `diff` | `{ retained, compressed, compressionRatio, avgRetainedScore, avgCompressedScore }` | 差异摘要 |
| `stats` | 统计对象 | 压缩前后节点数/分层/压缩率/上下文保留率 |
| `timeline` | `TimelineItem[]` | 执行时间线 |
| `discarded` | `{ nodeId, reason }[]` | 丢弃详情 |

---

### 3.4 `Compressor.recognizeIntent(userMessage, sessionId, previousMessages?)`

意图识别入口。

**返回 `IntentRecognitionResult`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `state` | `'confirmed' \| 'clarifying' \| 'detecting'` | 意图状态 |
| `intent` | `string` | 意图标识 |
| `intentName` | `string` | 意图名称 |
| `objective` | `string` | 目标描述 |
| `isNewIntent` | `boolean` | 是否新意图 |
| `confidence` | `number` | 置信度 0-1 |
| `clarified` | `boolean` | 是否经用户澄清 |
| `okrSummary` | `string` | OKR 摘要 |
| `clarifyQuestion` | `IntentClarifyQuestion` | 追问问题（state='clarifying' 时） |
| `candidates` | `IntentCandidate[]` | 候选意图列表 |

**示例**：
```typescript
const result = compressor.recognizeIntent('帮我分析 BTC', 'sess_001');
if (result.state === 'confirmed') {
  console.log('意图:', result.intentName, '置信度:', result.confidence);
} else if (result.state === 'clarifying') {
  console.log('请澄清:', result.clarifyQuestion?.question);
}
```

---

### 3.5 `Compressor.clarifyIntent(answer, sessionId, selectedIntentId?)`

接收用户对澄清问题的回答，重新推断并锁定意图。仅在 `state='clarifying'` 后调用。

---

### 3.6 `Compressor.getNotebookView(sessionId)`

获取 OKR 全景笔记本视图。

**返回 `NotebookView`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `longTermObjective` | `string` | 长期目标 |
| `intent` | `string` | 当前意图 |
| `midTermTasks` | `{ id, name, status, confidence? }[]` | 中期计划（A 层步骤摘要） |
| `shortTermLog` | `{ id, summary, timestamp, kept }[]` | 短期记录（C 层最近执行） |
| `notes` | `NoteEntry[]` | 活跃便签 |
| `okrSummary` | `string` | OKR 摘要文本 |

---

### 3.7 `Compressor.addNote(sessionId, note)`

添加短线任务便签。

**参数 `note`**：`Omit<NoteEntry, 'id' | 'createdAt' | 'updatedAt'>`

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | `string` | 便签标题 |
| `content` | `string` | 便签内容 |
| `intentGoalId` | `string` | 所属意图目标 ID |
| `horizon` | `'mid' \| 'short'` | OKR 层级 |
| `status` | `'active' \| 'done' \| 'archived'` | 状态 |
| `linkedNodeId` | `string` | 关联图节点 ID |

---

### 3.8 `Compressor.health()`

**返回 `HealthStatus`**：`{ healthy: boolean, version: string, uptimeMs: number, lastError?: string }`

---

### 3.9 `Compressor.getStats()`

**返回 `CompressorStats`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `totalCompressions` | `number` | 总压缩次数 |
| `averageCompressionRatio` | `number` | 平均压缩率 |
| `averageLatencyMs` | `number` | 平均耗时 |
| `totalTokensSaved` | `number` | 累计节省 Token |

---

### 3.10 `createGraphExecutor(config)`

创建图执行引擎。

**`GraphExecutorConfig`**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `architecture` | `ArchitectureGraph` | 是 | - | A 层架构图 |
| `blueprint` | `BlueprintGraph` | 是 | - | B 层蓝图 |
| `hitlEnabled` | `boolean` | 否 | `false` | 启用 HITL |
| `hitlConfig.defaultTimeoutMs` | `number` | 否 | - | 中断超时 |
| `hitlConfig.autoApproveLowRisk` | `boolean` | 否 | - | 低风险自动通过 |
| `hitlConfig.requireHumanForHighRisk` | `boolean` | 否 | - | 高风险强制人工 |
| `checkpointConfig.storageDir` | `string` | 否 | `./graph-checkpoints` | 存储目录 |
| `checkpointConfig.autoSave` | `boolean` | 否 | `true` | 自动保存 |
| `checkpointConfig.maxCheckpoints` | `number` | 否 | `50` | 最大检查点 |
| `maxTokenBudget` | `number` | 否 | `8000` | Token 预算 |
| `confidenceThreshold` | `number` | 否 | `0.6` | 置信度阈值 |

**`GraphExecutor.execute()` 返回**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | `boolean` | 是否成功 |
| `completedNodes` | `number` | 完成节点数 |
| `totalNodes` | `number` | 总节点数 |
| `tokenUsed` | `number` | Token 消耗 |
| `finalConfidence` | `number` | 最终置信度 |
| `interrupts` | `InterruptContext[]` | 中断上下文列表 |
| `error` | `string` | 错误信息（失败时） |

---

### 3.11 `createIncrementalCompressor(options?)`

创建增量压缩器。

**`IncrementalCompressorOptions`**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `initialMessages` | `CompressMessage[]` | `[]` | 初始消息 |
| `targetRatio` | `number` | `0.5` | 目标压缩率 |
| `minKeepThreshold` | `number` | `0.4` | 最低保留评分 |
| `autoIncrementThreshold` | `number` | `5` | 自动压缩触发消息数 |
| `highlightKeywords` | `string[]` | `[]` | 领域关键词 |
| `maxVersions` | `number` | `50` | 最大版本数 |
| `sessionId` | `string` | 自动生成 | 会话 ID |

**核心方法**：

| 方法 | 说明 |
|------|------|
| `append(messages)` | 追加消息，达到阈值自动压缩 |
| `appendOne(message)` | 追加单条 |
| `compress()` | 手动触发增量压缩 |
| `fullCompress()` | 全量重压缩 |
| `rollback(versionId)` | 回滚到指定版本 |
| `getLatestVersion()` | 获取最新版本 |
| `getSnapshot(versionId)` | 获取指定版本快照 |
| `getContextForLLM()` | 获取 LLM 上下文（保留消息 + 摘要） |
| `getDiff(a, b)` | 对比两版本差异 |
| `listVersions()` | 列出所有版本 |
| `getStats()` | 统计信息 |
| `exportSession()` / `importSession()` | 持久化导入导出 |
| `clear()` | 清空所有数据 |

---

## 4. 错误码

本模块为 TypeScript 库，不使用数字错误码，通过异常和返回字段传递错误：

| 场景 | 处理方式 | 说明 |
|------|---------|------|
| 压缩算法异常 | `compress()` 返回 fallback 结果（`compressionRatio: 1`，`report.strategy: 'error-fallback'`），同时触发 `onError` 回调 | 保证调用方始终获得结构化返回 |
| 执行引擎节点异常 | `execute()` 返回 `{ success: false, error }`，`isRunning` 复位 | 不抛出异常 |
| 并行节点执行失败 | 失败节点结果 `confidence: 0`，`outputs.error` 记录错误，不中断整组 | 组内容错 |
| Token 超预算 | `execute()` 提前返回 `{ success: false, error: 'Token 预算超限' }` | 硬限制 |
| 检查点文件损坏 | `loadOrCreateStore()` 静默返回新 store | 容错降级 |
| HITL 中断超时 | 由 `defaultTimeoutMs` 控制，`InterruptContext.isExpired` 标记 | 需调用方处理 |

---

## 5. 版本管理

| 项 | 值 |
|----|-----|
| 代码版本 | `0.1.0`（`contract.ts` 中 `VERSION` 常量） |
| 协议版本 | `1`（`PROTOCOL_VERSION`） |
| 文档版本 | v1.0 |
| 稳定标记 | `@stability stable`（contract.ts 头部注释） |

版本兼容策略：
- `Compressor` 接口为最小稳定接口，新增方法不破坏现有调用
- 底层算法（`compress` / `semanticCompress` / `shardedCompress`）返回统一的 `CompressionResult` 结构
- `VERSION` 常量包含在 `CompressionReport.algorithmVersion` 中，便于追溯
