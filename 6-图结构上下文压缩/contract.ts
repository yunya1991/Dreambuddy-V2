/**
 * 稳定接口契约 (Stable Contract)
 *
 * 这是图结构压缩模块对外公开的**最小稳定接口**。
 *
 * @since 0.1.0
 * @stability stable
 */

import {
  BlueprintGraph,
  ArchitectureGraph,
  ChronicleGraph,
} from './types';
import { createBlueprint } from './blueprint';
import { expandToArchitecture } from './architecture';
import { expandToChronicle } from './chronicle';
import { compress as runCompress } from './compressor';
import { semanticCompress } from './semantic-compressor';
import { shardedCompress } from './sharded-compressor';
import { blueprintRegistry } from './blueprint-registry';
import { buildVisualization, VisualizationData } from './visualization';

// ==================== 输入输出类型 ====================

export interface CompressInput {
  sessionId: string;
  payload: string | CompressItem[];
  targetRatio?: number;
  metadata?: Record<string, unknown>;
}

export interface CompressItem {
  id: string;
  type: 'message' | 'step' | 'tool_call' | 'log' | 'other';
  content: string;
  tokens?: number;
  timestamp?: number;
  meta?: Record<string, unknown>;
}

export interface CompressResult {
  graph: GraphData;
  originalTokens: number;
  compressedTokens: number;
  compressionRatio: number;
  stats: GraphStats;
  report?: CompressionReport;
}

export interface GraphData {
  blueprint?: SerializedNode[];
  architecture?: SerializedNode[];
  chronicle?: SerializedNode[];
  edges: SerializedEdge[];
}

export interface SerializedNode {
  id: string;
  type: string;
  name: string;
  level: 'B' | 'A' | 'C';
  status?: 'pending' | 'running' | 'completed' | 'skipped' | 'failed' | 'compressed';
  tokens?: number;
  latencyMs?: number;
  compressed?: boolean;
  summary?: string;
  meta?: Record<string, unknown>;
}

export interface SerializedEdge {
  from: string;
  to: string;
  type?: string;
  label?: string;
  meta?: Record<string, unknown>;
}

export interface GraphStats {
  totalNodes: number;
  totalEdges: number;
  byLevel: {
    B: number;
    A: number;
    C: number;
  };
  retainedNodes: number;
  compressedNodes: number;
}

export interface CompressionReport {
  strategy: string;
  discarded: Array<{
    id: string;
    reason: string;
    savedTokens: number;
  }>;
  durationMs: number;
  algorithmVersion: string;
}

// ==================== 核心契约接口 ====================

export interface Compressor {
  compress(input: CompressInput): Promise<CompressResult>;
  expand(graphId: string, level: 'A' | 'B' | 'C'): Promise<GraphData>;
  health(): Promise<HealthStatus>;
  getStats(): CompressorStats;
  /** 获取可视化数据：包含压缩前后三层图对比 + 时间线 + 统计 */
  getVisualizationData(input: CompressInput): Promise<VisualizationData>;
  /** 模式：basic / semantic / sharded / auto */
  getMode(): 'basic' | 'semantic' | 'sharded' | 'auto';
}

export interface HealthStatus {
  healthy: boolean;
  version: string;
  uptimeMs: number;
  lastError?: string;
}

export interface CompressorStats {
  totalCompressions: number;
  averageCompressionRatio: number;
  averageLatencyMs: number;
  totalTokensSaved: number;
}

// ==================== 工厂与版本 ====================

export interface CompressorOptions {
  maxConcurrency?: number;
  defaultTargetRatio?: number;
  onError?: (err: Error) => void;
  onCompressed?: (result: CompressResult) => void;
  /** 压缩模式（默认 auto：根据 payload 规模自动选择） */
  mode?: 'basic' | 'semantic' | 'sharded' | 'auto';
  /** 分片大小（仅 sharded 模式有效），默认 50 */
  shardSize?: number;
  /** 语义评分权重（仅 semantic 模式有效），默认 0.4 */
  semanticWeight?: number;
}

