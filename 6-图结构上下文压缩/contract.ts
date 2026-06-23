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
} from './models';
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

// ==================== 笔记本类型 ====================

/** 笔记条目（短线任务便签，映射到 A/C 层节点） */
export interface NoteEntry {
  id: string;
  title: string;
  content: string;
  /** 所属意图目标 ID */
  intentGoalId?: string;
  /** OKR 层级：mid=执行计划, short=当步任务 */
  horizon: 'mid' | 'short';
  status: 'active' | 'done' | 'archived';
  createdAt: number;
  updatedAt: number;
  /** 关联的 CompressItem ID（写入图结构的节点） */
  linkedNodeId?: string;
}

/** 笔记本视图（OKR 全景） */
export interface NotebookView {
  /** 当前长期目标 */
  longTermObjective: string;
  /** 当前意图 */
  intent: string;
  /** 中期计划（A 层步骤摘要） */
  midTermTasks: Array<{ id: string; name: string; status: string; confidence?: number }>;
  /** 短期记录（C 层最近执行） */
  shortTermLog: Array<{ id: string; summary: string; timestamp: number; kept: boolean }>;
  /** 活跃便签 */
  notes: NoteEntry[];
  /** OKR 摘要文本（供 LLM 注入） */
  okrSummary: string;
}

export interface Compressor {
  compress(input: CompressInput): Promise<CompressResult>;
  expand(graphId: string, level: 'A' | 'B' | 'C'): Promise<GraphData>;
  health(): Promise<HealthStatus>;
  getStats(): CompressorStats;
  /** 获取可视化数据：包含压缩前后三层图对比 + 时间线 + 统计 */
  getVisualizationData(input: CompressInput): Promise<VisualizationData>;
  /** 模式：basic / semantic / sharded / auto */
  getMode(): 'basic' | 'semantic' | 'sharded' | 'auto';
  /**
   * 意图识别入口（用户发出消息后的第一步）
   *
   * 返回两种状态：
   *   state='confirmed' → 意图已确认，可继续 Planner 调度
   *   state='clarifying' → 置信度不足，clarifyQuestion 包含需要追问用户的问题
   */
  recognizeIntent(
    userMessage: string,
    sessionId: string,
    previousMessages?: Array<{ role: string; content: string }>
  ): IntentRecognitionResult;
  /**
   * 接收用户对澄清问题的回答，重新推断并锁定意图（仅在 state='clarifying' 后调用）
   *
   * @param answer 用户自然语言回答
   * @param sessionId 会话 ID
   * @param selectedIntentId 若前端提供了明确选项，直接传 intentId（优先级最高）
   */
  clarifyIntent(
    answer: string,
    sessionId: string,
    selectedIntentId?: string
  ): IntentRecognitionResult;
  /**
   * 获取笔记本视图（OKR 全景：长中短目标 + 便签）
   */
  getNotebookView(sessionId: string): NotebookView;
  /**
   * 添加便签（短线任务）
   */
  addNote(sessionId: string, note: Omit<NoteEntry, 'id' | 'createdAt' | 'updatedAt'>): NoteEntry;
}

// ── 意图识别结果类型（对外暴露 v2 网关的状态） ────────────────

export interface IntentClarifyQuestion {
  question: string;
  options?: Array<{ label: string; intentId: string }>;
  hint?: string;
}

export interface IntentCandidate {
  id: string;
  name: string;
  confidence: number;
}

