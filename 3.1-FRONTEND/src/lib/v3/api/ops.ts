// ============================================
// Ops 域客户端 — 运维域 API
// ============================================

import api from '../../api-client';

export interface DecisionLevel {
  id: string;
  [key: string]: unknown;
}

export interface QueueInfo {
  id: string;
  [key: string]: unknown;
}

export const opsApi = {
  /** 获取决策层级列表 */
  getDecisionLevels: () =>
    api.get<DecisionLevel[]>('/api/ops/decision-levels'),

  /** 获取队列信息 */
  getQueues: () =>
    api.get<QueueInfo[]>('/api/ops/queues'),
};
