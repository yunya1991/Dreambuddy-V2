'use client';

import { V3Card } from '@/components';

const metrics = [
  { name: '活跃地址', value: '1.2M', change: '+5.3%', up: true },
  { name: '新增地址', value: '45.2K', change: '+2.1%', up: true },
  { name: '交易笔数', value: '312K', change: '-1.8%', up: false },
  { name: 'Gas 价格', value: '28 Gwei', change: '-12%', up: false },
  { name: 'TVL', value: '$52.3B', change: '+3.7%', up: true },
  { name: '大额转账', value: '156', change: '+22%', up: true },
  { name: '燃烧量', value: '2.1K ETH', change: '+8%', up: true },
  { name: 'DeFi 日活', value: '892K', change: '+4.2%', up: true },
];

export function OnchainMetrics() {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-300">链上核心指标</h3>
      <div className="grid grid-cols-2 gap-3">
        {metrics.map(m => (
          <V3Card key={m.name} padding="sm">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">{m.name}</span>
              <span className={`text-xs ${m.up ? 'text-emerald-400' : 'text-red-400'}`}>
                {m.up ? '↑' : '↓'} {m.change}
              </span>
            </div>
            <p className="text-lg font-semibold text-slate-200 mt-1">{m.value}</p>
          </V3Card>
        ))}
      </div>
    </div>
  );
}
