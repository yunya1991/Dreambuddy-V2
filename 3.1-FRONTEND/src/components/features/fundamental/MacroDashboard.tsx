'use client';

import { V3Card, V3Badge } from '@/components';

const indicators = [
  { name: '美联储利率', value: '5.25%', prev: '5.25%', impact: 'neutral' },
  { name: 'CPI 同比', value: '3.2%', prev: '3.4%', impact: 'bullish' },
  { name: '非农就业', value: '216K', prev: '198K', impact: 'bearish' },
  { name: 'PMI 制造业', value: '49.2', prev: '48.7', impact: 'neutral' },
  { name: '美元指数', value: '104.5', prev: '103.8', impact: 'bearish' },
  { name: 'VIX 恐慌指数', value: '14.2', prev: '16.1', impact: 'bullish' },
];

const impactVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };
const impactLabel = { bullish: '利多', bearish: '利空', neutral: '中性' };

export function MacroDashboard() {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-300">宏观经济指标</h3>
      <div className="space-y-2">
        {indicators.map(m => (
          <V3Card key={m.name} padding="sm" hover>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-400 w-24">{m.name}</span>
                <span className="text-sm font-semibold text-slate-200">{m.value}</span>
                <span className="text-[10px] text-slate-600">前值: {m.prev}</span>
              </div>
              <V3Badge variant={impactVariant[m.impact]} label={impactLabel[m.impact]} />
            </div>
          </V3Card>
        ))}
      </div>
    </div>
  );
}
