'use client';

import { V3Card } from '@/components';

const coins = [
  { symbol: 'BTC', score: 72 }, { symbol: 'ETH', score: 68 }, { symbol: 'SOL', score: 85 },
  { symbol: 'BNB', score: 45 }, { symbol: 'ARB', score: 38 }, { symbol: 'AVAX', score: 55 },
  { symbol: 'DOT', score: 42 }, { symbol: 'MATIC', score: 35 }, { symbol: 'LINK', score: 62 },
  { symbol: 'UNI', score: 48 }, { symbol: 'ATOM', score: 52 }, { symbol: 'OP', score: 41 },
];

function getHeatColor(score: number): string {
  if (score >= 65) return 'bg-emerald-500/60';
  if (score >= 50) return 'bg-emerald-500/30';
  if (score >= 40) return 'bg-slate-500/30';
  return 'bg-red-500/30';
}

export function SentimentHeatmap() {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-300">市场情绪热力图</h3>
      <div className="grid grid-cols-4 gap-2">
        {coins.map(c => (
          <div key={c.symbol} className={`p-3 rounded-lg ${getHeatColor(c.score)} border border-slate-700/30 text-center`}>
            <p className="text-xs font-medium text-slate-300">{c.symbol}</p>
            <p className="text-lg font-bold text-slate-200">{c.score}</p>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-center gap-4 text-[10px] text-slate-500">
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-500/30" /> 恐惧</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-slate-500/30" /> 中性</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-emerald-500/60" /> 贪婪</span>
      </div>
    </div>
  );
}
