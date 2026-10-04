// ============================================
// Chain 域客户端 — 链路产物域 API
// ============================================

import api from '../../api-client';

export interface ChainArtifact {
  id: string;
  [key: string]: unknown;
}

export const chainApi = {
  /** 获取链路产物列表 */
  getArtifacts: () =>
    api.get<ChainArtifact[]>('/api/chain/artifacts'),
};
