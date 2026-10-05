'use client';

import { useState, useEffect, useMemo } from 'react';
import { V3Card, V3Button, V3Empty } from '@/components';
import { useMonitorStore, type SACGLayerEvent } from '@/stores';

const layerColors: Record<string, string> = { S: 'text-purple-400', A: 'text-blue-400', C: 'text-emerald-400', G: 'text-amber-400' };
const layerBg: Record<string, string> = { S: 'bg-purple-500/10 border-purple-500/20', A: 'bg-blue-500/10 border-blue-500/20', C: 'bg-emerald-500/10 border-emerald-500/20', G: 'bg-amber-500/10 border-amber-500/20' };

export function HistoryPlayer() {
  const { sLayerEvents, aLayerEvents, cLayerEvents, gLayerEvents } = useMonitorStore();
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [speed, setSpeed] = useState(1);

  // 合并四层真实事件，按时间戳升序排列
  const allEvents = useMemo<SACGLayerEvent[]>(() => {
    const merged = [...sLayerEvents, ...aLayerEvents, ...cLayerEvents, ...gLayerEvents];
    return merged.sort((a, b) => a.timestamp - b.timestamp);
  }, [sLayerEvents, aLayerEvents, cLayerEvents, gLayerEvents]);

  const visibleEvents = allEvents.slice(0, currentIdx + 1);
  const progress = allEvents.length > 0 ? ((currentIdx + 1) / allEvents.length) * 100 : 0;

  // 播放：自动推进
  useEffect(() => {
    if (!isPlaying) return;
    const timer = setInterval(() => {
      setCurrentIdx(prev => {
        if (prev >= allEvents.length - 1) { setIsPlaying(false); return prev; }
        return prev + 1;
      });
    }, 2000 / speed);
    return () => clearInterval(timer);
  }, [isPlaying, speed, allEvents.length]);

  // 新事件到来时，如果在播放则自动跟随；否则重置到末尾
  useEffect(() => {
    if (allEvents.length > 0 && currentIdx >= allEvents.length) {
      setCurrentIdx(allEvents.length - 1);
    }
  }, [allEvents.length, currentIdx]);

  return (
    <V3Card title="SACG 历史回放" padding="md">
      <div className="space-y-4">
        {/* 播放控制 */}
        <div className="flex items-center gap-2">
          <V3Button size="sm" variant={isPlaying ? 'danger' : 'primary'} onClick={() => setIsPlaying(!isPlaying)}>
            {isPlaying ? '⏸ 暂停' : '▶ 播放'}
          </V3Button>
          <V3Button size="sm" variant="ghost" onClick={() => setCurrentIdx(Math.max(0, currentIdx - 1))}>⏮</V3Button>
          <V3Button size="sm" variant="ghost" onClick={() => setCurrentIdx(Math.min(allEvents.length - 1, currentIdx + 1))}>⏭</V3Button>
          <V3Button size="sm" variant="ghost" onClick={() => { setIsPlaying(false); setCurrentIdx(0); }}>⏹ 重置</V3Button>
          <div className="ml-auto flex items-center gap-1">
            <span className="text-[10px] text-slate-500">速度:</span>
            {[0.5, 1, 2, 4].map(s => (
              <button key={s} onClick={() => setSpeed(s)} className={`px-1.5 py-0.5 rounded text-[10px] ${speed === s ? 'bg-indigo-600/20 text-indigo-400' : 'text-slate-500'}`}>{s}x</button>
            ))}
          </div>
        </div>

        {/* 进度条 */}
        <div className="relative h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="absolute left-0 top-0 h-full bg-indigo-500 rounded-full transition-all duration-500" style={{ width: `${progress}%` }} />
        </div>
        <div className="flex items-center justify-between text-[10px] text-slate-500">
          <span>步骤 {allEvents.length > 0 ? currentIdx + 1 : 0} / {allEvents.length}</span>
          <span>{progress.toFixed(0)}%</span>
        </div>

        {/* 事件时间线 */}
        {allEvents.length === 0 ? (
          <V3Empty title="暂无 SACG 事件" description="等待感知/编排/执行/存储层产生事件" />
        ) : (
          <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
            {visibleEvents.map(event => (
              <div key={event.id} className={`flex items-center gap-2 p-2 rounded-lg border ${layerBg[event.layer]}`}>
                <span className={`text-xs font-mono font-bold ${layerColors[event.layer]}`}>{event.layer}</span>
                <span className="text-xs text-slate-300 flex-1 truncate">{event.description}</span>
                <span className="text-[10px] text-slate-500 flex-shrink-0">
                  {event.duration ? `${event.duration}ms` : new Date(event.timestamp).toLocaleTimeString('zh-CN')}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </V3Card>
  );
}
