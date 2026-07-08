'use client';

import { useState } from 'react';
import { SACGOverview } from '@/components/features/monitor/SACGOverview';
import { DAGGraphView } from '@/components/features/monitor/DAGGraphView';
import { BACTimeline } from '@/components/features/sacg/BACTimeline';
import { HistoryPlayer } from '@/components/features/sacg/HistoryPlayer';

const tabs = [
  { id: 'overview', label: 'SACG 总览' },
  { id: 'dag', label: 'DAG 图' },
  { id: 'bac', label: 'BAC 压缩' },
  { id: 'history', label: '历史回放' },
];

export default function MonitorPage() {
  const [activeTab, setActiveTab] = useState('overview');

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">SACG 监控</h1>
        <p className="text-xs text-slate-500">四层运行状态监控</p>
      </div>
      <div className="flex gap-1">
        {tabs.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1.5 rounded-lg text-xs transition-colors ${activeTab === tab.id ? 'bg-indigo-600/20 text-indigo-400' : 'text-slate-500 hover:bg-slate-800 hover:text-slate-300'}`}>
            {tab.label}
          </button>
        ))}
      </div>
      {activeTab === 'overview' && <SACGOverview />}
      {activeTab === 'dag' && <DAGGraphView />}
      {activeTab === 'bac' && <BACTimeline />}
      {activeTab === 'history' && <HistoryPlayer />}
    </div>
  );
}
