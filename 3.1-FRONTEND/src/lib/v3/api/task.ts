// ============================================
// Task 域客户端 — 任务管理 API
// ============================================

import api from '../../api-client';

export interface TaskResult {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  result?: unknown;
  error?: string;
  created_at?: string;
  updated_at?: string;
}

export const taskApi = {
  /** 获取任务结果 */
  getResult: (taskId: string) =>
    api.get<TaskResult>(`/api/task/result/${taskId}`),

  /** 获取任务列表 */
  list: (params?: { status?: string; limit?: number }) =>
    api.get<TaskResult[]>('/api/task/list', params as Record<string, string> | undefined),

  /** 创建任务 */
  create: (body: { type: string; input?: unknown }) =>
    api.post<TaskResult>('/api/task/create', body),

  /** 取消任务 */
  cancel: (taskId: string) =>
    api.post<{ success: boolean }>(`/api/task/${taskId}/cancel`),
};
