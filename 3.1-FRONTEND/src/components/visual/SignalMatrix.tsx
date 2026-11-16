'use client';

// 加权信号点阵（TASKS-20261116 T9-1）
// 四轴（趋势/惯性/周期/前瞻）+ 合成列 + 五态：全部取自后端 D-E19 的
// annotations.cells / annotations.rows.strength，前端零重算（不做加权、不做分类估计）。
// 合成列只是把后端已算好的 `strength` 投影出来，颜色按后端阈值做展示映射。

import { V3Badge, V3Empty } from '@/components';
import type { MatrixAnnotations, MatrixCell, VisualSpec } from './types';

const STATE_STYLE: Record<
  string,
  { label: string; dot: string; cell: string; text: string }
> = {
  lit: {
    label: '点亮',
    dot: 'bg-emerald-400',
    cell: 'border-emerald-500/40 bg-emerald-500/10',
    text: 'text-emerald-300',
  },
  warm: {
    label: '预热',
    dot: 'bg-amber-400',
    cell: 'border-amber-500/40 bg-amber-500/10',
    text: 'text-amber-300',
  },
  dim: {
    label: '暗淡',
    dot: 'bg-slate-500',
    cell: 'border-slate-600/40 bg-slate-600/10',
    text: 'text-slate-400',
  },
  conflict: {
    label: '冲突',
    dot: 'bg-rose-400',
    cell: 'border-rose-500/40 bg-rose-500/10',
    text: 'text-rose-300',
  },
  unavailable: {
    label: '不可用',
    dot: 'bg-zinc-600',
    cell: 'border-zinc-700/40 bg-zinc-700/10',
    text: 'text-zinc-500',
  },
};

const STATE_ORDER = ['lit', 'warm', 'dim', 'conflict', 'unavailable'];
const AXIS_FALLBACK = ['trend', 'inertia', 'cycle', 'foresight'];

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(0)}%`;
}

function signArrow(sign: number | undefined): string {
  if (!sign) return '→';
  return sign > 0 ? '↑' : '↓';
}

/** 合成列配色：只用后端阈值做展示映射，不重新判定状态 */
function compositeClass(strength: number | null, annotations?: MatrixAnnotations): string {
  if (strength === null) return 'border-slate-700/40 bg-slate-800/20 text-slate-500';
  const lit = annotations?.thresholds?.lit_pct;
  const warm = annotations?.thresholds?.warm_pct;
  if (typeof lit === 'number' && strength >= lit) return STATE_STYLE.lit.cell + ' ' + STATE_STYLE.lit.text;
  if (typeof warm === 'number' && strength >= warm)
    return STATE_STYLE.warm.cell + ' ' + STATE_STYLE.warm.text;
  return STATE_STYLE.dim.cell + ' ' + STATE_STYLE.dim.text;
}

export function SignalMatrix({ visual }: { visual: VisualSpec }) {
  const dataset = (visual?.dataset ?? {}) as Record<string, unknown>;
  const rowLabels = (dataset.row_labels ?? []) as string[];
  const colLabels = (dataset.col_labels ?? []) as string[];
  const values = (dataset.values ?? []) as (number | null)[][];
  const annotations = visual?.annotations;
  const axes = annotations?.axes ?? [];

  if (!visual || rowLabels.length === 0 || colLabels.length === 0) {
    return <V3Empty title="点阵无数据" description="后端未返回 matrix 的行列标签（样本不足或落库缺失）" />;
  }

  const colKeys = colLabels.map((_, index) => axes[index]?.key ?? AXIS_FALLBACK[index] ?? String(index));
  const gridTemplateColumns = `minmax(112px, 1.4fr) repeat(${colLabels.length}, minmax(52px, 1fr)) minmax(68px, 1fr)`;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {STATE_ORDER.map((state) => {
          const style = STATE_STYLE[state];
          return (
            <span
              key={state}
              className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] ${style.cell} ${style.text}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
              {style.label}
            </span>
          );
        })}
        <span className="text-[10px] text-slate-500">
          箭头 = 轴值符号（↑正 / ↓负 / →中性）· 合成 = 后端 d19 strength
        </span>
        {annotations?.thresholds_uncalibrated && <V3Badge variant="warning" label="阈值未标定" />}
      </div>

      <div className="space-y-1">
        <div className="grid items-end gap-1.5" style={{ gridTemplateColumns }}>
          <div className="text-[10px] text-slate-500">标的</div>
          {colLabels.map((label, index) => (
            <div key={`${label}-${index}`} className="text-center">
              <p className="text-[10px] text-slate-300">{label}</p>
              <p className="text-[9px] text-slate-500">权重 {pct(axes[index]?.weight)}</p>
            </div>
          ))}
          <div className="text-center">
            <p className="text-[10px] text-slate-300">合成</p>
            <p className="text-[9px] text-slate-500">加权</p>
          </div>
        </div>

        {rowLabels.map((symbol, rowIndex) => {
          const rowMeta = annotations?.rows?.[symbol];
          const composite = rowMeta?.strength ?? null;
          return (
            <div key={symbol} className="grid items-center gap-1.5" style={{ gridTemplateColumns }}>
              <div className="min-w-0">
                <p className="truncate text-[11px] text-slate-200">{rowMeta?.label || symbol}</p>
                <p className="truncate text-[9px] text-slate-500">
                  {rowMeta?.class || '—'}
                  {rowMeta?.as_of ? ` · ${rowMeta.as_of}` : ''}
                </p>
              </div>

              {colLabels.map((_, colIndex) => {
                const axisKey = colKeys[colIndex];
                const cell: MatrixCell | undefined = annotations?.cells?.[`${symbol}|${axisKey}`];
                const state = cell?.state ?? 'unavailable';
                const style = STATE_STYLE[state] ?? STATE_STYLE.unavailable;
                const strength = values[rowIndex]?.[colIndex] ?? cell?.strength ?? null;
                const opacity =
                  strength === null ? 0.35 : 0.35 + 0.65 * Math.max(0, Math.min(1, strength));
                return (
                  <div
                    key={axisKey}
                    className={`flex h-9 items-center justify-center rounded-md border ${style.cell}`}
                    title={`${rowMeta?.label || symbol} · ${colLabels[colIndex]} · ${style.label} · 强度 ${pct(
                      strength,
                    )} · 符号 ${signArrow(cell?.sign)}`}
                  >
                    <span className={`h-2 w-2 rounded-full ${style.dot}`} style={{ opacity }} />
                    <span className="ml-1 text-[10px] text-slate-300">{signArrow(cell?.sign)}</span>
                  </div>
                );
              })}

              <div
                className={`flex h-9 items-center justify-center rounded-md border ${compositeClass(
                  composite,
                  annotations,
                )}`}
                title={`${rowMeta?.label || symbol} · 合成强度 ${pct(composite)}`}
              >
                <span className="font-mono text-[10px]">{pct(composite)}</span>
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-[10px] text-slate-500">
        合成强度由后端加权求和（Σ 轴权重 × 归一轴强），前端只展示
        {typeof annotations?.thresholds?.lit_pct === 'number'
          ? ` · 阈值 点亮≥${pct(annotations.thresholds.lit_pct)} · 预热≥${pct(
              annotations.thresholds.warm_pct,
            )}`
          : ''}
        {annotations?.light_weights_hash
          ? ` · 权重指纹 ${String(annotations.light_weights_hash).slice(0, 8)}`
          : ''}
      </p>
    </div>
  );
}

export default SignalMatrix;
