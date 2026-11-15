'use client';

// T2 曲线渲染：后端已给 sampling/smoothing/meta，前端只画线（零统计）

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { VisualPoint } from './types';

interface SeriesMeta {
  smoothing?: { method?: string; window?: number };
  unit?: string;
  n?: number;
  [key: string]: unknown;
}

export function SeriesView({ points, meta }: { points: VisualPoint[]; meta: SeriesMeta }) {
  const hasSmoothed = points.some(point => point.smoothed !== null && point.smoothed !== undefined);
  const smoothing = meta?.smoothing;
  const unit = meta?.unit;

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-2">
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="x" tick={{ fontSize: 10, fill: '#64748b' }} minTickGap={48} />
          <YAxis
            tick={{ fontSize: 10, fill: '#64748b' }}
            width={58}
            domain={['auto', 'auto']}
            tickFormatter={(value: number) =>
              Math.abs(value) >= 1000 ? value.toLocaleString('en-US', { maximumFractionDigits: 0 }) : String(value)
            }
          />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 11 }}
            labelStyle={{ color: '#94a3b8' }}
          />
          <Legend wrapperStyle={{ fontSize: 10, color: '#64748b' }} />
          <Line
            type="monotone"
            dataKey="y"
            name={unit ? `原始（${unit}）` : '原始'}
            stroke="#60a5fa"
            strokeWidth={1.5}
            dot={false}
            connectNulls={false}
          />
          {hasSmoothed && (
            <Line
              type="monotone"
              dataKey="smoothed"
              name={smoothing?.method ? `${smoothing.method}${smoothing.window ?? ''}` : '平滑'}
              stroke="#a78bfa"
              strokeWidth={1.2}
              dot={false}
              connectNulls={false}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
      <p className="px-1 pt-1 text-[10px] text-slate-500">
        样本 n={meta?.n ?? '—'}
        {smoothing?.method ? ` · 平滑=${smoothing.method}${smoothing.window ?? ''}` : ' · 未平滑'}
        {points.length > 0 ? ` · ${points.length} 点` : ''}
      </p>
    </div>
  );
}

export default SeriesView;
