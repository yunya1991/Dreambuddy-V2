// ============================================
// Board 域客户端 — 治理域 API
// ============================================

import api from '../../api-client';

export interface BoardMetrics {
  [key: string]: unknown;
}

export interface Proposal {
  id: string;
  [key: string]: unknown;
}

export interface ApprovalSummary {
  total: number;
  pending: number;
  [key: string]: unknown;
}

export const boardApi = {
  /** 获取治理指标 */
  getMetrics: () =>
    api.get<BoardMetrics>('/api/board/metrics'),

  /** 获取提案列表 */
  listProposals: () =>
    api.get<Proposal[]>('/api/board/proposals'),

  /** 获取单条提案详情 */
  getProposal: (id: string) =>
    api.get<Proposal>(`/api/board/proposals/${id}`),

  /** 提交评审 */
  submitReview: (body: unknown) =>
    api.post<{ success: boolean }>('/api/board/review', body),

  /** 获取审批摘要 */
  getApprovalSummary: () =>
    api.get<ApprovalSummary>('/api/board/approval/summary'),

  /** 获取待审批列表 */
  getPendingApprovals: () =>
    api.get<Proposal[]>('/api/board/approval/pending'),

  /** 处理审批 */
  processApproval: (id: string, body: unknown) =>
    api.post<{ success: boolean }>(`/api/board/approval/${id}`, body),
};
