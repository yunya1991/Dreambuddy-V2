'use client';

import { useState } from 'react';
import { FundamentalGrid } from '@/components/features/fundamental/FundamentalGrid';
import { OnchainMetrics } from '@/components/features/fundamental/OnchainMetrics';
import { MacroDashboard } from '@/components/features/fundamental/MacroDashboard';
import { SentimentHeatmap } from '@/components/features/fundamental/SentimentHeatmap';
import { ModuleDetail } from '@/components/features/fundamental/ModuleDetail';

const tabModules: Record<string, string> = {
  flow: 'flow',
  valuation: 'valuation',
  narrative: 'narrative',
  news: 'news',
  breadth: 'breadth',
  calendar: 'calendar',
  intermarket: 'intermarket',
};

const tabs = [
  { id: 'overview', label: '总览' },
  { id: 'onchain', label: '链上数据' },
  { id: 'macro', label: '宏观指标' },
  { id: 'sentiment', label: '市场情绪' },
  { id: 'flow', label: '资金流向' },
  { id: 'valuation', label: '估值模型' },
  { id: 'narrative', label: '叙事分析' },
  { id: 'news', label: '新闻监控' },
  { id: 'breadth', label: '市场广度' },
  { id: 'calendar', label: '经济日历' },
  { id: 'intermarket', label: '跨市场' },
];

export default function FundamentalPage() {
  const [activeTab, setActiveTab] = useState('overview');

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">基本面分析</h1>
        <p className="text-xs text-slate-500">多维基本面评估系统</p>
      </div>
      <div className="flex gap-1 overflow-x-auto pb-2">
        {tabs.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1.5 rounded-lg text-xs whitespace-nowrap transition-colors ${activeTab === tab.id ? 'bg-indigo-600/20 text-indigo-400' : 'text-slate-500 hover:bg-slate-800 hover:text-slate-300'}`}>
            {tab.label}
          </button>
        ))}
      </div>
      <div>
        {activeTab === 'overview' && <FundamentalGrid />}
        {activeTab === 'onchain' && <OnchainMetrics />}
        {activeTab === 'macro' && <MacroDashboard />}
        {activeTab === 'sentiment' && <SentimentHeatmap />}
        {tabModules[activeTab] && (
          <ModuleDetail
            key={activeTab}
            module={tabModules[activeTab]}
            title={tabs.find(t => t.id === activeTab)?.label || activeTab}
          />
        )}
      </div>
    </div>
  );
}
