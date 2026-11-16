'use client';

// 数据研究 · 技术图表（同一入口，两个主 Tab）
// 主 Tab：数据研究（研究视图 / 卡片模式）、技术图表（八子页）。
// 两个子看板各自只读；卡片模式配置仍落 localStorage，不触碰研究视图与注册表。

import { useState } from 'react';
import { DataResearchBoard } from './DataResearchBoard';
import { DataResearchCardBoard } from './DataResearchCardBoard';
import { TechnicalChartBoard } from './TechnicalChartBoard';

export type HubTab = 'research' | 'technical';
type ResearchMode = 'view' | 'cards';

const MAIN_TABS: { id: HubTab; title: string; sub: string; steps: string }[] = [
  {
    id: 'research',
    title: '数据研究',
    sub: '目标 → 分类 → 归纳 → 验证 → 卡片',
    steps: 'S1–S5',
  },
  {
    id: 'technical',
    title: '技术图表',
    sub: '点阵 → 图影 → 叠加 → 反馈',
    steps: 'T1–T8',
  },
];

export function VisualHub({ initialTab = 'research' }: { initialTab?: HubTab }) {
  const [tab, setTab] = useState<HubTab>(initialTab);
  const [mode, setMode] = useState<ResearchMode>('view');

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">数据研究 · 技术图表</h1>
          <p className="mt-1 text-xs text-slate-500">
            研究结论与读图证据在同一入口；两个主 Tab 平级，互不改写
          </p>
        </div>
      </header>

      <div className="grid gap-2.5 sm:grid-cols-2">
        {MAIN_TABS.map((item) => {
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`relative overflow-hidden rounded-xl border px-3.5 py-3 text-left transition-colors ${
                active
                  ? 'border-indigo-500/55 bg-gradient-to-b from-indigo-500/12 to-indigo-500/[0.03]'
                  : 'border-slate-800 bg-slate-900/40 hover:border-slate-700'
              }`}
            >
              <span className={`flex items-center gap-2 text-sm font-semibold ${active ? 'text-indigo-200' : 'text-slate-300'}`}>
                {item.title}
              </span>
              <span className="mt-1 block text-[10.5px] text-slate-500">{item.sub}</span>
              <span className={`absolute right-3.5 top-3 font-mono text-[9px] ${active ? 'text-indigo-300' : 'text-slate-600'}`}>
                {item.steps}
              </span>
            </button>
          );
        })}
      </div>

      {tab === 'research' && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2">
          <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5">
            <button
              type="button"
              onClick={() => setMode('view')}
              className={`rounded-md px-2.5 py-1 text-[11px] ${
                mode === 'view' ? 'bg-indigo-500/20 text-indigo-200' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              研究视图
            </button>
            <button
              type="button"
              onClick={() => setMode('cards')}
              className={`rounded-md px-2.5 py-1 text-[11px] ${
                mode === 'cards' ? 'bg-indigo-500/20 text-indigo-200' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              卡片模式
            </button>
          </div>
          <span className="text-[10px] text-slate-600">
            {mode === 'view' ? '固定五子页，只读历史统计' : '自定义 tab / 能力卡，仅存浏览器本地'}
          </span>
        </div>
      )}

      {tab === 'research' &&
        (mode === 'view' ? <DataResearchBoard embedded /> : <DataResearchCardBoard />)}
      {tab === 'technical' && <TechnicalChartBoard embedded />}
    </div>
  );
}

export default VisualHub;
