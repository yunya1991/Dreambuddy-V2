/**
 * 外部通用模块本地存根（仅用于 tsc 静态类型检查）
 *
 * 真实运行时由 Next.js webpack/tsx 解析 `@yunya/graph-context-compressor`
 * 到 `6-图结构上下文压缩/index.ts`。但该外部模块存在大量 pre-existing TS 错误
 * （./types vs ./models 引用混乱），若让 tsc 跟进解析会引入 ~128 个外部错误。
 *
 * 策略：tsconfig `paths` 将别名指向本存根，让 tsc 只看到本文件的类型签名；
 * 运行时由 Next.js webpack tsconfigPathsPlugin 或 tsx 直接解析真实路径。
 *
 * 注：存根类型签名必须与真实模块保持一致，否则会引入新的类型不匹配。
 */

// ==================== 类型契约（与 contract.ts 镜像） ====================

export interface CompressInput {
  sessionId: string;
  payload: string | unknown[];
  targetRatio?: number;
  metadata?: Record<string, unknown>;
}

export interface CompressResult {
  sessionId: string;
  originalLength: number;
  compressedLength: number;
  ratio: number;
  graph?: GraphData;
  originalTokens?: number;
  compressedTokens?: number;
  compressionRatio?: number;
  stats?: Record<string, unknown>;
  report?: Record<string, unknown>;
  blueprint?: unknown;
  architecture?: unknown[];
  chronicle?: unknown[];
  inferenceSnapshot?: unknown;
  createdAt: number;
  updatedAt: number;
  [k: string]: unknown;
}

export interface GraphData {
  sessionId?: string;
  blueprint?: unknown[];
  architecture?: unknown[];
  chronicle?: unknown[];
  edges?: unknown[];
  [k: string]: unknown;
}

export interface CompressorOptions {
  defaultTargetRatio?: number;
  mode?: 'basic' | 'semantic' | 'sharded' | 'auto';
}

export interface CompressorStats {
  totalCompressions: number;
  averageCompressionRatio: number;
  averageLatencyMs: number;
  totalTokensSaved: number;
}

export interface HealthStatus {
  healthy: boolean;
  version: string;
  uptimeMs: number;
  lastError?: string;
}

export interface VisualizationData {
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
  timeline?: unknown[];
  diff?: Record<string, unknown>;
  stats?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface Compressor {
  compress(input: CompressInput): Promise<CompressResult>;
  expand(graphId: string, level: 'A' | 'B' | 'C'): Promise<GraphData>;
  health(): Promise<HealthStatus>;
  getStats(): CompressorStats;
  getVisualizationData(input: CompressInput): Promise<VisualizationData>;
  getMode(): 'basic' | 'semantic' | 'sharded' | 'auto';
}

// ==================== 镜像类型（来自 visualization.ts） ====================

export interface VizNode {
  id: string;
  layer?: string;
  label?: string;
  [k: string]: unknown;
}
export interface VizEdge {
  from: string;
  to: string;
  [k: string]: unknown;
}
export interface VizLayer {
  id: string;
  nodes?: VizNode[];
  [k: string]: unknown;
}
export interface TimelineItem {
  timestamp?: number;
  event?: string;
  [k: string]: unknown;
}
export interface DiffSummary {
  added?: number;
  removed?: number;
  modified?: number;
  [k: string]: unknown;
}

// ==================== 运行时入口（存根实现，真实模块由 webpack 注入） ====================

export const VERSION = 'stub-1.0.0';
export const PROTOCOL_VERSION = 'stub-v1';

export function createCompressor(_options?: CompressorOptions): Compressor {
  throw new Error(
    '[compressor-adapter/external-stub] createCompressor() 存根被调用 — 运行时应由 webpack 解析到真实模块'
  );
}
