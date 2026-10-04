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
};