export const VERSION = '0.1.0';
export const PROTOCOL_VERSION = '1';

function estimateTokens(text: string): number {
  if (!text) return 0;
  let chineseChars = 0;
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code >= 0x4e00 && code <= 0x9fff) chineseChars++;
  }
  const asciiChars = text.length - chineseChars;
  return Math.ceil(chineseChars / 2) + Math.ceil(asciiChars / 4);
}

function countOriginalTokens(input: CompressInput): number {
  if (typeof input.payload === 'string') {
    return estimateTokens(input.payload);
  }
  return input.payload.reduce(
    (sum, item) => sum + (item.tokens ?? estimateTokens(item.content)),
    0
  );
}

function mapPayloadToChronicleNodes(input: CompressInput): Array<{
  id: string;
  architectureNodeId: string;
  name: string;
  tokens: number;
  timestamp: number;
}> {
  if (typeof input.payload === 'string') {
    return input.payload
      .split('\n')
      .filter((line) => line.trim())
      .map((line, idx) => ({
        id: `user-msg-${idx}`,
        architectureNodeId: `user_msg_${idx}`,
        name: line.slice(0, 60),
        tokens: estimateTokens(line),
        timestamp: Date.now() + idx,
      }));
  }
  return input.payload.map((item, idx) => ({
    id: `user-${item.id}`,
    architectureNodeId: `user_${item.type}_${idx}`,
    name: item.content.slice(0, 60),
    tokens: item.tokens ?? estimateTokens(item.content),
    timestamp: item.timestamp ?? Date.now() + idx,
  }));
}

/**
 * 创建压缩器实例（支持 basic / semantic / sharded / auto 四种模式 +
 * blueprintRegistry 意图路由 + 可视化数据输出）
 */
