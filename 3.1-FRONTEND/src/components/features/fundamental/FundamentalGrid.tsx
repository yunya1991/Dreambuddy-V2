'use client';

import { V3Card, V3Badge } from '@/components';

const metrics = [
  { name: '市盈率 (P/E)', value: '24.5', signal: 'bearish', desc: '高于行业平均' },
  { name: '网络增长', value: '+3.2%', signal: 'bullish', desc: '月度活跃地址上升' },
  { name: '开发者活跃度', value: '85/100', signal: 'bullish', desc: 'GitHub commits 活跃' },
  { name: 'NVT 比率', value: '45', signal: 'neutral', desc: '处于正常区间' },
  { name: 'MVRV', value: '1.8', signal: 'bearish', desc: '略高于历史均值' },
  { name: '交易所流出', value: '+12K BTC', signal: 'bullish', desc: '长期持有趋势' },
  { name: '稳定币供给', value: '+$2.1B', signal: 'bullish', desc: '持续资金流入' },
  { name: '期货费率', value: '0.01%', signal: 'neutral', desc: '中性偏多' },
  { name: '期权 PCR', value: '0.85', signal: 'bullish', desc: '看涨期权略多' },
  { name: '鲸鱼动向', value: '净买入', signal: 'bullish', desc: '大户地址增持' },
  { name: '哈希率', value: '+5.1%', signal: 'neutral', desc: '算力稳步增长' },
  { name: '链上交易量', value: '$4.2B', signal: 'neutral', desc: '日均水平' },
];

const signalVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };
const signalLabel = { bullish: '看多', bearish: '看空', neutral: '中性' };

export function FundamentalGrid() {
  return (
    <div className="grid grid-cols-3 gap-3">
      {metrics.map(m => (
        <V3Card key={m.name} padding="sm" hover>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-slate-500">{m.name}</span>
            <V3Badge variant={signalVariant[m.signal]} label={signalLabel[m.signal]} />
          </div>
          <p className="text-lg font-semibold text-slate-200 mb-0.5">{m.value}</p>
          <p className="text-[10px] text-slate-500">{m.desc}</p>
        </V3Card>
      ))}
    </div>
  );
}
