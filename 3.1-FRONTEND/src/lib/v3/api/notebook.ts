// ============================================
// Notebook 域客户端 — 笔记本域 API
// ============================================

import api from '../../api-client';

export interface NotebookState {
  [key: string]: unknown;
}

export const notebookApi = {
  /** 获取笔记本状态 */
  get: () =>
    api.get<NotebookState>('/api/notebook'),

  /** 同步笔记本内容 */
  sync: (body: unknown) =>
    api.post<{ success: boolean }>('/api/notebook/sync', body),

  /** 获取笔记本任务列表 */
  getTasks: () =>
    api.get<unknown[]>('/api/notebook/tasks'),

  /** 更新笔记本步骤 */
  updateStep: (body: unknown) =>
    api.post<{ success: boolean }>('/api/notebook/step', body),

  /** 获取笔记本运行状态 */
  getState: () =>
    api.get<NotebookState>('/api/notebook/state'),
};