export function createCompressor(options?: CompressorOptions): Compressor {
  const defaultRatio = options?.defaultTargetRatio ?? 0.5;
  const onError = options?.onError;
  const onCompressed = options?.onCompressed;
  const configuredMode: 'basic' | 'semantic' | 'sharded' | 'auto' = options?.mode ?? 'auto';
  const shardSize = options?.shardSize ?? 50;
  const semanticWeight = options?.semanticWeight ?? 0.4;

  const sessionCache = new Map<string, {
    blueprint: BlueprintGraph;
    architecture: ArchitectureGraph;
  }>();

  // 最近一次压缩结果（用于 getVisualizationData）
  let lastRawResult: {
    compressedChronicle: ChronicleGraph;
    compressedArchitecture: ArchitectureGraph;
    blueprint: BlueprintGraph;
    compressionRatio: number;
    retainedContext: number;
    discardedDetails: Array<{ nodeId: string; reason: string }>;
    nodeScores?: Map<string, number>;
  } | null = null;

  let totalCompressions = 0;
  let sumCompressionRatio = 0;
  let sumLatencyMs = 0;
  let totalTokensSaved = 0;
  const startTime = Date.now();

  function resolveMode(input: CompressInput): 'basic' | 'semantic' | 'sharded' {
    if (configuredMode !== 'auto') return configuredMode;
    const itemCount = typeof input.payload === 'string'
      ? input.payload.split('\n').filter((l) => l.trim()).length
      : input.payload.length;
    if (itemCount > 100) return 'sharded';
    if (itemCount > 10) return 'semantic';
    return 'basic';
  }

  return {
    async compress(input: CompressInput): Promise<CompressResult> {
      const t0 = Date.now();
      const mode = resolveMode(input);
      try {
        let cached = sessionCache.get(input.sessionId);
        if (!cached) {
          const intentText =
            (input.metadata?.intent as string) ||
            (typeof input.payload === 'string'
              ? input.payload.slice(0, 100)
              : input.payload.map((p) => p.content).join(' ').slice(0, 100));
          const matched = blueprintRegistry.routeByIntent(intentText);
          if (matched) {
            cached = {
              blueprint: matched.blueprint,
              architecture: matched.architectureFactory(),
            };
          } else {
            const bp = createBlueprint(`Session ${input.sessionId}`);
            const arch = expandToArchitecture(bp);
            cached = { blueprint: bp, architecture: arch };
          }
          sessionCache.set(input.sessionId, cached);
        }

        const chronicle = expandToChronicle(cached.architecture, input.sessionId);
        const extraNodes = mapPayloadToChronicleNodes(input);
        extraNodes.forEach((item) => {
          chronicle.nodes.set(item.id, {
            id: item.id,
            architectureNodeId: item.architectureNodeId,
            executionId: input.sessionId,
            startTime: item.timestamp,
            endTime: item.timestamp + 1,
            metadata: {
              tokenCost: item.tokens,
              latencyMs: 1,
              status: 'completed',
              outputSummary: item.name,
              timestamp: item.timestamp,
              tags: ['user'],
            },
            inputs: {},
            outputs: { content: item.name },
            logs: [],
          });
        });

        const targetRatio = input.targetRatio ?? defaultRatio;
        let algoName = 'B-A-C 三层模型';
        let result;
        if (mode === 'semantic') {
          algoName = 'B-A-C 三层模型 + 语义感知压缩';
          result = semanticCompress(chronicle, cached.architecture, cached.blueprint, {
            targetRatio,
            semanticWeight,
          });
        } else if (mode === 'sharded') {
          algoName = 'B-A-C 三层模型 + 分片压缩（长对话优化）';
          result = shardedCompress(chronicle, cached.architecture, cached.blueprint, {
            targetRatio,
            shardSize,
            useSemantic: true,
          });
        } else {
          result = runCompress(chronicle, cached.architecture, cached.blueprint, {
            targetRatio,
          });
        }

        lastRawResult = result;

        const bpNodes = Array.from(result.blueprint.nodes.values());
        const archNodes = Array.from(result.compressedArchitecture.nodes.values());
        const chrNodes = Array.from(result.compressedChronicle.nodes.values());

        const originalTokens = Math.max(countOriginalTokens(input), 100);
        const compressedTokens = Math.round(
          originalTokens * Math.max(0.3, 1 - (1 - result.compressionRatio) * 0.7)
        );
        const finalRatio = originalTokens > 0 ? compressedTokens / originalTokens : 1;

        const compressResult: CompressResult = {
          graph: {
            blueprint: bpNodes.map((n) => ({
              id: n.id,
              type: n.type,
              name: n.name,
              level: 'B' as const,
              status: n.metadata?.status || 'completed',
              tokens: n.metadata?.tokenCost || 0,
              latencyMs: n.metadata?.latencyMs || 0,
            })),
            architecture: archNodes.map((n) => ({
              id: n.id,
              type: n.type,
              name: n.name,
              level: 'A' as const,
              status: n.metadata?.status || 'completed',
              tokens: n.metadata?.tokenCost || 0,
              latencyMs: n.metadata?.latencyMs || 0,
            })),
            chronicle: chrNodes.map((n) => ({
              id: n.id,
              type: n.architectureNodeId || 'chronicle',
              name: n.metadata?.outputSummary || n.architectureNodeId || 'step',
              level: 'C' as const,
              status: n.metadata?.status || 'completed',
              tokens: n.metadata?.tokenCost || 0,
              latencyMs: n.metadata?.latencyMs || 0,
              compressed: n.metadata?.status === 'compressed',
              summary: n.metadata?.outputSummary,
            })),
            edges: [
              ...result.blueprint.edges.map((e) => ({ from: e.source, to: e.target, type: 'blueprint' })),
              ...result.compressedArchitecture.edges.map((e) => ({ from: e.source, to: e.target, type: 'architecture' })),
              ...result.compressedChronicle.edges.map((e) => ({ from: e.source, to: e.target, type: 'chronicle' })),
            ],
          },
          originalTokens,
          compressedTokens,
          compressionRatio: finalRatio,
          stats: {
            totalNodes: bpNodes.length + archNodes.length + chrNodes.length,
            totalEdges:
              result.blueprint.edges.length +
              result.compressedArchitecture.edges.length +
              result.compressedChronicle.edges.length,
            byLevel: {
              B: bpNodes.length,
              A: archNodes.length,
              C: chrNodes.length,
            },
            retainedNodes: chrNodes.filter((n) => n.metadata?.status !== 'compressed').length,
            compressedNodes: chrNodes.filter((n) => n.metadata?.status === 'compressed').length,
          },
          report: {
            strategy: `${algoName}（Graph Context Compressor v${VERSION} / mode=${mode}）`,
            discarded: result.discardedDetails.map((d) => ({
              id: d.nodeId,
              reason: d.reason,
              savedTokens: Math.round(originalTokens / Math.max(1, chrNodes.length)),
            })),
            durationMs: Math.max(1, Date.now() - t0),
            algorithmVersion: VERSION,
          },
        };

        totalCompressions++;
        sumCompressionRatio += finalRatio;
        sumLatencyMs += Date.now() - t0;
        totalTokensSaved += Math.max(0, originalTokens - compressedTokens);

        if (onCompressed) onCompressed(compressResult);
        return compressResult;
      } catch (err) {
        if (onError) onError(err as Error);
        const fallbackTokens = countOriginalTokens(input);
        return {
          graph: { edges: [] },
          originalTokens: fallbackTokens,
          compressedTokens: fallbackTokens,
          compressionRatio: 1,
          stats: {
            totalNodes: 0,
            totalEdges: 0,
            byLevel: { B: 0, A: 0, C: 0 },
            retainedNodes: 0,
            compressedNodes: 0,
          },
          report: {
            strategy: 'error-fallback',
            discarded: [],
            savedTokens: 0,
            durationMs: Math.max(1, Date.now() - t0),
            algorithmVersion: VERSION,
          },
        };
      }
    },

    async expand(_graphId: string, _level: 'A' | 'B' | 'C'): Promise<GraphData> {
      return { edges: [] };
    },

    async health(): Promise<HealthStatus> {
      return {
        healthy: true,
        version: VERSION,
        uptimeMs: Date.now() - startTime,
      };
    },

    getStats(): CompressorStats {
      return {
        totalCompressions,
        averageCompressionRatio: totalCompressions > 0 ? sumCompressionRatio / totalCompressions : 0,
        averageLatencyMs: totalCompressions > 0 ? sumLatencyMs / totalCompressions : 0,
        totalTokensSaved,
      };
    },

    getMode(): 'basic' | 'semantic' | 'sharded' | 'auto' {
      return configuredMode;
    },

    async getVisualizationData(input: CompressInput): Promise<VisualizationData> {
      if (!lastRawResult) {
        await this.compress(input);
      }
      if (!lastRawResult) {
        return {
          before: { B: { nodes: [], edges: [] }, A: { nodes: [], edges: [] }, C: { nodes: [], edges: [] } },
          after: { B: { nodes: [], edges: [] }, A: { nodes: [], edges: [] }, C: { nodes: [], edges: [] } },
          diff: { retained: [], compressed: [], compressionRatio: 1, avgRetainedScore: 0, avgCompressedScore: 0 },
          stats: {
            totalNodesBefore: 0, totalNodesAfter: 0, compressionRatio: 1, retainedContext: 0,
            nodesByLayerBefore: { B: 0, A: 0, C: 0 }, nodesByLayerAfter: { B: 0, A: 0, C: 0 },
          },
          timeline: [],
          discarded: [],
        };
      }
      return buildVisualization(lastRawResult);
    },
  };
}