export interface IntentRecognitionResult {
  /** 'confirmed' = 意图已确认可继续；'clarifying' = 需要追问用户 */
  state: 'confirmed' | 'clarifying' | 'detecting';
  intent: string;
  intentName: string;
  objective: string;
  isNewIntent: boolean;
  /** 置信度 0-1 */
  confidence: number;
  /** 是否经过用户澄清确认 */
  clarified: boolean;
  okrSummary: string;
  /** 追问问题（state='clarifying' 时才有） */
  clarifyQuestion?: IntentClarifyQuestion;
  /** 候选意图列表（state='clarifying' 时辅助展示） */
  candidates?: IntentCandidate[];
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

// ==================== 意图网关导入 ====================
import { getIntentGateway } from './intent-gateway.ts';
import type { IntentGatewayResult, IntentGateway as IGateway } from './intent-gateway.ts';

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

// ── 辅助：把 IntentGatewayResult 转为对外接口 IntentRecognitionResult ──
function buildIntentResult(
  r: IntentGatewayResult,
  gateway: IGateway
): IntentRecognitionResult {
  return {
    state: r.state,
    intent: r.goal.intent,
    intentName: (r.goal as any).name ?? r.goal.intent,
    objective: r.goal.objective,
    isNewIntent: r.isNewIntent,
    confidence: r.goal.confidence,
    clarified: r.goal.clarified ?? false,
    okrSummary: gateway.getOKRSummary(),
    clarifyQuestion: r.clarifyQuestion
      ? { question: r.clarifyQuestion.question, options: r.clarifyQuestion.options, hint: r.clarifyQuestion.hint }
      : undefined,
    candidates: r.candidates?.map(c => ({ id: c.id, name: c.name, confidence: c.confidence })),
  };
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

        type BN = import('./models').BNode;
        type AN = import('./models').ANode;
        type CN = import('./models').CNode;
        type AE = import('./models').AEdge;
        const bpNodes = Array.from(result.blueprint.nodes.values()) as BN[];
        const archNodes = Array.from(result.compressedArchitecture.nodes.values()) as AN[];
        const chrNodes = Array.from(result.compressedChronicle.nodes.values()) as CN[];

        const originalTokens = Math.max(countOriginalTokens(input), 100);
        const compressedTokens = Math.round(
          originalTokens * Math.max(0.3, 1 - (1 - result.compressionRatio) * 0.7)
        );
        const finalRatio = originalTokens > 0 ? compressedTokens / originalTokens : 1;

        const compressResult: CompressResult = {
          graph: {
            blueprint: bpNodes.map((n: BN) => ({
              id: n.id,
              type: n.type,
              name: n.name,
              level: 'B' as const,
              status: n.metadata?.status || 'completed',
              tokens: n.metadata?.tokenCost || 0,
              latencyMs: n.metadata?.latencyMs || 0,
            })),
            architecture: archNodes.map((n: AN) => ({
              id: n.id,
              type: n.type,
              name: n.name,
              level: 'A' as const,
              status: n.metadata?.status || 'completed',
              tokens: n.metadata?.tokenCost || 0,
              latencyMs: n.metadata?.latencyMs || 0,
            })),
            chronicle: chrNodes.map((n: CN) => ({
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
              ...result.blueprint.edges.map((e: AE) => ({ from: e.source, to: e.target, type: 'blueprint' })),
              ...result.compressedArchitecture.edges.map((e: AE) => ({ from: e.source, to: e.target, type: 'architecture' })),
              ...result.compressedChronicle.edges.map((e: AE) => ({ from: e.source, to: e.target, type: 'chronicle' })),
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
            discarded: result.discardedDetails.map((d: { nodeId: string; reason: string }) => ({
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

    // ── 意图识别网关 (v2：支持 confirmed / clarifying 两态) ───
    recognizeIntent(
      userMessage: string,
      sessionId: string,
      previousMessages: Array<{ role: string; content: string }> = []
    ): IntentRecognitionResult {
      const gateway = getIntentGateway(sessionId);
      const r = gateway.process(userMessage, previousMessages);
      intentBlueprintItems.set(sessionId, r.blueprintItem);
      return buildIntentResult(r, gateway);
    },

    // ── 澄清确认（clarifying → confirmed）────────────────────
    clarifyIntent(
      answer: string,
      sessionId: string,
      selectedIntentId?: string
    ): IntentRecognitionResult {
      const gateway = getIntentGateway(sessionId);
      const r = gateway.clarify(answer, selectedIntentId);
      intentBlueprintItems.set(sessionId, r.blueprintItem);
      return buildIntentResult(r, gateway);
    },

    // ── 笔记本视图 ────────────────────────────────────────────
    getNotebookView(sessionId: string): NotebookView {
      const gateway = getIntentGateway(sessionId);
      const goal = gateway.getCurrentGoal();
      const notes = notebookNotes.get(sessionId) ?? [];
      const lastResult = lastRawResult;

      const midTermTasks = lastResult
        ? Array.from(lastResult.compressedArchitecture.nodes.values()).slice(0, 8).map((n: any) => ({
            id: n.id,
            name: n.name,
            status: n.metadata?.status ?? 'pending',
            confidence: undefined,
          }))
        : [];

      const shortTermLog = lastResult
        ? Array.from(lastResult.compressedChronicle.nodes.values()).slice(-10).map((n: any) => ({
            id: n.id,
            summary: n.metadata?.outputSummary ?? n.architectureNodeId ?? n.id,
            timestamp: n.startTime ?? Date.now(),
            kept: n.metadata?.status !== 'compressed',
          }))
        : [];

      const okrSummary = goal
        ? `【长期目标】${goal.objective}\n【已完成轮次】${goal.completedRounds}\n【活跃便签】${notes.filter(n => n.status === 'active').length} 条`
        : '（未识别到意图目标）';

      return {
        longTermObjective: goal?.objective ?? '（未设置）',
        intent: goal?.intent ?? 'general',
        midTermTasks,
        shortTermLog,
        notes,
        okrSummary,
      };
    },

    // ── 添加便签（短线任务） ───────────────────────────────────
    addNote(sessionId: string, note: Omit<NoteEntry, 'id' | 'createdAt' | 'updatedAt'>): NoteEntry {
      const id = `note_${sessionId}_${Date.now()}`;
      const now = Date.now();
      const entry: NoteEntry = { ...note, id, createdAt: now, updatedAt: now };
      const list = notebookNotes.get(sessionId) ?? [];
      list.push(entry);
      notebookNotes.set(sessionId, list);
      return entry;
    },
  };
}

// 模块级缓存：意图 B 层节点 + 笔记本便签
const intentBlueprintItems = new Map<string, CompressItem>();
const notebookNotes = new Map<string, NoteEntry[]>();
