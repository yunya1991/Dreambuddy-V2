/**
 * Compressor Adapter — 核心适配器
 *
 * 防御性边界：处理图文压缩模块的初始化、调用、降级和健康检查。
 * 由 DreamBuddy 维护，不属于图文模块本身。
 *
 * 设计原则：
 * - 启动时做健康探测，失败则降级
 * - 运行时崩溃则自动降级，不影响主流程
 * - 所有操作都有兜底，不会抛出异常
 *
 * @stability internal
 */

import type {
  CompressInput,
  CompressResult,
  AdapterHealth,
  AdapterStats,
  AdapterConfig,
} from './types';
import { createFallbackResult, estimateTokens } from './fallback';

// ==================== 默认配置 ====================

const DEFAULT_CONFIG: AdapterConfig = {
  enabled: true,
  fallbackStrategy: 'text-summarize',
  initTimeoutMs: 5000,
  defaultTargetRatio: 0.5,
  minTokensForCompression: 200,
};

// ==================== CompressorAdapter ====================

/**
 * 压缩器适配器
 *
 * 用法：
 * ```typescript
 * const adapter = new CompressorAdapter();
 * await adapter.initialize();
 *
 * const result = await adapter.compress({
 *   sessionId: 'session-001',
 *   payload: [...],
 *   targetRatio: 0.3,
 * });
 *
 * const health = adapter.health();
 * const stats = adapter.getStats();
 * ```
 */
export class CompressorAdapter {
  private config: AdapterConfig;
  private mode: 'graph' | 'fallback' | 'disabled' = 'disabled';
  private graphModule: GraphModuleRef | null = null;
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
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  // ==================== 初始化 ====================

  /**
   * 初始化适配器：尝试加载图文压缩模块并做健康检查
   */
  async initialize(): Promise<void> {
    if (!this.config.enabled) {
      this.mode = 'disabled';
      this.healthy = false;
      console.log('[CompressorAdapter] DISABLED via config');
      return;
    }

    try {
      // 尝试加载图文模块
      const module = await this.tryLoadGraphModule();

      if (!module) {
        this.degrade('fallback', new Error('图文模块加载返回空'));
        return;
      }

      // 健康检查
      const timeout = this.config.initTimeoutMs ?? 5000;
      const health = await Promise.race([
        module.health(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('健康检查超时')), timeout)
        ),
      ]);

      if (!health.healthy) {
        this.degrade('fallback', new Error(health.lastError ?? '健康检查失败'));
        return;
      }

      // 协议版本兼容性检查（如果模块暴露了 PROTOCOL_VERSION）
      if (module.PROTOCOL_VERSION && module.PROTOCOL_VERSION !== '1') {
        console.warn(
          `[CompressorAdapter] 协议版本不匹配: expected=1, got=${module.PROTOCOL_VERSION}，降级`
        );
        this.degrade('fallback', new Error('PROTOCOL_VERSION 不兼容'));
        return;
      }

