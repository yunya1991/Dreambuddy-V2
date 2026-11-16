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
  /** 主览图多线：每条线对应 points[].members[key]（值已由后端 rebase，前端零重算） */
  lines?: { key: string; label: string }[];
  [key: string]: unknown;
}

type CoveragePoint = VisualPoint & {
  coverage_ratio?: number | null;
  partial_members?: string[] | null;
};

const LINE_COLORS = ['#60a5fa', '#fbbf24', '#34d399', '#f472b6', '#a78bfa', '#22d3ee'];

function coverageClass(ratio: number | null): string {
  if (ratio === null) return 'bg-slate-700/40';
  if (ratio >= 0.8) return 'bg-emerald-400/80';
  if (ratio >= 0.5) return 'bg-amber-400/80';
  return 'bg-rose-500/70';
}

export function SeriesView({ points, meta }: { points: VisualPoint[]; meta: SeriesMeta }) {
  const hasSmoothed = points.some(point => point.smoothed !== null && point.smoothed !== undefined);
  const smoothing = meta?.smoothing;
  const unit = meta?.unit;
  const lines = Array.isArray(meta?.lines) ? meta.lines : [];
  const isMultiLine = lines.length > 1;
  const coveragePoints = (points as CoveragePoint[]).filter(
    point => typeof point.coverage_ratio === 'number',
  );
  const hasCoverage = coveragePoints.length > 0;

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
          {isMultiLine ? (
            lines.map((line, index) => (
              <Line
                key={line.key}
                type="monotone"
                dataKey={(point: VisualPoint) => {
                  const members = (point as VisualPoint & { members?: Record<string, number | null> })
                    .members;
                  const value = members?.[line.key];
                  return value === undefined ? null : value;
                }}
                name={line.label}
                stroke={LINE_COLORS[index % LINE_COLORS.length]}
                strokeWidth={1.4}
                dot={false}
                connectNulls={false}
              />
            ))
          ) : (
            <>
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
                  name={
                    smoothing?.method ? `${smoothing.method}${smoothing.window ?? ''}` : '平滑'
                  }
                  stroke="#a78bfa"
                  strokeWidth={1.2}
                  dot={false}
                  connectNulls={false}
                />
              )}
            </>
          )}
        </LineChart>
      </ResponsiveContainer>
      {hasCoverage && (
        <div className="px-1 pt-1">
          <div className="flex h-1.5 w-full gap-px overflow-hidden rounded">
            {coveragePoints.map((point, index) => {
              const ratio =
                typeof point.coverage_ratio === 'number' ? (point.coverage_ratio as number) : null;
              const members = Array.isArray(point.partial_members)
                ? (point.partial_members as string[])
                : [];
              return (
                <div
                  key={`${point.x}-${index}`}
                  className={`flex-1 ${coverageClass(ratio)}`}
                  title={`${point.x} 覆盖 ${
                    ratio === null ? '—' : `${Math.round(ratio * 100)}%`
                  }${members.length > 0 ? ` · 缺失 ${members.join(',')}` : ''}`}
                />
              );
            })}
          </div>
          <p className="pt-1 text-[10px] text-slate-500">
            覆盖度带：绿≥80% · 黄≥50% · 红&lt;50%（逐点成员覆盖率；缺口不向前填充）
          </p>
        </div>
      )}
      <p className="px-1 pt-1 text-[10px] text-slate-500">
        样本 n={meta?.n ?? '—'}
        {smoothing?.method ? ` · 平滑=${smoothing.method}${smoothing.window ?? ''}` : ' · 未平滑'}
        {points.length > 0 ? ` · ${points.length} 点` : ''}
      </p>
    </div>
  );
}

export default SeriesView;
