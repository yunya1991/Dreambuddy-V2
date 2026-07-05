'use client';

import { V3Card, V3Badge, V3StatusDot } from '@/components';

const proposals = [
  { id: '1', title: 'BTC 多头策略调整', status: 'active', votes: { for: 3, against: 0 }, stage: 'approval' },
  { id: '2', title: 'SOL 仓位减半', status: 'approved', votes: { for: 4, against: 1 }, stage: 'audit' },
  { id: '3', title: 'ETH 链上分析请求', status: 'pending', votes: { for: 0, against: 0 }, stage: 'draft' },
];

const stageLabels: Record<string, string> = { draft: '草稿', gate: '门禁', approval: '审批', apply: '应用', audit: '审计' };
const statusVariant: Record<string, 'default' | 'success' | 'warning' | 'danger'> = { pending: 'default', active: 'warning', approved: 'success', rejected: 'danger' };

export function GovernanceScreen() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
        {Object.entries(stageLabels).map(([stage, label]) => (
          <div key={stage} className="flex items-center gap-1">
            <div className="w-8 h-8 rounded-full border-2 border-slate-700 flex items-center justify-center">
              <span className="text-[10px] text-slate-500">{label}</span>
            </div>
            {stage !== 'audit' && <span className="text-slate-700 mx-1">→</span>}
          </div>
        ))}
      </div>
      <V3Card title="提案列表" actions={<span className="text-xs text-slate-500">{proposals.length} 个</span>}>
        <div className="space-y-2">
          {proposals.map(p => (
            <div key={p.id} className="flex items-center justify-between p-3 rounded-lg bg-slate-900/50 border border-slate-700/30">
              <div className="flex items-center gap-3">
                <V3StatusDot status={p.status === 'active' ? 'active' : p.status === 'approved' ? 'success' : p.status === 'rejected' ? 'error' : 'idle'} size="sm" />
                <div>
                  <p className="text-sm text-slate-200">{p.title}</p>
                  <p className="text-[10px] text-slate-500">阶段: {stageLabels[p.stage]}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <V3Badge variant={statusVariant[p.status]} label={p.status === 'active' ? '审批中' : p.status === 'approved' ? '已通过' : p.status === 'rejected' ? '已拒绝' : '待处理'} />
                <span className="text-[10px] text-emerald-400">+{p.votes.for}</span>
                <span className="text-[10px] text-red-400">-{p.votes.against}</span>
              </div>
            </div>
          ))}
        </div>
      </V3Card>
    </div>
  );
}
