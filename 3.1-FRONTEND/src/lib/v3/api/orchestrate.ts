// ============================================
// Orchestrate 域客户端 — 编排域 API
// ============================================
// 无直接路由，通过 bridge 调用编排引擎

import api from '../../api-client';

export const orchestrateApi = {
  /** 编排执行 */
  orchestrate: (body: unknown) =>
    api.post<unknown>('/api/orchestrate', body),
};
