/**
 * 6-图结构上下文压缩 — 通用功能模块入口
 *
 * 对外暴露：
 *   - createCompressor()  → 工厂方法，支持 basic / semantic / sharded / auto 四种模式
 *   - createCompressor() 新增 getVisualizationData()：返回压缩前后三层图对比 + 时间线
 *   - blueprintRegistry  → 跨 session 共享架构模板（按意图路由）
 *   - VERSION / PROTOCOL_VERSION
 *
 * 子模块：
 *   contract.ts  → 接口契约 + Compressor 实例工厂
 *   semantic-compressor.ts → 基于 TF-IDF + 关键词命中 + 信息熵的语义评分压缩
 *   sharded-compressor.ts → 分片压缩（长对话优化）
 *   blueprint-registry.ts → 跨 session 架构模板注册表 + 意图路由
 *   visualization.ts → 构建压缩前后三层图对比 + 时间线 + 统计
 *   compressor.ts / chronicle.ts / architecture.ts / blueprint.ts / types.ts → B-A-C 核心算法
 *
 * 调用方（如 3-FRONTEND/dream-universal-gateway）：
 *   在 tsconfig.json 中配置 paths:
 *     "@yunya/graph-context-compressor": ["../../../6-图结构上下文压缩/index.ts"]
 *   然后 import:
 *     import { createCompressor } from '@yunya/graph-context-compressor';
 *     const c = createCompressor({ mode: 'auto' });
 *     const result = await c.compress({ sessionId: 's1', payload: [...] });
 *     const viz = await c.getVisualizationData({ sessionId: 's1', payload: [...] });
 */

export { createCompressor, VERSION, PROTOCOL_VERSION } from './contract';
export type { CompressInput, CompressItem, CompressResult, GraphData, SerializedNode, SerializedEdge, GraphStats, CompressionReport, Compressor, HealthStatus, CompressorStats, CompressorOptions } from './contract';
export { blueprintRegistry } from './blueprint-registry';
export type { BlueprintTemplate } from './blueprint-registry';
export { semanticCompress } from './semantic-compressor';
export type { SemanticCompressionOptions } from './semantic-compressor';
export { shardedCompress, describeShards } from './sharded-compressor';
export type { ShardOptions } from './sharded-compressor';
export { buildVisualization } from './visualization';
export type { VizNode, VizEdge, VizLayer, TimelineItem, DiffSummary, VisualizationData } from './visualization';

// 底层算法 + 类型（供高级调用方使用）
export { createBlueprint, findComponent, getChildren } from './blueprint';
export { expandToArchitecture, getDependencies, getPathTo } from './architecture';
export { expandToChronicle, calculateSize, getTotalLatency, getTotalTokens } from './chronicle';
export { compress, generateCompressionReport } from './compressor';
export * from './types';

// 双维度编排架构 planner（统一从根入口导出，避免子路径 alias 问题）
export {
  ExecutionPlanner,
  ensureRegistryInitialized,
  getSkillsSummary,
  createDefaultContext,
  createSuccessResult,
  createFailureResult,
  orchestrate,
} from './planner/index.ts';
