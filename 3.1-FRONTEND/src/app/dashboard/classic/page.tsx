'use client';

import { ClassicPhaseIndicator } from '@/components/features/classic/ClassicPhaseIndicator';
import { ClassicPhasePanel } from '@/components/features/classic/ClassicPhasePanel';
import { GovernanceFlow } from '@/components/features/classic/GovernanceFlow';
import { IndicatorPanel } from '@/components/features/classic/IndicatorPanel';

export default function ClassicPage() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">经典交易系统</h1>
        <p className="text-xs text-slate-500">C0→C8 八阶段流水线 + Draft→Gate→Approval→Apply→Audit 治理审批流</p>
      </div>
      <ClassicPhaseIndicator />
      <div className="grid grid-cols-5 gap-4">
        <div className="col-span-3">
          <ClassicPhasePanel />
        </div>
        <div className="col-span-2 space-y-4">
          <GovernanceFlow />
          <IndicatorPanel />
        </div>
      </div>
    </div>
  );
}
