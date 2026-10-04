// ============================================
// Artifact 域客户端 — 产物文件域 API
// ============================================

import api from '../../api-client';

export interface Artifact {
  id: string;
  [key: string]: unknown;
}

export const artifactApi = {
  /** 获取产物列表（/api/artifact 或 /api/artifacts） */
  list: () =>
    api.get<Artifact[]>('/api/artifacts'),

  /** 获取单个产物详情 */
  get: (id: string) =>
    api.get<Artifact>(`/api/artifacts/${id}`),
};
