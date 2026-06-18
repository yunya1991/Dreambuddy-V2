/**
 * Compressor Adapter — 类型定义
 *
 * 这些类型镜像了 graph-context-compressor/src/contract.ts 中的定义。
 * 主线只依赖这些类型，不直接引用图文模块内部类型。
 *
 * @stability internal
 */

// ==================== 压缩输入输出 ====================

/** 压缩输入 */
export interface CompressInput {
  sessionId: string;
  payload: string | CompressItem[];
  targetRatio?: number;
  metadata?: Record<string, unknown>;
}

/** 待压缩项 */
export interface CompressItem {
  id: string;
  type: 'message' | 'step' | 'tool_call' | 'log' | 'other';
  content: string;
  tokens?: number;
  timestamp?: number;
  meta?: Record<string, unknown>;
}

/** 压缩结果 */
export interface CompressResult {
  graph: GraphData;
  originalTokens: number;
  compressedTokens: number;
  compressionRatio: number;
  stats: GraphStats;
  report?: CompressionReport;
}

/** 图数据 */
export interface GraphData {
  blueprint?: SerializedNode[];
  architecture?: SerializedNode[];
  chronicle?: SerializedNode[];
  edges: SerializedEdge[];
}

/** 节点 */
export interface SerializedNode {
  id: string;
  type: string;
  name: string;
  level: 'B' | 'A' | 'C';
  status?: 'pending' | 'running' | 'completed' | 'skipped' | 'failed';
  tokens?: number;
  latencyMs?: number;
  compressed?: boolean;
  summary?: string;
  meta?: Record<string, unknown>;
}

/** 边 */
export interface SerializedEdge {
  from: string;
  to: string;
  type?: string;
  label?: string;
  meta?: Record<string, unknown>;
}

/** 图统计 */
export interface GraphStats {
  totalNodes: number;
  totalEdges: number;
  byLevel: { B: number; A: number; C: number };
  retainedNodes: number;
  compressedNodes: number;
}

/** 压缩报告 */
export interface CompressionReport {
  strategy: string;
  discarded: Array<{ id: string; reason: string; savedTokens: number }>;
  durationMs: number;
  algorithmVersion: string;
}

// ==================== 适配器状态 ====================

/** 适配器健康状态 */
export interface AdapterHealth {
  healthy: boolean;
  mode: 'graph' | 'fallback' | 'disabled';
  graphCompressorVersion?: string;
  lastError?: string;
  uptimeMs: number;
}

/** 适配器统计 */
export interface AdapterStats {
  totalCompressions: number;
  graphCompressions: number;
  fallbackCompressions: number;
  averageCompressionRatio: number;
  averageLatencyMs: number;
  totalTokensSaved: number;
}

/** 适配器配置 */
export interface AdapterConfig {
  /** 主开关（对应 USE_SCHEDULER） */
  enabled: boolean;
  /** 降级策略 */
  fallbackStrategy: 'text-summarize' | 'pass-through' | 'error';
  /** 图文模块路径（本地调试用） */
  modulePath?: string;
  /** 初始化超时（毫秒） */
  initTimeoutMs?: number;
  /** 默认压缩比 */
  defaultTargetRatio?: number;
  /** 降级阈值：当 token 数低于此值时不压缩 */
  minTokensForCompression?: number;
}
