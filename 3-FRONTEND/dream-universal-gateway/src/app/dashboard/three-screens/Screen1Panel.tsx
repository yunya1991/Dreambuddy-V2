'use client';

import { useThreeScreensStore } from '@/stores';
import { V3Card, V3Badge } from '@/components';

const dimLabels = ['宏观', '链上', '技术', '情绪', '基本面', '择时', '风控'];
const dimKeys = ['macro', 'onchain', 'technical', 'sentiment', 'fundamental', 'timing', 'risk'] as const;

export function Screen1Panel() {
  const { screen1 } = useThreeScreensStore();

  if (!screen1) {
    return <V3Card><p className="text-sm text-slate-500">Screen1 战略层未启动</p></V3Card>;
  }

  const dirColor = screen1.directionAnchor === 'bullish' ? 'text-emerald-400' : screen1.directionAnchor === 'bearish' ? 'text-red-400' : 'text-slate-400';
  const dirLabel = screen1.directionAnchor === 'bullish' ? '看多' : screen1.directionAnchor === 'bearish' ? '看空' : '中性';

  return (
    <V3Card title="Screen 1 · 战略层" subtitle="周线方向">
      <div className="space-y-4">
        <div className="flex items-center justify-between p-3 rounded-lg bg-slate-900/50 border border-slate-700/30">
          <span className="text-xs text-slate-500">方向锚定</span>
          <span className={`text-lg font-bold ${dirColor}`}>{dirLabel}</span>
        </div>
        <div className="grid grid-cols-7 gap-2">
          {dimKeys.map((key, i) => {
            const dim = screen1.dimensions[key];
            const color = dim.score >= 70 ? 'text-emerald-400 border-emerald-500/30' : dim.score >= 40 ? 'text-amber-400 border-amber-500/30' : 'text-red-400 border-red-500/30';
            return (
              <div key={key} className={`flex flex-col items-center p-2 rounded-lg border ${color} bg-slate-900/50`}>
                <svg className="w-8 h-8" viewBox="0 0 36 36">
                  <circle cx="18" cy="18" r="15.5" fill="none" stroke="currentColor" strokeWidth="3" opacity="0.2" />
                  <circle cx="18" cy="18" r="15.5" fill="none" stroke="currentColor" strokeWidth="3" strokeDasharray={`${dim.score} ${100 - dim.score}`} strokeLinecap="round" transform="rotate(-90 18 18)" />
                </svg>
                <span className="text-[10px] mt-1">{dimLabels[i]}</span>
                <span className="text-xs font-semibold">{dim.score}</span>
              </div>
            );
          })}
        </div>
        {screen1.debate && (
          <div className="p-3 rounded-lg bg-purple-900/10 border border-purple-500/20">
            <p className="text-[10px] text-purple-400 mb-1">大师辩论摘要</p>
            <p className="text-xs text-slate-400">{screen1.debate}</p>
          </div>
        )}
      </div>
    </V3Card>
  );
}
