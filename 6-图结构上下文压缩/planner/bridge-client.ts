/**
 * ============================================================
 *  WorkBuddy OS Bridge Client (TS 侧)
 * ============================================================
 *
 * 位置: 6-图结构上下文压缩/planner/bridge-client.ts
 *
 * 架构说明:
 * - S链: 意图识别层（S链 + 意图识别引擎，解决用户目标 → 图架构B层）
 * - A链: 执行闭环（三大闭环 + 三屏交易），使用SKILL方法论
 * - C链: 经典量化（经典指标系统）
 * - F链: 基本面（资金流、情绪、新闻）
 *
 * 功能:
 * 1. 调用 Python 侧 Bridge Server 的模块执行接口
 * 2. 调用 Python 侧注册表查询接口
 * 3. 健康检查与状态监控
 * 4. 批量执行模块
 *
 * 设计原则:
 * - 统一接口：与 Python 侧 API 完全对齐
 * - 类型安全：完整的 TypeScript 类型定义
 * - 重试机制：网络波动时自动重试
 * - 超时控制：防止请求阻塞
 * - 错误处理：统一的错误格式
 */

// ============================================================
// 类型定义
// ============================================================

export interface HealthResponse {
  status: string;
  version: string;
  timestamp: number;
  uptime: number;
}

export interface StatusResponse {
  status: string;
  modules_loaded: number;
  execution_engine: string;
  registry_version: string;
  stats: Record<string, any>;
}

export interface ConfidenceDimensions {
  data_completeness: number;
  logical_consistency: number;
  cross_validation?: number;
  historical_performance?: number;
}

export interface ModuleOutputs {
  direction?: string;
  confidence?: number;
  analysis?: string;
  reasoning?: string;
  value?: number;
  values?: Record<string, number>;
  signal?: string;
  signals?: Array<Record<string, any>>;
  strategy?: string;
  strategies?: Array<Record<string, any>>;
  backtest?: Record<string, any>;
  risk?: Record<string, any>;
  [key: string]: any;
}

export interface ModuleResult {
  success: boolean;
  capabilityId: string;
  outputs: ModuleOutputs;
  confidence: number;
  confidenceDimensions?: ConfidenceDimensions;
  tokensUsed?: number;
  latencyMs?: number;
  error?: string;
  warnings: string[];
  suggestions: string[];
  metadata: Record<string, any>;
  fallbackUsed: boolean;
  fallbackReason?: string;
}

export interface ModuleInfo {
  id: string;
  name: string;
  description: string;
  version: string;
  chain: string;
  category: string;
  tags: string[];
  lifecycle: Record<string, any>;
  security_level: string;
  estimated_tokens: number;
  estimated_latency_ms: number;
  confidence_range: number[];
  applicable_stages: string[];
  applicable_intents: string[];
  market_conditions: string[];
  historical_accuracy: number;
  dependencies: string[];
  adapter: Record<string, any>;
  fallback: Record<string, any>;
  domain: string;
  category_name: string;
}

export interface RegistryQueryParams {
  chain?: string;
  category?: string;
  domain?: string;
  stage?: string;
  tag?: string;
  security_level?: string;
  min_accuracy?: number;
  max_tokens?: number;
  intent?: string;
  market_condition?: string;
}

export interface ModuleExecuteRequest {
  module_id: string;
  inputs?: Record<string, any>;
  context?: Record<string, any>;
  session_id?: string;
  symbol?: string;
}

export interface ModuleBatchExecuteRequest {
  calls: Array<{
    module_id: string;
    inputs?: Record<string, any>;
  }>;
  context?: Record<string, any>;
  session_id?: string;
}

export interface ExecutionStats {
  [moduleId: string]: {
    execution_count: number;
    total_latency_ms: number;
    avg_latency_ms: number;
  };
}

// ============================================================
// Bridge Client
// ============================================================

export class BridgeClient {
  private baseUrl: string;
  private timeoutMs: number;
  private maxRetries: number;
  private retryDelayMs: number;

  constructor(options?: {
    baseUrl?: string;
    timeoutMs?: number;
    maxRetries?: number;
    retryDelayMs?: number;
  }) {
    this.baseUrl = options?.baseUrl || 'http://127.0.0.1:8095';
    this.timeoutMs = options?.timeoutMs || 30000;
    this.maxRetries = options?.maxRetries || 2;
    this.retryDelayMs = options?.retryDelayMs || 500;
  }

  // ============================================================
  // HTTP 请求封装
  // ============================================================

