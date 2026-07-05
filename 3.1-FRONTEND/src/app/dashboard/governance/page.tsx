'use client';

import { GovernanceScreen } from '@/components/features/governance/GovernanceScreen';

export default function GovernancePage() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">治理面板</h1>
        <p className="text-xs text-slate-500">Draft→Gate→Approval→Apply→Audit</p>
      </div>
      <GovernanceScreen />
    </div>
  );
}
