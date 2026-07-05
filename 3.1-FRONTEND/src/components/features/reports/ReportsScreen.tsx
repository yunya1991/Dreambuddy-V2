'use client';

import { useState } from 'react';
import { V3Card, V3Badge, V3Empty, IconSearch } from '@/components';

const artifacts = [
  { id: 'a1', type: 'report', title: 'BTC 周度分析报告 2024-W12', date: '2024-03-22' },
  { id: 'a2', type: 'data', title: '链上数据快照 BTC', date: '2024-03-21' },
  { id: 'a3', type: 'chart', title: 'ETH/USDT 技术分析图', date: '2024-03-20' },
  { id: 'a4', type: 'text', title: '宏观策略备忘录', date: '2024-03-19' },
  { id: 'a5', type: 'report', title: 'SOL 风险评估报告', date: '2024-03-18' },
  { id: 'a6', type: 'chart', title: '资金流向分析图', date: '2024-03-17' },
];

const typeVariant: Record<string, 'default' | 'success' | 'warning' | 'sacg-a'> = { text: 'default', data: 'warning', chart: 'sacg-a', report: 'success' };
const typeLabel: Record<string, string> = { text: '文本', data: '数据', chart: '图表', report: '报告' };

export function ReportsScreen() {
  const [filter, setFilter] = useState<string>('all');
  const [search, setSearch] = useState('');

  const filtered = artifacts.filter(a => {
    if (filter !== 'all' && a.type !== filter) return false;
    if (search && !a.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <div className="flex-1 relative">
          <IconSearch className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-600" />
          <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索产物..." className="w-full bg-slate-900/50 border border-slate-700/50 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50" />
        </div>
        <div className="flex gap-1">
          {['all', 'report', 'data', 'chart', 'text'].map(f => (
            <button key={f} onClick={() => setFilter(f)} className={`px-2 py-1 rounded text-[10px] ${filter === f ? 'bg-indigo-600/20 text-indigo-400' : 'text-slate-500 hover:text-slate-300'}`}>
              {f === 'all' ? '全部' : typeLabel[f]}
            </button>
          ))}
        </div>
      </div>
      <V3Card>
        {filtered.length === 0 ? (
          <V3Empty title="未找到产物" description="尝试调整搜索条件或类型筛选" />
        ) : (
          <div className="space-y-1.5">
            {filtered.map(a => (
              <div key={a.id} className="flex items-center justify-between p-3 rounded-lg hover:bg-slate-800/50 transition-colors">
                <div className="flex items-center gap-3">
                  <V3Badge variant={typeVariant[a.type]} label={typeLabel[a.type]} />
                  <span className="text-sm text-slate-300">{a.title}</span>
                </div>
                <span className="text-[10px] text-slate-600">{a.date}</span>
              </div>
            ))}
          </div>
        )}
      </V3Card>
    </div>
  );
}
