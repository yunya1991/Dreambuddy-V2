// ============================================
// Config 域客户端 — 配置管理域 API
// ============================================

import api from '../../api-client';

export interface TradingParams {
  [key: string]: unknown;
}

export interface Strategy {
  id: string;
  name: string;
  [key: string]: unknown;
}

export interface Channel {
  id: string;
  name: string;
  [key: string]: unknown;
}

export interface ApiKeyItem {
  id: string;
  name: string;
  [key: string]: unknown;
}

export const configApi = {
  /** 获取交易参数 */
  getTradingParams: () =>
    api.get<TradingParams>('/api/config/trading-params'),

  /** 更新交易参数 */
  updateTradingParams: (body: Partial<TradingParams>) =>
    api.put<TradingParams>('/api/config/trading-params', body),

  /** 暂停交易 */
  pauseTrading: () =>
    api.post<{ success: boolean }>('/api/config/trading-params/pause'),

  /** 恢复交易 */
  resumeTrading: () =>
    api.post<{ success: boolean }>('/api/config/trading-params/resume'),

  /** 重置日统计 */
  resetDaily: () =>
    api.post<{ success: boolean }>('/api/config/trading-params/reset-daily'),

  /** 获取策略列表 */
  listStrategies: () =>
    api.get<Strategy[]>('/api/config/strategies'),

  /** 解析策略 */
  parseStrategy: (body: unknown) =>
    api.post<Strategy>('/api/config/strategies/parse', body),

  /** 应用策略 */
  applyStrategy: (id: string) =>
    api.post<Strategy>(`/api/config/strategies/${id}/apply`),

  /** 暂停策略 */
  pauseStrategy: (id: string) =>
    api.post<{ success: boolean }>(`/api/config/strategies/${id}/pause`),

  /** 获取渠道列表 */
  listChannels: () =>
    api.get<Channel[]>('/api/config/channels'),

  /** 测试渠道连通性 */
  testChannel: (id: string) =>
    api.post<{ success: boolean }>(`/api/config/channels/${id}/test`),

  /** 获取 API 密钥列表 */
  listApiKeys: () =>
    api.get<ApiKeyItem[]>('/api/config/api-keys'),

  /** 测试 API 密钥连通性 */
  testApiKey: (id: string) =>
    api.post<{ success: boolean }>(`/api/config/api-keys/${id}/test`),
};
