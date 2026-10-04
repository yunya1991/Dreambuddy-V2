// ============================================
// Fundamental 域客户端 — 基本面域 API
// ============================================
// 无直接路由，通过 bridge 或 market 域获取

import api from '../../api-client';

export interface FundamentalSnapshot {
  [key: string]: unknown;
}

export const fundamentalApi = {
  /** 获取基本面快照 */
  getSnapshot: () =>
    api.get<FundamentalSnapshot>('/api/fundamental/snapshot'),
};
