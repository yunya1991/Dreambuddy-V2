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
  /** 最小 token 数，低于该值不压缩 */
  minTokensForCompression?: number;
}

// ==================== 推理引擎 ====================

/** 关键决策节点 */
export interface DecisionNode {
  id: string;
  name: string;
  type: 'goal' | 'constraint' | 'choice' | 'tradeoff' | 'action';
  description: string;
  weight: number;
  confidence: number;
  sourceMessageIds: string[];
  createdAt: number;
}

/** 关键推理路径 */
export interface ReasoningPath {
  id: string;
  name: string;
  nodeIds: string[];
  rationale: string;
  confidence: number;
  priority: 'high' | 'medium' | 'low';
}

/** 冲突检测 */
export interface ConflictDetection {
  id: string;
  type: 'goal-conflict' | 'constraint-conflict' | 'inconsistency' | 'duplicate';
  severity: 'high' | 'medium' | 'low';
  description: string;
  involvedNodes: string[];
  suggestion: string;
  detectedAt: number;
}

/** 下一步建议 */
export interface NextStepSuggestion {
  id: string;
  title: string;
  description: string;
  action: 'ask-clarify' | 'refine-goal' | 'explore-alternative' | 'execute-action' | 'validate' | 'other';
  priority: 'high' | 'medium' | 'low';
  estimatedTokens?: number;
  references?: string[];
}

/** 推理分析结果 */
export interface InferenceResult {
  sessionId: string;
  analyzedAt: number;
  keyDecisionNodes: DecisionNode[];
  keyReasoningPaths: ReasoningPath[];
  conflicts: ConflictDetection[];
  riskScore: number;
  riskLevel: 'low' | 'medium' | 'high' | 'critical';
  nextSteps: NextStepSuggestion[];
  summary: string;
  metadata: {
    messageCount: number;
    inferenceTokens: number;
    analysisDurationMs: number;
    mode: 'graph' | 'fallback';
  };
}

// ==================== 会话持久化 ====================

/** 会话元数据 */
export interface SessionMeta {
  sessionId: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
  tokenEstimate: number;
  tag?: string[];
}

/** 会话数据结构（持久化用） */
export interface SessionData {
  sessionId: string;
  title?: string;
  messages: any[];
  meta?: Record<string, unknown>;
  graphSnapshot?: {
    blueprint?: any[];
    architecture?: any[];
    chronicle?: any[];
  };
  inferenceSnapshot?: InferenceResult;
  createdAt: number;
  updatedAt: number;
}

// 从通用模块再导出，方便前端统一 import
export type {
  VisualizationData,
  VizNode,
  VizEdge,
  TimelineItem,
  DiffSummary,
} from '../../../../../6-图结构上下文压缩/index.ts';
