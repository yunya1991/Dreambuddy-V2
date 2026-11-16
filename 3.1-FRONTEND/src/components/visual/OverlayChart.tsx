'use client';

// 技术分析叠加（TASKS-20261116 T9-3）：价格 + MA + ATR 带 + 分位条 + 点亮日
// 原则：每一层都必须有后端来源；来源缺失时该层不画、并在来源清单里标 missing，绝不补造。
// 前端零统计：价格/MA 取 D-E15 已算好的 points，分位取 D-A04，点亮日取 D-E19 的 as_of。

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { VisualPoint } from './types';

export interface OverlaySource {
  id: string;
  label: string;
  capability: string | null;
  status: 'ok' | 'missing';
  detail?: string;
}

export interface PercentileSnapshot {
  value: number | null;
  lookback?: number | null;
  sample_n?: number | null;
}

interface OverlayChartProps {
  points: VisualPoint[];
  smoothing?: { method?: string; window?: number };
  unit?: string;
  percentile?: PercentileSnapshot | null;
  litDays?: string[];
  sources?: OverlaySource[];
  title?: string;
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function OverlayChart({
  points,
  smoothing,
  unit,
  percentile,
  litDays = [],
  sources = [],
  title,
}: OverlayChartProps) {
  if (!points || points.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800/60 bg-slate-900/30 px-3 py-6 text-center text-[11px] text-slate-500">
        未提供价格序列（D-E15），不画叠加图
      </div>
    );
  }

  const hasMa = points.some((point) => num(point.smoothed) !== null);
  const hasBand = points.some(
    (point) => num(point.atr_upper) !== null && num(point.atr_lower) !== null,
  );
  const litSet = new Set(litDays.filter(Boolean));
  const percentileValue = percentile?.value ?? null;

  return (
    <div className="space-y-2">
      {title && <p className="text-[11px] text-slate-400">{title}</p>}
      <div className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-2">
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="x" tick={{ fontSize: 10, fill: '#64748b' }} minTickGap={48} />
            <YAxis
              tick={{ fontSize: 10, fill: '#64748b' }}
              width={58}
              domain={['auto', 'auto']}
              tickFormatter={(value: number) =>
                Math.abs(value) >= 1000
                  ? value.toLocaleString('en-US', { maximumFractionDigits: 0 })
                  : String(value)
              }
            />
            <Tooltip
              contentStyle={{
                background: '#0f172a',
                border: '1px solid #1e293b',
                borderRadius: 8,
                fontSize: 11,
              }}
              labelStyle={{ color: '#94a3b8' }}
            />
            <Legend wrapperStyle={{ fontSize: 10, color: '#64748b' }} />

            {hasBand && (
              <Area
                type="monotone"
                dataKey="atr_upper"
                name="ATR 上轨"
                stroke="none"
                fill="#f59e0b"
                fillOpacity={0.12}
                connectNulls={false}
                isAnimationActive={false}
              />
            )}
            {hasBand && (
              <Area
                type="monotone"
                dataKey="atr_lower"
                name="ATR 下轨"
                stroke="none"
                fill="#0f172a"
                fillOpacity={0.9}
                connectNulls={false}
                isAnimationActive={false}
              />
            )}

            <Line
              type="monotone"
              dataKey="y"
              name={unit ? `价格（${unit}）` : '价格'}
              stroke="#60a5fa"
              strokeWidth={1.5}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            {hasMa && (
              <Line
                type="monotone"
                dataKey="smoothed"
                name={smoothing?.method ? `${smoothing.method}${smoothing.window ?? ''}` : 'MA'}
                stroke="#a78bfa"
                strokeWidth={1.2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            )}

            {[...litSet].map((day) => (
              <ReferenceLine
                key={day}
                x={day}
                stroke="#34d399"
                strokeDasharray="4 3"
                label={{ value: '点亮', fill: '#34d399', fontSize: 9, position: 'insideTopRight' }}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>

        <div className="px-1 pt-2">
          <div className="flex items-center gap-2">
            <span className="w-16 shrink-0 text-[10px] text-slate-500">历史分位</span>
            <div className="relative h-2 flex-1 overflow-hidden rounded bg-slate-700/40">
              {percentileValue !== null && (
                <div
                  className="absolute inset-y-0 left-0 rounded bg-indigo-500/60"
                  style={{ width: `${Math.max(0, Math.min(1, percentileValue)) * 100}%` }}
                />
              )}
            </div>
            <span className="w-24 shrink-0 text-right font-mono text-[10px] text-slate-400">
              {percentileValue === null
                ? '—'
                : `${(Math.max(0, Math.min(1, percentileValue)) * 100).toFixed(0)}%`}
            </span>
          </div>
          <p className="pt-1 text-[10px] text-slate-500">
            分位来自 D-A04
            {percentile?.lookback ? ` · lookback ${percentile.lookback}` : ''}
            {typeof percentile?.sample_n === 'number' ? ` · n ${percentile.sample_n}` : ''}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[10px]">
        <span className="text-slate-500">叠加来源：</span>
        {sources.map((source) => (
          <span
            key={source.id}
            title={source.detail}
            className={`rounded border px-1.5 py-0.5 ${
              source.status === 'ok'
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : 'border-amber-500/30 bg-amber-500/10 text-amber-300'
            }`}
          >
            {source.label}
            {source.capability ? ` · ${source.capability}` : ''}
            {source.status === 'missing' ? ' · 未接线' : ''}
          </span>
        ))}
      </div>

      <p className="text-[10px] text-slate-500">
        点亮日为 D-E19 的 as_of（虚线）；ATR 带需后端提供 `atr_upper/atr_lower`，缺失时该层不画也不估算。
      </p>
    </div>
  );
}

export default OverlayChart;
