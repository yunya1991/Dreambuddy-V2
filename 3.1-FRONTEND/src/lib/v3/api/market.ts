// ============================================
// Market 域客户端 — 市场数据 API
// ============================================

import api from '../../api-client';

export interface MarketRoute {
  route?: string;
  content?: string;
  [key: string]: unknown;
}

export interface MarketDistribution {
  [symbol: string]: number;
}

export interface MarketSegment {
  id: string;
  name: string;
  [key: string]: unknown;
}

export const marketApi = {
  /** 获取市场路由 */
  getRoute: () =>
    api.get<MarketRoute>('/api/market/route'),

  /** 获取市场内容 */
  getContent: () =>
    api.get<Record<string, unknown>>('/api/market/content'),

  /** 获取市场分布 */
  getDistribution: () =>
    api.get<MarketDistribution>('/api/market/distribution'),

  /** 获取市场审计 */
  getAudit: () =>
    api.get<Record<string, unknown>>('/api/market/audit'),

  /** 获取市场活动 */
  getCampaigns: () =>
    api.get<unknown[]>('/api/market/campaigns'),

  /** 获取市场效果 */
  getEffectiveness: () =>
    api.get<Record<string, unknown>>('/api/market/effectiveness'),

  /** 获取市场分段 */
  getSegments: () =>
    api.get<MarketSegment[]>('/api/market/segments'),
};
