// ============================================
// Monitor 域客户端 — 监控域 API
// ============================================

import api from '../../api-client';

export interface MonitorStats {
  [key: string]: unknown;
}

export interface MonitorEvent {
  id: string;
  [key: string]: unknown;
}

export const monitorApi = {
  /** 获取监控统计 */
  getStats: () =>
    api.get<MonitorStats>('/api/monitor/stats'),

  /** SSE 流地址 */
  streamUrl: '/api/monitor/stream',

  /** 获取监控事件列表 */
  getEvents: () =>
    api.get<MonitorEvent[]>('/api/monitor/events'),

  /** 获取主动推送消息 */
  getProactive: () =>
    api.get<unknown[]>('/api/monitor/proactive'),
};
