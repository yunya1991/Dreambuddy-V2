'use client';

import { useClassicStore } from '@/stores';
import { V3Card, V3StatusDot } from '@/components';

const stageLabels = ['Draft', 'Gate', 'Approval', 'Apply', 'Audit'];
const stageChinese = ['草稿', '门禁', '审批', '应用', '审计'];

export function GovernanceFlow() {
  const { governance } = useClassicStore();

  return (
    <V3Card title="治理审批流" padding="sm">
      <div className="flex items-center justify-between mb-3">
        {stageLabels.map((label, i) => {
          const g = governance.find(s => s.stage === label.toLowerCase() as any);
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
      {governance.some(g => g.comment) && (
        <div className="mt-2 p-2 rounded bg-slate-900/30 border border-slate-700/20">
          {governance.filter(g => g.comment).map((g, i) => (
            <p key={i} className="text-[10px] text-slate-500">{g.stage}: {g.comment}</p>
          ))}
        </div>
      )}
    </V3Card>
  );
}
