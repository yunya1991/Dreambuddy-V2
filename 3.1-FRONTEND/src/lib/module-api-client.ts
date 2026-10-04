/**
 * 4 模块统一 API 客户端
 *
 * M25 策略生成 → http://127.0.0.1:8095
 * M26 策略管理 → http://127.0.0.1:8093
 * M27 治理审批 → http://127.0.0.1:8094
 * M28 信号触发 → http://127.0.0.1:8096
 */

const BASE_URLS = {
  M25: process.env.NEXT_PUBLIC_M25_URL || 'http://127.0.0.1:8095',
  M26: process.env.NEXT_PUBLIC_M26_URL || 'http://127.0.0.1:8093',
  M27: process.env.NEXT_PUBLIC_M27_URL || 'http://127.0.0.1:8094',
  M28: process.env.NEXT_PUBLIC_M28_URL || 'http://127.0.0.1:8096',
} as const;

export interface ApiResponse<T = any> {
  ok: boolean;
  data?: T;
  error?: string;
  [key: string]: any;
}

async function request<T = any>(
  module: keyof typeof BASE_URLS,
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  try {
    const res = await fetch(`${BASE_URLS[module]}${endpoint}`, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    });
    const json = await res.json();
    return json as ApiResponse<T>;
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

// ============================================================
// M25 策略生成系统 (port 8095)
// ============================================================
export const M25_API = {
  health: () => request('M25', '/health'),
  baselineList: () => request('M25', '/api/v1/baseline/list'),
  baselineGet: (id: string) => request('M25', `/api/v1/baseline/get?id=${encodeURIComponent(id)}`),
  baselineMetrics: (id: string) => request('M25', `/api/v1/baseline/metrics?id=${encodeURIComponent(id)}`),
  genIntent: (intent: string) =>
    request('M25', '/api/v1/gen/intent', { method: 'POST', body: JSON.stringify({ intent }) }),
  genBacktest: (strategyId: string, config?: Record<string, any>) =>
    request('M25', '/api/v1/gen/backtest', { method: 'POST', body: JSON.stringify({ strategy_id: strategyId, ...config }) }),
  genCompare: (strategyId: string, baselineId: string) =>
    request('M25', '/api/v1/gen/compare', { method: 'POST', body: JSON.stringify({ strategy_id: strategyId, baseline_id: baselineId }) }),
  genPipeline: (intent: string) =>
    request('M25', '/api/v1/gen/pipeline', { method: 'POST', body: JSON.stringify({ intent }) }),
};

// ============================================================
// M26 策略管理系统 (port 8093)
// ============================================================
export const M26_API = {
  health: () => request('M26', '/health'),
  libStrategies: () => request('M26', '/api/v1/lib/strategies'),
  libStrategyDetail: (id: string) => request('M26', `/api/v1/lib/strategies/${encodeURIComponent(id)}`),
  libStrategyEvents: (id: string) => request('M26', `/api/v1/lib/strategies/${encodeURIComponent(id)}/events`),
  libTiers: () => request('M26', '/api/v1/lib/tiers'),
  libUpsert: (data: Record<string, any>) =>
    request('M26', '/api/v1/lib/strategies/upsert', { method: 'POST', body: JSON.stringify(data) }),
  userStrategies: () => request('M26', '/api/v1/user/strategies'),
  userCreate: (data: Record<string, any>) =>
    request('M26', '/api/v1/user/strategies', { method: 'POST', body: JSON.stringify(data) }),
  userUpdate: (id: string, data: Record<string, any>) =>
    request('M26', `/api/v1/user/strategies/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }),
  userDelete: (id: string) =>
    request('M26', `/api/v1/user/strategies/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  userClone: (id: string) =>
    request('M26', `/api/v1/user/strategies/${encodeURIComponent(id)}/clone`, { method: 'POST' }),
};

// ============================================================
// M27 治理审批系统 (port 8094)
// ============================================================
export const M27_API = {
  health: () => request('M27', '/health'),
  pipelineList: () => request('M27', '/api/v1/pipeline/list'),
  pipelineCreate: (strategyId: string, title?: string) =>
    request('M27', '/api/v1/pipeline/create', { method: 'POST', body: JSON.stringify({ strategy_id: strategyId, title: title || `Pipeline-${Date.now()}` }) }),
  pipelineState: (traceId: string) => request('M27', `/api/v1/pipeline/state/${encodeURIComponent(traceId)}`),
  pipelineAdvance: (traceId: string, stage: string) =>
    request('M27', `/api/v1/pipeline/stage/${encodeURIComponent(traceId)}/${encodeURIComponent(stage)}`, { method: 'PUT' }),
  changesetDraft: (data: Record<string, any>) =>
    request('M27', '/api/v1/changeset/draft', { method: 'POST', body: JSON.stringify(data) }),
  changesetGet: (draftId: string) => request('M27', `/api/v1/changeset/draft/${encodeURIComponent(draftId)}`),
  changesetValidate: (draftId: string) =>
    request('M27', '/api/v1/changeset/validate', { method: 'POST', body: JSON.stringify({ draft_id: draftId }) }),
  approvalCreate: (data: Record<string, any>) =>
    request('M27', '/api/v1/approvals', { method: 'POST', body: JSON.stringify(data) }),
  approvalList: () => request('M27', '/api/v1/approvals'),
  approvalGet: (id: string) => request('M27', `/api/v1/approvals/${encodeURIComponent(id)}`),
  approvalApprove: (id: string) => request('M27', `/api/v1/approvals/${encodeURIComponent(id)}/ok`),
  auditQuery: (params?: Record<string, any>) =>
    request('M27', `/api/v1/audit/query${params ? '?' + new URLSearchParams(params).toString() : ''}`),
  auditVerify: () => request('M27', '/api/v1/audit/verify'),
  gateEvaluate: (data: Record<string, any>) =>
    request('M27', '/api/v1/gate/evaluate', { method: 'POST', body: JSON.stringify(data) }),
};

// ============================================================
// M28 信号触发模块 (port 8096)
// ============================================================
export const M28_API = {
  health: () => request('M28', '/health'),
  universeAliases: () => request('M28', '/api/v1/universe/aliases'),
  universeScreen: (candidates: any[], btcClose?: Record<string, number>, betaRange?: { min: number; max: number }) =>
    request('M28', '/api/v1/universe/screen', {
      method: 'POST',
      body: JSON.stringify({ candidates, btc_close: btcClose, beta_range: betaRange }),
    }),
  universeBeta: (candidates: any[], btcRet: number[]) =>
    request('M28', '/api/v1/universe/beta', { method: 'POST', body: JSON.stringify({ candidates, btc_ret: btcRet }) }),
  universeCorr: (candidates: any[], btcClose?: Record<string, number>) =>
    request('M28', '/api/v1/universe/corr', { method: 'POST', body: JSON.stringify({ candidates, btc_close: btcClose }) }),
  webhookEvents: () => request('M28', '/api/v1/webhook/events'),
  webhookFreqtrade: (data: Record<string, any>) =>
    request('M28', '/webhook/freqtrade', { method: 'POST', body: JSON.stringify(data) }),
};
