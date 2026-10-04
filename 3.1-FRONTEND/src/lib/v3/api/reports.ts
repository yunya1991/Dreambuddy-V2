// ============================================
// Reports 域客户端 — 研报域 API
// ============================================

import api from '../../api-client';

export interface Report {
  id: string;
  title: string;
  [key: string]: unknown;
}

export interface Briefing {
  id: string;
  title: string;
  [key: string]: unknown;
}

export const reportsApi = {
  /** 获取研报列表 */
  list: () =>
    api.get<Report[]>('/api/reports'),

  /** 获取简报列表 */
  getBriefings: () =>
    api.get<Briefing[]>('/api/briefings'),

  /** 获取单条简报详情 */
  getBriefing: (id: string) =>
    api.get<Briefing>(`/api/briefings/${id}`),
};