      this.graphModule = module;
      this.mode = 'graph';
      this.healthy = true;
      console.log(
        `[CompressorAdapter] INITIALIZED (graph mode) v${health.version}`
      );
    } catch (err) {
      this.degrade('fallback', err as Error);
    }
  }

  // ==================== 核心 API ====================

  /**
   * 执行压缩
   *
   * - 图文模式：调用图文模块
   * - 降级模式：文本摘要
   * - 禁用模式：透传（返回空图）
   */
  async compress(input: CompressInput): Promise<CompressResult> {
    const start = Date.now();

    // 小输入不压缩，直接透传
    const tokens =
      typeof input.payload === 'string'
        ? estimateTokens(input.payload)
        : input.payload.reduce((sum, item) => sum + (item.tokens ?? estimateTokens(item.content)), 0);

    if (tokens < (this.config.minTokensForCompression ?? 200)) {
      return this.passThroughResult(input, tokens);
    }

    // 降级模式
    if (this.mode === 'fallback') {
      return this.executeFallback(input, tokens, start);
    }

    // 禁用模式
    if (this.mode === 'disabled') {
      return this.passThroughResult(input, tokens);
    }

    // 图文模式
    try {
      const result = await this.executeGraph(input);
      this.recordStats(result, Date.now() - start, true);
      return result;
    } catch (err) {
      console.warn('[CompressorAdapter] 图文模块调用失败，降级', err);
      this.healthy = false;
      this.lastError = (err as Error).message;
      return this.executeFallback(input, tokens, start);
    }
  }

  /**
   * 健康状态
   */
  health(): AdapterHealth {
    return {
      healthy: this.healthy,
      mode: this.mode,
      graphCompressorVersion: this.graphModule?.VERSION,
      lastError: this.lastError,
      uptimeMs: Date.now() - this.startTime,
    };
  }

  /**
   * 累计统计
   */
  getStats(): AdapterStats {
    return { ...this.stats };
  }

  // ==================== 私有方法 ====================

  /**
   * 尝试加载图文模块
   *
   * 支持两种路径（按优先级）：
   * 1. npm 包（正式集成后）
   * 2. 本地文件（开发调试）
   */
  private async tryLoadGraphModule(): Promise<GraphModuleRef | null> {
    try {
      // 尝试 npm 包（图文体作为私有 npm 包集成后生效）
      // @ts-ignore — 模块作为 npm 包安装后才存在
      const mod = await import('graph-context-compressor');
      if (mod && typeof mod.createCompressor === 'function') {
        return {
          VERSION: mod.VERSION ?? 'unknown',
          PROTOCOL_VERSION: mod.PROTOCOL_VERSION ?? '1',
          createCompressor: mod.createCompressor,
          health: async () => {
            const inst = mod.createCompressor();
            return inst.health();
          },
        };
      }
    } catch {
      // npm 包不存在，尝试本地路径
    }

    try {
      // 尝试本地文件路径（开发调试用）
      const localPath = this.config.modulePath ?? '../../../graph-compressor/src';
      // @ts-ignore — 本地路径仅在开发时存在
      const mod = await import(/* webpackIgnore: true */ localPath);
      if (mod && typeof mod.createCompressor === 'function') {
        return {
          VERSION: mod.VERSION ?? 'unknown',
          PROTOCOL_VERSION: mod.PROTOCOL_VERSION ?? '1',
          createCompressor: mod.createCompressor,
          health: async () => {
            const inst = mod.createCompressor();
            return inst.health();
          },
        };
      }
    } catch {
      // 本地路径也不存在
    }

    return null;
  }

  private degrade(mode: 'fallback' | 'disabled', err: Error): void {
    this.mode = mode;
    this.healthy = false;
    this.lastError = err.message;
    console.warn(
      `[CompressorAdapter] DEGRADED to ${mode}: ${err.message}`
    );
  }

  private async executeGraph(input: CompressInput): Promise<CompressResult> {
    if (!this.graphModule) throw new Error('模块未初始化');
    const compressor = this.graphModule.createCompressor({
      defaultTargetRatio: this.config.defaultTargetRatio,
    });
    return compressor.compress(input);
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

  private passThroughResult(
    input: CompressInput,
    tokens: number
  ): CompressResult {
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

    // 增量更新平均压缩比和延迟
    const n = this.stats.totalCompressions;
    this.stats.averageCompressionRatio =
      (this.stats.averageCompressionRatio * (n - 1) + result.compressionRatio) / n;
    this.stats.averageLatencyMs =
      (this.stats.averageLatencyMs * (n - 1) + latencyMs) / n;
    this.stats.totalTokensSaved +=
      result.originalTokens - result.compressedTokens;
  }
}

// ==================== 图文模块引用接口 ====================

interface GraphModuleRef {
  VERSION: string;
  PROTOCOL_VERSION: string;
  createCompressor: (options?: unknown) => GraphCompressorInstance;
  health: () => Promise<{ healthy: boolean; version: string; lastError?: string }>;
}

interface GraphCompressorInstance {
  compress(input: CompressInput): Promise<CompressResult>;
  health(): Promise<{ healthy: boolean; version: string; lastError?: string }>;
  getStats(): unknown;
}
