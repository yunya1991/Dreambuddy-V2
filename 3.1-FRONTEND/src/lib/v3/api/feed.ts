// ============================================
// Feed 域客户端 — 消息流域 API
// ============================================

import api from '../../api-client';

export interface FeedItem {
  id: string;
  [key: string]: unknown;
}

export const feedApi = {
  /** 获取消息流 */
  get: () =>
    api.get<FeedItem[]>('/api/feed'),

  /** 获取消息流（可按 workflow_type 过滤） */
  list: (workflowType?: string) =>
    api.get<FeedItem[]>('/api/feed', workflowType ? { workflow_type: workflowType } : undefined),
};
