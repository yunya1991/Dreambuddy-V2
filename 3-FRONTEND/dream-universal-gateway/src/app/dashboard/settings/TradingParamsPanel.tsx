'use client';

import { V3Card } from '@/components';

const params = [
  { label: '最大持仓', value: '3', unit: '个' },
  { label: '单笔风险', value: '2', unit: '%' },
  { label: '止损比例', value: '1.5', unit: '%' },
  { label: '止盈比例', value: '3:1', unit: '' },
  { label: '杠杆倍数', value: '3x', unit: '' },
  { label: '最小交易额', value: '100', unit: 'USDT' },
  { label: '滑点容忍', value: '0.1', unit: '%' },
  { label: '冷却期', value: '30', unit: 'min' },
];

export function TradingParamsPanel() {
  return (
    <V3Card title="交易参数">
      <div className="grid grid-cols-2 gap-3">
        {params.map(p => (
          <div key={p.label} className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/30">
            <p className="text-[10px] text-slate-500 mb-1">{p.label}</p>
            <p className="text-lg font-semibold text-slate-200">
              {p.value}<span className="text-xs text-slate-500 ml-1">{p.unit}</span>
            </p>
          </div>
        ))}
      </div>
      <div className="mt-4 p-3 rounded-lg bg-slate-900/30 border border-slate-700/20">
        <p className="text-[10px] text-slate-500 mb-1">允许交易品种</p>
        <div className="flex flex-wrap gap-1">
          {['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT', 'ARB-USDT'].map(s => (
            <span key={s} className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400">{s}</span>
          ))}
        </div>
      </div>
    </V3Card>
  );
}
