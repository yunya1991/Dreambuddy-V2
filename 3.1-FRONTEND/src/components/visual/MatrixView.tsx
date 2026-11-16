'use client';

// SPEC-54 matrix 渲染：加权信号点阵（资产 × 四轴）
// 前端零统计——状态色 / 强度 / 轴值符号全部来自后端 annotations，前端只做映射与格式化

import type { MatrixAnnotations, MatrixCell } from './types';

const STATE_STYLE: Record<string, { label: string; dot: string; cell: string }> = {
  lit: { label: '点亮', dot: 'bg-emerald-400', cell: 'border-emerald-500/40 bg-emerald-500/10' },
  warm: { label: '预热', dot: 'bg-amber-400', cell: 'border-amber-500/40 bg-amber-500/10' },
  dim: { label: '暗淡', dot: 'bg-slate-500', cell: 'border-slate-600/40 bg-slate-600/10' },
  conflict: { label: '冲突', dot: 'bg-rose-400', cell: 'border-rose-500/40 bg-rose-500/10' },
  unavailable: {
    label: '不可用',
    dot: 'bg-zinc-600',
    cell: 'border-zinc-700/40 bg-zinc-700/10',
  },
};

const STATE_ORDER = ['lit', 'warm', 'dim', 'conflict', 'unavailable'];
const AXIS_KEYS = ['trend', 'inertia', 'cycle', 'foresight'];

function signArrow(sign: number | undefined): string {
  if (sign === undefined || sign === null || sign === 0) return '→';
  return sign > 0 ? '↑' : '↓';
}

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(0)}%`;
}

export function MatrixView({
  rowLabels,
  colLabels,
  values,
  annotations,
}: {
  rowLabels: string[];
  colLabels: string[];
  values: (number | null)[][];
  annotations?: MatrixAnnotations;
}) {
  const axes = annotations?.axes ?? [];
  const colKeys = colLabels.map((_, index) => axes[index]?.key ?? AXIS_KEYS[index] ?? String(index));
  const gridTemplateColumns = `minmax(108px, 1.5fr) repeat(${colLabels.length}, minmax(56px, 1fr))`;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {STATE_ORDER.map(state => {
          const style = STATE_STYLE[state];
          return (
            <span
              key={state}
              className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] ${style.cell}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
              {style.label}
            </span>
          );
        })}
        <span className="text-[10px] text-slate-500">箭头：↑ 轴值为正 · ↓ 为负 · → 中性</span>
      </div>

      <div className="space-y-1">
        <div className="grid items-end gap-1.5" style={{ gridTemplateColumns }}>
          <div className="text-[10px] text-slate-500">资产</div>
          {colLabels.map((label, index) => (
            <div key={`${label}-${index}`} className="text-center">
              <p className="text-[10px] text-slate-300">{label}</p>
              <p className="text-[9px] text-slate-500">权重 {pct(axes[index]?.weight)}</p>
            </div>
          ))}
        </div>

        {rowLabels.map((symbol, rowIndex) => {
          const meta = annotations?.rows?.[symbol];
          return (
            <div key={symbol} className="grid items-center gap-1.5" style={{ gridTemplateColumns }}>
              <div className="min-w-0">
                <p className="truncate text-[11px] text-slate-200">{meta?.label || symbol}</p>
                <p className="truncate text-[9px] text-slate-500">
                  {meta?.class || '—'}
                  {meta?.as_of ? ` · ${meta.as_of}` : ''}
                </p>
              </div>
              {colLabels.map((_, colIndex) => {
                const axisKey = colKeys[colIndex];
                const cell: MatrixCell | undefined = annotations?.cells?.[`${symbol}|${axisKey}`];
                const style = STATE_STYLE[cell?.state ?? 'unavailable'] ?? STATE_STYLE.unavailable;
                const strength = values[rowIndex]?.[colIndex] ?? cell?.strength ?? null;
                const opacity = strength === null ? 0.35 : 0.35 + 0.65 * Math.max(0, Math.min(1, strength));
                return (
                  <div
                    key={axisKey}
                    className={`flex h-9 items-center justify-center rounded-md border ${style.cell}`}
                    title={`${meta?.label || symbol} · ${colLabels[colIndex]} · ${style.label} · 强度 ${pct(
                      strength,
                    )} · 符号 ${signArrow(cell?.sign)}`}
                  >
                    <span
                      className={`h-2 w-2 rounded-full ${style.dot}`}
                      style={{ opacity }}
                    />
                    <span className="ml-1 text-[10px] text-slate-300">{signArrow(cell?.sign)}</span>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

      <p className="text-[10px] text-slate-500">
        点大小/透明度 = 轴强度（|轴值| / 轴权重，零重算）
        {typeof annotations?.thresholds?.lit_pct === 'number'
          ? ` · 阈值 点亮≥${pct(annotations.thresholds.lit_pct)} · 预热≥${pct(
              annotations.thresholds.warm_pct,
            )}`
          : ''}
        {annotations?.thresholds_uncalibrated ? ' · 阈值未标定' : ''}
        {annotations?.light_weights_hash
          ? ` · hash ${String(annotations.light_weights_hash).slice(0, 8)}`
          : ''}
      </p>
    </div>
  );
}

export default MatrixView;
