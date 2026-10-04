'use client';

import { useClassicStore } from '@/stores';
import { V3Card, V3StatusDot, V3Badge } from '@/components';

const stageLabels = ['Draft', 'Gate', 'Approval', 'Apply', 'Audit'];
const stageChinese = ['草稿', '门禁', '审批', '应用', '审计'];

export function GovernanceFlow() {
  const {
    governance,
    approvalPending,
    approvalApprovedCount,
    approvalPendingCount,
    approvalLoading,
    pipelineGatePassed,
    pipelineApprovalId,
  } = useClassicStore();

  // 如果经典系统有真实 Gate/Approval 状态，覆盖治理流
  const enrichedGovernance = governance.map(g => {
    if (g.stage === 'gate' && pipelineGatePassed !== undefined) {
      return { ...g, status: pipelineGatePassed ? 'approved' as const : 'rejected' as const };
    }
    if (g.stage === 'approval' && pipelineApprovalId !== undefined) {
      return { ...g, status: 'approved' as const, comment: `approval_id=${pipelineApprovalId}` };
    }
    return g;
  });

  return (
    <V3Card title="治理审批流" padding="sm">
      {/* 真实审批统计 */}
      {!approvalLoading && (approvalApprovedCount !== undefined || approvalPendingCount !== undefined) && (
        <div className="flex items-center gap-2 mb-3">
          <V3Badge variant="success">已审批 {approvalApprovedCount ?? 0}</V3Badge>
          <V3Badge variant="info">待审批 {approvalPendingCount ?? 0}</V3Badge>
        </div>
      )}

      {/* 离线降级 */}
      {approvalLoading && (
        <div className="mb-3 text-[10px] text-slate-500">加载审批状态中...</div>
      )}

      {/* 待审批列表 */}
      {approvalPending && approvalPending.length > 0 && (
        <div className="mb-3 space-y-1">
          <p className="text-[10px] text-slate-500 mb-1">待审批项</p>
          {approvalPending.slice(0, 3).map((item, i) => (
            <div key={i} className="flex items-center justify-between p-1.5 rounded bg-slate-900/30 border border-slate-700/20">
              <span className="text-[10px] text-slate-400">{item.strategy_name || item.id || `item-${i}`}</span>
              <V3Badge variant="info">{item.status || 'pending'}</V3Badge>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between mb-3">
        {stageLabels.map((label, i) => {
          const g = enrichedGovernance.find(s => s.stage === label.toLowerCase() as any);
          const dotStatus = g?.status === 'approved' ? 'success' as const : g?.status === 'active' ? 'active' as const : g?.status === 'rejected' ? 'error' as const : 'idle' as const;
          return (
            <div key={label} className="flex items-center gap-1">
              <div className="flex flex-col items-center gap-1">
                <div className={`w-8 h-8 rounded-full border-2 flex items-center justify-center ${g?.status === 'approved' ? 'border-emerald-500 bg-emerald-900/30' : g?.status === 'active' ? 'border-blue-500 bg-blue-900/30' : g?.status === 'rejected' ? 'border-red-500 bg-red-900/30' : 'border-slate-700 bg-slate-800'}`}>
                  <V3StatusDot status={dotStatus} size="sm" />
                </div>
                <span className="text-[10px] text-slate-500">{stageChinese[i]}</span>
              </div>
              {i < stageLabels.length - 1 && <div className={`w-6 h-0.5 ${g?.status === 'approved' ? 'bg-emerald-500' : 'bg-slate-700'}`} />}
            </div>
          );
        })}
      </div>
      {enrichedGovernance.some(g => g.comment) && (
        <div className="mt-2 p-2 rounded bg-slate-900/30 border border-slate-700/20">
          {enrichedGovernance.filter(g => g.comment).map((g, i) => (
            <p key={i} className="text-[10px] text-slate-500">{g.stage}: {g.comment}</p>
          ))}
        </div>
      )}
    </V3Card>
  );
}
