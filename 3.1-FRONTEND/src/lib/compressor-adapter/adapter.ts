/**
 * Compressor Adapter — 核心适配器
 *
 * 直接引用通用模块 `@yunya/graph-context-compressor`（对应 `6-图结构上下文压缩/`）。
 * 设计原则：
 * - 启动时初始化通用模块实例，失败则降级到文本摘要
 * - 运行时崩溃则自动降级，不影响主流程
 * - 所有操作都有兜底，不会抛出异常
 *
 * @stability stable
 */

import type {
  CompressInput,
  CompressResult,
  GraphData,
  InferenceResult,
  SessionData,
  SessionMeta,
  VisualizationData,
} from './types';
import { createFallbackResult, estimateTokens } from './fallback';
import {
  createCompressor,
  VERSION as MODULE_VERSION,
  PROTOCOL_VERSION,
} from '../../../../../6-图结构上下文压缩/index';
import type {
  CompressInput,
  CompressResult,
  Compressor,
  CompressorOptions,
  CompressorStats,
  HealthStatus,
  VisualizationData,
} from '../../../../../6-图结构上下文压缩/index';

// 注意：上面的 `createCompressor` 返回的是通用模块的 `Compressor` 类型，
// 它和我们 adapter 中使用的 `CompressInput / CompressResult` 结构一致，
// 但为了严格类型，这里做一个类型兼容的实例包装。

// ==================== Graph-aware 压缩：轻量节点类型 ====================
interface GraphNodeLite {
  id: string;
  confidence?: number;
  riskScore?: number;
  issuesFound?: string[];
  corrections?: string[];
  tokenCost?: number;
}
interface GraphStateLite {
  sessionId: string;
  architectureNodes: Map<string, GraphNodeLite> | Iterable<[string, GraphNodeLite]>;
  compressionSignal: {
    highValueNodes: string[];
    compressibleNodes: string[];
  };
}

// ==================== 通用模块实例 ====================
interface GraphCompressorRef {
  version: string;
  protocolVersion: string;
  compress(input: CompressInput): Promise<CompressResult>;
  expand(graphId: string, level: 'A' | 'B' | 'C'): Promise<GraphData>;
  health(): Promise<{ healthy: boolean; version: string; uptimeMs: number; lastError?: string }>;
  getStats(): {
    totalCompressions: number;
    averageCompressionRatio: number;
    averageLatencyMs: number;
    totalTokensSaved: number;
  };
  getVisualizationData(input: CompressInput): Promise<VisualizationData>;
  getMode(): 'basic' | 'semantic' | 'sharded' | 'auto';
  analyzeFromMessages(messages: any[]): Promise<InferenceResult>;
  saveSession(sessionId: string, sessionData: any): Promise<boolean>;
  loadSession(sessionId: string): Promise<any | null>;
  listSessions(): Promise<string[]>;
  deleteSession(sessionId: string): Promise<boolean>;
}

let _moduleRef: GraphCompressorRef | null = null;
let _moduleLoadError: string | null = null;

function tryLoadGraphModule(): void {
  try {
    const instance = createCompressor({
      defaultTargetRatio: 0.5,
      mode: 'auto',
    });
    _moduleRef = {
      version: MODULE_VERSION as string,
      protocolVersion: PROTOCOL_VERSION as string,
      compress: (input) => instance.compress(input),
      expand: (id, level) => instance.expand(id, level),
      health: () => instance.health(),
      getStats: () => instance.getStats(),
      getVisualizationData: (input) => instance.getVisualizationData(input),
      getMode: () => instance.getMode(),
      analyzeFromMessages: (messages) =>
        typeof (instance as any).analyzeFromMessages === 'function'
          ? (instance as any).analyzeFromMessages(messages)
          : Promise.resolve(createMockInferenceResult(messages)),
      saveSession: (id, data) =>
        typeof (instance as any).saveSession === 'function'
          ? (instance as any).saveSession(id, data)
          : Promise.resolve(persistSaveSession(id, data)),
      loadSession: (id) =>
        typeof (instance as any).loadSession === 'function'
          ? (instance as any).loadSession(id)
          : Promise.resolve(persistLoadSession(id)),
      listSessions: () =>
        typeof (instance as any).listSessions === 'function'
          ? (instance as any).listSessions()
          : Promise.resolve(persistListSessions()),
      deleteSession: (id) =>
        typeof (instance as any).deleteSession === 'function'
          ? (instance as any).deleteSession(id)
          : Promise.resolve(persistDeleteSession(id)),
    };
  } catch (err) {
    _moduleLoadError = (err as Error).message;
  }
}

