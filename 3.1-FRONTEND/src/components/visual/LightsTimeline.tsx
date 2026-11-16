'use client';

// 点亮图影（TASKS-20261116 T9-2）：标的 × as_of 影带
// 数据来自后端 D-E19 的逐期回放（`lights.history[]`），前端只做「期 → 色块」的展示折叠：
// 行级色 = 该期后端 summary 计数的投影（冲突优先 → 点亮 → 预热 → 不可用 → 暗淡），不重算任何轴。
// 后端未回放历史时只显示最新一期，并显式提示可回放的期数；缺期不补造。

import { useMemo, useState } from 'react';
import { V3Empty } from '@/components';
import type { LightRow } from './types';

export interface LightsPeriod {
  as_of: string;
  rows: LightRow[];
}

const BAND_STYLE: Record<string, { label: string; block: string; text: string }> = {
  conflict: { label: '冲突', block: 'bg-rose-500/70', text: 'text-rose-300' },
  lit: { label: '点亮', block: 'bg-emerald-500/70', text: 'text-emerald-300' },
  warm: { label: '预热', block: 'bg-amber-500/60', text: 'text-amber-300' },
  dim: { label: '暗淡', block: 'bg-slate-600/60', text: 'text-slate-400' },
  unavailable: { label: '不可用', block: 'bg-zinc-700/50', text: 'text-zinc-500' },
};

const LEGEND = ['lit', 'warm', 'dim', 'conflict', 'unavailable'];

/** 行级色：只折叠后端 counts，不做加权/阈值估计 */
export function bandState(row: LightRow | undefined): string {
  if (!row) return 'unavailable';
  const summary = row.summary || { lit_n: 0, warm_n: 0, conflict_n: 0, unavailable_n: 0 };
  if ((summary.conflict_n ?? 0) > 0) return 'conflict';
  if ((summary.lit_n ?? 0) > 0) return 'lit';
  if ((summary.warm_n ?? 0) > 0) return 'warm';
  if ((summary.unavailable_n ?? 0) >= 4) return 'unavailable';
  return 'dim';
}

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(0)}%`;
}

interface LightsTimelineProps {
  periods: LightsPeriod[];
  loading?: boolean;
  error?: string;
  onRequestHistory?: () => void;
  historyCount?: number;
}

export function LightsTimeline({
  periods,
  loading = false,
  error,
  onRequestHistory,
  historyCount = 12,
}: LightsTimelineProps) {
  const ordered = useMemo(
    () => [...(periods ?? [])].sort((a, b) => (a.as_of < b.as_of ? 1 : -1)),
    [periods],
  );
  const [selected, setSelected] = useState(0);

  if (!ordered.length) {
    return (
      <V3Empty
        title="点亮影带无数据"
        description="后端未返回 D-E19 点亮结果（样本不足或落库缺失）；历史未回放时不补造影带"
      />
    );
  }

  const active = ordered[Math.min(selected, ordered.length - 1)];
  const symbols = active.rows.map((row) => row.symbol);
  const byPeriod = new Map(ordered.map((period) => [period.as_of, period]));
  const gridTemplateColumns = `minmax(96px, 1.2fr) repeat(${ordered.length}, minmax(10px, 1fr))`;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {LEGEND.map((state) => (
          <span key={state} className="inline-flex items-center gap-1 text-[10px] text-slate-400">
            <span className={`h-2 w-2 rounded-sm ${BAND_STYLE[state].block}`} />
            {BAND_STYLE[state].label}
          </span>
        ))}
        <span className="text-[10px] text-slate-500">
          {ordered.length} 期 · 最新 {ordered[0].as_of}
        </span>
        {onRequestHistory && (
          <button
            type="button"
            onClick={onRequestHistory}
            disabled={loading}
            className="ml-auto rounded-md border border-indigo-500/40 bg-indigo-500/15 px-2 py-0.5 text-[10px] text-indigo-200 hover:bg-indigo-500/25 disabled:border-slate-800 disabled:bg-transparent disabled:text-slate-600"
          >
            {loading ? '回放中…' : `回放最近 ${historyCount} 期`}
          </button>
        )}
      </div>

      {error && <p className="text-[11px] text-amber-400">影带回放降级：{error}</p>}

      <div className="space-y-1">
        <div className="grid items-end gap-1" style={{ gridTemplateColumns }}>
          <div className="text-[10px] text-slate-500">标的 \ 期</div>
          {ordered.map((period, index) => (
            <button
              key={period.as_of}
              type="button"
              title={period.as_of}
              onClick={() => setSelected(index)}
              className={`h-4 rounded-sm text-[9px] ${
                index === selected ? 'bg-indigo-500/30 text-indigo-200' : 'text-slate-600 hover:bg-slate-800'
              }`}
            >
              {period.as_of.slice(5)}
            </button>
          ))}
        </div>

        {symbols.map((symbol) => (
          <div key={symbol} className="grid items-center gap-1" style={{ gridTemplateColumns }}>
            <div className="truncate text-[11px] text-slate-200">{symbol}</div>
            {ordered.map((period) => {
              const periodRows = byPeriod.get(period.as_of)?.rows ?? [];
              const row = periodRows.find((item) => item.symbol === symbol);
              const state = bandState(row);
              const style = BAND_STYLE[state] ?? BAND_STYLE.unavailable;
              return (
                <div
                  key={`${symbol}-${period.as_of}`}
                  title={`${symbol} · ${period.as_of} · ${style.label} · 合成强度 ${pct(row?.strength)}`}
                  className={`h-4 rounded-sm ${style.block} ${
                    period.as_of === active.as_of ? '' : 'opacity-70'
                  }`}
                />
              );
            })}
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2">
        <p className="text-[10px] text-slate-500">
          {active.as_of} · 行级色 = 后端四轴计数的展示折叠（冲突优先），非新统计量
        </p>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
          {active.rows.map((row) => {
            const style = BAND_STYLE[bandState(row)] ?? BAND_STYLE.unavailable;
            return (
              <span key={row.symbol} className={`text-[10px] ${style.text}`}>
                {row.symbol} {pct(row.strength)} · 点亮{row.summary?.lit_n ?? 0}/预热
                {row.summary?.warm_n ?? 0}
                {row.as_of && row.as_of !== active.as_of ? ` · 行内 ${row.as_of}` : ''}
              </span>
            );
          })}
        </div>
      </div>

      <p className="text-[10px] text-slate-500">
        影带只展示后端逐期回放的 D-E19 判定；某期缺失则该列不出现，不用邻期填充。
      </p>
    </div>
  );
}

export default LightsTimeline;
