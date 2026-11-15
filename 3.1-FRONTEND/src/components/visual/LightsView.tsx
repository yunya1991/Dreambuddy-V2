'use client';

// SPEC-54 D-E19 点亮投影渲染：五态色 + 四轴强度
// 前端零统计——只展示后端已判定的 state/bucket/strength（LT-AC3 零重算）

import { V3Badge, V3Empty } from '@/components';
import type { LightAxis, LightAxisKey, LightRow, LightState, LightsPayload } from './types';

const STATE_STYLE: Record<LightState, { label: string; chip: string; dot: string }> = {
  lit: {
    label: '点亮',
    chip: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
    dot: 'bg-emerald-400',
  },
  warm: {
    label: '预热',
    chip: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
    dot: 'bg-amber-400',
  },
  dim: {
    label: '暗淡',
    chip: 'bg-slate-600/20 text-slate-400 border-slate-600/40',
    dot: 'bg-slate-500',
  },
  conflict: {
    label: '冲突',
    chip: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
    dot: 'bg-rose-400',
  },
  unavailable: {
    label: '不可用',
    chip: 'bg-zinc-700/20 text-zinc-500 border-zinc-700/40',
    dot: 'bg-zinc-600',
  },
};

const AXES: { key: LightAxisKey; label: string }[] = [
  { key: 'trend', label: '趋势' },
  { key: 'inertia', label: '惯性' },
  { key: 'cycle', label: '周期' },
  { key: 'foresight', label: '前瞻' },
];

const STATE_ORDER: LightState[] = ['lit', 'warm', 'dim', 'conflict', 'unavailable'];

function strengthText(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(0)}%`;
}

function AxisChip({ axis }: { axis?: LightAxis }) {
  if (!axis) {
    return (
      <span className={`rounded border px-1.5 py-0.5 text-[10px] ${STATE_STYLE.unavailable.chip}`}>
        不可用
      </span>
    );
  }
  const style = STATE_STYLE[axis.state] ?? STATE_STYLE.unavailable;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] ${style.chip}`}
      title={`${style.label} · 强度 ${strengthText(axis.strength)} · 桶 ${axis.bucket}${
        axis.flags?.length ? ` · ${axis.flags.join(',')}` : ''
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {style.label}
    </span>
  );
}

function LightCard({ row }: { row: LightRow }) {
  const ratio = Math.max(0, Math.min(1, row.strength ?? 0));
  return (
    <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-slate-200">{row.symbol}</p>
          <p className="text-[10px] text-slate-500">
            {row.class}
            {row.as_of ? ` · ${row.as_of}` : ''}
            {typeof row.n === 'number' ? ` · n=${row.n}` : ''}
          </p>
        </div>
        <span className="shrink-0 text-[11px] font-medium text-slate-300">{strengthText(row.strength)}</span>
      </div>

      <div className="mb-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-700/40">
        <div
          className={`h-full rounded-full ${ratio >= 0.7 ? 'bg-emerald-400' : ratio >= 0.4 ? 'bg-amber-400' : 'bg-slate-500'}`}
          style={{ width: `${Math.round(ratio * 100)}%` }}
        />
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        {AXES.map(axis => (
          <div key={axis.key} className="flex items-center justify-between gap-1">
            <span className="text-[10px] text-slate-500">{axis.label}</span>
            <AxisChip axis={row.axes?.[axis.key]} />
          </div>
        ))}
      </div>

      <p className="mt-2 text-[10px] text-slate-500">
        点亮 {row.summary?.lit_n ?? 0} · 预热 {row.summary?.warm_n ?? 0} · 冲突{' '}
        {row.summary?.conflict_n ?? 0} · 不可用 {row.summary?.unavailable_n ?? 0}
      </p>
      {row.flags?.length ? (
        <p className="mt-1 truncate text-[10px] text-amber-500/70" title={row.flags.join(',')}>
          {row.flags.join(', ')}
        </p>
      ) : null}
    </div>
  );
}

export function LightsView({ payload }: { payload: LightsPayload }) {
  const rows = payload?.rows ?? [];
  const meta = payload?.meta;
  if (!payload?.ok || rows.length === 0) {
    return <V3Empty title="点亮投影不可用" description="后端未返回 D-E19 点亮结果（样本不足或落库缺失）" />;
  }

  const thresholds = meta?.thresholds;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {STATE_ORDER.map(state => (
          <span
            key={state}
            className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] ${STATE_STYLE[state].chip}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${STATE_STYLE[state].dot}`} />
            {STATE_STYLE[state].label}
          </span>
        ))}
        {thresholds && (
          <span className="text-[10px] text-slate-500">
            阈值 点亮≥{strengthText(thresholds.lit_pct)} · 预热≥{strengthText(thresholds.warm_pct)}
          </span>
        )}
        {meta?.thresholds_uncalibrated && <V3Badge variant="warning" label="阈值未标定" />}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {rows.map(row => (
          <LightCard key={row.symbol} row={row} />
        ))}
      </div>

      <p className="text-[10px] text-slate-500">
        轴强度 = |轴值| / 轴权重（零重算）· 权重 {meta?.light_weights_mode ?? '—'}
        {meta?.light_weights_hash ? ` · hash ${String(meta.light_weights_hash).slice(0, 8)}` : ''}
        {typeof meta?.min_rows === 'number' ? ` · 样本门 ${meta.min_rows}` : ''}
        {payload.answer ? ` · ${payload.answer}` : ''}
      </p>
    </div>
  );
}

export default LightsView;