// 启动时尝试加载
tryLoadGraphModule();

// ==================== mock / 降级 助手 ====================

const SESSION_STORAGE_PREFIX = 'compressor-adapter:session:';
const SESSION_INDEX_KEY = 'compressor-adapter:session-index';

function getStorage(): Storage | null {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null;
  } catch {
    return null;
  }
}

function readSessionIndex(): string[] {
  const storage = getStorage();
  if (!storage) return [];
  try {
    const raw = storage.getItem(SESSION_INDEX_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function writeSessionIndex(ids: string[]): void {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.setItem(SESSION_INDEX_KEY, JSON.stringify(ids));
  } catch {
    // 忽略存储错误
  }
}

function persistSaveSession(sessionId: string, sessionData: any): boolean {
  const storage = getStorage();
  if (!storage) {
    // 无 localStorage 时走内存缓存
    _memorySessions.set(sessionId, sessionData);
    return true;
  }
  try {
    const now = Date.now();
    const existing = persistLoadSession(sessionId);
    const data: SessionData = {
      sessionId,
      title: sessionData.title ?? existing?.title ?? sessionId,
      messages: sessionData.messages ?? existing?.messages ?? [],
      meta: sessionData.meta ?? existing?.meta ?? {},
      graphSnapshot: sessionData.graphSnapshot ?? existing?.graphSnapshot,
      inferenceSnapshot: sessionData.inferenceSnapshot ?? existing?.inferenceSnapshot,
      createdAt: existing?.createdAt ?? now,
      updatedAt: now,
    };
    storage.setItem(SESSION_STORAGE_PREFIX + sessionId, JSON.stringify(data));
    const index = readSessionIndex();
    if (!index.includes(sessionId)) index.unshift(sessionId);
    writeSessionIndex(index);
    return true;
  } catch (err) {
    console.warn('[CompressorAdapter] saveSession 存储失败：', err);
    return false;
  }
}

function persistLoadSession(sessionId: string): SessionData | null {
  const storage = getStorage();
  if (!storage) {
    const mem = _memorySessions.get(sessionId);
    return mem ? (mem as SessionData) : null;
  }
  try {
    const raw = storage.getItem(SESSION_STORAGE_PREFIX + sessionId);
    if (!raw) return null;
    return JSON.parse(raw) as SessionData;
  } catch {
    return null;
  }
}

function persistListSessions(): string[] {
  const storage = getStorage();
  if (!storage) return Array.from(_memorySessions.keys());
  return readSessionIndex();
}

function persistDeleteSession(sessionId: string): boolean {
  const storage = getStorage();
  if (!storage) return _memorySessions.delete(sessionId);
  try {
    storage.removeItem(SESSION_STORAGE_PREFIX + sessionId);
    const index = readSessionIndex().filter((id) => id !== sessionId);
    writeSessionIndex(index);
    return true;
  } catch {
    return false;
  }
}

const _memorySessions = new Map<string, any>();

function createMockInferenceResult(messages: any[], sessionId?: string): InferenceResult {
  const now = Date.now();
  const count = Array.isArray(messages) ? messages.length : 0;
  const tokenEstimate =
    count * 80 +
    (Array.isArray(messages)
      ? messages.reduce(
          (sum, m) =>
            sum +
            estimateTokens(
              typeof m?.content === 'string' ? m.content : JSON.stringify(m ?? '')
            ),
          0
        )
      : 0);

  const nodes = [
    {
      id: 'node-goal-1',
      name: '明确目标',
      type: 'goal' as const,
      description: '从输入中识别的主目标节点',
      weight: 0.9,
      confidence: 0.85,
      sourceMessageIds: count > 0 ? ['msg-0'] : [],
      createdAt: now,
    },
    {
      id: 'node-constraint-1',
      name: '资源约束',
      type: 'constraint' as const,
      description: '识别到的资源/时间/成本约束',
      weight: 0.75,
      confidence: 0.7,
      sourceMessageIds: count > 1 ? ['msg-1'] : [],
      createdAt: now,
    },
    {
      id: 'node-action-1',
      name: '执行动作',
      type: 'action' as const,
      description: '可执行的操作节点',
      weight: 0.7,
      confidence: 0.65,
      sourceMessageIds: count > 2 ? ['msg-2'] : [],
      createdAt: now,
    },
  ];

  const conflicts =
    count >= 3
      ? [
          {
            id: 'conflict-1',
            type: 'inconsistency' as const,
            severity: 'medium' as const,
            description: '检测到前后表述存在轻微不一致',
            involvedNodes: ['node-goal-1', 'node-action-1'],
            suggestion: '请确认目标与执行动作的一致性',
            detectedAt: now,
          },
        ]
      : [];

  const riskScore = Math.min(1, 0.2 + conflicts.length * 0.25 + (count === 0 ? 0.15 : 0));
  const riskLevel: 'low' | 'medium' | 'high' | 'critical' =
    riskScore < 0.3 ? 'low' : riskScore < 0.55 ? 'medium' : riskScore < 0.8 ? 'high' : 'critical';

  return {
    sessionId: sessionId ?? 'local-session',
    analyzedAt: now,
    keyDecisionNodes: nodes,
    keyReasoningPaths: [
      {
        id: 'path-1',
        name: '主推理路径',
        nodeIds: nodes.map((n) => n.id),
        rationale: '基于对话目标与约束的主路径',
        confidence: 0.8,
        priority: 'high',
      },
    ],
    conflicts,
    riskScore,
    riskLevel,
    nextSteps: [
      {
        id: 'next-1',
        title: '明确关键约束',
        description: '补充约束条件以降低不确定性',
        action: 'ask-clarify',
        priority: riskScore > 0.5 ? 'high' : 'medium',
        estimatedTokens: 120,
      },
      {
        id: 'next-2',
        title: '验证执行路径',
        description: '对主推理路径做一次校验',
        action: 'validate',
        priority: 'medium',
      },
    ],
    summary:
      count === 0
        ? '当前会话为空，建议提供初始输入以生成推理分析。'
        : `已分析 ${count} 条消息，识别 ${nodes.length} 个关键节点，${conflicts.length} 个冲突，风险等级 ${riskLevel.toUpperCase()}。`,
    metadata: {
      messageCount: count,
      inferenceTokens: tokenEstimate,
      analysisDurationMs: Math.max(1, Date.now() - now),
      mode: 'fallback',
    },
  };
}

// ==================== Adapter ====================

export interface AdapterHealth {
  healthy: boolean;
  mode: 'graph' | 'fallback' | 'disabled';
  graphCompressorVersion?: string;
  lastError?: string;
  uptimeMs: number;
}

export interface AdapterStats {
  totalCompressions: number;
  graphCompressions: number;
  fallbackCompressions: number;
  averageCompressionRatio: number;
  averageLatencyMs: number;
  totalTokensSaved: number;
}

export interface AdapterConfig {
  enabled: boolean;
  fallbackStrategy: 'text-summarize' | 'pass-through' | 'error';
  initTimeoutMs?: number;
  defaultTargetRatio?: number;
  minTokensForCompression?: number;
}

export class CompressorAdapter {
  private config: AdapterConfig;
  private mode: 'graph' | 'fallback' | 'disabled' = 'fallback';
  private healthy = false;
  private lastError: string | undefined;
  private startTime = Date.now();
  private stats: AdapterStats = {
    totalCompressions: 0,
    graphCompressions: 0,
    fallbackCompressions: 0,
    averageCompressionRatio: 0,
    averageLatencyMs: 0,
    totalTokensSaved: 0,
  };

  constructor(config?: Partial<AdapterConfig>) {
    this.config = {
      enabled: config?.enabled !== false,
      fallbackStrategy: config?.fallbackStrategy || 'text-summarize',
      initTimeoutMs: config?.initTimeoutMs || 5000,
      defaultTargetRatio: config?.defaultTargetRatio || 0.5,
      minTokensForCompression: config?.minTokensForCompression || 200,
    };
  }

  // ==================== 初始化 ====================
  async initialize(): Promise<void> {
    if (!this.config.enabled) {
      this.mode = 'disabled';
      this.healthy = false;
      console.log('[CompressorAdapter] DISABLED via config');
      return;
    }

    try {
      if (!_moduleRef) {
        this.degrade('fallback', new Error(_moduleLoadError || '模块加载失败'));
        return;
      }

      const timeout = this.config.initTimeoutMs ?? 5000;
      const health = await Promise.race([
        _moduleRef.health(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('健康检查超时')), timeout)
        ),
      ]);

      if (!health.healthy) {
        this.degrade('fallback', new Error(health.lastError || '健康检查失败'));
        return;
      }

      if (_moduleRef.protocolVersion !== '1') {
        console.warn(
          `[CompressorAdapter] 协议版本不匹配: expected=1, got=${_moduleRef.protocolVersion}`
        );
      }

      this.mode = 'graph';
      this.healthy = true;
      console.log(
        `[CompressorAdapter] INITIALIZED (graph mode) v${_moduleRef.version}`
      );
    } catch (err) {
      this.degrade('fallback', err as Error);
    }
  }

  // ==================== 核心 API ====================

  async compress(input: CompressInput): Promise<CompressResult> {
    const start = Date.now();

    // 小输入不压缩，直接透传
    const tokens =
      typeof input.payload === 'string'
        ? estimateTokens(input.payload)
        : input.payload.reduce(
            (sum, item) => sum + (item.tokens ?? estimateTokens(item.content)),
            0
          );

    if (tokens < (this.config.minTokensForCompression ?? 200)) {
      return this.passThroughResult(input, tokens);
    }

    if (this.mode === 'fallback') {
      return this.executeFallback(input, tokens, start);
    }

    if (this.mode === 'disabled') {
      return this.passThroughResult(input, tokens);
    }

    // graph 模式
    try {
      if (!_moduleRef) throw new Error('模块未初始化');
      const result = await _moduleRef.compress(input);
      this.recordStats(result, Date.now() - start, true);
      return result;
    } catch (err) {
      console.warn('[CompressorAdapter] 图压缩模块调用失败，降级', err);
      this.healthy = false;
      this.lastError = (err as Error).message;
      return this.executeFallback(input, tokens, start);
    }
  }

  /**
   * Graph-aware 压缩：直接从 graph-reflection-bridge 的节点状态生成压缩结果。
   * 节点 metadata（confidence / riskScore / issuesFound）驱动 highValueNodes / compressibleNodes。
   */
  compressFromGraphState(graphState: GraphStateLite): CompressResult {
    const start = Date.now();
    const highValueIds = new Set(graphState.compressionSignal.highValueNodes);
    const compressibleIds = new Set(graphState.compressionSignal.compressibleNodes);

    const architectureNodesList: [string, GraphNodeLite][] =
      graphState.architectureNodes instanceof Map
        ? Array.from(graphState.architectureNodes.entries())
        : Array.from(graphState.architectureNodes);

    let originalTokens = 0;
    let compressedTokens = 0;

    const nodes = architectureNodesList.map(([id, node]) => {
      const isHighValue = highValueIds.has(id);
      const isCompressible = compressibleIds.has(id);
      const nodeTokens = node.tokenCost ?? Math.max(50, id.length * 30);
      const retainedTokens = isCompressible
        ? Math.max(10, Math.floor(nodeTokens * 0.3))
        : nodeTokens;

      originalTokens += nodeTokens;
      compressedTokens += retainedTokens;

      return {
        id,
        type: `step:${id}`,
        name: id,
        level: 'A' as const,
        tokens: retainedTokens,
        compressed: isCompressible,
        meta: {
          confidence: node.confidence,
          risk: node.riskScore,
          hasIssues: (node.issuesFound?.length ?? 0) > 0,
          hasCorrections: (node.corrections?.length ?? 0) > 0,
          signal: isHighValue ? 'high-value' : isCompressible ? 'compressible' : 'retained',
        },
      };
    });

    const edges = nodes.slice(1).map((n, i) => ({
      from: nodes[i].id,
      to: n.id,
      type: 'follows',
    }));

    const ratio = originalTokens > 0 ? compressedTokens / originalTokens : 1;
    const result: CompressResult = {
      graph: {
        architecture: nodes,
        edges,
      } as GraphData,
      originalTokens,
      compressedTokens,
      compressionRatio: ratio,
      stats: {
        totalNodes: nodes.length,
        totalEdges: edges.length,
        byLevel: { B: 0, A: nodes.length, C: 0 },
        retainedNodes: nodes.filter((n) => !n.compressed).length,
        compressedNodes: nodes.filter((n) => n.compressed).length,
      },
      report: {
        strategy: 'graph-reflection-aware',
        discarded: nodes
          .filter((n) => n.compressed)
          .map((n) => ({
            id: n.id,
            reason: (n.meta as any)?.signal ?? 'compressible',
            savedTokens: (n.tokens ?? 0) - Math.max(10, Math.floor((n.tokens ?? 50) * 0.3)),
          })),
        durationMs: Math.max(1, Date.now() - start),
        algorithmVersion: 'graph-reflection-v1',
      },
    };

    this.stats.totalCompressions++;
    this.stats.fallbackCompressions++;
    const n = this.stats.totalCompressions;
    this.stats.averageCompressionRatio =
      (this.stats.averageCompressionRatio * (n - 1) + ratio) / n;
    this.stats.averageLatencyMs =
      (this.stats.averageLatencyMs * (n - 1) + (Date.now() - start)) / n;
    this.stats.totalTokensSaved += originalTokens - compressedTokens;

    return result;
  }

  health(): AdapterHealth {
    return {
      healthy: this.healthy,
      mode: this.mode,
      graphCompressorVersion: _moduleRef?.version,
      lastError: this.lastError,
      uptimeMs: Date.now() - this.startTime,
    };
  }

  getStats(): AdapterStats {
    return { ...this.stats };
  }

  /** 获取可视化数据：包含压缩前后三层图对比 + 时间线 + 统计 */
  async getVisualizationData(input: CompressInput): Promise<VisualizationData> {
    if (!this.config.enabled && this.mode === 'fallback') {
      return {
        before: {
          B: { nodes: [], edges: [] }, A: { nodes: [], edges: [] }, C: { nodes: [], edges: [] },
        },
        after: {
          B: { nodes: [], edges: [] }, A: { nodes: [], edges: [] }, C: { nodes: [], edges: [] },
        },
        diff: { retained: [], compressed: [], compressionRatio: 1, avgRetainedScore: 0, avgCompressedScore: 0 },
        stats: {
          totalNodesBefore: 0, totalNodesAfter: 0, compressionRatio: 1, retainedContext: 0,
          nodesByLayerBefore: { B: 0, A: 0, C: 0 }, nodesByLayerAfter: { B: 0, A: 0, C: 0 },
        },
        timeline: [],
        discarded: [],
      };
    }
    try {
      if (!_moduleRef) throw new Error('模块未初始化');
      return await _moduleRef.getVisualizationData(input);
    } catch (err) {
      console.warn('[CompressorAdapter] getVisualizationData 失败：', err);
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
  }

  /** 返回当前压缩器模式（basic / semantic / sharded / auto） */
  getMode(): 'graph' | 'fallback' | 'disabled' | 'basic' | 'semantic' | 'sharded' | 'auto' {
    if (this.mode !== 'graph') return this.mode;
    return _moduleRef?.getMode() || 'auto';
  }

  // ==================== 推理引擎 API ====================

  /**
   * analyzeFromMessages — 从消息列表生成推理分析结果。
   * 返回：关键决策节点、关键推理路径、冲突检测、风险评分、下一步建议。
   * graph 模式优先调用通用模块实现；模块未实现则降级到本地 mock。
   */
  async analyzeFromMessages(messages: any[]): Promise<InferenceResult> {
    const start = Date.now();
    if (this.mode === 'disabled') {
      return createMockInferenceResult(messages, 'disabled-session');
    }
    try {
      if (!_moduleRef) return createMockInferenceResult(messages, 'fallback-session');
      const result = await _moduleRef.analyzeFromMessages(messages);
      return { ...result, metadata: { ...result.metadata, analysisDurationMs: Date.now() - start } };
    } catch (err) {
      console.warn('[CompressorAdapter] analyzeFromMessages 调用失败，降级', err);
      this.lastError = (err as Error).message;
      return createMockInferenceResult(messages, 'fallback-session');
    }
  }

  /** analyzeSession — 使用当前实例会话上下文进行分析（消息通过内部状态）。
   * 当前实现等价于 analyzeFromMessages，但可携带 sessionId。*/
  async analyzeSession(
    sessionId: string,
    messages: any[]
  ): Promise<InferenceResult> {
    const result = await this.analyzeFromMessages(messages);
    return { ...result, sessionId };
  }

  // ==================== 会话持久化 API ====================

  async saveSession(sessionId: string, sessionData: any): Promise<boolean> {
    if (this.mode === 'disabled') return persistSaveSession(sessionId, sessionData);
    try {
      if (!_moduleRef) return persistSaveSession(sessionId, sessionData);
      return await _moduleRef.saveSession(sessionId, sessionData);
    } catch (err) {
      console.warn('[CompressorAdapter] saveSession 调用失败，降级', err);
      this.lastError = (err as Error).message;
      return persistSaveSession(sessionId, sessionData);
    }
  }

  async loadSession(sessionId: string): Promise<SessionData | null> {
    if (this.mode === 'disabled') return persistLoadSession(sessionId);
    try {
      if (!_moduleRef) return persistLoadSession(sessionId);
      return (await _moduleRef.loadSession(sessionId)) as SessionData | null;
    } catch (err) {
      console.warn('[CompressorAdapter] loadSession 调用失败，降级', err);
      this.lastError = (err as Error).message;
      return persistLoadSession(sessionId);
    }
  }

  async listSessions(): Promise<string[]> {
    if (this.mode === 'disabled') return persistListSessions();
    try {
      if (!_moduleRef) return persistListSessions();
      return await _moduleRef.listSessions();
    } catch (err) {
      console.warn('[CompressorAdapter] listSessions 调用失败，降级', err);
      this.lastError = (err as Error).message;
      return persistListSessions();
    }
  }

  async deleteSession(sessionId: string): Promise<boolean> {
    if (this.mode === 'disabled') return persistDeleteSession(sessionId);
    try {
      if (!_moduleRef) return persistDeleteSession(sessionId);
      return await _moduleRef.deleteSession(sessionId);
    } catch (err) {
      console.warn('[CompressorAdapter] deleteSession 调用失败，降级', err);
      this.lastError = (err as Error).message;
      return persistDeleteSession(sessionId);
    }
  }

  /** 列出会话元数据（更完整信息，前端可用于列表显示） */
  async listSessionMetas(): Promise<SessionMeta[]> {
    const ids = await this.listSessions();
    const metas: SessionMeta[] = [];
    for (const id of ids) {
      const data = await this.loadSession(id);
      if (!data) continue;
      metas.push({
        sessionId: data.sessionId,
        title: data.title ?? data.sessionId,
        createdAt: data.createdAt,
        updatedAt: data.updatedAt,
        messageCount: Array.isArray(data.messages) ? data.messages.length : 0,
        tokenEstimate: Array.isArray(data.messages)
          ? data.messages.reduce(
              (sum, m) =>
                sum +
                estimateTokens(typeof m?.content === 'string' ? m.content : JSON.stringify(m ?? '')),
              0
            )
          : 0,
      });
    }
    return metas;
  }

  // ==================== 私有方法 ====================

  private degrade(mode: 'fallback' | 'disabled', err: Error): void {
    this.mode = mode;
    this.healthy = false;
    this.lastError = err.message;
    console.warn(`[CompressorAdapter] DEGRADED to ${mode}: ${err.message}`);
  }

  private executeFallback(
    input: CompressInput,
    originalTokens: number,
    start: number
  ): CompressResult {
    const result = createFallbackResult(
      input,
      originalTokens,
      this.config.defaultTargetRatio ?? 0.5
    );
    this.recordStats(result, Date.now() - start, false);
    return result;
  }

  private passThroughResult(input: CompressInput, tokens: number): CompressResult {
    return {
      graph: { edges: [] },
      originalTokens: tokens,
      compressedTokens: tokens,
      compressionRatio: 1,
      stats: {
        totalNodes: 0,
        totalEdges: 0,
        byLevel: { B: 0, A: 0, C: 0 },
        retainedNodes: 0,
        compressedNodes: 0,
      },
    };
  }

  private recordStats(
    result: CompressResult,
    latencyMs: number,
    isGraph: boolean
  ): void {
    this.stats.totalCompressions++;
    if (isGraph) {
      this.stats.graphCompressions++;
    } else {
      this.stats.fallbackCompressions++;
    }

    const n = this.stats.totalCompressions;
    this.stats.averageCompressionRatio =
      (this.stats.averageCompressionRatio * (n - 1) + result.compressionRatio) / n;
    this.stats.averageLatencyMs =
      (this.stats.averageLatencyMs * (n - 1) + latencyMs) / n;
    this.stats.totalTokensSaved +=
      result.originalTokens - result.compressedTokens;
  }
}
