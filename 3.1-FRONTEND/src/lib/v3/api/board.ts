// ============================================
// Board 域客户端 — 治理域 API
// P0: 收紧 Proposal 接口 + deriveStageFromStatus 派生函数
// P1: 加 vote/getProposalVotes 方法接入 /votes 路由
// ============================================

import api from '../../api-client';

export interface BoardMetrics {
  [key: string]: unknown;
}

// Prisma StrategyStatus 枚举 (schema.prisma 第 268-274 行)
export type StrategyStatus = 'DRAFT' | 'APPROVED' | 'APPLIED' | 'PAUSED' | 'EXPIRED';

// 治理流程五阶段: 草稿 → 门禁 → 审批 → 应用 → 审计
// 注: gate(门禁) 阶段无 StrategyStatus 对应, 仅在头部流程图中作视觉占位
export type Stage = 'draft' | 'gate' | 'approval' | 'apply' | 'audit';

export interface Proposal {
  id: string;
  title: string;
  // 后端 MOCK_PROPOSALS 含 status:'EXECUTING' (不在 Prisma 枚举内) — deriveStageFromStatus 兜底处理
  status: StrategyStatus | string;
  type?: string;
  department?: string;
  direction?: string;
  symbol?: string;
  confidence?: number | null;
  edgeScore?: number | null;
  createdAt: string;
  dataSource?: 'mock' | 'db';   // P1: 标记数据来源, 前端显示「（演示数据）」角标
}

export interface ApprovalSummary {
  total: number;
  pending: number;
  [key: string]: unknown;
}

// P1: 提案投票
export interface ProposalVote {
  id: string;
  vote: 'FOR' | 'AGAINST';
  createdAt?: string;
}

/**
 * 由 StrategyStatus 派生治理 Stage
 * 映射表: DRAFT→draft, APPROVED→approval, APPLIED→apply, PAUSED/EXPIRED→audit, 其他→audit(兜底)
 */
export function deriveStageFromStatus(status: string): Stage {
  switch (status) {
    case 'DRAFT':
      return 'draft';
    case 'APPROVED':
      return 'approval';
    case 'APPLIED':
      return 'apply';
    case 'PAUSED':
    case 'EXPIRED':
      return 'audit';
    default:
      // 'EXECUTING' 或其他未知值 — 兜底归入审计
      return 'audit';
  }
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

  // P1: 投票交互 — 调用 /api/board/proposals/:id/votes 路由
  /** 投票 (P1: voter 后端硬编码 anonymous, P2 接 next-auth) */
  vote: (proposalId: string, vote: 'FOR' | 'AGAINST') =>
    api.post<{ success: boolean; id?: string }>(`/api/board/proposals/${proposalId}/votes`, { vote }),

  /** 获取提案所有投票 */
  getProposalVotes: (proposalId: string) =>
    api.get<ProposalVote[]>(`/api/board/proposals/${proposalId}/votes`),
};
