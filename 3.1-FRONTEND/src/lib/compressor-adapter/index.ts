/**
 * Compressor Adapter — 统一入口
 *
 * Feature Flag：
 * - 默认启用（与 Scheduler/CostKeeper 联动）
 * - 设置 USE_SCHEDULER=false 可全局禁用
 * - 默认降级策略：text-summarize（文本摘要）
 */

import { CompressorAdapter } from './adapter';
export { CompressorAdapter };
export { createFallbackResult, estimateTokens } from './fallback';
export type {
  CompressInput,
  CompressResult,
  GraphData,
  SerializedNode,
  SerializedEdge,
  GraphStats,
  CompressionReport,
  AdapterHealth,
  AdapterStats,
  AdapterConfig,
  DecisionNode,
  ReasoningPath,
  ConflictDetection,
  NextStepSuggestion,
  InferenceResult,
  SessionMeta,
  SessionData,
} from './types';

// ==================== 编排器适配器 ====================
export {
  OrchestrateAdapter,
  getOrchestrateAdapter,
  createOrchestrateAdapter,
} from './orchestrate-adapter';
export type {
  OrchestrateConfig,
  OrchestrateRequest,
  OrchestrateResponse,
  OrchestrateStatus,
} from './orchestrate-adapter';

// ==================== 全局单例（应用级共享） ====================

let _adapter: CompressorAdapter | null = null;
let _initialized = false;

/**
 * 获取压缩器适配器单例
 *
 * 特性：
 * - 延迟初始化（第一次调用时才初始化）
 * - 全局共享（整个应用生命周期内）
 * - 默认启用（与 Scheduler/CostKeeper 联动）
 */
export function getCompressorAdapter(): CompressorAdapter {
  if (!_adapter) {
    // 默认启用压缩器。仅当显式设置 USE_SCHEDULER=false 时禁用
    const explicitlyDisabled =
      typeof process !== 'undefined' &&
      (process.env.USE_SCHEDULER === 'false' || process.env.USE_SCHEDULER === '0');

    _adapter = new CompressorAdapter({
      enabled: !explicitlyDisabled,
      fallbackStrategy: 'text-summarize',
      defaultTargetRatio: 0.5,
      minTokensForCompression: 200,
    });
  }
  return _adapter;
}

/**
 * 全局压缩器实例（懒加载单例）
 *
 * 用法：
 * ```typescript
 * import { compressorAdapter } from '@/lib/compressor-adapter';
 * await compressorAdapter.initialize();
 * const result = await compressorAdapter.compress(input);
 * ```
 */
export const compressorAdapter: CompressorAdapter = new Proxy({} as CompressorAdapter, {
  get(_target, prop) {
    const adapter = getCompressorAdapter();
    if (!_initialized && prop === 'initialize') {
      _initialized = true;
      return async () => {
        await adapter.initialize();
      };
    }
    if (prop === 'initialize') {
      if (!_initialized) {
        _initialized = true;
        return async () => {
          await adapter.initialize();
        };
      }
      return async () => {
        // 重复调用 no-op
      };
    }
    return (adapter as unknown as Record<string, unknown>)[prop as string];
  },
});
