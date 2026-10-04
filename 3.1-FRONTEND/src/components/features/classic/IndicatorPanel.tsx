'use client';

import { useState } from 'react';
import { useClassicStore } from '@/stores';
import { V3Card, V3Badge } from '@/components';
import { IconSearch } from '@/components';

export function IndicatorPanel() {
  const { indicators, timeframe, toggleIndicator, setTimeframe, gateThresholds } = useClassicStore();
  const [search, setSearch] = useState('');

  const filtered = indicators.filter(ind => ind.name.toLowerCase().includes(search.toLowerCase()));

  const timeframes = ['5M', '15M', '1H', '4H', '1D', '1W'];

  // Gate 阈值展示
  const gateEntries = gateThresholds
    ? Object.entries(gateThresholds).filter(([k]) => k !== 'oos_ok' && k !== 'sensitivity_ok')
    : [];

  return (
    <V3Card title="技术指标配置" padding="sm">
      <div className="space-y-3">
        {/* ===== Gate 阈值（来自经典系统）===== */}
        {gateEntries.length > 0 && (
          <div className="p-2 rounded-lg bg-emerald-900/10 border border-emerald-500/20">
            <p className="text-[10px] text-emerald-400 mb-1.5">Gate 阈值（经典系统）</p>
            <div className="flex flex-wrap gap-1">
              {gateEntries.map(([k, v]) => (
                <span key={k} className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/30 text-emerald-300">
                  {k}: {typeof v === 'number' ? v.toFixed(2) : String(v)}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-2">
          <div className="flex-1 relative">
            <IconSearch className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-600" />
            <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索指标..." className="w-full bg-slate-900/50 border border-slate-700/50 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50" />
          </div>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-slate-500">周期:</span>
          {timeframes.map(tf => (
            <button key={tf} onClick={() => setTimeframe(tf)} className={`px-2 py-0.5 rounded text-[10px] ${timeframe === tf ? 'bg-indigo-600/20 text-indigo-400' : 'text-slate-500 hover:text-slate-300'}`}>{tf}</button>
          ))}
        </div>
        <div className="space-y-1.5">
          {filtered.map(ind => (
            <div key={ind.name} className="flex items-center justify-between p-2 rounded-lg bg-slate-900/30 border border-slate-700/20">
              <div className="flex items-center gap-2">
                <button onClick={() => toggleIndicator(ind.name)} className={`w-3 h-3 rounded-full border-2 ${ind.enabled ? 'bg-emerald-500 border-emerald-500' : 'border-slate-600'}`} />
                <span className="text-xs text-slate-300">{ind.name}</span>
              </div>
              <div className="flex gap-1">
                {Object.entries(ind.params).map(([k, v]) => (
                  <span key={k} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-500">{k}: {v}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </V3Card>
  );
}
