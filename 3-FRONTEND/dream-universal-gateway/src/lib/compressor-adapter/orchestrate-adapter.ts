/**
 * Orchestrate Adapter — 编排器适配器
 *
 * 功能:
 * - 封装与 /api/orchestrate 的交互
 * - 提供与 CompressorAdapter 一致的接口风格
 * - 支持在对话过程中实时调用编排器
 * - 支持降级策略
 *
 * 核心理念: 与 CompressorAdapter 保持相同的设计风格:
 * - 懒加载单例模式
 * - 所有操作都有兜底
 * - 提供健康检查和统计
 * - 支持手动调用和自动调用
 *
 * @stability experimental
 */

import { createFallbackResult } from './fallback';

// ============================================================
// 类型定义
// ============================================================

export interface OrchestrateConfig {
  enabled: boolean;
  apiBaseUrl?: string;
  autoInvoke: boolean;
  defaultTradingMode: 'ai_skill' | 'classic' | 'hybrid';
  defaultComplexity: 'quick' | 'standard' | 'deep';
  defaultChainWeights: {
    s_chain: number;
    c_chain: number;
    f_chain: number;
  };
  maxRetries: number;
  retryDelayMs: number;
  timeoutMs: number;
}

export interface OrchestrateRequest {
  sessionId?: string;
  userRequest: string;
  intent?: 'market_query' | 'deep_analysis' | 'execute_trade' | 'strategy_verify' | 'risk_alert';
  symbol?: string;
  complexity?: 'quick' | 'standard' | 'deep';
  tradingMode?: 'ai_skill' | 'classic' | 'hybrid';
  chainWeights?: {
    s_chain: number;
    c_chain: number;
    f_chain: number;
  };
  maxLatencyMs?: number;
}

export interface OrchestrateResponse {
  success: boolean;
  planId: string;
  sessionId: string;
  totalTokensUsed: number;
  totalLatencyMs: number;
  overallConfidence: number;
  steps?: Array<{
    stepId: string;
    stage: string;
    chain: string;
    status: string;
    answer: string;
    confidence: number;
    skillsCalled: Array<{
      skillId: string;
      skillName: string;
      confidence: number;
      latencyMs?: number;
    }>;
    decision?: string;
  }>;
  crossValidationResults?: Array<{
    nodeId: string;
    consensus?: {
      direction: string;
      overallConfidence: number;
      agreementLevel: string;
    };
  }>;
  conclusion?: {
    direction: string;
    confidence: number;
    keyDecisionPoints: string[];
    reasoningPath: string[];
    nextSteps?: Array<{
      action: string;
      reasoning: string;
      estimatedConfidence?: number;
    }>;
  };
  graphData?: {
    nodes: Array<{
      id: string;
      type: string;
      name: string;
      level: string;
      status: string;
      tokens: number;
      summary: string;
      metadata: Record<string, unknown>;
    }>;
    edges: Array<{
      from: string;
      to: string;
      type: string;
    }>;
    stats: {
      totalNodes: number;
      avgConfidence: number;
      executionTime: number;
    };
  };
  error?: string;
  errorType?: string;
}

export interface OrchestrateStatus {
  healthy: boolean;
  initialized: boolean;
  lastError?: string;
  totalCalls: number;
  totalLatencyMs: number;
  averageLatencyMs: number;
  successRate: number;
}

// ============================================================
// 默认配置
// ============================================================

const DEFAULT_CONFIG: OrchestrateConfig = {
  enabled: true,
  autoInvoke: false,
  defaultTradingMode: 'hybrid',
  defaultComplexity: 'standard',
  defaultChainWeights: {
    s_chain: 0.45,
    c_chain: 0.35,
    f_chain: 0.20,
  },
  maxRetries: 2,
  retryDelayMs: 1000,
  timeoutMs: 30000,
};

// ============================================================
// 适配器实现
// ============================================================

export class OrchestrateAdapter {
  private config: OrchestrateConfig;
  private _initialized = false;
  private _healthy = false;
  private _lastError?: string;

  // 统计信息
  private _totalCalls = 0;
  private _successCalls = 0;
  private _totalLatencyMs = 0;

  constructor(config: Partial<OrchestrateConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  // ============================================================
  // 初始化
  // ============================================================

  /**
   * 初始化适配器 - 验证 API 是否可用
   */
  async initialize(): Promise<boolean> {
    if (!this.config.enabled) {
      this._healthy = false;
      this._initialized = true;
      return false;
    }

    try {
      // 通过 GET 请求验证 API 状态
      const response = await fetch('/api/orchestrate', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
        signal: AbortSignal.timeout(5000),
      });

      if (response.ok) {
        const data = await response.json();
        this._healthy = data.success || data.status === 'operational';
      } else {
        this._healthy = false;
        this._lastError = `HTTP ${response.status}`;
      }

      this._initialized = true;
      return this._healthy;
    } catch (error) {
      this._healthy = false;
      this._lastError = error instanceof Error ? error.message : 'Unknown error';
      this._initialized = true;
      return false;
    }
  }

  // ============================================================
  // 核心方法
  // ============================================================

