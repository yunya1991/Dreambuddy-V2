'use client';

import { useState } from 'react';
import { V3Card, V3Badge } from '@/components';

type BACLevel = 'B' | 'A' | 'C';
const levelLabels = { B: 'Blueprint 蓝图', A: 'Architecture 架构', C: 'Chronicle 编年' };
const levelColors = { B: 'border-blue-500/30 bg-blue-900/10', A: 'border-purple-500/30 bg-purple-900/10', C: 'border-amber-500/30 bg-amber-900/10' };
const levelVariant = { B: 'sacg-a' as const, A: 'sacg-s' as const, C: 'sacg-g' as const };

const checkpoints = [
  { id: 'cp1', level: 'B', timestamp: Date.now() - 86400000, entries: 156, compressed: false },
  { id: 'cp2', level: 'A', timestamp: Date.now() - 43200000, entries: 42, compressed: false },
  { id: 'cp3', level: 'C', timestamp: Date.now() - 3600000, entries: 12, compressed: true },
  { id: 'cp4', level: 'B', timestamp: Date.now() - 1800000, entries: 203, compressed: false },
  { id: 'cp5', level: 'A', timestamp: Date.now() - 600000, entries: 58, compressed: false },
];

export function BACTimeline() {
  const [selectedLevel, setSelectedLevel] = useState<BACLevel>('B');

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-4">
        {(Object.keys(levelLabels) as BACLevel[]).map(level => (
          <button key={level} onClick={() => setSelectedLevel(level)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs transition-colors ${selectedLevel === level ? levelColors[level] : 'border-slate-700/30 bg-slate-800/30 text-slate-500 hover:text-slate-300'}`}>
            <V3Badge variant={levelVariant[level]} dot label={level} />
            <span>{levelLabels[level]}</span>
          </button>
        ))}
      </div>
      <V3Card title={`${levelLabels[selectedLevel]} 层`} padding="sm">
        <div className="space-y-2">
          {checkpoints.filter(cp => cp.level === selectedLevel).map(cp => (
            <div key={cp.id} className={`flex items-center justify-between p-3 rounded-lg border ${levelColors[cp.level]}`}>
              <div className="flex items-center gap-3">
                <V3Badge variant={levelVariant[cp.level]} label={cp.level} />
                <div>
                  <p className="text-xs text-slate-300">{cp.entries} 条记录</p>
                  <p className="text-[10px] text-slate-500">{new Date(cp.timestamp).toLocaleString('zh-CN')}</p>
                </div>
              </div>
              {cp.compressed && <V3Badge variant="success" label="已压缩" />}
            </div>
          ))}
          {checkpoints.filter(cp => cp.level === selectedLevel).length === 0 && (
            <p className="text-xs text-slate-500 text-center py-4">暂无检查点</p>
          )}
        </div>
      </V3Card>
      <div className="p-3 rounded-lg bg-slate-800/30 border border-slate-700/20">
        <p className="text-[10px] text-slate-500 mb-1">压缩方向</p>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-blue-400">B (全量)</span>
          <span className="text-slate-600">→</span>
          <span className="text-purple-400">A (结构化)</span>
          <span className="text-slate-600">→</span>
          <span className="text-amber-400">C (压缩)</span>
        </div>
        <p className="text-[10px] text-slate-600 mt-1">正向展开: C→A→B / 反向压缩: B→A→C</p>
      </div>
    </div>
  );
}
