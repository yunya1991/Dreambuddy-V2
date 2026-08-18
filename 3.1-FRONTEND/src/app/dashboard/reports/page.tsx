'use client';

import { ReportsScreen } from '@/components/features/reports/ReportsScreen';

export default function ReportsPage() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">产物中台</h1>
        <p className="text-xs text-slate-500">交易报告 · 数据产物 · 图表归档</p>
      </div>
      <ReportsScreen />
    </div>
  );
}