  private async request<T>(
    method: 'GET' | 'POST',
    path: string,
    body?: any,
    params?: Record<string, any>
  ): Promise<T> {
    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const url = new URL(`${this.baseUrl}${path}`);
        if (params) {
          Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
              url.searchParams.append(key, String(value));
            }
          });
        }

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);

        const response = await fetch(url.toString(), {
          method,
          headers: {
            'Content-Type': 'application/json',
          },
          body: body ? JSON.stringify(body) : undefined,
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
          let errorMsg = `HTTP ${response.status}`;
          try {
            const errorData = await response.json();
            errorMsg = errorData.detail || errorMsg;
          } catch {
            // ignore
          }
          throw new Error(errorMsg);
        }

        return await response.json() as T;
      } catch (e) {
        lastError = e as Error;
        if (attempt < this.maxRetries) {
          await this.sleep(this.retryDelayMs * Math.pow(2, attempt));
        }
      }
    }

    throw lastError || new Error('Request failed');
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  // ============================================================
  // 健康检查
  // ============================================================

  async healthCheck(): Promise<HealthResponse> {
    return this.request<HealthResponse>('GET', '/health');
  }

  async getStatus(): Promise<StatusResponse> {
    return this.request<StatusResponse>('GET', '/api/v1/status');
  }

  async isAvailable(): Promise<boolean> {
    try {
      const health = await this.healthCheck();
      return health.status === 'healthy';
    } catch {
      return false;
    }
  }

  // ============================================================
  // 注册表查询
  // ============================================================

  async listModules(params?: RegistryQueryParams): Promise<{
    success: boolean;
    count: number;
    modules: ModuleInfo[];
  }> {
    return this.request<any>('GET', '/api/v1/registry/modules', undefined, params);
  }

  async queryModules(params: RegistryQueryParams): Promise<{
    success: boolean;
    count: number;
    modules: ModuleInfo[];
  }> {
    return this.request<any>('POST', '/api/v1/registry/query', params);
  }

  async getModule(moduleId: string): Promise<{
    success: boolean;
    module: ModuleInfo;
  }> {
    return this.request<any>('GET', `/api/v1/registry/modules/${moduleId}`);
  }

  async listDomains(): Promise<{
    success: boolean;
    domains: string[];
  }> {
    return this.request<any>('GET', '/api/v1/registry/domains');
  }

  async listChains(): Promise<{
    success: boolean;
    chains: string[];
  }> {
    return this.request<any>('GET', '/api/v1/registry/chains');
  }

  async getRegistryStats(): Promise<{
    success: boolean;
    stats: Record<string, any>;
  }> {
    return this.request<any>('GET', '/api/v1/registry/stats');
  }

  async reloadRegistry(): Promise<{
    success: boolean;
    modules_loaded: number;
  }> {
    return this.request<any>('POST', '/api/v1/registry/reload');
  }

  // ============================================================
  // 模块执行
  // ============================================================

  async executeModule(request: ModuleExecuteRequest): Promise<{
    success: boolean;
    result: ModuleResult;
  }> {
    return this.request<any>('POST', '/api/v1/modules/execute', request);
  }

  async executeBatch(request: ModuleBatchExecuteRequest): Promise<{
    success: boolean;
    count: number;
    results: ModuleResult[];
  }> {
    return this.request<any>('POST', '/api/v1/modules/batch', request);
  }

  async checkModuleAvailable(moduleId: string): Promise<{
    success: boolean;
    module_id: string;
    available: boolean;
    has_adapter: boolean;
  }> {
    return this.request<any>('GET', `/api/v1/modules/${moduleId}/available`);
  }

  // ============================================================
  // 执行统计
  // ============================================================

  async getExecutionStats(): Promise<{
    success: boolean;
    stats: ExecutionStats;
  }> {
    return this.request<any>('GET', '/api/v1/execution/stats');
  }

  async resetExecutionStats(): Promise<{
    success: boolean;
    message: string;
  }> {
    return this.request<any>('POST', '/api/v1/execution/stats/reset');
  }

  // ============================================================
  // 便捷方法
  // ============================================================

  getBaseUrl(): string {
    return this.baseUrl;
  }

  setBaseUrl(url: string): void {
    this.baseUrl = url;
  }
}

// ============================================================
// 单例
// ============================================================

let globalBridgeClient: BridgeClient | null = null;

export function getBridgeClient(options?: ConstructorParameters<typeof BridgeClient>[0]): BridgeClient {
  if (!globalBridgeClient) {
    globalBridgeClient = new BridgeClient(options);
  }
  return globalBridgeClient;
}

export function resetBridgeClient(): void {
  globalBridgeClient = null;
}
