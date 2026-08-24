import React, { useMemo, useState } from 'react';
import {
  LineChart, Line, YAxis, ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Badge } from '../ui/badge';
import {
  DOTPLOT_INDICATOR_NAMES, DOTPLOT_INDICATOR_LABELS,
} from '../../lib/api';
import { useEvolution } from './EvolutionContext';

function valueColor(v: number): string {
  if (v > 0.5) return 'text-green-600 bg-green-50';
  if (v < -0.5) return 'text-red-600 bg-red-50';
  return 'text-slate-600 bg-slate-50';
}

function heatmapColor(v: number, min: number, max: number): string {
  if (max <= min) return '#e2e8f0';
  const t = (v - min) / (max - min); // 0..1
  if (t > 0.66) return '#16a34a';
  if (t > 0.33) return '#eab308';
  return '#ef4444';
}

export const IndicatorDiagnosticPanel: React.FC = () => {
  const { data } = useEvolution();
  const [mode, setMode] = useState<'sparkline' | 'heatmap'>('sparkline');

  const indicators = data?.indicators || {};
  const trajectory = data?.trajectory || [];
  const dates = trajectory.map((d) => d.t);

  // 每个 indicator 的 {values, latest, min, max}
  const indStats = useMemo(() => {
    const stats: Record<string, { values: number[]; latest: number; min: number; max: number }> = {};
    for (const name of DOTPLOT_INDICATOR_NAMES) {
      const vals = (indicators[name] || []).map((v) => (typeof v === 'number' ? v : 0));
      const valid = vals.filter((v) => Number.isFinite(v));
      stats[name] = {
        values: vals,
        latest: vals.length ? vals[vals.length - 1] : 0,
        min: valid.length ? Math.min(...valid) : 0,
        max: valid.length ? Math.max(...valid) : 1,
      };
    }
    return stats;
  }, [indicators]);

  // heatmap 数据
  const heatmapRows = useMemo(() => {
    if (mode !== 'heatmap') return [];
    // 取最后 30 天
    const window = 30;
    const rows: Array<{ name: string; cells: Array<{ date: string; v: number }> }> = [];
    for (const name of DOTPLOT_INDICATOR_NAMES) {
      const vals = indStats[name]?.values || [];
      const startIdx = Math.max(0, vals.length - window);
      const cells = vals.slice(startIdx).map((v, i) => ({
        date: dates[startIdx + i] || '',
        v,
      }));
      rows.push({ name, cells });
    }
    return rows;
  }, [mode, indStats, dates]);

  // 全局 min/max for heatmap normalization
  const globalMinMax = useMemo(() => {
    let gMin = Infinity, gMax = -Infinity;
    for (const name of DOTPLOT_INDICATOR_NAMES) {
      const s = indStats[name];
      if (!s) continue;
      gMin = Math.min(gMin, s.min);
      gMax = Math.max(gMax, s.max);
    }
    if (!Number.isFinite(gMin)) { gMin = 0; gMax = 1; }
    return { gMin, gMax };
  }, [indStats]);

  const sparklineData = (name: string) => {
    const vals = indStats[name]?.values || [];
    return vals.map((v, i) => ({ idx: i, v, date: dates[i] || '' }));
  };

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Panel 4: 指标演变诊断条</CardTitle>
          <div className="flex gap-1">
            <button
              onClick={() => setMode('sparkline')}
              className={`rounded px-2 py-0.5 text-xs ${mode === 'sparkline' ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-600'}`}
            >
              Sparkline
            </button>
            <button
              onClick={() => setMode('heatmap')}
              className={`rounded px-2 py-0.5 text-xs ${mode === 'heatmap' ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-600'}`}
            >
              Heatmap
            </button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {trajectory.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-sm text-slate-400">暂无数据</div>
        ) : mode === 'sparkline' ? (
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
            {DOTPLOT_INDICATOR_NAMES.map((name) => {
              const s = indStats[name];
              if (!s) return null;
              const label = DOTPLOT_INDICATOR_LABELS[name] || name;
              return (
                <div key={name} className="rounded border border-slate-200 p-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-medium text-slate-600">{label}</span>
                    <Badge variant="outline" className={`text-[10px] ${valueColor(s.latest)}`}>
                      {s.latest.toFixed(2)}
                    </Badge>
                  </div>
                  <ResponsiveContainer width="100%" height={36}>
                    <LineChart data={sparklineData(name)} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                      <YAxis domain={['dataMin', 'dataMax']} hide />
                      <Line
                        type="monotone" dataKey="v"
                        stroke="#3b82f6" strokeWidth={1}
                        dot={false}
                      />
                      <ReferenceLine y={0} stroke="#cbd5e1" strokeDasharray="2 2" />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]">
              <thead>
                <tr>
                  <th className="sticky left-0 bg-white px-2 py-1 text-left text-slate-500">指标</th>
                  {heatmapRows[0]?.cells.map((c, i) => (
                    <th key={i} className="px-0.5 py-1 text-slate-400" style={{ minWidth: 18 }}>
                      {c.date.slice(5)}
                    </th>
                  )) || null}
                </tr>
              </thead>
              <tbody>
                {heatmapRows.map((row) => (
                  <tr key={row.name}>
                    <td className="sticky left-0 bg-white px-2 py-0.5 text-left font-medium text-slate-600 whitespace-nowrap">
                      {DOTPLOT_INDICATOR_LABELS[row.name] || row.name}
                    </td>
                    {row.cells.map((cell, i) => (
                      <td key={i} className="p-0">
                        <div
                          className="mx-auto"
                          style={{
                            width: 16, height: 16,
                            backgroundColor: heatmapColor(cell.v, globalMinMax.gMin, globalMinMax.gMax),
                            opacity: 0.8,
                            borderRadius: 2,
                          }}
                          title={`${cell.date}: ${cell.v.toFixed(3)}`}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
