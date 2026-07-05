'use client';

import { useState, useEffect } from 'react';
import { V3Card, V3Button } from '@/components';

interface TimelineEvent {
  id: string;
  layer: 'S' | 'A' | 'C' | 'G';
  label: string;
  timestamp: number;
}

const mockEvents: TimelineEvent[] = [
  { id: 'e1', layer: 'S', label: '意图识别: 分析BTC趋势', timestamp: 0 },
  { id: 'e2', layer: 'S', label: '市场感知: 获取实时数据', timestamp: 1500 },
  { id: 'e3', layer: 'A', label: '编排: 创建研究链', timestamp: 3000 },
  { id: 'e4', layer: 'A', label: 'DAG: 3个并行节点', timestamp: 4500 },
  { id: 'e5', layer: 'C', label: '执行: 运行技术分析', timestamp: 6000 },
  { id: 'e6', layer: 'C', label: '执行: 运行链上分析', timestamp: 7500 },
  { id: 'e7', layer: 'G', label: '存储: 保存分析结果', timestamp: 9000 },
  { id: 'e8', layer: 'G', label: '压缩: BAC 压缩归档', timestamp: 10500 },
];

const layerColors: Record<string, string> = { S: 'text-purple-400', A: 'text-blue-400', C: 'text-emerald-400', G: 'text-amber-400' };
const layerBg: Record<string, string> = { S: 'bg-purple-500/10 border-purple-500/20', A: 'bg-blue-500/10 border-blue-500/20', C: 'bg-emerald-500/10 border-emerald-500/20', G: 'bg-amber-500/10 border-amber-500/20' };

export function HistoryPlayer() {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [speed, setSpeed] = useState(1);

  const visibleEvents = mockEvents.slice(0, currentIdx + 1);
  const progress = mockEvents.length > 0 ? ((currentIdx + 1) / mockEvents.length) * 100 : 0;

  useEffect(() => {
    if (!isPlaying) return;
    const timer = setInterval(() => {
      setCurrentIdx(prev => {
        if (prev >= mockEvents.length - 1) { setIsPlaying(false); return prev; }
        return prev + 1;
      });
    }, 2000 / speed);
    return () => clearInterval(timer);
  }, [isPlaying, speed]);

  return (
    <V3Card title="SACG 历史回放" padding="md">
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <V3Button size="sm" variant={isPlaying ? 'danger' : 'primary'} onClick={() => setIsPlaying(!isPlaying)}>
            {isPlaying ? '⏸ 暂停' : '▶ 播放'}
          </V3Button>
          <V3Button size="sm" variant="ghost" onClick={() => setCurrentIdx(Math.max(0, currentIdx - 1))}>⏮</V3Button>
          <V3Button size="sm" variant="ghost" onClick={() => setCurrentIdx(Math.min(mockEvents.length - 1, currentIdx + 1))}>⏭</V3Button>
          <V3Button size="sm" variant="ghost" onClick={() => { setIsPlaying(false); setCurrentIdx(0); }}>⏹ 重置</V3Button>
          <div className="ml-auto flex items-center gap-1">
            <span className="text-[10px] text-slate-500">速度:</span>
            {[0.5, 1, 2, 4].map(s => (
              <button key={s} onClick={() => setSpeed(s)} className={`px-1.5 py-0.5 rounded text-[10px] ${speed === s ? 'bg-indigo-600/20 text-indigo-400' : 'text-slate-500'}`}>{s}x</button>
            ))}
          </div>
        </div>
        <div className="relative h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="absolute left-0 top-0 h-full bg-indigo-500 rounded-full transition-all duration-500" style={{ width: `${progress}%` }} />
        </div>
        <div className="flex items-center justify-between text-[10px] text-slate-500">
          <span>步骤 {currentIdx + 1} / {mockEvents.length}</span>
          <span>{progress.toFixed(0)}%</span>
        </div>
        <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
          {visibleEvents.map(event => (
            <div key={event.id} className={`flex items-center gap-2 p-2 rounded-lg border ${layerBg[event.layer]}`}>
              <span className={`text-xs font-mono font-bold ${layerColors[event.layer]}`}>{event.layer}</span>
              <span className="text-xs text-slate-300">{event.label}</span>
            </div>
          ))}
        </div>
      </div>
    </V3Card>
  );
}