  /**
   * 执行编排请求
   * 这是主入口方法
   */
  async orchestrate(
    request: OrchestrateRequest
  ): Promise<OrchestrateResponse> {
    if (!this._initialized) {
      await this.initialize();
    }

    if (!this.config.enabled || !this._healthy) {
      return this.createFallbackResponse(request);
    }

    const startTime = Date.now();
    let lastError: unknown;

    for (let attempt = 0; attempt <= this.config.maxRetries; attempt++) {
      try {
        const response = await this.makeRequest(request);

        if (response.success) {
          this._totalCalls++;
          this._successCalls++;
          this._totalLatencyMs += Date.now() - startTime;
          return response;
        }

        lastError = response.error;

        // 如果不是最后一次尝试，延迟重试
        if (attempt < this.config.maxRetries) {
          await new Promise(resolve => setTimeout(resolve, this.config.retryDelayMs));
        }
      } catch (error) {
        lastError = error;
        this._lastError = error instanceof Error ? error.message : 'Unknown error';

        if (attempt < this.config.maxRetries) {
          await new Promise(resolve => setTimeout(resolve, this.config.retryDelayMs));
        }
      }
    }

    // 所有尝试都失败
    this._totalCalls++;
    return this.createFallbackResponse(request, lastError as Error | undefined);
  }

  /**
   * 获取编排器状态
   */
  getStatus(): OrchestrateStatus {
    const successRate = this._totalCalls > 0 ? this._successCalls / this._totalCalls : 0;
    const averageLatencyMs = this._totalCalls > 0 ? Math.round(this._totalLatencyMs / this._totalCalls) : 0;

    return {
      healthy: this._healthy,
      initialized: this._initialized,
      lastError: this._lastError,
      totalCalls: this._totalCalls,
      totalLatencyMs: this._totalLatencyMs,
      averageLatencyMs,
      successRate: Math.round(successRate * 100),
    };
  }

  /**
   * 重置统计信息
   */
  resetStats(): void {
    this._totalCalls = 0;
    this._successCalls = 0;
    this._totalLatencyMs = 0;
    this._lastError = undefined;
  }

  /**
   * 启用/禁用适配器
   */
  setEnabled(enabled: boolean): void {
    this.config.enabled = enabled;
    if (!enabled) {
      this._healthy = false;
    }
  }

  /**
   * 更新配置
   */
  updateConfig(newConfig: Partial<OrchestrateConfig>): void {
    this.config = { ...this.config, ...newConfig };
  }

  /**
   * 获取当前配置
   */
  getConfig(): OrchestrateConfig {
    return { ...this.config };
  }

  // ============================================================
  // 便捷方法
  // ============================================================

  /**
   * 快速查询市场
   */
  async quickQuery(
    userRequest: string,
    options: Partial<OrchestrateRequest> = {}
  ): Promise<OrchestrateResponse> {
    return this.orchestrate({
      ...options,
      userRequest,
      intent: 'market_query',
      complexity: 'quick',
    });
  }

  /**
   * 深度分析
   */
  async deepAnalysis(
    userRequest: string,
    options: Partial<OrchestrateRequest> = {}
  ): Promise<OrchestrateResponse> {
    return this.orchestrate({
      ...options,
      userRequest,
      intent: 'deep_analysis',
      complexity: 'deep',
    });
  }

  /**
   * 执行交易分析
   */
  async tradeExecution(
    userRequest: string,
    options: Partial<OrchestrateRequest> = {}
  ): Promise<OrchestrateResponse> {
    return this.orchestrate({
      ...options,
      userRequest,
      intent: 'execute_trade',
      complexity: 'standard',
    });
  }

  /**
   * 策略验证
   */
  async strategyVerify(
    userRequest: string,
    options: Partial<OrchestrateRequest> = {}
  ): Promise<OrchestrateResponse> {
    return this.orchestrate({
      ...options,
      userRequest,
      intent: 'strategy_verify',
      complexity: 'standard',
    });
  }

  // ============================================================
  // 私有辅助方法
  // ============================================================

  private async makeRequest(request: OrchestrateRequest): Promise<OrchestrateResponse> {
    const body: OrchestrateRequest = {
      sessionId: request.sessionId,
      userRequest: request.userRequest,
      intent: request.intent,
      symbol: request.symbol,
      complexity: request.complexity || this.config.defaultComplexity,
      tradingMode: request.tradingMode || this.config.defaultTradingMode,
      chainWeights: request.chainWeights || this.config.defaultChainWeights,
      maxLatencyMs: request.maxLatencyMs || this.config.timeoutMs,
    };

    const response = await fetch('/api/orchestrate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(body.maxLatencyMs || this.config.timeoutMs),
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => '');
      throw new Error(`HTTP ${response.status}: ${errorText || response.statusText}`);
    }

    return await response.json();
  }

  private createFallbackResponse(
    request: OrchestrateRequest,
    error?: Error
  ): OrchestrateResponse {
    const errorMsg = error?.message || this._lastError || 'Orchestrator unavailable';

    return {
      success: false,
      planId: `fallback_${Date.now()}`,
      sessionId: request.sessionId || 'anonymous',
      totalTokensUsed: 0,
      totalLatencyMs: 0,
      overallConfidence: 0,
      steps: [],
      conclusion: {
        direction: 'neutral',
        confidence: 0,
        keyDecisionPoints: [],
        reasoningPath: [],
        nextSteps: [],
      },
      error: errorMsg,
      errorType: 'orchestration_unavailable',
    };
  }
}

// ============================================================
// 单例管理
// ============================================================

let _globalAdapter: OrchestrateAdapter | null = null;

/**
 * 获取全局编排器适配器
 */
export function getOrchestrateAdapter(): OrchestrateAdapter {
  if (!_globalAdapter) {
    _globalAdapter = new OrchestrateAdapter();
  }
  return _globalAdapter;
}

/**
 * 创建新的编排器适配器实例
 */
export function createOrchestrateAdapter(config?: Partial<OrchestrateConfig>): OrchestrateAdapter {
  return new OrchestrateAdapter(config);
}
